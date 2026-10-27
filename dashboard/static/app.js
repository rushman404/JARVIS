/* JARVIS-dashboard (Fase 18) — de PWA.
 *
 * Regels (docs/fase18_dashboard_design.md §10.8 en §13.1):
 *  - Gegevens uit de API worden NOOIT als HTML behandeld: geen innerHTML,
 *    insertAdjacentHTML, outerHTML of document.write. Tekst gaat via
 *    textContent, elementen via document.createElement.
 *  - Geen inline code of styles (strikte CSP); alleen klassen en CSSOM.
 *  - Alle verzoeken gaan naar de eigen origin. Het token zit in een
 *    HttpOnly-cookie; dit script ziet het nooit.
 *  - Gevaarlijke acties (slaapstand) worden nooit direct uitgevoerd: de
 *    server zet een goedkeuring klaar, die hier als overlay verschijnt.
 */
(function () {
  'use strict';

  // Moet gelijk zijn aan API_VERSIE in dashboard/api.py (een test bewaakt dat).
  var VERSIE = '23.4';

  var STAGE_B = 1180;
  var STAGE_H = 820;
  var POLL_MS = 2000;
  var TEGEL_MS = 5000;
  var WEER_MS = 10 * 60 * 1000;
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
    mislukt: 0           // verzoeken achter elkaar zonder enig antwoord
  };

  // Welke panelen er per kolom bestaan (vaste lijst; de volgorde en
  // zichtbaarheid komen uit config/dashboard.json).
  var PANELEN = {
    links: [['spraakstatus', 'Spraakstatus'], ['timers', 'Timers & wekkers'], ['weer', 'Weer'], ['nachtmodus', 'Nachtmodus']],
    midden: [['gesprek', 'Gesprek'], ['routines', 'Routines'], ['auditlog', 'Auditlog']],
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

  function toonStatus(s) {
    if (!s || typeof s !== 'object') { return; }
    toonFase(s.fase);
    // Fase 20, M1: wat JARVIS nu doet (of net deed), onder de orb.
    if (s.taak) {
      $('orbHint').textContent = s.taak.charAt(0).toUpperCase() + s.taak.slice(1);
    }
    toonNacht(s.nachtmodus_stand, !!s.nachtmodus);
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
  function toonGesprek(beurten) {
    var doos = $('chatlog');
    leeg(doos);
    if (!Array.isArray(beurten) || !beurten.length) {
      var welkom = el('div', 'ai');
      welkom.appendChild(el('div', '', 'Goedendag, Sir. Het gesprek verschijnt hier zodra u met JARVIS praat.'));
      doos.appendChild(welkom);
      return;
    }
    beurten.forEach(function (b) {
      var bel = el('div', b.wie === 'me' ? 'me' : 'ai');
      bel.appendChild(el('div', '', b.tekst));
      doos.appendChild(bel);
    });
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

  function vraagSlaapstand() {
    if (!magBedienen()) { return; }
    // De server zet een goedkeuring klaar; de overlay verschijnt via SSE.
    api('/api/power', { method: 'POST', body: { actie: 'slaap' } }).then(function (r) {
      if (r.status === 202) { laadPending(); }
    });
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

  // ----- goedkeuring -----
  function laadPending() {
    api('/api/pending').then(function (r) { if (r.status === 200) { toonPending(r.data); } });
  }

  function toonPending(p) {
    staat.pending = p && p.id ? p : null;
    staat.pendingOntvangen = Date.now();
    var overlay = $('goedkeuring');
    if (!staat.pending) { overlay.hidden = true; return; }
    $('gkVraag').textContent = p.vraag || p.actie;
    var delen = ['Actie: ' + p.actie];
    if (p.argumenten && p.argumenten.target) { delen.push('doel: ' + p.argumenten.target); }
    delen.push('risico: ' + String(p.risico).toUpperCase());
    $('gkUitleg').textContent = delen.join(' · ');
    $('gkFout').textContent = magBedienen() ? '' : 'Alleen een bedien-apparaat kan dit goedkeuren.';
    $('gkJa').disabled = !magBedienen();
    $('gkNee').disabled = !magBedienen();
    overlay.hidden = false;
    tekenAftel();
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

  function beslis(besluit) {
    var p = staat.pending;
    if (!p || !magBedienen()) { return; }
    $('gkJa').disabled = true;
    $('gkNee').disabled = true;
    api('/api/goedkeuring', { method: 'POST', body: { id: p.id, nonce: p.nonce, besluit: besluit } })
      .then(function (r) {
        if (r.status === 200) {
          $('goedkeuring').hidden = true;
          staat.pending = null;
        } else {
          $('gkFout').textContent = (r.data && r.data.fout && r.data.fout.melding) || 'Dat lukte niet.';
          if (r.status === 409 || r.status === 410) {
            setTimeout(function () { $('goedkeuring').hidden = true; staat.pending = null; }, 1500);
          } else {
            $('gkJa').disabled = false;
            $('gkNee').disabled = false;
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
    laadWidgets();
    laadRoutines();
    if (!staat.tegelTimer) {
      staat.tegelTimer = setInterval(laadTegels, TEGEL_MS);
      setInterval(laadWeer, WEER_MS);
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
    Array.prototype.forEach.call($('doel').querySelectorAll('button'), function (b) {
      b.addEventListener('click', function () { kiesDoel(b.getAttribute('data-doel')); });
    });
    $('slaapKnop').classList.add('alleen-bedien');
    $('slaapKnop').addEventListener('click', vraagSlaapstand);

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
    setInterval(function () { tikTimers(); tekenAftel(); }, 1000);
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

    api('/api/sessie').then(function (r) {
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
