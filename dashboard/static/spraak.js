/* JARVIS — spraakpaneel: de iPad als microfoon (Fase 20, M4) en speaker (M5).
 *
 * Opent de microfoon, zet het geluid om naar 16 kHz mono (int16) en stuurt
 * het via één WebSocket (/api/spraak/stroom) naar het brein, dat er het
 * wake word en het luisteren mee doet. Valt de verbinding weg, dan verbindt
 * de pagina vanzelf opnieuw. Het antwoord van JARVIS komt over dezelfde
 * verbinding terug (4 bytes samplefrequentie + int16-geluid) en wordt hier
 * achter elkaar afgespeeld; zolang dat klinkt, stuurt de pagina geen
 * microfoongeluid (JARVIS hoort zichzelf niet). Regels als in app.js: ES5 (iOS 12), geen
 * innerHTML, alleen de eigen origin en de HttpOnly-cookie.
 */
(function () {
  'use strict';

  var RATE = 16000;
  var FASE_TEKST = {
    rust: 'JARVIS wacht op “Hey JARVIS”',
    luistert: 'JARVIS luistert…',
    denkt: 'JARVIS denkt na…',
    spreekt: 'JARVIS spreekt',
    slaapt: 'JARVIS slaapt (wakker met “Hey JARVIS”)'
  };

  var Ctx = window.AudioContext || window.webkitAudioContext;
  var staat = {
    aan: false, ctx: null, stream: null, bron: null, proc: null,
    sok: null, wacht: 1000, herverbind: null, statusTimer: null, omzetter: null,
    speeltTot: 0, spelers: [], houdWakker: null
  };

  // ----- afspelen (M5) -----
  function speel(buf) {
    var ctx = staat.ctx;
    if (!ctx || buf.byteLength < 6) { return; }
    var rate = new DataView(buf).getUint32(0, true);
    var pcm = new Int16Array(buf, 4, (buf.byteLength - 4) >> 1);
    var audio = ctx.createBuffer(1, pcm.length, rate);
    var kanaal = audio.getChannelData(0);
    for (var i = 0; i < pcm.length; i++) { kanaal[i] = pcm[i] / 32768; }
    var bron = ctx.createBufferSource();
    bron.buffer = audio;
    bron.connect(ctx.destination);
    var start = Math.max(ctx.currentTime + 0.05, staat.speeltTot);
    bron.start(start);
    staat.speeltTot = start + audio.duration;
    staat.spelers.push(bron);
    bron.onended = function () {
      var plek = staat.spelers.indexOf(bron);
      if (plek !== -1) { staat.spelers.splice(plek, 1); }
    };
  }

  function stopAfspelen() {
    staat.spelers.forEach(function (b) { try { b.stop(0); } catch (e) { /* al klaar */ } });
    staat.spelers = [];
    staat.speeltTot = 0;
  }

  function speeltAf() {
    return staat.ctx && staat.ctx.currentTime < staat.speeltTot + 0.3;
  }

  function bericht(e) {
    if (typeof e.data === 'string') {
      var m = null;
      try { m = JSON.parse(e.data); } catch (f) { return; }
      if (m && m.type === 'stop') { stopAfspelen(); }
      return;
    }
    speel(e.data);
  }

  function zegHallo() {
    var sok = staat.sok;
    if (sok && sok.readyState === 1) {
      sok.send(JSON.stringify({ type: 'hallo', spreker: $('spreker').checked }));
    }
  }

  function $(id) { return document.getElementById(id); }
  function fout(tekst) { $('fout').textContent = tekst || ''; }
  function zetStaat(tekst) { $('staat').textContent = tekst; }

  // Van 44,1/48 kHz naar 16 kHz: gemiddelde per blok (laagdoorlaat).
  function maakOmzetter(bronRate) {
    var stap = bronRate / RATE;
    var pos = 0;
    return function (invoer) {
      var uit = new Int16Array(Math.floor((invoer.length - pos) / stap) + 1);
      var n = 0;
      while (pos + stap <= invoer.length) {
        var begin = Math.floor(pos);
        var eind = Math.floor(pos + stap);
        var som = 0;
        for (var i = begin; i < eind; i++) { som += invoer[i]; }
        var w = som / Math.max(1, eind - begin);
        uit[n++] = Math.max(-32768, Math.min(32767, Math.round(w * 32767)));
        pos += stap;
      }
      pos -= invoer.length;
      if (pos < 0) { pos = 0; }
      return uit.subarray(0, n);
    };
  }

  // ----- verbinding -----
  // Eerst een eenmalig kaartje via fetch (daar gaat de cookie wél mee); dat
  // gaat als eerste bericht over de WebSocket. Safari stuurt de cookie niet
  // altijd mee met een WebSocket (Fase 20, M5-fix).
  function verbind() {
    if (!staat.aan) { return; }
    zetStaat('Verbinden…');
    fetch('/api/spraak/kaartje', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: '{}'
    }).then(function (r) {
      return r.json().catch(function () { return null; }).then(function (d) {
        if (r.status === 200 && d && d.kaartje) { open(d.kaartje); return; }
        if (r.status === 401) {
          fout('Niet gekoppeld in Safari: open het dashboard in Safari en koppel met de bedien-rol.');
        } else {
          fout((d && d.fout && d.fout.melding) || ('Geen toegang tot de spraakstroom (' + r.status + ').'));
        }
        planHerverbinding();
      });
    }).catch(function () {
      fout('Geen verbinding met JARVIS.');
      planHerverbinding();
    });
  }

  function open(kaartje) {
    if (!staat.aan) { return; }
    var sok;
    try {
      sok = new WebSocket('wss://' + location.host + '/api/spraak/stroom');
    } catch (e) {
      fout('WebSocket kon niet openen: ' + String((e && e.message) || e));
      planHerverbinding();
      return;
    }
    sok.binaryType = 'arraybuffer';
    staat.sok = sok;
    sok.onopen = function () {
      sok.send(JSON.stringify({ type: 'kaartje', kaartje: kaartje }));
      staat.wacht = 1000;
      fout('');
      zetStaat('● Luistert via de iPad');
      zegHallo();
    };
    sok.onmessage = bericht;
    sok.onclose = function (e) {
      if (staat.sok === sok) { staat.sok = null; }
      if (staat.aan) {
        // De code helpt bij het zoeken: 1006 = niet tot stand gekomen of
        // afgebroken, 1008 = kaartje geweigerd.
        zetStaat('Verbinding weg; opnieuw proberen…');
        $('route').textContent = 'Laatste fout: code ' + (e && e.code) + (e && e.reason ? ' (' + e.reason + ')' : '');
        planHerverbinding();
      }
    };
    sok.onerror = function () { /* onclose volgt */ };
  }

  function planHerverbinding() {
    if (staat.herverbind || !staat.aan) { return; }
    staat.herverbind = setTimeout(function () {
      staat.herverbind = null;
      verbind();
    }, staat.wacht);
    staat.wacht = Math.min(staat.wacht * 2, 10000);
  }

  // ----- microfoon -----
  function start() {
    fout('');
    if (!Ctx || !(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) {
      fout('Deze browser kan de microfoon niet gebruiken. Open de pagina in Safari (niet via het beginscherm).');
      return;
    }
    if (!staat.ctx) { staat.ctx = new Ctx(); }
    if (staat.ctx.state === 'suspended' && staat.ctx.resume) { staat.ctx.resume(); }
    staat.aan = true;
    $('aanuit').textContent = 'Stop luisteren';
    zetStaat('Microfoon openen…');

    navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
      .then(function (stream) {
        if (!staat.aan) { stream.getTracks().forEach(function (t) { t.stop(); }); return; }
        var ctx = staat.ctx;
        staat.stream = stream;
        staat.bron = ctx.createMediaStreamSource(stream);
        staat.proc = ctx.createScriptProcessor(4096, 1, 1);
        staat.omzetter = maakOmzetter(ctx.sampleRate);
        staat.proc.onaudioprocess = function (e) {
          var invoer = e.inputBuffer.getChannelData(0);
          var piek = 0;
          for (var i = 0; i < invoer.length; i += 4) { piek = Math.max(piek, Math.abs(invoer[i])); }
          $('niveau').style.width = Math.min(100, Math.round(piek * 140)) + '%';
          var pcm = staat.omzetter(invoer);
          var sok = staat.sok;
          // Terwijl JARVIS uit de iPad praat, niets sturen (geen echo).
          if (speeltAf()) { return; }
          if (pcm.length && sok && sok.readyState === 1 && sok.bufferedAmount < 64000) {
            sok.send(pcm.buffer.slice(pcm.byteOffset, pcm.byteOffset + pcm.byteLength));
          }
        };
        staat.bron.connect(staat.proc);
        // Zonder verbinding naar de uitgang roept iOS onaudioprocess niet aan.
        staat.proc.connect(ctx.destination);
        verbind();
        volgStatus();
        // Tijdens een lang antwoord stuurt de pagina geen geluid; een klein
        // teken van leven houdt de verbinding open.
        staat.houdWakker = setInterval(function () {
          var sok = staat.sok;
          if (sok && sok.readyState === 1 && speeltAf()) { sok.send('k'); }
        }, 3000);
      })
      .catch(function (e) {
        fout(e && e.name === 'NotAllowedError'
          ? 'Geen toestemming voor de microfoon. Sta hem toe (Instellingen → Safari → Microfoon) en probeer opnieuw.'
          : 'De microfoon kon niet open: ' + String((e && e.message) || e));
        stop();
      });
  }

  function stop() {
    staat.aan = false;
    $('aanuit').textContent = 'Start luisteren';
    if (staat.herverbind) { clearTimeout(staat.herverbind); staat.herverbind = null; }
    if (staat.statusTimer) { clearInterval(staat.statusTimer); staat.statusTimer = null; }
    if (staat.houdWakker) { clearInterval(staat.houdWakker); staat.houdWakker = null; }
    stopAfspelen();
    if (staat.sok) { try { staat.sok.close(); } catch (e) { /* al dicht */ } staat.sok = null; }
    if (staat.proc) { staat.proc.onaudioprocess = null; try { staat.proc.disconnect(); } catch (e) { /* los */ } }
    if (staat.bron) { try { staat.bron.disconnect(); } catch (e) { /* los */ } }
    if (staat.stream) { staat.stream.getTracks().forEach(function (t) { t.stop(); }); }
    staat.proc = staat.bron = staat.stream = null;
    $('niveau').style.width = '0%';
    $('jarvis').textContent = '';
    $('route').textContent = '';
    zetStaat('Uit');
  }

  // ----- wat JARVIS doet -----
  function volgStatus() {
    if (staat.statusTimer) { return; }
    var lees = function () {
      if (document.hidden) { return; }
      fetch('/api/status', { credentials: 'same-origin' }).then(function (r) {
        return r.status === 200 ? r.json() : null;
      }).then(function (s) {
        if (s && s.fase) { $('jarvis').textContent = FASE_TEKST[s.fase] || ''; }
        if (s && s.ipad && staat.sok) {
          // Laat zien waar JARVIS nu luistert en spreekt.
          $('route').textContent = 'Microfoon: ' + (s.ipad.microfoon ? 'iPad ✓' : 'laptop') +
            ' · Speaker: ' + (s.ipad.speaker ? 'iPad ✓' : 'laptop');
        }
      }).catch(function () {});
    };
    lees();
    staat.statusTimer = setInterval(lees, 2000);
  }

  document.addEventListener('visibilitychange', function () {
    // iOS 12 pauzeert het geluid als de pagina uit beeld gaat.
    if (!document.hidden && staat.aan && staat.ctx && staat.ctx.state === 'suspended') {
      $('uitleg').textContent = 'Tik op Stop en weer op Start om verder te luisteren (iOS pauzeerde de microfoon).';
    }
  });

  document.addEventListener('DOMContentLoaded', function () {
    $('aanuit').addEventListener('click', function () {
      if (staat.aan) { stop(); } else { start(); }
    });
    $('spreker').addEventListener('change', zegHallo);
  });
})();
