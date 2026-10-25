/* JARVIS — spraakproef (Fase 20, M3).
 *
 * Kijkt of de iPad (iOS 12, Safari) als microfoon en speaker kan dienen:
 *  - microfoon openen, het geluid omzetten naar 16 kHz mono (int16) en in
 *    stukjes van 0,25 s naar het brein sturen, dat het meet;
 *  - een testzin met de stem van JARVIS ophalen en afspelen.
 * Regels als in app.js: ES5 (iOS 12), geen innerHTML, alleen de eigen origin
 * en de HttpOnly-cookie (geen token in JS).
 */
(function () {
  'use strict';

  var RATE = 16000;
  var SECONDEN = 6;
  var STUK = RATE / 4;  // 0,25 s per verzoek

  var Ctx = window.AudioContext || window.webkitAudioContext;
  var staat = { ctx: null, bezig: false };

  function $(id) { return document.getElementById(id); }

  function regel(lijst, ok, tekst) {
    var li = document.createElement('li');
    li.className = ok === true ? 'ok' : (ok === false ? 'nee' : 'let');
    li.textContent = (ok === true ? '✓ ' : (ok === false ? '✗ ' : '• ')) + tekst;
    $(lijst).appendChild(li);
  }

  function leeg(id) {
    var doos = $(id);
    while (doos.firstChild) { doos.removeChild(doos.firstChild); }
  }

  function fout(tekst) { $('fout').textContent = tekst || ''; }

  function post(pad, body) {
    return fetch(pad, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (r) {
      return r.json().catch(function () { return null; }).then(function (data) {
        return { status: r.status, data: data };
      });
    });
  }

  function melding(r, standaard) {
    if (r.status === 401) { return 'Niet gekoppeld in Safari: open eerst het dashboard in Safari en koppel met de bedien-rol.'; }
    if (r.status === 403) { return 'Hiervoor is de bedien-rol nodig.'; }
    return (r.data && r.data.fout && r.data.fout.melding) || standaard;
  }

  // ----- 1. ondersteuning -----
  function controleer() {
    leeg('steun');
    var standalone = window.navigator.standalone === true;
    regel('steun', !standalone, standalone
      ? 'Geopend als beginscherm-app: daar werkt de microfoon niet op iOS 12. Open deze pagina in Safari.'
      : 'Geopend in Safari');
    var gum = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    regel('steun', gum, gum ? 'Microfoon-toegang mogelijk' : 'Geen microfoon-toegang in deze browser');
    regel('steun', !!Ctx, Ctx ? 'Web Audio aanwezig' : 'Geen Web Audio');
    regel('steun', location.protocol === 'https:', 'Beveiligde verbinding (HTTPS)');
    $('opnemen').disabled = !(gum && Ctx);
    $('afspelen').disabled = !Ctx;
  }

  // ----- hulp: audio -----
  function zorgVoorCtx() {
    // iOS 12: alleen binnen een tik mag geluid starten.
    if (!staat.ctx) { staat.ctx = new Ctx(); }
    if (staat.ctx.state === 'suspended' && staat.ctx.resume) { staat.ctx.resume(); }
    return staat.ctx;
  }

  function naarBase64(int16) {
    var bytes = new Uint8Array(int16.buffer, int16.byteOffset, int16.byteLength);
    var delen = [];
    for (var i = 0; i < bytes.length; i += 8192) {
      delen.push(String.fromCharCode.apply(null, bytes.subarray(i, i + 8192)));
    }
    return window.btoa(delen.join(''));
  }

  // Van 44,1/48 kHz naar 16 kHz: per uitvoersample het gemiddelde van de
  // invoersamples die erbij horen (een eenvoudig laagdoorlaatfilter).
  function maakOmzetter(bronRate) {
    var stap = bronRate / RATE;
    var pos = 0;
    return function (invoer) {
      var uit = [];
      while (pos + stap <= invoer.length) {
        var begin = Math.floor(pos);
        var eind = Math.floor(pos + stap);
        var som = 0;
        for (var i = begin; i < eind; i++) { som += invoer[i]; }
        var w = som / Math.max(1, eind - begin);
        uit.push(Math.max(-32768, Math.min(32767, Math.round(w * 32767))));
        pos += stap;
      }
      pos -= invoer.length;
      if (pos < 0) { pos = 0; }
      return uit;
    };
  }

  // ----- 2. opnemen -----
  function neemOp() {
    if (staat.bezig) { return; }
    fout('');
    leeg('uitslag');
    var ctx = zorgVoorCtx();
    staat.bezig = true;
    $('opnemen').disabled = true;
    $('opnameStatus').textContent = 'Microfoon openen…';

    navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
      .then(function (stream) {
        return post('/api/spraak/proef/start').then(function (r) {
          if (r.status !== 200) { throw new Error(melding(r, 'De proef kon niet starten.')); }
          return opname(ctx, stream, r.data.id);
        });
      })
      .catch(function (e) {
        fout(e && e.name === 'NotAllowedError'
          ? 'Geen toestemming voor de microfoon. Sta hem toe (Instellingen → Safari → Microfoon) en probeer opnieuw.'
          : String((e && e.message) || e));
        klaarMetOpnemen();
      });
  }

  function opname(ctx, stream, proefId) {
    var bron = ctx.createMediaStreamSource(stream);
    var proc = ctx.createScriptProcessor(4096, 1, 1);
    var omzetter = maakOmzetter(ctx.sampleRate);
    var buffer = [];
    var seq = 0;
    var verzonden = [];
    var totaal = 0;
    var start = Date.now();

    function verstuur(samples) {
      if (!samples.length) { return; }
      var stuk = new Int16Array(samples);
      verzonden.push(post('/api/spraak/proef/stuk', {
        id: proefId, seq: seq, t: Date.now() - start, pcm: naarBase64(stuk)
      }));
      seq += 1;
    }

    return new Promise(function (klaar) {
      proc.onaudioprocess = function (e) {
        var invoer = e.inputBuffer.getChannelData(0);
        var piek = 0;
        for (var i = 0; i < invoer.length; i++) { piek = Math.max(piek, Math.abs(invoer[i])); }
        $('niveau').style.width = Math.min(100, Math.round(piek * 140)) + '%';
        var nieuw = omzetter(invoer);
        buffer = buffer.concat(nieuw);
        totaal += nieuw.length;
        while (buffer.length >= STUK) { verstuur(buffer.splice(0, STUK)); }
        var over = Math.max(0, SECONDEN - Math.floor((Date.now() - start) / 1000));
        $('opnameStatus').textContent = 'Neemt op… nog ' + over + ' s. Zeg: “Hey JARVIS, hoe laat is het?”';
        if (totaal >= SECONDEN * RATE) {
          proc.onaudioprocess = null;
          verstuur(buffer.splice(0, buffer.length));
          try { bron.disconnect(); proc.disconnect(); } catch (f) { /* al los */ }
          stream.getTracks().forEach(function (t) { t.stop(); });
          klaar();
        }
      };
      bron.connect(proc);
      // Zonder verbinding naar de uitgang roept iOS onaudioprocess niet aan.
      proc.connect(ctx.destination);
    }).then(function () {
      $('niveau').style.width = '0%';
      $('opnameStatus').textContent = 'Versturen en meten…';
      return Promise.all(verzonden);
    }).then(function (antwoorden) {
      var mislukt = antwoorden.filter(function (r) { return r.status !== 200; });
      if (mislukt.length) { throw new Error(melding(mislukt[0], 'Versturen mislukte.')); }
      return post('/api/spraak/proef/klaar', { id: proefId });
    }).then(function (r) {
      if (r.status !== 200) { throw new Error(melding(r, 'Meten mislukte.')); }
      toonUitslag(r.data, ctx.sampleRate);
      klaarMetOpnemen();
    });
  }

  function toonUitslag(u, bronRate) {
    leeg('uitslag');
    regel('uitslag', u.ontbrekend === 0, u.seconden + ' s ontvangen in ' + u.stukken + ' stukjes' +
      (u.ontbrekend ? ' (' + u.ontbrekend + ' ontbreken)' : '') + '; grootste pauze ' + u.grootste_gat_ms + ' ms');
    regel('uitslag', u.rms_dbfs > -50 && u.oversturing <= 1,
      'Niveau ' + u.rms_dbfs + ' dBFS (piek ' + u.piek_dbfs + '), oversturing ' + u.oversturing + '%');
    if (u.wake_word_score === null || u.wake_word_score === undefined) {
      regel('uitslag', null, 'Wake word: niet gemeten (geen model op het brein)');
    } else {
      regel('uitslag', u.wake_word_score >= 0.5, '“Hey JARVIS”-score ' + u.wake_word_score + ' (vanaf 0,5 telt hij)');
    }
    regel('uitslag', u.herkend ? true : null, u.herkend ? 'Verstaan: “' + u.herkend + '”' : 'Spraakherkenning: niets verstaan');
    regel('uitslag', null, 'Microfoon van de iPad: ' + bronRate + ' Hz, omgezet naar 16 kHz');
    $('opnameStatus').textContent = u.oordeel;
  }

  function klaarMetOpnemen() {
    staat.bezig = false;
    $('opnemen').disabled = false;
    $('opnemen').textContent = 'Opnieuw opnemen';
  }

  // ----- 3. afspelen -----
  function speelAf() {
    fout('');
    var ctx = zorgVoorCtx();
    // Een stil geluidje direct in de tik "ontgrendelt" het geluid op iOS 12.
    var stil = ctx.createBuffer(1, 1, 22050);
    var s = ctx.createBufferSource();
    s.buffer = stil;
    s.connect(ctx.destination);
    s.start(0);

    var t0 = Date.now();
    $('afspeelStatus').textContent = 'Testzin ophalen…';
    fetch('/api/spraak/proef/testzin.wav', { credentials: 'same-origin' }).then(function (r) {
      if (r.status !== 200) {
        return r.json().catch(function () { return null; }).then(function (d) {
          throw new Error(melding({ status: r.status, data: d }, 'De testzin kon niet worden opgehaald.'));
        });
      }
      return r.arrayBuffer();
    }).then(function (buf) {
      var opgehaald = Date.now() - t0;
      ctx.decodeAudioData(buf, function (audio) {
        var bron = ctx.createBufferSource();
        bron.buffer = audio;
        bron.connect(ctx.destination);
        bron.start(0);
        $('afspeelStatus').textContent = 'Speelt af (' + audio.duration.toFixed(1) + ' s). Opgehaald in ' +
          opgehaald + ' ms, geluid na ' + (Date.now() - t0) + ' ms. Hoorde u JARVIS?';
      }, function () {
        fout('De iPad kon de testzin niet afspelen.');
      });
    }).catch(function (e) {
      fout(String((e && e.message) || e));
      $('afspeelStatus').textContent = '';
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    controleer();
    $('opnemen').addEventListener('click', neemOp);
    $('afspelen').addEventListener('click', speelAf);
  });
})();
