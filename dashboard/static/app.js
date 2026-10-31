/* JARVIS-dashboard (Fase 18) — de PWA.
 *
 * Regels (docs/fase18_dashboard_design.md §10.8 en §13.1):
 *  - Gegevens uit de API worden NOOIT als HTML behandeld: geen innerHTML,
 *    insertAdjacentHTML, outerHTML of document.write. Tekst gaat via
 *    textContent, elementen via document.createElement.
 *  - Geen inline code of styles (strikte CSP); alleen klassen en CSSOM.
 *  - Alle verzoeken gaan naar de eigen origin. Het token zit in een
 *    HttpOnly-cookie; dit script ziet het nooit.
 *  - Gevaarlijke acties (uit, herstart, slaap) worden nooit direct uitgevoerd: de
 *    server zet een goedkeuring klaar, die hier als overlay verschijnt.
 */
(function () {
  'use strict';

  // Moet gelijk zijn aan API_VERSIE in dashboard/api.py (een test bewaakt dat).
  var VERSIE = '29.1';

  var STAGE_B = 1180;
  var STAGE_H = 820;
  var POLL_MS = 2000;
  var TEGEL_MS = 5000;
  var WEER_MS = 10 * 60 * 1000;
  var VANDAAG_MS = 2 * 60 * 1000;
  var SVG_NS = 'http://www.w3.org/2000/svg';

  var $ = function (id) { return document.getElementById(id); };

  var staat = {
    bron: null,          // EventSource
    pollTimer: null,
    tegelTimer: null,
    rol: null,
    koppelRol: 'bedien',
    doel: 'local',       // welke pc het Systeem-paneel toont
    timers: [],
    timerStart: {},      // id -> eerste bekende resterende tijd (voor de balk)
    timerVraag: null,    // id van de timer waarvoor "annuleren?" open staat
    timerDelen: {},      // id -> { tijd, vul } om elke seconde bij te werken
    pending: null,
    pendingOntvangen: 0, // Date.now() bij ontvangst van de pending
    meldingen: [],
    laatst: {},          // paneel -> laatst getekende gegevens (JSON)
    schuift: false,      // de volumeschuif wordt bediend
    sh: null,            // slim huis aanpassen: gekozen / beschikbaar / filter
    widgets: null,       // config/dashboard.json zoals de server hem gaf
    meldingenTonen: true,
    meldGeluid: true,     // geluidje bij een nieuwe melding (Fase 20, M6)
    gezien: null,         // id's van meldingen die al eens getoond zijn
    nachtAan: false,
    geluid: null,         // AudioContext, pas na de eerste tik (iOS)
    bannerTimer: null,
    concept: null,       // instellingen die nog niet zijn opgeslagen
    ontkoppelVraag: false,
    tab: null,           // open tabblad in het overzicht
    gamePcOnline: null,  // true/false zodra bekend (bolletje bij Game-PC)
    gesprek: [],         // getoonde beurten, oudste eerst (ook oudere pagina's)
    gesprekMeer: true,   // of er vóór de oudste getoonde beurt nog meer is
    gesprekLaadt: false, // er wordt een oudere pagina opgehaald
    gesprekGetekend: false,
    wisVraag: null,      // timer van "Echt wissen?"
    mislukt: 0           // verzoeken achter elkaar zonder enig antwoord
  };

  // Welke panelen er per kolom bestaan (vaste lijst; de volgorde en
  // zichtbaarheid komen uit config/dashboard.json).
  var PANELEN = {
    links: [['spraakstatus', 'Spraakstatus'], ['timers', 'Timers & wekkers'], ['weer', 'Weer'], ['nachtmodus', 'Nachtmodus']],
    midden: [['gesprek', 'Gesprek'], ['routines', 'Routines'], ['vandaag', 'Vandaag'], ['auditlog', 'Auditlog']],
    rechts: [['systeem', 'Systeem'], ['media', 'Media & volume'], ['slim_huis', 'Slim huis']]
  };
  var KOLOM_NAAM = { links: 'Links', midden: 'Midden', rechts: 'Rechts' };

  // ----- kleine DOM-hulpjes (nooit HTML uit data) -----
  function el(tag, cls, tekst) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (tekst !== undefined && tekst !== null) { e.textContent = String(tekst); }
    return e;
  }

  function leeg(node) {
    while (node.firstChild) { node.removeChild(node.firstChild); }
  }

  // Vaste, eigen iconen (paden staan in deze code, nooit uit de API).
  var ICONEN = {
    lamp: 'M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z',
    cover: 'M4 4h16v3H4zM4 10h16M4 13h16M4 16h16M12 16v4',
    climate: 'M10 14V5a2 2 0 0 1 4 0v9a4 4 0 1 1-4 0z',
    media_player: 'M3 6h18v11H3zM8 21h8',
    switch: 'M7 7h10v10H7zM12 3v4M9 17v4M15 17v4',
    scene: 'M6 4l14 8-14 8z',
    button: 'M12 3v8M7.5 6.5a7 7 0 1 0 9 0'
  };

  function icoon(pad, maat) {
    var svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('width', String(maat || 22));
    svg.setAttribute('height', String(maat || 22));
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.7');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    var p = document.createElementNS(SVG_NS, 'path');
    p.setAttribute('d', pad);
    svg.appendChild(p);
    return svg;
  }

  function magBedienen() { return staat.rol === 'bedien'; }

  // Alleen opnieuw tekenen als de gegevens echt veranderd zijn: een paneel
  // dat elke paar seconden vervangen wordt, kan een tik "opeten".
  function veranderd(paneel, data) {
    var json = JSON.stringify(data);
    if (staat.laatst[paneel] === json) { return false; }
    staat.laatst[paneel] = json;
    return true;
  }

  // ----- schalen: de 1180x820-stage past in elk venster -----
  // De stage is 1180 breed; de hoogte rekt mee met het scherm, zodat een
  // 4:3-iPad (1024x768, bijv. iPad Air 1) helemaal gevuld wordt zonder
  // balken. Alleen op brede schermen (laptop, 16:9) blijft hij 820 hoog en
  // wordt hij gecentreerd.
  var STAGE_H_MIN = 760;
  // Hoger dan een 4:3-iPad in landschap (1180 / 4 * 3 = 885) wordt hij niet:
  // staat de iPad rechtop, dan zou de stage anders 1500+ hoog uitrekken.
  var STAGE_H_MAX = 885;

  var laatsteBreedte = 0;

  // De maat van het venster zelf (layout-viewport). window.innerWidth telt
  // de zoom van Safari mee: zoomt iOS na het draaien in, dan schaalde de app
  // naar die verkeerde maat en bleef hij zo hangen.
  function venster() {
    var d = document.documentElement;
    return { b: d.clientWidth || window.innerWidth, h: d.clientHeight || window.innerHeight };
  }

  function pasAan() {
    var stage = $('stage');
    var v = venster();
    // Typt u in een veld en verandert alleen de hoogte (het toetsenbord van
    // iOS komt omhoog), dan niet opnieuw schalen: anders verspringt het
    // veld en sluit het toetsenbord meteen weer.
    var actief = document.activeElement;
    if (actief && actief.tagName === 'INPUT' && v.b === laatsteBreedte) { return; }
    laatsteBreedte = v.b;
    var s = v.b / STAGE_B;
    var hoogte = v.h / s;
    if (hoogte < STAGE_H_MIN) {
      s = Math.min(v.b / STAGE_B, v.h / STAGE_H);
      hoogte = STAGE_H;
    } else if (hoogte > STAGE_H_MAX) {
      hoogte = STAGE_H_MAX;
    }
    stage.style.height = hoogte + 'px';
    stage.style.transform = 'scale(' + s + ')';
    stage.style.left = Math.max(0, (v.b - STAGE_B * s) / 2) + 'px';
    stage.style.top = Math.max(0, (v.h - hoogte * s) / 2) + 'px';
  }

  // Na het draaien geeft iOS 12 de nieuwe maat pas na een poosje door; meet
  // daarom een paar keer na en zet de pagina terug linksboven.
  function naDraaien() {
    if (document.activeElement && document.activeElement.blur) { document.activeElement.blur(); }
    [0, 150, 400, 800].forEach(function (ms) {
      setTimeout(function () { window.scrollTo(0, 0); pasAan(); }, ms);
    });
  }

  // Oudere Safari (iOS 12) kent geen `gap` in flexbox; dan zet styles.css
  // dezelfde ruimtes via marges (klasse .geen-flex-gap op <html>).
  function controleerFlexGap() {
    var proef = document.createElement('div');
    proef.style.display = 'flex';
    proef.style.flexDirection = 'column';
    proef.style.rowGap = '1px';
    proef.appendChild(document.createElement('div'));
    proef.appendChild(document.createElement('div'));
    document.body.appendChild(proef);
    var werkt = proef.scrollHeight === 1;
    document.body.removeChild(proef);
    if (!werkt) { document.documentElement.classList.add('geen-flex-gap'); }
  }

  // ----- klok -----
  function tik() {
    var d = new Date();
    $('klok').textContent = d.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' });
    $('datum').textContent = d.toLocaleDateString('nl-NL', { weekday: 'short', day: 'numeric', month: 'short' })
      .replace('.', '').toUpperCase();
  }

  function mmss(seconden) {
    seconden = Math.max(0, Math.round(seconden));
    var u = Math.floor(seconden / 3600);
    var m = Math.floor((seconden % 3600) / 60);
    var s = String(seconden % 60).padStart(2, '0');
    return u > 0 ? u + ':' + String(m).padStart(2, '0') + ':' + s : String(m).padStart(2, '0') + ':' + s;
  }

  // ----- API -----
  function api(pad, opties) {
    opties = opties || {};
    var init = { method: opties.method || 'GET', credentials: 'same-origin', cache: 'no-store', headers: {} };
    if (opties.body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(opties.body);
    }
    return fetch(pad, init).then(function (r) {
      if (r.status === 401) { ontkoppeld(); }
      return r.json().catch(function () { return null; }).then(function (data) {
        return { status: r.status, data: data };
      });
    });
  }

  // ----- verbindingsstatus in de header -----
  // ----- geen verbinding: de laptop is helemaal niet bereikbaar -----
  // (geen HTTP-fout maar een netwerkfout; op de iPad meestal een certificaat
  // dat niet volledig vertrouwd is, of een ander IP-adres).
  function netwerkFout() {
    staat.mislukt += 1;
    zetVerbonden(false);
    // Bij het openen meteen; tijdens gebruik pas na een paar pogingen.
    if (staat.mislukt >= (staat.rol ? 3 : 1)) { $('geenVerbinding').hidden = false; }
  }

  function netwerkOk() {
    staat.mislukt = 0;
    $('geenVerbinding').hidden = true;
  }

  function zetVerbonden(aan, tekst) {
    $('pil').classList.toggle('offline', !aan);
    $('pilTekst').textContent = tekst || (aan ? 'Online · wake word “Hey JARVIS”' : 'Verbinding verbroken');
  }

  // ----- spraakstatus-orb -----
  var FASES = {
    rust: { label: 'IN RUST', hint: 'Wacht op “Hey JARVIS”', reactor: '' },
    luistert: { label: 'LUISTERT', hint: 'Spreek uw opdracht in', reactor: 'speaking' },
    denkt: { label: 'DENKT NA', hint: 'Plan maken en uitvoeren', reactor: 'thinking' },
    spreekt: { label: 'SPREEKT', hint: 'JARVIS antwoordt', reactor: 'speaking' },
    slaapt: { label: 'SLAAPT', hint: 'Wakker met “Hey JARVIS”', reactor: 'sleeping' }
  };

  function toonFase(fase) {
    var f = FASES[fase] ? fase : 'rust';
    var def = FASES[f];
    ['orb', 'orbLabel'].forEach(function (id) {
      var e = $(id);
      Object.keys(FASES).forEach(function (k) { e.classList.remove('fase-' + k); });
      e.classList.add('fase-' + f);
    });
    $('reactor').className = 'ai-reactor' + (def.reactor ? ' ' + def.reactor : '');
    $('orbLabel').textContent = def.label;
    $('orbHint').textContent = def.hint;
    $('orb').setAttribute('aria-label', 'JARVIS: ' + def.label.toLowerCase());
  }

  // ----- nachtmodus -----
  var NACHT_INFO = {
    auto: 'Volgt de vaste tijden.',
    aan: 'Handmatig aan; verloopt bij de volgende vaste overgang.',
    uit: 'Handmatig uit; verloopt bij de volgende vaste overgang.'
  };

  function toonNacht(stand, actief) {
    staat.nachtAan = !!actief;  // 's nachts geen meldingsgeluid (M6)
    Array.prototype.forEach.call($('nacht').querySelectorAll('button'), function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-stand') === stand));
    });
    $('nachtInfo').textContent = (NACHT_INFO[stand] || '') + (actief ? ' Nu actief.' : ' Nu niet actief.');
  }

  function zetNacht(stand) {
    if (!magBedienen()) { return; }
    api('/api/nachtmodus', { method: 'POST', body: { stand: stand } }).then(function (r) {
      if (r.status === 200) { toonNacht(r.data.stand, stand === 'aan'); }
    });
  }

  // ----- focusmodus (Fase 26, M2) -----
  function toonFocus(f) {
    f = f || {};
    staat.focus = f.aan ? { tot: f.tot, resterend: f.resterend, ontvangen: Date.now() } : null;
    Array.prototype.forEach.call($('focus').querySelectorAll('button'), function (b) {
      var minuten = b.getAttribute('data-minuten');
      var aan = b.getAttribute('data-actie') === 'aan';
      var ingedrukt = f.aan ? (aan && !minuten && !f.tot) || (aan && !!minuten && !!f.tot) : !aan;
      b.setAttribute('aria-pressed', String(ingedrukt));
    });
    tekenFocus();
  }

  function tekenFocus() {
    var f = staat.focus;
    if (!f) { $('focusInfo').textContent = 'Focus staat uit.'; return; }
    if (!f.tot) { $('focusInfo').textContent = 'Focus aan, zonder eindtijd. Discord gedempt, DM’s stil.'; return; }
    var rest = Math.max(0, (f.resterend || 0) - (Date.now() - f.ontvangen) / 1000);
    $('focusInfo').textContent = 'Focus tot ' + f.tot + ' (nog ' + mmss(rest) + ').';
  }

  function zetFocus(knop) {
    if (!magBedienen()) { return; }
    var body = { actie: knop.getAttribute('data-actie') };
    var minuten = knop.getAttribute('data-minuten');
    if (minuten) { body.minuten = parseInt(minuten, 10); }
    $('focusInfo').textContent = 'Even geduld…';
    api('/api/focus', { method: 'POST', body: body }).then(function (r) {
      if (r.status === 200 && r.data) {
        toonFocus(r.data.focus);
        if (r.data.tekst) { $('focusInfo').textContent = r.data.tekst; }
      } else {
        $('focusInfo').textContent = 'Dat lukte niet.';
      }
    });
  }

  function toonStatus(s) {
    if (!s || typeof s !== 'object') { return; }
    toonFase(s.fase);
    // Fase 20, M1: wat JARVIS nu doet (of net deed), onder de orb.
    if (s.taak) {
      $('orbHint').textContent = s.taak.charAt(0).toUpperCase() + s.taak.slice(1);
    }
    toonNacht(s.nachtmodus_stand, !!s.nachtmodus);
    if (s.focus) { toonFocus(s.focus); }
    toonAfsluiting(s.afsluiting || null);
  }

  // ----- typen met JARVIS (Fase 20, M1) -----
  // De keuze stil/hardop staat in de dashboard-instellingen op de server
  // (de PWA bewaart bewust niets in de browser, zie Fase 18).
  function zetHardop(aan) {
    $('hardop').setAttribute('aria-pressed', String(aan));
    $('hardop').setAttribute('aria-label', aan ? 'JARVIS antwoordt hardop' : 'JARVIS antwoordt stil (alleen tekst)');
  }

  function bewaarHardop(aan) {
    var basis = staat.widgets;
    if (!basis || !magBedienen()) { return; }
    var config = JSON.parse(JSON.stringify(basis));
    config.instellingen = config.instellingen || {};
    config.instellingen.hardop = aan;
    api('/api/widgets', { method: 'PUT', body: config }).then(function (r) {
      if (r.status === 200) { staat.widgets = config; }
    });
  }

  function verstuurOpdracht(e) {
    e.preventDefault();
    if (!magBedienen()) { return; }
    var veld = $('opdracht');
    var tekst = veld.value.replace(/\s+/g, ' ').trim();
    if (!tekst) { return; }
    var hardop = $('hardop').getAttribute('aria-pressed') === 'true';
    $('invoerFout').textContent = '';
    $('verstuur').disabled = true;
    api('/api/command', { method: 'POST', body: { tekst: tekst, hardop: hardop } }).then(function (r) {
      $('verstuur').disabled = false;
      if (r.status === 202) {
        veld.value = '';
        veld.blur();
        window.scrollTo(0, 0);  // iOS 12 laat de pagina anders verschoven staan
        // Het gesprek komt live binnen (SSE); zonder live-verbinding even ophalen.
        api('/api/gesprek').then(function (g) { if (g.status === 200) { toonGesprek(g.data); } });
      } else {
        $('invoerFout').textContent = (r.data && r.data.fout && r.data.fout.melding) || 'Versturen is mislukt.';
      }
    }).catch(function () {
      $('verstuur').disabled = false;
      $('invoerFout').textContent = 'Geen verbinding met JARVIS.';
    });
  }

  // ----- timers -----
  function toonTimers(lijst) {
    staat.timers = Array.isArray(lijst) ? lijst : [];
    var nu = Date.now() / 1000;
    staat.timers.forEach(function (t) {
      if (!staat.timerStart[t.id]) { staat.timerStart[t.id] = Math.max(1, t.af_loopt_op - nu); }
    });
    tekenTimers();
  }

  function tekenTimers() {
    var doos = $('timers');
    leeg(doos);
    staat.timerDelen = {};
    var nu = Date.now() / 1000;
    var actief = staat.timers.filter(function (t) { return t.af_loopt_op > nu; });
    if (!actief.length) {
      doos.appendChild(el('div', 'leeg', 'Geen actieve timers.'));
      return;
    }
    var lijst = el('div', 'timers');
    actief.forEach(function (t) {
      var rest = t.af_loopt_op - nu;
      if (staat.timerVraag === t.id) {
        var vraag = el('div', 'timer-vraag');
        vraag.appendChild(el('span', '', '“' + t.naam + '” annuleren?'));
        var knoppen = el('div', '');
        var nee = el('button', '', 'Nee');
        nee.type = 'button';
        nee.addEventListener('click', function () { staat.timerVraag = null; tekenTimers(); });
        var ja = el('button', 'ja', 'Ja');
        ja.type = 'button';
        ja.addEventListener('click', function () { annuleerTimer(t.id); });
        knoppen.appendChild(nee);
        knoppen.appendChild(ja);
        vraag.appendChild(knoppen);
        lijst.appendChild(vraag);
        return;
      }
      var rij = el('button', 'timer alleen-bedien');
      rij.type = 'button';
      rij.setAttribute('aria-label', 'Timer ' + t.naam + ', nog ' + mmss(rest) + '. Tik om te annuleren.');
      var kop = el('div', 'timer-kop');
      kop.appendChild(el('span', 'timer-naam', t.naam));
      var tijd = el('span', 'timer-tijd', mmss(rest));
      kop.appendChild(tijd);
      rij.appendChild(kop);
      var balk = el('div', 'timer-balk');
      var vul = el('div');
      vul.style.width = Math.max(0, Math.min(100, rest / staat.timerStart[t.id] * 100)) + '%';
      balk.appendChild(vul);
      rij.appendChild(balk);
      staat.timerDelen[t.id] = { tijd: tijd, vul: vul, af: t.af_loopt_op };
      rij.addEventListener('click', function () {
        if (!magBedienen()) { return; }
        staat.timerVraag = t.id;
        tekenTimers();
      });
      lijst.appendChild(rij);
    });
    doos.appendChild(lijst);
  }

  // Elke seconde alleen tijd en balk bijwerken (geen nieuwe knoppen, zodat
  // een tik nooit verloren gaat). Is er een timer afgelopen: opnieuw tekenen.
  function tikTimers() {
    var nu = Date.now() / 1000;
    var opnieuw = false;
    Object.keys(staat.timerDelen).forEach(function (id) {
      var d = staat.timerDelen[id];
      var rest = d.af - nu;
      if (rest <= 0) { opnieuw = true; return; }
      d.tijd.textContent = mmss(rest);
      d.vul.style.width = Math.max(0, Math.min(100, rest / staat.timerStart[id] * 100)) + '%';
    });
    if (opnieuw) { tekenTimers(); }
  }

  function annuleerTimer(id) {
    api('/api/timers/' + encodeURIComponent(id), { method: 'DELETE' }).then(function () {
      staat.timerVraag = null;
      staat.timers = staat.timers.filter(function (t) { return t.id !== id; });
      tekenTimers();
    });
  }

  // ----- gesprek -----
  // De server stuurt live de laatste GESPREK_PAGINA beurten; oudere haalt
  // de PWA zelf op als u naar boven scrolt (POST /api/gesprek/ouder).
  var GESPREK_PAGINA = 30;
  var MAANDEN = ['jan', 'feb', 'mrt', 'apr', 'mei', 'jun', 'jul', 'aug', 'sep', 'okt', 'nov', 'dec'];

  function dagLabel(d) {
    var nu = new Date();
    var vandaag = new Date(nu.getFullYear(), nu.getMonth(), nu.getDate()).getTime();
    var dag = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    var verschil = Math.round((vandaag - dag) / 86400000);
    if (verschil === 0) { return 'Vandaag'; }
    if (verschil === 1) { return 'Gisteren'; }
    var label = d.getDate() + ' ' + MAANDEN[d.getMonth()];
    return d.getFullYear() === nu.getFullYear() ? label : label + ' ' + d.getFullYear();
  }

  function tweeCijfers(n) { return (n < 10 ? '0' : '') + n; }

  // Nieuwe live-beurten samenvoegen met wat er al (ook ouder) getoond wordt.
  function toonGesprek(beurten) {
    if (!Array.isArray(beurten)) { return; }
    if (!beurten.length) {
      staat.gesprek = [];
      staat.gesprekMeer = false;
    } else {
      var plek = -1;
      for (var i = 0; i < staat.gesprek.length; i++) {
        if (staat.gesprek[i].id === beurten[0].id) { plek = i; break; }
      }
      if (plek >= 0) {
        staat.gesprek = staat.gesprek.slice(0, plek).concat(beurten);
      } else {
        staat.gesprek = beurten.slice();
        staat.gesprekMeer = beurten.length >= GESPREK_PAGINA;
      }
    }
    tekenGesprek(false);
  }

  function laadOuderGesprek() {
    if (staat.gesprekLaadt || !staat.gesprekMeer || !staat.gesprek.length) { return; }
    staat.gesprekLaadt = true;
    tekenGesprek(true);
    api('/api/gesprek/ouder', { method: 'POST', body: { voor: staat.gesprek[0].id } }).then(function (r) {
      staat.gesprekLaadt = false;
      if (r.status === 200 && r.data && Array.isArray(r.data.beurten)) {
        staat.gesprek = r.data.beurten.concat(staat.gesprek);
        staat.gesprekMeer = !!r.data.meer;
      }
      tekenGesprek(true);
    }).catch(function () {
      staat.gesprekLaadt = false;
      tekenGesprek(true);
    });
  }

  // behoud = de beurten die u nu ziet op hun plek houden (bij een oudere
  // pagina erboven). Anders: onderaan blijven als u al onderaan was.
  function tekenGesprek(behoud) {
    var doos = $('chatlog');
    var onderaan = !staat.gesprekGetekend || doos.scrollHeight - doos.scrollTop - doos.clientHeight < 40;
    var hoogteVoor = doos.scrollHeight;
    var topVoor = doos.scrollTop;
    leeg(doos);
    if (!staat.gesprek.length) {
      var welkom = el('div', 'ai');
      welkom.appendChild(el('div', '', 'Goedendag, Sir. Het gesprek verschijnt hier zodra u met JARVIS praat.'));
      doos.appendChild(welkom);
    } else if (staat.gesprekMeer) {
      var meer = el('button', 'gesprek-meer', staat.gesprekLaadt ? 'Oudere berichten laden…' : 'Oudere berichten');
      meer.type = 'button';
      meer.addEventListener('click', laadOuderGesprek);
      doos.appendChild(meer);
    } else {
      doos.appendChild(el('div', 'gesprek-begin', 'Begin van het gesprek (JARVIS bewaart 30 dagen)'));
    }
    var vorigeDag = null;
    staat.gesprek.forEach(function (b) {
      var d = typeof b.tijd === 'number' ? new Date(b.tijd * 1000) : null;
      if (d) {
        var dag = dagLabel(d);
        if (dag !== vorigeDag) { doos.appendChild(el('div', 'dag', dag)); vorigeDag = dag; }
      }
      var bel = el('div', b.wie === 'me' ? 'me' : 'ai');
      bel.appendChild(el('div', '', b.tekst));
      if (d) { bel.appendChild(el('span', 'tijd', tweeCijfers(d.getHours()) + ':' + tweeCijfers(d.getMinutes()))); }
      doos.appendChild(bel);
    });
    if (behoud) {
      doos.scrollTop = doos.scrollHeight - hoogteVoor + topVoor;
    } else if (onderaan) {
      doos.scrollTop = doos.scrollHeight;
    }
    staat.gesprekGetekend = true;
  }

  function scrolGesprek() {
    if ($('chatlog').scrollTop < 60) { laadOuderGesprek(); }
  }

  // Twee keer tikken: eerst "Echt wissen?", binnen 4 seconden nog eens.
  function wisGesprek() {
    if (!magBedienen()) { return; }
    var knop = $('gesprekWis');
    if (!staat.wisVraag) {
      knop.textContent = 'Echt wissen?';
      knop.classList.add('gevaar');
      staat.wisVraag = setTimeout(stopWisVraag, 4000);
      return;
    }
    stopWisVraag();
    api('/api/gesprek/wissen', { method: 'POST', body: {} }).then(function (r) {
      if (r.status === 200) {
        staat.gesprek = [];
        staat.gesprekMeer = false;
        tekenGesprek(false);
      }
    });
  }

  function stopWisVraag() {
    clearTimeout(staat.wisVraag);
    staat.wisVraag = null;
    $('gesprekWis').textContent = 'Wissen';
    $('gesprekWis').classList.remove('gevaar');
  }

  // ----- auditlog -----
  function toonAudit(regels) {
    var doos = $('audit');
    leeg(doos);
    if (!Array.isArray(regels) || !regels.length) {
      doos.appendChild(el('div', 'leeg', 'Nog geen acties.'));
      return;
    }
    regels.slice(0, 5).forEach(function (r) {
      var rij = el('div', 'log');
      rij.appendChild(el('span', 't', r.tijd));
      rij.appendChild(el('span', 'n', r.actie));
      var risico = String(r.risico || 'LOW').toUpperCase();
      rij.appendChild(el('span', 'r ' + risico.toLowerCase(), risico));
      rij.appendChild(el('span', 's ' + (r.goedgekeurd ? 'ok' : 'nee'), r.goedgekeurd ? '✓ gelukt' : r.resultaat));
      doos.appendChild(rij);
    });
  }

  // ----- systeem (meters) -----
  function kiesDoel(doel) {
    staat.doel = doel;
    Array.prototype.forEach.call($('doel').querySelectorAll('button'), function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-doel') === doel));
    });
    leeg($('meters'));
    $('meters').appendChild(el('div', 'leeg', 'Meters worden geladen…'));
    delete staat.laatst.meters;
    $('powerFout').textContent = '';
    zetPowerKnoppen();
    laadMeters();
  }

  function laadMeters() {
    var doel = staat.doel;
    api('/api/pc-status/' + doel).then(function (r) {
      if (doel !== staat.doel || !veranderd('meters', [doel, r.status, r.data])) { return; }
      var doos = $('meters');
      leeg(doos);
      var brein = doel === 'local' && r.data && r.data.brein;
      if (r.status !== 200 || !r.data || !r.data.beschikbaar) {
        doos.appendChild(el('div', 'leeg', (r.data && r.data.melding) || 'Meters niet beschikbaar.'));
        if (brein) { doos.appendChild(breinRegel(brein)); }
        return;
      }
      r.data.meters.forEach(function (m) {
        var blok = el('div');
        var rij = el('div', 'row');
        rij.appendChild(el('span', 'dim', m.naam));
        var waarde = m.waarde === null || m.waarde === undefined ? '—' : m.waarde + m.eenheid;
        rij.appendChild(el('span', 'num meter-waarde' + (m.hoog ? ' hoog' : ''), waarde));
        blok.appendChild(rij);
        var balk = el('div', 'bar');
        var vul = el('div', m.hoog ? 'hoog' : '');
        vul.style.width = (m.procent || 0) + '%';
        balk.appendChild(vul);
        blok.appendChild(balk);
        doos.appendChild(blok);
      });
      if (brein) { doos.appendChild(breinRegel(brein)); }
    }).catch(function () {});
  }

  // Hoe lang JARVIS al draait en of de waakhond hem bewaakt (Fase 19, M2).
  function duur(minuten) {
    if (minuten < 60) { return minuten + ' min'; }
    var uren = Math.floor(minuten / 60);
    if (uren < 48) { return uren + ' u ' + (minuten % 60) + ' min'; }
    return Math.floor(uren / 24) + ' dagen';
  }

  function breinRegel(b) {
    var blok = el('div', 'brein');
    var tekst = 'JARVIS actief ' + duur(b.actief_minuten || 0);
    if (b.bewaakt) {
      tekst += ' · bewaakt · ' + b.herstarts + (b.herstarts === 1 ? ' herstart' : ' herstarts');
    } else {
      tekst += ' · niet bewaakt';
    }
    blok.appendChild(el('div', 'dim', tekst));
    if (b.laatste_herstart) {
      blok.appendChild(el('div', 'dim', 'Laatste herstart ' + b.laatste_herstart.tijd + ': ' + b.laatste_herstart.reden));
    }
    var bk = b.backup;
    if (bk && bk.ingeschakeld) {
      // Fase 19, M3: de laatste backup; oranje als hij mislukt of te oud is.
      var bkTekst;
      if (bk.ok === false) {
        bkTekst = 'Backup mislukt' + (bk.fout ? ': ' + bk.fout : '');
      } else if (!bk.laatste) {
        bkTekst = 'Nog geen backup';
      } else {
        bkTekst = 'Backup ' + bk.laatste + (bk.verouderd ? ' (te oud)' : ' ✓');
      }
      var probleem = bk.ok === false || (bk.laatste && bk.verouderd);
      blok.appendChild(el('div', probleem ? 'waarschuwing' : 'dim', bkTekst));
    }
    var ai = b.ai_brein;
    if (ai && ai.brein) {
      // Fase 25, M2: Gemini, of Ollama als terugval (oranje bij een storing).
      var aiTekst;
      if (ai.brein === 'gemini') {
        aiTekst = 'AI: Gemini ✓';
      } else {
        aiTekst = 'AI: Ollama' + (ai.reden ? ' (' + ai.reden + (ai.tot ? ', tot ' + ai.tot : '') + ')' : '');
      }
      var aiStoring = ai.brein !== 'gemini' && ai.reden && ai.reden !== 'geen Gemini-sleutel';
      blok.appendChild(el('div', aiStoring ? 'waarschuwing' : 'dim', aiTekst));
    }
    var kp = Array.isArray(b.koppelingen) ? b.koppelingen : [];
    if (kp.length) {
      // Fase 23, M1: welke accounts gekoppeld zijn; oranje bij een probleem.
      var kpProbleem = kp.filter(function (k) { return k.gekoppeld && k.probleem; });
      var kpTekst = 'Koppelingen: ' + kp.map(function (k) {
        return k.naam + (!k.gekoppeld ? ' –' : (k.probleem ? ' !' : ' ✓'));
      }).join(' · ');
      if (kpProbleem.length) {
        kpTekst += ' (' + kpProbleem.map(function (k) { return k.naam + ': ' + k.probleem; }).join('; ') + ')';
      }
      blok.appendChild(el('div', kpProbleem.length ? 'waarschuwing' : 'dim', kpTekst));
    }
    var up = b.updates;
    if (up && up.ingeschakeld && up.beschikbaar > 0) {
      // Fase 19, M6: er is een nieuwe versie; installeren gaat via de overlay.
      var upRij = el('div', 'update-rij');
      upRij.appendChild(el('div', 'waarschuwing',
        'Update: ' + up.beschikbaar + (up.beschikbaar === 1 ? ' wijziging' : ' wijzigingen') +
        (up.wijzigingen && up.wijzigingen.length ? ' (' + up.wijzigingen.slice(0, 2).join('; ') + ')' : '')));
      var knop = el('button', 'knop alleen-bedien', 'Installeren…');
      knop.type = 'button';
      knop.addEventListener('click', vraagUpdate);
      upRij.appendChild(knop);
      blok.appendChild(upRij);
    }
    return blok;
  }

  function vraagUpdate() {
    if (!magBedienen()) { return; }
    // De server zet een goedkeuring klaar; de overlay verschijnt via SSE.
    api('/api/update', { method: 'POST', body: {} }).then(function (r) {
      if (r.status === 202) { laadPending(); }
    });
  }

  // ----- power: uit / aan / herstart / slaap -----
  // Uit, herstart en slaap: de server zet een goedkeuring klaar en de
  // overlay verschijnt via SSE. Aan (Wake-on-LAN) en annuleren gaan direct.
  function vraagPower(actie) {
    if (!magBedienen()) { return; }
    $('powerFout').textContent = '';
    var body = { actie: actie };
    if (actie !== 'annuleer') { body.doel = staat.doel; }
    api('/api/power', { method: 'POST', body: body }).then(function (r) {
      if (r.status === 202) {
        laadPending();
      } else if (r.status === 200) {
        if (actie === 'aan') { $('powerFout').textContent = 'De game-pc wordt aangezet…'; }
        if (actie === 'annuleer') { toonAfsluiting(null); }
      } else {
        $('powerFout').textContent = (r.data && r.data.fout && r.data.fout.melding) || 'Dat lukte niet.';
      }
    }).catch(function () {
      $('powerFout').textContent = 'Geen verbinding met JARVIS.';
    });
  }

  // Welke knoppen er zijn: Aan alleen voor de game-pc; staat die uit, dan
  // kan hij alleen aan, staat hij aan, dan kan Aan niet.
  function zetPowerKnoppen() {
    var gamePc = staat.doel === 'game-pc';
    var online = staat.gamePcOnline;
    Array.prototype.forEach.call($('powerKnoppen').querySelectorAll('button'), function (b) {
      var actie = b.getAttribute('data-power');
      if (actie === 'aan') {
        b.hidden = !gamePc;
        b.disabled = gamePc && online === true;
      } else {
        b.disabled = gamePc && online === false;
      }
    });
  }

  function laadGamePcStip() {
    api('/api/pc-status/game-pc').then(function (r) {
      var online = r.status === 200 && !!(r.data && r.data.beschikbaar);
      if (staat.gamePcOnline === online) { return; }
      staat.gamePcOnline = online;
      var stip = $('gamePcStip');
      stip.className = 'pc-stip ' + (online ? 'aan' : 'uit');
      stip.parentNode.setAttribute('title', online ? 'Game-PC staat aan' : 'Game-PC staat uit');
      zetPowerKnoppen();
    }).catch(function () {});
  }

  // Na een ja op uit/herstart: zolang Windows aftelt een Annuleren-knop.
  function toonAfsluiting(a) {
    var knop = $('annuleerKnop');
    if (!a) { knop.hidden = true; return; }
    var waar = a.doel === 'game-pc' ? ' (game-pc)' : ' (deze pc)';
    knop.textContent = (a.actie === 'restart' ? 'Herstart annuleren' : 'Afsluiten annuleren') + waar;
    knop.hidden = false;
  }

  // ----- media -----
  function laadMedia() {
    if (staat.schuift) { return; }  // niet terugspringen tijdens het schuiven
    api('/api/media').then(function (r) {
      if (staat.schuift || !veranderd('media', [r.status, r.data])) { return; }
      var doos = $('media');
      leeg(doos);
      var data = r.status === 200 && r.data ? r.data : {};
      var apps = Array.isArray(data.apps) ? data.apps : [];
      apps.forEach(function (a) { doos.appendChild(mediaRij(a, data.uitleg)); });
      if (!apps.length) { doos.appendChild(el('div', 'leeg', 'Geen media-gegevens.')); }
    }).catch(function () {});
  }

  // Eén app (Spotify) met een schuif voor het volume in de app zelf.
  function mediaRij(a, uitleg) {
    var blok = el('div', 'media-rij');
    var rij = el('div', 'row');
    rij.appendChild(el('span', 'naam', a.naam));
    var getal = el('span', 'num', a.actief ? a.volume + '%' : '');
    rij.appendChild(getal);
    blok.appendChild(rij);

    if (!a.actief) {
      blok.appendChild(el('div', 'media-uitleg', uitleg || 'Speelt nu niet'));
      return blok;
    }

    var schuif = document.createElement('input');
    schuif.type = 'range';
    schuif.min = '0';
    schuif.max = '100';
    schuif.step = '1';
    schuif.value = String(a.volume);
    schuif.className = 'schuif alleen-bedien';
    schuif.disabled = !magBedienen();
    schuif.setAttribute('aria-label', 'Volume van ' + a.naam);
    var start = function () { staat.schuift = true; };
    schuif.addEventListener('touchstart', start);
    schuif.addEventListener('mousedown', start);
    schuif.addEventListener('input', function () {
      staat.schuift = true;
      getal.textContent = schuif.value + '%';
    });
    schuif.addEventListener('change', function () {
      var waarde = parseInt(schuif.value, 10);
      api('/api/media', { method: 'POST', body: { actie: 'app_volume', app: a.naam, waarde: waarde } })
        .then(function (r) {
          staat.schuift = false;
          if (r.status !== 200) {
            getal.textContent = (r.data && r.data.fout && r.data.fout.melding) ? '!' : '';
            schuif.title = (r.data && r.data.fout && r.data.fout.melding) || '';
          }
          delete staat.laatst.media;
          laadMedia();
        })
        .catch(function () { staat.schuift = false; });
    });
    blok.appendChild(schuif);
    return blok;
  }

  function media(actie) {
    if (!magBedienen()) { return; }
    api('/api/media', { method: 'POST', body: { actie: actie } }).then(laadMedia);
  }

  // ----- slim huis -----
  function laadSlimHuis() {
    api('/api/ha/status').then(function (r) {
      if (!veranderd('slimhuis', [r.status, r.data])) { return; }
      var doos = $('tegels');
      leeg(doos);
      if (r.status !== 200 || !r.data) { return; }
      if (!r.data.beschikbaar) {
        doos.appendChild(el('div', 'leeg', 'Home Assistant is niet bereikbaar.'));
      }
      r.data.tegels.forEach(function (t) {
        var tegel = el('button', 'tile' + (t.aan ? ' aan' : '') + (t.domein === 'light' ? ' lamp' : '') +
          (t.tikbaar ? ' alleen-bedien' : ''));
        tegel.type = 'button';
        tegel.disabled = !t.tikbaar;
        tegel.setAttribute('aria-pressed', String(!!t.aan));
        var top = el('div', 'top');
        top.appendChild(icoon(ICONEN[t.domein === 'light' ? 'lamp' : t.domein] || ICONEN.switch));
        top.appendChild(el('span', 'label', t.label));
        tegel.appendChild(top);
        var onder = el('div');
        onder.appendChild(el('div', 'naam', t.naam));
        onder.appendChild(el('div', 'detail', t.detail));
        tegel.appendChild(onder);
        if (t.tikbaar) {
          tegel.addEventListener('click', function () {
            if (!magBedienen()) { return; }
            // Een lamp die meer kan dan aan/uit: eerst het lampvenster.
            if (t.lamp && (t.lamp.dimbaar || t.lamp.warmte || t.lamp.kleur)) { openLamp(t); return; }
            tegel.classList.add('bezig');
            api('/api/ha/actie', { method: 'POST', body: { id: t.id } }).then(laadSlimHuis);
          });
        }
        doos.appendChild(tegel);
      });
      doos.appendChild(plusTegel());
    }).catch(function () {});
  }

  // ----- één lamp instellen (Fase 20, M2) -----
  // Dezelfde namen als LAMP_KLEUREN in dashboard/bronnen.py; de kleur hier is
  // alleen voor het rondje op het scherm.
  var LAMP_KLEUREN = [
    ['rood', '#ff3030'], ['oranje', '#ff8a1e'], ['geel', '#ffd21e'], ['groen', '#2ed06a'],
    ['cyaan', '#30d0ff'], ['blauw', '#3a5cff'], ['paars', '#9a3cff'], ['roze', '#ff4fa8']
  ];

  function openLamp(t) {
    staat.lamp = t;
    $('lampTitel').textContent = String(t.naam || 'Lamp').toUpperCase();
    $('lampFout').textContent = '';
    $('lampAanUit').textContent = t.aan ? 'Uitzetten' : 'Aanzetten';
    $('lampHelderheidBlok').hidden = !t.lamp.dimbaar;
    $('lampWarmteBlok').hidden = !t.lamp.warmte;
    $('lampKleurBlok').hidden = !t.lamp.kleur;
    var procent = t.lamp.helderheid || 100;
    $('lampHelderheid').value = String(procent);
    $('lampProcent').textContent = t.aan ? procent + '%' : 'uit';
    $('lampVenster').hidden = false;
  }

  function stuurLamp(instelling) {
    if (!staat.lamp || !magBedienen()) { return; }
    var body = { id: staat.lamp.id };
    Object.keys(instelling).forEach(function (k) { body[k] = instelling[k]; });
    $('lampFout').textContent = '';
    api('/api/ha/lamp', { method: 'POST', body: body }).then(function (r) {
      if (r.status === 200) {
        staat.lamp.aan = true;
        $('lampAanUit').textContent = 'Uitzetten';
        laadSlimHuis();
      } else {
        $('lampFout').textContent = (r.data && r.data.fout && r.data.fout.melding) || 'Instellen is mislukt.';
      }
    });
  }

  function lampKnoppen() {
    var doos = $('lampKleuren');
    leeg(doos);
    LAMP_KLEUREN.forEach(function (k) {
      var knop = el('button', 'lamp-kleur');
      knop.type = 'button';
      knop.style.background = k[1];  // CSSOM, geen inline style (CSP)
      knop.setAttribute('aria-label', 'Kleur ' + k[0]);
      knop.addEventListener('click', function () { stuurLamp({ kleur: k[0] }); });
      doos.appendChild(knop);
    });
    Array.prototype.forEach.call($('lampWarmte').querySelectorAll('button'), function (b) {
      b.addEventListener('click', function () { stuurLamp({ warmte: b.getAttribute('data-warmte') }); });
    });
    var schuif = $('lampHelderheid');
    schuif.addEventListener('input', function () { $('lampProcent').textContent = schuif.value + '%'; });
    // "change" komt pas bij loslaten: één verzoek per schuifbeweging.
    schuif.addEventListener('change', function () { stuurLamp({ helderheid: parseInt(schuif.value, 10) }); });
    $('lampAanUit').addEventListener('click', function () {
      if (!staat.lamp || !magBedienen()) { return; }
      api('/api/ha/actie', { method: 'POST', body: { id: staat.lamp.id } }).then(function (r) {
        if (r.status === 200) {
          staat.lamp.aan = !staat.lamp.aan;
          $('lampAanUit').textContent = staat.lamp.aan ? 'Uitzetten' : 'Aanzetten';
          $('lampProcent').textContent = staat.lamp.aan ? schuif.value + '%' : 'uit';
          laadSlimHuis();
        }
      });
    });
    $('lampSluit').addEventListener('click', function () { $('lampVenster').hidden = true; staat.lamp = null; });
  }

  // ----- routines starten (Fase 20, M2) -----
  function laadRoutines() {
    api('/api/routines').then(function (r) {
      if (!veranderd('routines', [r.status, r.data])) { return; }
      var doos = $('routines');
      leeg(doos);
      var lijst = r.status === 200 && Array.isArray(r.data) ? r.data : [];
      if (!lijst.length) { doos.appendChild(el('div', 'leeg', 'Nog geen routines.')); return; }
      lijst.forEach(function (routine) {
        var naam = String(routine.naam || routine.id);
        var knop = el('button', 'knop routine alleen-bedien', naam.charAt(0).toUpperCase() + naam.slice(1));
        knop.type = 'button';
        if (routine.beschrijving) { knop.title = routine.beschrijving; }
        knop.addEventListener('click', function () {
          if (!magBedienen()) { return; }
          knop.classList.add('bezig');
          api('/api/routines/start', { method: 'POST', body: { naam: routine.id } }).then(function (a) {
            knop.classList.remove('bezig');
            if (a.status !== 202) {
              $('invoerFout').textContent = (a.data && a.data.fout && a.data.fout.melding) || 'Starten is mislukt.';
            }
          });
        });
        doos.appendChild(knop);
      });
    }).catch(function () {});
  }

  // ----- slim huis aanpassen ("+"-tegel) -----
  var DOMEIN_NAAM = {
    light: 'Lamp', 'switch': 'Schakelaar', button: 'Knop', cover: 'Rolluik', climate: 'Klimaat',
    media_player: 'Mediaspeler', fan: 'Ventilator', sensor: 'Sensor', binary_sensor: 'Melder'
  };

  function plusTegel() {
    var tegel = el('button', 'tile plus alleen-bedien');
    tegel.type = 'button';
    tegel.setAttribute('aria-label', 'Apparaten op het dashboard aanpassen');
    tegel.appendChild(el('div', 'plus-teken', '+'));
    tegel.appendChild(el('div', 'detail', 'Aanpassen'));
    tegel.addEventListener('click', function () { if (magBedienen()) { openSlimHuisEditor(); } });
    return tegel;
  }

  function openSlimHuisEditor() {
    $('shFout').textContent = 'Laden…';
    $('shEditor').hidden = false;
    staat.sh = { gekozen: [], beschikbaar: [], filter: staat.sh ? staat.sh.filter : 'light' };
    tekenSlimHuisEditor();
    api('/api/ha/apparaten').then(function (r) {
      if (r.status !== 200 || !r.data) { $('shFout').textContent = 'Kon de apparaten niet laden.'; return; }
      staat.sh.gekozen = r.data.gekozen || [];
      staat.sh.beschikbaar = r.data.beschikbaar || [];
      $('shFout').textContent = r.data.beschikbaar_ha ? '' : 'Home Assistant is niet bereikbaar; u kunt alleen verwijderen.';
      tekenSlimHuisEditor();
    }).catch(function () { $('shFout').textContent = 'Geen verbinding met JARVIS.'; });
  }

  function shRij(item, knoppen) {
    var rij = el('div', 'sh-rij');
    var tekst = el('div', 'sh-tekst');
    tekst.appendChild(el('div', 'naam', item.naam));
    tekst.appendChild(el('div', 'soort', DOMEIN_NAAM[item.domein] || item.domein));
    rij.appendChild(tekst);
    knoppen.forEach(function (k) {
      var b = el('button', 'pijl' + (k.cls ? ' ' + k.cls : ''), k.tekst);
      b.type = 'button';
      b.setAttribute('aria-label', k.label);
      b.disabled = !!k.uit;
      b.addEventListener('click', k.doe);
      rij.appendChild(b);
    });
    return rij;
  }

  function tekenSlimHuisEditor() {
    var sh = staat.sh;
    var links = $('shGekozen');
    leeg(links);
    if (!sh.gekozen.length) { links.appendChild(el('div', 'leeg', 'Nog geen apparaten.')); }
    sh.gekozen.forEach(function (item, i) {
      links.appendChild(shRij(item, [
        { tekst: '▲', label: item.naam + ' omhoog', uit: i === 0, doe: function () { shVerschuif(i, -1); } },
        { tekst: '▼', label: item.naam + ' omlaag', uit: i === sh.gekozen.length - 1, doe: function () { shVerschuif(i, 1); } },
        { tekst: '✕', label: item.naam + ' verwijderen', cls: 'weg', doe: function () {
          sh.gekozen.splice(i, 1);
          sh.beschikbaar.push(item);
          tekenSlimHuisEditor();
        } }
      ]));
    });

    Array.prototype.forEach.call($('shFilter').querySelectorAll('button'), function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-filter') === sh.filter));
    });
    var rechts = $('shBeschikbaar');
    leeg(rechts);
    var lijst = sh.beschikbaar.filter(function (a) {
      if (sh.filter === 'overig') { return a.domein !== 'light' && a.domein !== 'switch' && a.domein !== 'button'; }
      if (sh.filter === 'switch') { return a.domein === 'switch' || a.domein === 'button'; }
      return a.domein === sh.filter;
    });
    if (!lijst.length) { rechts.appendChild(el('div', 'leeg', 'Niets meer om toe te voegen.')); }
    lijst.forEach(function (item) {
      rechts.appendChild(shRij(item, [
        { tekst: '+', label: item.naam + ' toevoegen', cls: 'erbij', uit: sh.gekozen.length >= 24, doe: function () {
          sh.beschikbaar = sh.beschikbaar.filter(function (a) { return a.id !== item.id; });
          sh.gekozen.push(item);
          tekenSlimHuisEditor();
        } }
      ]));
    });
  }

  function shVerschuif(i, richting) {
    var lijst = staat.sh.gekozen;
    var j = i + richting;
    if (j < 0 || j >= lijst.length) { return; }
    var tijdelijk = lijst[i];
    lijst[i] = lijst[j];
    lijst[j] = tijdelijk;
    tekenSlimHuisEditor();
  }

  function slaSlimHuisOp() {
    if (!magBedienen() || !staat.sh) { return; }
    $('shOpslaan').disabled = true;
    var ids = staat.sh.gekozen.map(function (a) { return a.id; });
    api('/api/ha/apparaten', { method: 'PUT', body: { apparaten: ids } }).then(function (r) {
      $('shOpslaan').disabled = false;
      if (r.status === 200) {
        $('shEditor').hidden = true;
        delete staat.laatst.slimhuis;
        laadSlimHuis();
      } else {
        $('shFout').textContent = (r.data && r.data.fout && r.data.fout.melding) || 'Opslaan is mislukt.';
      }
    }).catch(function () { $('shOpslaan').disabled = false; });
  }

  // ----- weer -----
  function laadWeer() {
    api('/api/weer').then(function (r) {
      var w = r.data || {};
      $('weerTitel').textContent = w.plaats ? 'Weer · ' + w.plaats : 'Weer';
      if (r.status !== 200 || !w.beschikbaar) {
        $('weerTemp').textContent = '--°';
        $('weerOms').textContent = 'Geen weerbericht';
        return;
      }
      $('weerTemp').textContent = (w.temperatuur === null ? '--' : w.temperatuur) + '°';
      var oms = w.beschrijving || '';
      if (w.max !== null && w.min !== null && w.max !== undefined) { oms += ' · ' + w.max + '° / ' + w.min + '°'; }
      $('weerOms').textContent = oms;
    }).catch(function () {});
  }

  // ----- Vandaag (Fase 23, M7): agenda, belangrijke mail, nieuwe DM's -----
  function laadVandaag() {
    api('/api/vandaag').then(function (r) {
      if (r.status === 200 && r.data) { tekenVandaag(r.data); }
    }).catch(function () {});
  }

  var VD_STATUS = {
    niet_ingesteld: 'Niet gekoppeld',
    niet_gekoppeld: 'Niet gekoppeld',
    niet_gebruikt: 'Game-pc niet in gebruik',
    uit: 'Game-pc staat uit',
    fout: 'Nu niet bereikbaar'
  };

  function vdRij(kop, aantal, opvallend) {
    var rij = el('div', 'vd-rij');
    var k = el('div', 'vd-kop', kop);
    if (aantal) { k.appendChild(el('span', 'vd-aantal' + (opvallend ? ' let' : ''), aantal)); }
    rij.appendChild(k);
    var lijst = el('div', 'vd-lijst');
    rij.appendChild(lijst);
    return { rij: rij, lijst: lijst };
  }

  function vdRegel(lijst, cls, delen) {
    var r = el('div', 'vd-regel' + (cls ? ' ' + cls : ''));
    delen.forEach(function (d) {
      if (typeof d === 'string') { r.appendChild(document.createTextNode(d)); } else { r.appendChild(d); }
    });
    lijst.appendChild(r);
  }

  function tekenVandaag(d) {
    var doos = $('vandaag');
    leeg(doos);
    // Agenda: eerst wat nog komt (hooguit 3), dan de vertrektijd.
    var ag = d.agenda || {};
    var afspraken = ag.afspraken || [];
    var komend = afspraken.filter(function (a) { return !a.voorbij; });
    var agenda = vdRij('AGENDA', ag.status === 'ok' && afspraken.length ? afspraken.length + (ag.meer || 0) : 0);
    if (ag.status !== 'ok') {
      vdRegel(agenda.lijst, 'stil', [VD_STATUS[ag.status] || 'Onbekend']);
    } else if (!afspraken.length) {
      vdRegel(agenda.lijst, 'stil', ['Geen afspraken']);
    } else {
      (komend.length ? komend : afspraken).slice(0, 3).forEach(function (a) {
        var tijd = el('span', 'vd-tijd', a.hele_dag ? 'dag' : a.tijd);
        vdRegel(agenda.lijst, a.voorbij ? 'voorbij' : '', [tijd, a.titel + (a.plaats ? ' · ' + a.plaats : '')]);
      });
      if (!komend.length) { vdRegel(agenda.lijst, 'stil', ['Alles is voorbij']); }
    }
    if (ag.vertrek) {
      vdRegel(agenda.lijst, 'vertrek', ['Vertrek ' + ag.vertrek.om + ' · ' + ag.vertrek.minuten + ' min rijden']);
    }
    doos.appendChild(agenda.rij);
    // Deadlines (Fase 26): vandaag en de komende dagen; oranje als het
    // vandaag of morgen af moet.
    var dl = d.deadlines || {};
    var dls = dl.deadlines || [];
    var dringend = dls.some(function (x) { return x.dagen <= 1; });
    var deadlines = vdRij('DEADLINES', dls.length + (dl.meer || 0), dringend);
    if (dl.status !== 'ok') {
      vdRegel(deadlines.lijst, 'stil', [VD_STATUS[dl.status] || 'Onbekend']);
    } else if (!dls.length) {
      vdRegel(deadlines.lijst, 'stil', ['Geen deadlines deze week']);
    } else {
      dls.slice(0, 3).forEach(function (x) {
        vdRegel(deadlines.lijst, x.dagen <= 1 ? 'dringend' : '', [el('span', 'vd-wanneer', x.wanneer), x.titel]);
      });
    }
    doos.appendChild(deadlines.rij);
    // Mail: alleen de belangrijke, ongelezen.
    var ml = d.mail || {};
    var mail = vdRij('MAIL', ml.aantal, true);
    if (ml.status !== 'ok') {
      vdRegel(mail.lijst, 'stil', [VD_STATUS[ml.status] || 'Onbekend']);
    } else if (!ml.aantal) {
      vdRegel(mail.lijst, 'stil', ['Geen belangrijke mail']);
    } else {
      (ml.mails || []).slice(0, 2).forEach(function (m) {
        vdRegel(mail.lijst, '', [el('span', 'vd-van', m.van + ': '), m.onderwerp]);
      });
    }
    doos.appendChild(mail.rij);
    // Discord: nieuwe DM's (het paneel markeert niets als gelezen).
    var dc = d.discord || {};
    var discord = vdRij('DISCORD', dc.aantal, true);
    if (dc.status !== 'ok') {
      vdRegel(discord.lijst, 'stil', [VD_STATUS[dc.status] || 'Onbekend']);
    } else if (!dc.aantal) {
      vdRegel(discord.lijst, 'stil', ['Geen nieuwe DM’s']);
    } else {
      (dc.dms || []).slice(-2).forEach(function (m) {
        vdRegel(discord.lijst, '', [el('span', 'vd-van', m.van + ': '), m.tekst]);
      });
    }
    doos.appendChild(discord.rij);
  }

  // ----- goedkeuring -----
  function laadPending() {
    api('/api/pending').then(function (r) { if (r.status === 200) { toonPending(r.data); } });
  }

  function toonPending(p) {
    staat.pending = p && p.id ? p : null;
    staat.pendingOntvangen = Date.now();
    var overlay = $('goedkeuring');
    if (!staat.pending) { overlay.hidden = true; return; }
    var keuzes = p.keuzes || [];
    var correctie = p.soort === 'commando_correctie';
    $('gkTitel').textContent = correctie ? 'BEDOELDE U…?' : 'GOEDKEURING NODIG';
    if (correctie) {
      // Fase 24: "Bedoelde u…?" — de vraag groot, wat u zei eronder.
      $('gkVraag').textContent = keuzes.length > 1 ? 'Bedoelde u…?' : p.actie;
      $('gkUitleg').textContent = 'U zei: "' + p.vraag + '"';
    } else {
      $('gkVraag').textContent = p.vraag || p.actie;
      var delen = ['Actie: ' + p.actie];
      if (p.argumenten && p.argumenten.target) { delen.push('doel: ' + p.argumenten.target); }
      delen.push('risico: ' + String(p.risico).toUpperCase());
      $('gkUitleg').textContent = delen.join(' · ');
    }
    tekenKeuzes(correctie && keuzes.length > 1 ? keuzes : []);
    $('gkJa').hidden = correctie && keuzes.length > 1;
    $('gkJa').textContent = correctie ? 'Ja' : 'Ja, doorgaan';
    $('gkNee').textContent = correctie ? (keuzes.length > 1 ? 'Geen van deze' : 'Nee') : 'Annuleer';
    $('gkFout').textContent = magBedienen() ? '' : 'Alleen een bedien-apparaat kan dit goedkeuren.';
    zetKnoppen(!magBedienen());
    overlay.hidden = false;
    tekenAftel();
  }

  // Eén knop per kandidaat; een tik kiest hem (besluit "ja" + keuze).
  function tekenKeuzes(keuzes) {
    var doos = $('gkKeuzes');
    while (doos.firstChild) { doos.removeChild(doos.firstChild); }
    for (var i = 0; i < keuzes.length; i++) {
      var knop = document.createElement('button');
      knop.type = 'button';
      knop.className = 'knop primair';
      knop.textContent = (i + 1) + '. ' + keuzes[i];
      knop.addEventListener('click', (function (index) {
        return function () { beslis('ja', index); };
      })(i));
      doos.appendChild(knop);
    }
    doos.hidden = keuzes.length === 0;
  }

  function zetKnoppen(uit) {
    $('gkJa').disabled = uit;
    $('gkNee').disabled = uit;
    var knoppen = $('gkKeuzes').getElementsByTagName('button');
    for (var i = 0; i < knoppen.length; i++) { knoppen[i].disabled = uit; }
  }

  function tekenAftel() {
    var p = staat.pending;
    if (!p) { return; }
    var rest = Math.max(0, (p.resterende_seconden || 0) - (Date.now() - staat.pendingOntvangen) / 1000);
    $('gkTijd').textContent = mmss(rest);
    var totaal = p.verloopt_op ? Math.max(1, p.resterende_seconden || 1) : 1;
    $('gkBalk').style.width = Math.min(100, rest / totaal * 100) + '%';
    if (rest <= 0) { $('goedkeuring').hidden = true; staat.pending = null; }
  }

  function beslis(besluit, keuze) {
    var p = staat.pending;
    if (!p || !magBedienen()) { return; }
    zetKnoppen(true);
    var body = { id: p.id, nonce: p.nonce, besluit: besluit };
    if (typeof keuze === 'number') { body.keuze = keuze; }
    api('/api/goedkeuring', { method: 'POST', body: body })
      .then(function (r) {
        if (r.status === 200) {
          $('goedkeuring').hidden = true;
          staat.pending = null;
        } else {
          $('gkFout').textContent = (r.data && r.data.fout && r.data.fout.melding) || 'Dat lukte niet.';
          if (r.status === 409 || r.status === 410) {
            setTimeout(function () { $('goedkeuring').hidden = true; staat.pending = null; }, 1500);
          } else {
            zetKnoppen(false);
          }
        }
      });
  }

  // ----- meldingen -----
  // ----- nieuwe melding: banner + geluidje (Fase 20, M6) -----
  // iOS laat pas geluid toe na een tik; de eerste tik ergens ontgrendelt het.
  function ontgrendelGeluid() {
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (staat.geluid || !Ctx) { return; }
    try {
      staat.geluid = new Ctx();
      var stil = staat.geluid.createBuffer(1, 1, 22050);
      var bron = staat.geluid.createBufferSource();
      bron.buffer = stil;
      bron.connect(staat.geluid.destination);
      bron.start(0);
    } catch (e) { staat.geluid = null; return; }
    // Eén keer laten zien (en horen) dat het werkt.
    if (staat.meldingenTonen && staat.meldGeluid && !staat.nachtAan) {
      toonBanner('Geluid voor meldingen staat aan.');
      speelGong();
    }
  }

  function stuurTestmelding() {
    if (!magBedienen()) { return; }
    ontgrendelGeluid();
    $('instellingen').hidden = true;
    api('/api/notifications/test', { method: 'POST', body: {} }).then(function (r) {
      // Komt hij niet live binnen (geen SSE), dan hier ophalen.
      if (r.status === 200) { setTimeout(laadMeldingen, 1500); }
    });
  }

  function speelGong() {
    var ctx = staat.geluid;
    if (!ctx) { return; }
    if (ctx.state === 'suspended' && ctx.resume) { ctx.resume(); }
    [[880, 0], [1320, 0.16]].forEach(function (t) {
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      var begin = ctx.currentTime + t[1];
      osc.frequency.value = t[0];
      gain.gain.setValueAtTime(0.0001, begin);
      gain.gain.exponentialRampToValueAtTime(0.18, begin + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, begin + 0.35);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(begin);
      osc.stop(begin + 0.4);
    });
  }

  function toonBanner(tekst) {
    var banner = $('banner');
    banner.textContent = tekst;
    banner.hidden = false;
    if (staat.bannerTimer) { clearTimeout(staat.bannerTimer); }
    staat.bannerTimer = setTimeout(function () { banner.hidden = true; }, 8000);
  }

  function nieuweMeldingen(lijst) {
    var eerste = staat.gezien === null;
    if (eerste) { staat.gezien = {}; }
    var nieuw = [];
    lijst.forEach(function (m) {
      if (!staat.gezien[m.id]) {
        staat.gezien[m.id] = true;
        if (!eerste && !m.gelezen) { nieuw.push(m); }
      }
    });
    // Bij het openen van de app niets afspelen: alleen wat er nu bijkomt.
    if (!nieuw.length || !staat.meldingenTonen) { return; }
    toonBanner(nieuw[nieuw.length - 1].tekst);
    if (staat.meldGeluid && !staat.nachtAan) { speelGong(); }
  }

  function laadMeldingen() {
    api('/api/notifications').then(function (r) {
      if (r.status !== 200 || !r.data) { return; }
      staat.meldingen = r.data.meldingen || [];
      nieuweMeldingen(staat.meldingen);
      var ongelezen = r.data.ongelezen || 0;
      $('meldingKnop').hidden = ongelezen === 0 || !staat.meldingenTonen;
      $('meldingKnop').textContent = ongelezen + (ongelezen === 1 ? ' melding' : ' meldingen');
      if (!$('meldingen').hidden) { tekenMeldingen(); }
    }).catch(function () {});
  }

  function tekenMeldingen() {
    var doos = $('meldingLijst');
    leeg(doos);
    if (!staat.meldingen.length) { doos.appendChild(el('div', 'leeg', 'Geen meldingen.')); }
    staat.meldingen.forEach(function (m) {
      var item = el('div', 'melding-item' + (m.gelezen ? '' : ' nieuw'));
      item.appendChild(el('div', '', m.tekst));
      var tijd = m.aangemaakt_op ? new Date(m.aangemaakt_op * 1000).toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' }) : '';
      item.appendChild(el('div', 'tijd', tijd));
      doos.appendChild(item);
    });
    $('mGelezen').disabled = !magBedienen();
  }

  function meldingenGelezen() {
    if (!magBedienen()) { return; }
    api('/api/notifications/lees', { method: 'POST', body: {} }).then(laadMeldingen);
  }

  // ----- layout uit config/dashboard.json (M5) -----
  function laadWidgets() {
    api('/api/widgets').then(function (r) {
      if (r.status === 200 && r.data) { pasLayoutToe(r.data); }
    }).catch(function () {});
  }

  function pasLayoutToe(config) {
    staat.widgets = config;
    var kolommen = (config && config.kolommen) || {};
    Object.keys(PANELEN).forEach(function (kolom) {
      var doos = $('kol-' + kolom);
      var bestaand = PANELEN[kolom].map(function (p) { return p[0]; });
      var zichtbaar = (Array.isArray(kolommen[kolom]) ? kolommen[kolom] : bestaand)
        .filter(function (id) { return bestaand.indexOf(id) !== -1; });
      // Eerst de zichtbare in de gekozen volgorde, dan de verborgen.
      zichtbaar.concat(bestaand.filter(function (id) { return zichtbaar.indexOf(id) === -1; }))
        .forEach(function (id) {
          var paneel = doos.querySelector('[data-widget="' + id + '"]');
          if (!paneel) { return; }
          paneel.hidden = zichtbaar.indexOf(id) === -1;
          doos.appendChild(paneel);
        });
    });
    var inst = (config && config.instellingen) || {};
    staat.meldingenTonen = inst.meldingen !== false;
    staat.meldGeluid = inst.meldgeluid !== false;
    zetHardop(inst.hardop === true);
    laadMeldingen();
  }

  // ----- instellingenscherm (M5) -----
  // ----- routines maken en aanpassen (Fase 27, M1) -----
  var RE_SOORT = {
    open: { hint: 'bijv. Discord' },
    sluit: { hint: 'bijv. Spotify' },
    volume: { hint: '0 tot 100' },
    lamp: { hint: 'bijv. bedlamp op 30%' },
    tv_aan: { hint: '' },
    tv_uit: { hint: '' },
    spotify: { hint: 'wat afspelen (leeg = muziek)' },
    scene: { hint: 'naam van de scène' },
    opdracht: { hint: 'wat JARVIS moet doen' }
  };

  function laadRoutinesInst() {
    $('instRoutineInfo').textContent = '';
    api('/api/routines/bewerken').then(function (r) {
      if (r.status !== 200 || !r.data) {
        leeg($('instRoutines'));
        $('instRoutines').appendChild(el('div', 'dim', 'Routines konden niet geladen worden.'));
        return;
      }
      staat.routinesBewerken = r.data.routines || [];
      tekenRoutinesInst();
    });
  }

  function tekenRoutinesInst() {
    var doos = $('instRoutines');
    leeg(doos);
    var lijst = staat.routinesBewerken || [];
    if (!lijst.length) { doos.appendChild(el('div', 'dim', 'Nog geen routines.')); }
    lijst.forEach(function (r) {
      var rij = el('div', 'inst-routine');
      var links = el('span', '');
      links.appendChild(el('span', 'naam', r.naam));
      links.appendChild(el('span', 'dim', r.stappen.length + (r.stappen.length === 1 ? ' stap' : ' stappen')));
      rij.appendChild(links);
      var knop = el('button', 'knop klein alleen-bedien', r.bewerkbaar ? 'Bewerken' : 'Vast');
      knop.type = 'button';
      knop.disabled = !r.bewerkbaar || !magBedienen();
      knop.addEventListener('click', function () { openRoutineEditor(r); });
      rij.appendChild(knop);
      doos.appendChild(rij);
    });
    $('instNieuweRoutine').disabled = !magBedienen();
  }

  function openRoutineEditor(routine) {
    var r = routine || { naam: '', protocollen: [], start_zin: '', eind_zin: '', vertrouwd: false, stappen: [] };
    staat.routineConcept = {
      oude_naam: routine ? routine.naam : null,
      vertrouwd: !!r.vertrouwd,
      stappen: r.stappen.map(function (s) { return JSON.parse(JSON.stringify(s)); }),
      verwijderVraag: false
    };
    $('reTitel').textContent = routine ? 'ROUTINE BEWERKEN' : 'NIEUWE ROUTINE';
    $('reNaam').value = r.naam;
    $('reProtocollen').value = (r.protocollen || []).join(', ');
    $('reStart').value = r.start_zin || '';
    $('reEind').value = r.eind_zin || '';
    $('reVerwijder').hidden = !routine;
    $('reVerwijder').textContent = 'Verwijderen…';
    $('reFout').textContent = '';
    $('reWaarde').value = '';
    toonSoortHint();
    toonVertrouwd();
    tekenStappen();
    $('routineEditor').hidden = false;
  }

  function toonVertrouwd() {
    var aan = staat.routineConcept.vertrouwd;
    $('reVertrouwd').setAttribute('aria-pressed', String(aan));
    $('reVertrouwd').textContent = aan ? 'Aan' : 'Uit';
  }

  function toonSoortHint() {
    var soort = $('reSoort').value;
    var hint = (RE_SOORT[soort] || {}).hint;
    $('reWaarde').placeholder = hint || '';
    $('reWaarde').disabled = !hint;
    if (!hint) { $('reWaarde').value = ''; }
  }

  function stapTekst(s) {
    if (s.soort === 'open') { return 'Open ' + s.programma; }
    if (s.soort === 'sluit') { return 'Sluit ' + s.programma; }
    if (s.soort === 'volume') { return 'Volume op ' + s.procent + '%'; }
    if (s.soort === 'opdracht') { return 'Zeg: “' + s.tekst + '”'; }
    return 'Bestaande stap: ' + (s.omschrijving || s.tool_name);
  }

  function tekenStappen() {
    var lijst = $('reStappen');
    leeg(lijst);
    var stappen = staat.routineConcept.stappen;
    if (!stappen.length) { lijst.appendChild(el('li', 'dim', 'Nog geen stappen.')); }
    stappen.forEach(function (s, i) {
      var li = el('li', 're-stap');
      var rij = el('div', 're-stap-rij');
      rij.appendChild(el('span', 'tekst' + (s.soort === 'bestaand' ? ' vast' : ''), stapTekst(s)));
      [['↑', -1], ['↓', 1]].forEach(function (k) {
        var b = el('button', '', k[0]);
        b.type = 'button';
        b.setAttribute('aria-label', k[1] < 0 ? 'Omhoog' : 'Omlaag');
        b.disabled = (k[1] < 0 && i === 0) || (k[1] > 0 && i === stappen.length - 1);
        b.addEventListener('click', function () { verplaatsStap(i, k[1]); });
        rij.appendChild(b);
      });
      var weg = el('button', '', '✕');
      weg.type = 'button';
      weg.setAttribute('aria-label', 'Stap verwijderen');
      weg.addEventListener('click', function () { stappen.splice(i, 1); tekenStappen(); });
      rij.appendChild(weg);
      li.appendChild(rij);
      lijst.appendChild(li);
    });
  }

  function verplaatsStap(i, richting) {
    var stappen = staat.routineConcept.stappen;
    var j = i + richting;
    if (j < 0 || j >= stappen.length) { return; }
    var tmp = stappen[i];
    stappen[i] = stappen[j];
    stappen[j] = tmp;
    tekenStappen();
  }

  function nieuweStap() {
    var soort = $('reSoort').value;
    var w = $('reWaarde').value.replace(/^\s+|\s+$/g, '');
    if (soort === 'open' || soort === 'sluit') {
      return w ? { soort: soort, programma: w } : 'Vul de naam van het programma in.';
    }
    if (soort === 'volume') {
      var p = parseInt(w, 10);
      return (String(p) === w && p >= 0 && p <= 100) ? { soort: 'volume', procent: p } : 'Het volume is een getal van 0 tot 100.';
    }
    if (soort === 'tv_aan') { return { soort: 'opdracht', tekst: 'zet de tv aan' }; }
    if (soort === 'tv_uit') { return { soort: 'opdracht', tekst: 'zet de tv uit' }; }
    if (soort === 'spotify') { return { soort: 'opdracht', tekst: 'speel ' + (w || 'muziek') + ' op spotify' }; }
    if (!w) { return 'Vul in wat de stap moet doen.'; }
    if (soort === 'lamp') { return { soort: 'opdracht', tekst: 'zet ' + w }; }
    if (soort === 'scene') { return { soort: 'opdracht', tekst: 'activeer scene ' + w }; }
    return { soort: 'opdracht', tekst: w };
  }

  function voegStapToe() {
    var stap = nieuweStap();
    if (typeof stap === 'string') { $('reFout').textContent = stap; return; }
    if (staat.routineConcept.stappen.length >= 20) { $('reFout').textContent = 'Hooguit 20 stappen.'; return; }
    $('reFout').textContent = '';
    staat.routineConcept.stappen.push(stap);
    $('reWaarde').value = '';
    tekenStappen();
  }

  function opslaanRoutine() {
    if (!magBedienen()) { return; }
    var c = staat.routineConcept;
    var body = {
      oude_naam: c.oude_naam,
      naam: $('reNaam').value,
      protocollen: $('reProtocollen').value.split(',').map(function (p) { return p.replace(/^\s+|\s+$/g, ''); })
        .filter(function (p) { return p; }),
      start_zin: $('reStart').value,
      eind_zin: $('reEind').value,
      vertrouwd: c.vertrouwd,
      stappen: c.stappen
    };
    $('reOpslaan').disabled = true;
    api('/api/routines/opslaan', { method: 'POST', body: body }).then(function (r) {
      $('reOpslaan').disabled = false;
      if (r.status === 200) {
        $('routineEditor').hidden = true;
        $('instRoutineInfo').textContent = 'Routine “' + r.data.routine.naam + '” opgeslagen.';
        laadRoutinesInst();
        laadRoutines();
      } else {
        $('reFout').textContent = (r.data && r.data.fout && r.data.fout.melding) || 'Opslaan lukte niet.';
      }
    });
  }

  function verwijderRoutine() {
    var c = staat.routineConcept;
    if (!magBedienen() || !c.oude_naam) { return; }
    if (!c.verwijderVraag) {
      c.verwijderVraag = true;
      $('reVerwijder').textContent = 'Zeker verwijderen?';
      return;
    }
    api('/api/routines/verwijder', { method: 'POST', body: { naam: c.oude_naam } }).then(function (r) {
      if (r.status === 200) {
        $('routineEditor').hidden = true;
        $('instRoutineInfo').textContent = 'Routine “' + c.oude_naam + '” verwijderd.';
        laadRoutinesInst();
        laadRoutines();
      } else {
        $('reFout').textContent = (r.data && r.data.fout && r.data.fout.melding) || 'Verwijderen lukte niet.';
      }
    });
  }

  function openInstellingen() {
    var kolommen = (staat.widgets && staat.widgets.kolommen) || {};
    staat.concept = { meldingen: staat.meldingenTonen, meldgeluid: staat.meldGeluid, kolommen: {} };
    Object.keys(PANELEN).forEach(function (kolom) {
      var zichtbaar = Array.isArray(kolommen[kolom]) ? kolommen[kolom] : PANELEN[kolom].map(function (p) { return p[0]; });
      var lijst = [];
      zichtbaar.forEach(function (id) {
        var def = PANELEN[kolom].filter(function (p) { return p[0] === id; })[0];
        if (def) { lijst.push({ id: id, naam: def[1], aan: true }); }
      });
      PANELEN[kolom].forEach(function (p) {
        if (zichtbaar.indexOf(p[0]) === -1) { lijst.push({ id: p[0], naam: p[1], aan: false }); }
      });
      staat.concept.kolommen[kolom] = lijst;
    });
    staat.ontkoppelVraag = false;
    $('instOntkoppel').textContent = 'Ontkoppelen…';
    $('instFout').textContent = magBedienen() ? '' : 'Alleen een bedien-apparaat kan de indeling opslaan.';
    $('instOpslaan').disabled = !magBedienen();
    $('instRol').textContent = 'Gekoppeld als ' + (staat.rol === 'bedien' ? 'bedien-apparaat' : 'alleen kijken');
    tekenInstellingen();
    $('instellingen').hidden = false;
    laadVersie();
    laadRoutinesInst();
    laadPatronenInst();
  }

  // ----- geleerde gewoontes (Fase 29, M4) -----
  var DAGTYPE = { werkdag: 'doordeweeks', weekend: 'weekend', focus: 'bij de focus' };

  function laadPatronenInst() {
    api('/api/patronen').then(function (r) {
      if (r.status !== 200 || !r.data) {
        leeg($('instPatronen'));
        $('instPatronen').appendChild(el('div', 'dim', 'Gewoontes konden niet geladen worden.'));
        return;
      }
      tekenPatronenInst(r.data.patronen || []);
    });
  }

  function patroonActie(id, actie) {
    api('/api/patronen', { method: 'POST', body: { id: id, actie: actie } }).then(function (r) {
      if (r.status === 200 && r.data) { tekenPatronenInst(r.data.patronen || []); } else { laadPatronenInst(); }
    });
  }

  function tekenPatronenInst(lijst) {
    var doos = $('instPatronen');
    leeg(doos);
    if (!lijst.length) { doos.appendChild(el('div', 'dim', 'Nog geen vaste gewoontes geleerd.')); }
    lijst.forEach(function (p) {
      var rij = el('div', 'inst-routine inst-patroon');
      var links = el('span', '');
      links.appendChild(el('span', 'naam', p.label.charAt(0).toUpperCase() + p.label.slice(1)));
      var wanneer = (DAGTYPE[p.dagtype] || '') + (p.tijd ? ' rond ' + p.tijd : '') + ' · ' + p.dagen + ' dagen';
      if (p.stil_tot) { wanneer += ' · stil tot ' + p.stil_tot.split('-').reverse().join('-'); }
      links.appendChild(el('span', 'dim', wanneer));
      rij.appendChild(links);
      var knoppen = el('span', 'inst-patroon-knoppen');
      var schakel = el('button', 'schakel alleen-bedien', p.aan ? 'Aan' : 'Uit');
      schakel.type = 'button';
      schakel.setAttribute('aria-pressed', String(!!p.aan));
      schakel.disabled = !magBedienen();
      schakel.addEventListener('click', function () { patroonActie(p.id, p.aan ? 'uit' : 'aan'); });
      var wis = el('button', 'knop klein gevaar alleen-bedien', 'Wissen…');
      wis.type = 'button';
      wis.disabled = !magBedienen();
      wis.addEventListener('click', function () {
        if (wis.getAttribute('data-zeker') === '1') { patroonActie(p.id, 'wissen'); return; }
        wis.setAttribute('data-zeker', '1');
        wis.textContent = 'Zeker wissen?';
      });
      knoppen.appendChild(schakel);
      knoppen.appendChild(wis);
      rij.appendChild(knoppen);
      doos.appendChild(rij);
    });
  }

  // Welke versie van JARVIS draait (Fase 21): commit + datum van git.
  function laadVersie() {
    $('instVersie').textContent = '…';
    $('instVersieTekst').textContent = '';
    api('/api/versie').then(function (r) {
      if (r.status !== 200 || !r.data) {
        $('instVersie').textContent = 'onbekend';
        return;
      }
      var d = r.data;
      $('instVersie').textContent = d.commit + (d.datum ? ' · ' + d.datum : '');
      var tekst = d.omschrijving ? '(' + d.omschrijving + ')' : '';
      if (d.herstart_nodig) {
        tekst = 'Nieuwe versie ' + d.op_schijf + ' gedownload: herstart JARVIS. ' + tekst;
      }
      // De versie van de code op DIT apparaat; wijkt die af van de server,
      // dan draait de iPad nog oude code uit zijn cache.
      tekst += ' · dashboard ' + VERSIE;
      if (d.dashboard && d.dashboard !== VERSIE) {
        tekst += ' (laptop heeft ' + d.dashboard + ': sluit de app en open hem opnieuw)';
      }
      $('instVersieTekst').textContent = tekst;
    });
  }

  function tekenInstellingen() {
    var doos = $('instPanelen');
    leeg(doos);
    Object.keys(PANELEN).forEach(function (kolom) {
      var lijst = staat.concept.kolommen[kolom];
      var blok = el('div', 'inst-kolom');
      blok.appendChild(el('div', 'inst-kolom-naam', KOLOM_NAAM[kolom]));
      lijst.forEach(function (item, i) {
        var rij = el('div', 'inst-paneel' + (item.aan ? '' : ' uit'));
        rij.appendChild(el('span', 'naam', item.naam));
        var op = el('button', 'pijl', '▲');
        op.type = 'button';
        op.setAttribute('aria-label', item.naam + ' omhoog');
        op.disabled = i === 0;
        op.addEventListener('click', function () { verschuif(kolom, i, -1); });
        var neer = el('button', 'pijl', '▼');
        neer.type = 'button';
        neer.setAttribute('aria-label', item.naam + ' omlaag');
        neer.disabled = i === lijst.length - 1;
        neer.addEventListener('click', function () { verschuif(kolom, i, 1); });
        var schakel = el('button', 'schakel', item.aan ? 'Aan' : 'Uit');
        schakel.type = 'button';
        schakel.setAttribute('aria-pressed', String(item.aan));
        schakel.setAttribute('aria-label', item.naam + (item.aan ? ' verbergen' : ' tonen'));
        schakel.addEventListener('click', function () { item.aan = !item.aan; tekenInstellingen(); });
        rij.appendChild(op);
        rij.appendChild(neer);
        rij.appendChild(schakel);
        blok.appendChild(rij);
      });
      doos.appendChild(blok);
    });
    var m = $('instMeldingen');
    m.setAttribute('aria-pressed', String(staat.concept.meldingen));
    m.textContent = staat.concept.meldingen ? 'Aan' : 'Uit';
    var g = $('instMeldGeluid');
    g.setAttribute('aria-pressed', String(staat.concept.meldgeluid));
    g.textContent = staat.concept.meldgeluid ? 'Aan' : 'Uit';
  }

  function verschuif(kolom, i, richting) {
    var lijst = staat.concept.kolommen[kolom];
    var j = i + richting;
    if (j < 0 || j >= lijst.length) { return; }
    var tijdelijk = lijst[i];
    lijst[i] = lijst[j];
    lijst[j] = tijdelijk;
    tekenInstellingen();
  }

  function slaInstellingenOp() {
    if (!magBedienen() || !staat.concept) { return; }
    var basis = staat.widgets || {};
    // Alles van de huidige indeling meenemen (ook de slim-huisknoppen);
    // alleen de panelen en de instellingen uit dit venster veranderen.
    var config = JSON.parse(JSON.stringify(basis));
    config.versie = typeof basis.versie === 'number' ? basis.versie : 1;
    config.kolommen = {};
    config.instellingen = config.instellingen || {};
    config.instellingen.meldingen = staat.concept.meldingen;
    config.instellingen.meldgeluid = staat.concept.meldgeluid;
    Object.keys(PANELEN).forEach(function (kolom) {
      config.kolommen[kolom] = staat.concept.kolommen[kolom]
        .filter(function (item) { return item.aan; })
        .map(function (item) { return item.id; });
    });
    $('instOpslaan').disabled = true;
    api('/api/widgets', { method: 'PUT', body: config }).then(function (r) {
      $('instOpslaan').disabled = false;
      if (r.status === 200) {
        pasLayoutToe(config);
        $('instellingen').hidden = true;
      } else {
        $('instFout').textContent = (r.data && r.data.fout && r.data.fout.melding) || 'Opslaan is mislukt.';
      }
    });
  }

  function vernieuwToken() {
    $('instFout').textContent = '';
    api('/api/tokens/rotatie', { method: 'POST', body: { sessie: true } }).then(function (r) {
      if (r.status === 200) {
        $('instFout').textContent = 'Token vernieuwd. Het oude werkt niet meer.';
      } else if (r.status === 429) {
        $('instFout').textContent = 'Te vaak geprobeerd; wacht even.';
      } else {
        $('instFout').textContent = (r.data && r.data.fout && r.data.fout.melding) || 'Vernieuwen is mislukt.';
      }
    });
  }

  function ontkoppelDezeIpad() {
    if (!staat.ontkoppelVraag) {
      staat.ontkoppelVraag = true;
      $('instOntkoppel').textContent = 'Zeker? Tik nogmaals';
      return;
    }
    api('/api/afmelden', { method: 'POST', body: {} }).then(function (r) {
      if (r.status === 200) {
        $('instellingen').hidden = true;
        ontkoppeld();
      } else {
        $('instFout').textContent = (r.data && r.data.fout && r.data.fout.melding) || 'Ontkoppelen is mislukt.';
      }
    });
  }

  // ----- overzicht (M6): alleen lezen -----
  function openOverzicht() {
    $('overzicht').hidden = false;
    kiesTab(staat.tab || 'logboek');
  }

  function kiesTab(tab) {
    staat.tab = tab;
    Array.prototype.forEach.call($('oTabs').querySelectorAll('button'), function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-tab') === tab));
    });
    leeg($('oInhoud'));
    $('oInfo').textContent = 'Laden…';
    var pad = { logboek: '/api/logs', geheugen: '/api/memory', routines: '/api/routines' }[tab];
    api(pad).then(function (r) {
      if (staat.tab !== tab) { return; }
      if (r.status !== 200 || !r.data) { $('oInfo').textContent = 'Kon dit niet laden.'; return; }
      if (tab === 'logboek') { tekenLogboek(r.data); }
      if (tab === 'geheugen') { tekenGeheugen(r.data); }
      if (tab === 'routines') { tekenRoutines(r.data); }
    }).catch(function () { $('oInfo').textContent = 'Geen verbinding met JARVIS.'; });
  }

  function tekenLogboek(regels) {
    var doos = $('oInhoud');
    $('oInfo').textContent = regels.length ? 'De laatste ' + regels.length + ' regels van logs/jarvis.log, nieuwste bovenaan.' : 'Het logboek is leeg.';
    regels.forEach(function (r) {
      var rij = el('div', 'lograij');
      rij.appendChild(el('span', 't', r.tijd));
      rij.appendChild(el('span', 'niv ' + String(r.niveau || '').toLowerCase(), r.niveau));
      rij.appendChild(el('span', 'bron', r.bron));
      rij.appendChild(el('span', 'tekst', r.tekst));
      doos.appendChild(rij);
    });
  }

  function tekenGeheugen(g) {
    var doos = $('oInhoud');
    $('oInfo').textContent = g.totaal ? g.totaal + ' feiten in het geheugen; de recentst bijgewerkte staan bovenaan.' : 'Het geheugen is nog leeg.';
    var chips = el('div', 'chips');
    (g.categorieen || []).forEach(function (c) { chips.appendChild(el('span', 'chip', c.naam + ' · ' + c.aantal)); });
    doos.appendChild(chips);
    (g.items || []).forEach(function (i) {
      var rij = el('div', 'geh-rij');
      rij.appendChild(el('span', 'cat', i.categorie));
      rij.appendChild(el('span', 'sleutel', i.sleutel));
      rij.appendChild(el('span', 'waarde', i.waarde));
      rij.appendChild(el('span', 'wanneer', i.bijgewerkt));
      doos.appendChild(rij);
    });
  }

  function tekenRoutines(lijst) {
    var doos = $('oInhoud');
    $('oInfo').textContent = lijst.length ? 'Routines starten gaat via de stem (vanaf het dashboard in Fase 20).' : 'Er zijn nog geen routines.';
    lijst.forEach(function (r) {
      var kaart = el('div', 'routine');
      var kop = el('div', 'routine-kop');
      var naam = el('span', 'routine-naam', r.naam);
      if (r.vertrouwd) { naam.appendChild(el('span', 'vertrouwd', 'VERTROUWD')); }
      kop.appendChild(naam);
      kop.appendChild(el('span', 'routine-gebruik', r.gebruikt + '× gebruikt' + (r.laatst_gebruikt ? ' · laatst ' + r.laatst_gebruikt : '')));
      kaart.appendChild(kop);
      if (r.beschrijving) { kaart.appendChild(el('div', 'routine-oms', r.beschrijving)); }
      var stappen = el('ol', 'routine-stappen');
      (r.stappen || []).forEach(function (s) { stappen.appendChild(el('li', '', s)); });
      kaart.appendChild(stappen);
      doos.appendChild(kaart);
    });
  }

  // ----- live: SSE met terugval op polling -----
  function stopPolling() {
    if (staat.pollTimer) { clearInterval(staat.pollTimer); staat.pollTimer = null; }
  }

  function poll() {
    if (document.hidden) { return; }  // op de achtergrond niets vragen
    api('/api/status').then(function (r) {
      netwerkOk();
      if (r.status === 200) {
        zetVerbonden(true, 'Online (zonder live-verbinding)');
        toonStatus(r.data);
        // Mislukte /api/sessie bij het laden (bijv. JARVIS startte net
        // opnieuw na een update), dan is er nog geen rol: nu opnieuw vragen.
        if (!staat.rol) { haalSessie(); }
        herstelLive();
      } else if (r.status === 429) {
        // Even te veel verzoeken (bijv. Safari én de beginscherm-app open):
        // de server is er wel, dus niet "verbroken" tonen; gewoon wachten.
      } else if (r.status !== 401) {
        zetVerbonden(false);
      }
    }).catch(netwerkFout);
  }

  // Was de server even weg (bijv. een herstart door de waakhond), dan geeft
  // Safari de live-verbinding soms definitief op (CLOSED). Alleen díe weer
  // openen, met een oplopende pauze (5 s tot 1 min), zodat er nooit een
  // stortvloed aan verzoeken ontstaat.
  function herstelLive() {
    if (!staat.bron || staat.bron.readyState !== 2) { return; }
    var nu = Date.now();
    if (nu < (staat.liveVolgende || 0)) { return; }
    staat.liveWacht = Math.min((staat.liveWacht || 2500) * 2, 60000);
    staat.liveVolgende = nu + staat.liveWacht;
    openLive();
  }

  function startPolling() {
    if (!staat.pollTimer) {
      poll();
      staat.pollTimer = setInterval(poll, POLL_MS);
    }
  }

  function laadTegels() {
    if (document.hidden || !staat.rol) { return; }
    laadMeters();
    laadGamePcStip();
    laadMedia();
    laadSlimHuis();
  }

  function leesData(e) {
    try { return JSON.parse(e.data); } catch (fout) { return null; }
  }

  function verbind() {
    document.body.classList.toggle('rol-kijk', staat.rol === 'kijk');
    // Typen kan alleen met de bedien-rol (Fase 20, M1).
    $('opdracht').disabled = !magBedienen();
    $('verstuur').disabled = !magBedienen();
    $('opdracht').placeholder = magBedienen() ? 'Typ een opdracht voor JARVIS…' : 'Alleen kijken: typen kan niet';
    laadTegels();
    laadWeer();
    laadVandaag();
    laadWidgets();
    laadRoutines();
    if (!staat.tegelTimer) {
      staat.tegelTimer = setInterval(laadTegels, TEGEL_MS);
      setInterval(laadWeer, WEER_MS);
      setInterval(laadVandaag, VANDAAG_MS);
    }

    openLive();
  }

  function openLive() {
    if (staat.bron) { staat.bron.close(); }
    if (!window.EventSource) { startPolling(); return; }

    var bron = new EventSource('/api/events');
    staat.bron = bron;
    bron.onopen = function () {
      staat.liveWacht = 0;
      staat.liveVolgende = 0;
      stopPolling(); netwerkOk(); zetVerbonden(true);
    };
    // Geen "verbroken" meer bij elke hapering van de live-verbinding: de
    // polling hieronder ziet zelf of de server bereikbaar is.
    bron.onerror = function () { startPolling(); };
    bron.addEventListener('status', function (e) { toonStatus(leesData(e)); });
    bron.addEventListener('timer', function (e) { toonTimers(leesData(e)); });
    bron.addEventListener('pending', function (e) { toonPending(leesData(e)); });
    bron.addEventListener('audit', function (e) { toonAudit(leesData(e)); });
    bron.addEventListener('gesprek', function (e) { toonGesprek(leesData(e)); });
    bron.addEventListener('melding', function () { laadMeldingen(); });
  }

  function ontkoppeld() {
    stopPolling();
    if (staat.bron) { staat.bron.close(); staat.bron = null; }
    staat.rol = null;
    zetVerbonden(false, 'Niet gekoppeld');
    toonKoppel();
  }

  // ----- koppelen -----
  function toonKoppel() {
    if (!$('koppel').hidden) { return; }
    $('koppel').hidden = false;
    $('koppelFout').textContent = '';
    $('koppelCode').value = '';
    // Op een touchscreen (iPad) alleen het eigen cijfertoetsenbord: het
    // systeemtoetsenbord verschoof op iOS 12 de pagina en sloot weer.
    if (!isTouch()) { $('koppelCode').focus(); }
  }

  function isTouch() {
    return 'ontouchstart' in window || (navigator.maxTouchPoints || 0) > 0;
  }

  function toets(cijfer) {
    var veld = $('koppelCode');
    var waarde = veld.value.replace(/\D/g, '');
    if (cijfer === 'wis') {
      waarde = '';
    } else if (cijfer === 'terug') {
      waarde = waarde.slice(0, -1);
    } else if (waarde.length < 8) {
      waarde += cijfer;
    }
    veld.value = waarde;
    $('koppelFout').textContent = '';
  }

  function kiesRol(rol) {
    staat.koppelRol = rol;
    Array.prototype.forEach.call($('koppelRol').querySelectorAll('button'), function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-rol') === rol));
    });
  }

  function koppel(e) {
    e.preventDefault();
    var code = $('koppelCode').value.replace(/\D/g, '');
    if (code.length !== 8) {
      $('koppelFout').textContent = 'De koppelcode heeft 8 cijfers.';
      return;
    }
    $('koppelKnop').disabled = true;
    $('koppelFout').textContent = '';
    fetch('/api/pair', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: code, rol: staat.koppelRol, naam: 'iPad' })
    }).then(function (r) {
      return r.json().catch(function () { return null; }).then(function (data) {
        if (r.status === 201) {
          staat.rol = data && data.rol;
          $('koppel').hidden = true;
          verbind();
        } else if (r.status === 429 || r.status === 403) {
          $('koppelFout').textContent = 'Te veel pogingen. Wacht even en vraag een nieuwe code.';
        } else {
          $('koppelFout').textContent = 'De code klopt niet of is verlopen.';
        }
      });
    }).catch(function () { $('koppelFout').textContent = 'Geen verbinding met JARVIS.'; })
      .then(function () { $('koppelKnop').disabled = false; });
  }

  // ----- versie: een oude app (cache) ververst zichzelf -----
  // Op iOS 12 heeft de app op het beginscherm eigen opslag met een eigen
  // service worker. Draait daar nog een oude versie, dan ruimt de app zijn
  // service worker en caches op en herlaadt hij één keer (niet vaker: de
  // vlag in sessionStorage voorkomt een herlaad-lus).
  function controleerVersie() {
    fetch('/api/health', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.versie && data.versie !== VERSIE) { vernieuwApp(data.versie); }
      })
      .catch(function () { /* offline: later opnieuw */ });
  }

  function vernieuwApp(nieuweVersie) {
    var sleutel = 'jarvis-vernieuwd-' + nieuweVersie;
    try {
      if (window.sessionStorage.getItem(sleutel)) { return; }
      window.sessionStorage.setItem(sleutel, '1');
    } catch (fout) { /* geen sessionStorage: toch één keer proberen */ }

    var werk = [];
    if (navigator.serviceWorker && navigator.serviceWorker.getRegistrations) {
      werk.push(navigator.serviceWorker.getRegistrations().then(function (registraties) {
        return Promise.all(registraties.map(function (r) { return r.unregister(); }));
      }));
    }
    if (window.caches && window.caches.keys) {
      werk.push(window.caches.keys().then(function (namen) {
        return Promise.all(namen.map(function (n) { return window.caches.delete(n); }));
      }));
    }
    Promise.all(werk).catch(function () {}).then(function () { window.location.reload(); });
  }

  // ----- start -----
  function knoppen() {
    Array.prototype.forEach.call($('koppelRol').querySelectorAll('button'), function (b) {
      b.addEventListener('click', function () { kiesRol(b.getAttribute('data-rol')); });
    });
    $('koppelForm').addEventListener('submit', koppel);
    Array.prototype.forEach.call($('keypad').querySelectorAll('button'), function (b) {
      b.addEventListener('click', function () { toets(b.getAttribute('data-cijfer')); });
    });
    if (isTouch()) { $('koppelCode').setAttribute('readonly', 'readonly'); }
    $('invoer').addEventListener('submit', verstuurOpdracht);
    lampKnoppen();
    $('opdracht').addEventListener('blur', function () { window.scrollTo(0, 0); });
    $('hardop').addEventListener('click', function () {
      if (!magBedienen()) { return; }
      var aan = $('hardop').getAttribute('aria-pressed') !== 'true';
      zetHardop(aan);
      bewaarHardop(aan);
    });

    Array.prototype.forEach.call($('nacht').querySelectorAll('button'), function (b) {
      b.classList.add('alleen-bedien');
      b.addEventListener('click', function () { zetNacht(b.getAttribute('data-stand')); });
    });
    Array.prototype.forEach.call($('focus').querySelectorAll('button'), function (b) {
      b.addEventListener('click', function () { zetFocus(b); });
    });
    Array.prototype.forEach.call($('doel').querySelectorAll('button'), function (b) {
      b.addEventListener('click', function () { kiesDoel(b.getAttribute('data-doel')); });
    });
    Array.prototype.forEach.call($('powerKnoppen').querySelectorAll('button'), function (b) {
      b.classList.add('alleen-bedien');
      b.addEventListener('click', function () { vraagPower(b.getAttribute('data-power')); });
    });
    $('annuleerKnop').classList.add('alleen-bedien');
    $('annuleerKnop').addEventListener('click', function () { vraagPower('annuleer'); });
    $('gesprekWis').addEventListener('click', wisGesprek);
    $('chatlog').addEventListener('scroll', scrolGesprek);

    var mediaKnoppen = { vorige: 'vorige', speel: 'play_pauze', volgende: 'volgende' };
    Object.keys(mediaKnoppen).forEach(function (id) {
      var b = $(id);
      b.disabled = false;
      b.classList.add('alleen-bedien');
      b.addEventListener('click', function () { media(mediaKnoppen[id]); });
    });

    $('gkJa').addEventListener('click', function () { beslis('ja'); });
    $('gkNee').addEventListener('click', function () { beslis('nee'); });

    $('meldingKnop').addEventListener('click', function () { $('meldingen').hidden = false; tekenMeldingen(); });
    $('mSluit').addEventListener('click', function () { $('meldingen').hidden = true; });
    $('mGelezen').addEventListener('click', meldingenGelezen);

    $('instellingenKnop').addEventListener('click', function () { if (staat.rol) { openInstellingen(); } });
    $('instAnnuleer').addEventListener('click', function () { $('instellingen').hidden = true; });
    $('instNieuweRoutine').addEventListener('click', function () { openRoutineEditor(null); });
    $('reSoort').addEventListener('change', toonSoortHint);
    $('reVoegToe').addEventListener('click', voegStapToe);
    $('reVertrouwd').addEventListener('click', function () {
      staat.routineConcept.vertrouwd = !staat.routineConcept.vertrouwd;
      toonVertrouwd();
    });
    $('reOpslaan').addEventListener('click', opslaanRoutine);
    $('reVerwijder').addEventListener('click', verwijderRoutine);
    $('reAnnuleer').addEventListener('click', function () { $('routineEditor').hidden = true; });
    $('instOpslaan').addEventListener('click', slaInstellingenOp);
    $('instMeldingen').addEventListener('click', function () {
      staat.concept.meldingen = !staat.concept.meldingen;
      tekenInstellingen();
    });
    $('instTestMelding').addEventListener('click', stuurTestmelding);
    $('instMeldGeluid').addEventListener('click', function () {
      staat.concept.meldgeluid = !staat.concept.meldgeluid;
      tekenInstellingen();
    });
    $('banner').addEventListener('click', function () {
      $('banner').hidden = true;
      $('meldingKnop').click();
    });
    // De eerste tik ergens ontgrendelt het geluid (iOS).
    document.addEventListener('touchend', ontgrendelGeluid);
    document.addEventListener('click', ontgrendelGeluid);
    $('instVernieuw').addEventListener('click', vernieuwToken);
    $('gvOpnieuw').addEventListener('click', function () { window.location.reload(); });
    $('shAnnuleer').addEventListener('click', function () { $('shEditor').hidden = true; });
    $('shOpslaan').addEventListener('click', slaSlimHuisOp);
    Array.prototype.forEach.call($('shFilter').querySelectorAll('button'), function (b) {
      b.addEventListener('click', function () {
        if (staat.sh) { staat.sh.filter = b.getAttribute('data-filter'); tekenSlimHuisEditor(); }
      });
    });

    $('overzichtKnop').addEventListener('click', function () { if (staat.rol) { openOverzicht(); } });
    $('oSluit').addEventListener('click', function () { $('overzicht').hidden = true; });
    $('oVernieuw').addEventListener('click', function () { kiesTab(staat.tab || 'logboek'); });
    Array.prototype.forEach.call($('oTabs').querySelectorAll('button'), function (b) {
      b.addEventListener('click', function () { kiesTab(b.getAttribute('data-tab')); });
    });
    $('instOntkoppel').addEventListener('click', ontkoppelDezeIpad);
  }

  function start() {
    controleerFlexGap();
    pasAan();
    window.addEventListener('resize', pasAan);
    window.addEventListener('orientationchange', naDraaien);
    tik();
    setInterval(tik, 10000);
    // Timers en de goedkeuring tellen lokaal elke seconde af.
    setInterval(function () { tikTimers(); tekenAftel(); tekenFocus(); }, 1000);
    knoppen();
    controleerVersie();
    // Een app op het beginscherm wordt bij terugkeren niet herladen: dan
    // opnieuw de versie controleren.
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) { controleerVersie(); }
    });

    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js').catch(function () { /* zonder vertrouwd certificaat geen SW */ });
    }

    haalSessie();
  }

  // Is dit apparaat gekoppeld, en met welke rol? Lukt het niet, dan pollt
  // de status; die roept dit opnieuw aan zodra de server weer antwoordt.
  function haalSessie() {
    if (staat.sessieBezig) { return; }
    staat.sessieBezig = true;
    api('/api/sessie').then(function (r) {
      staat.sessieBezig = false;
      netwerkOk();
      if (r.status === 200 && r.data && r.data.rol) {
        staat.rol = r.data.rol;
        verbind();
      } else if (r.status === 200) {
        ontkoppeld();
      } else {
        zetVerbonden(false);
        startPolling();
      }
    }).catch(function () {
      staat.sessieBezig = false;
      netwerkFout();
      startPolling();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
