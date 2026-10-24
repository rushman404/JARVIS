/* JARVIS-dashboard (Fase 18) — de PWA.
 *
 * Regels (docs/fase18_dashboard_design.md §10.8 en §13.1):
 *  - Gegevens uit de API worden NOOIT als HTML behandeld: geen innerHTML,
 *    insertAdjacentHTML, outerHTML of document.write. Tekst gaat via
 *    textContent, elementen via document.createElement.
 *  - Geen inline code of styles (strikte CSP); alleen klassen en CSSOM.
 *  - Alle verzoeken gaan naar de eigen origin. Het token zit in een
 *    HttpOnly-cookie; dit script ziet het nooit.
 */
(function () {
  'use strict';

  var STAGE_B = 1180;
  var STAGE_H = 820;
  var POLL_MS = 2000;

  var $ = function (id) { return document.getElementById(id); };

  var staat = {
    verbonden: false,
    bron: null,        // EventSource
    pollTimer: null,
    rol: null,
    koppelRol: 'bedien'
  };

  // ----- schalen: de 1180x820-stage past in elk venster -----
  function pasAan() {
    var s = Math.min(window.innerWidth / STAGE_B, window.innerHeight / STAGE_H);
    var stage = $('stage');
    stage.style.transform = 'scale(' + s + ')';
    stage.style.left = Math.max(0, (window.innerWidth - STAGE_B * s) / 2) + 'px';
    stage.style.top = Math.max(0, (window.innerHeight - STAGE_H * s) / 2) + 'px';
  }

  // ----- klok -----
  function tik() {
    var d = new Date();
    $('klok').textContent = d.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' });
    $('datum').textContent = d.toLocaleDateString('nl-NL', { weekday: 'short', day: 'numeric', month: 'short' })
      .replace('.', '').toUpperCase();
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
      return r.json().catch(function () { return null; }).then(function (data) {
        return { status: r.status, data: data };
      });
    });
  }

  // ----- verbindingsstatus in de header -----
  function zetVerbonden(aan, tekst) {
    staat.verbonden = aan;
    $('pil').classList.toggle('offline', !aan);
    $('pilTekst').textContent = tekst || (aan ? 'Online · wake word “Hey JARVIS”' : 'Verbinding verbroken');
  }

  // ----- spraakstatus-orb -----
  var FASES = {
    rust: { label: 'IN RUST', hint: 'Wacht op “Hey JARVIS”', reactor: '' },
    luistert: { label: 'LUISTERT', hint: 'Spreek uw opdracht in', reactor: 'speaking' },
    denkt: { label: 'DENKT NA', hint: 'Plan maken en uitvoeren', reactor: 'thinking' },
    spreekt: { label: 'SPREEKT', hint: 'JARVIS antwoordt', reactor: 'speaking' }
  };

  function toonFase(fase) {
    var f = FASES[fase] ? fase : 'rust';
    var def = FASES[f];
    ['orb', 'orbLabel'].forEach(function (id) {
      var el = $(id);
      Object.keys(FASES).forEach(function (k) { el.classList.remove('fase-' + k); });
      el.classList.add('fase-' + f);
    });
    $('reactor').className = 'ai-reactor' + (def.reactor ? ' ' + def.reactor : '');
    $('orbLabel').textContent = def.label;
    $('orbHint').textContent = def.hint;
    $('orb').setAttribute('aria-label', 'JARVIS: ' + def.label.toLowerCase());
  }

  // ----- nachtmodus (in M3 alleen tonen) -----
  var NACHT_INFO = {
    auto: 'Volgt de vaste tijden.',
    aan: 'Handmatig aan; verloopt bij de volgende vaste overgang.',
    uit: 'Handmatig uit; verloopt bij de volgende vaste overgang.'
  };

  function toonNacht(stand, actief) {
    var knoppen = $('nacht').querySelectorAll('button');
    Array.prototype.forEach.call(knoppen, function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-stand') === stand));
    });
    var info = NACHT_INFO[stand] || '';
    $('nachtInfo').textContent = info + (actief ? ' Nu actief.' : ' Nu niet actief.');
  }

  function toonStatus(s) {
    if (!s || typeof s !== 'object') { return; }
    toonFase(s.fase);
    toonNacht(s.nachtmodus_stand, !!s.nachtmodus);
    var doel = s.pc_target === 'game-pc' ? 'game-pc' : 'local';
    Array.prototype.forEach.call($('doel').querySelectorAll('button'), function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-doel') === doel));
    });
  }

  // ----- live: SSE met terugval op polling -----
  function stopPolling() {
    if (staat.pollTimer) { clearInterval(staat.pollTimer); staat.pollTimer = null; }
  }

  function poll() {
    api('/api/status').then(function (r) {
      if (r.status === 200) {
        zetVerbonden(true, 'Online (zonder live-verbinding)');
        toonStatus(r.data);
      } else if (r.status === 401) {
        ontkoppeld();
      } else {
        zetVerbonden(false);
      }
    }).catch(function () { zetVerbonden(false); });
  }

  function startPolling() {
    if (!staat.pollTimer) {
      poll();
      staat.pollTimer = setInterval(poll, POLL_MS);
    }
  }

  function verbind() {
    if (staat.bron) { staat.bron.close(); }
    if (!window.EventSource) { startPolling(); return; }

    var bron = new EventSource('/api/events');
    staat.bron = bron;

    bron.onopen = function () { stopPolling(); zetVerbonden(true); };
    bron.onerror = function () {
      zetVerbonden(false);
      // De browser probeert het zelf opnieuw; tot dan pollen we. Is de
      // sessie ongeldig, dan ziet poll() dat (401) en tonen we het koppelscherm.
      startPolling();
    };
    bron.addEventListener('status', function (e) { toonStatus(leesData(e)); });
  }

  function leesData(e) {
    try { return JSON.parse(e.data); } catch (fout) { return null; }
  }

  function ontkoppeld() {
    stopPolling();
    if (staat.bron) { staat.bron.close(); staat.bron = null; }
    zetVerbonden(false, 'Niet gekoppeld');
    toonKoppel();
  }

  // ----- koppelen -----
  function toonKoppel() {
    $('koppel').hidden = false;
    $('koppelFout').textContent = '';
    $('koppelCode').value = '';
    $('koppelCode').focus();
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
    api('/api/pair', { method: 'POST', body: { code: code, rol: staat.koppelRol, naam: 'iPad' } })
      .then(function (r) {
        if (r.status === 201) {
          staat.rol = r.data && r.data.rol;
          $('koppel').hidden = true;
          verbind();
        } else if (r.status === 429 || r.status === 403) {
          $('koppelFout').textContent = 'Te veel pogingen. Wacht even en vraag een nieuwe code.';
        } else {
          $('koppelFout').textContent = 'De code klopt niet of is verlopen.';
        }
      })
      .catch(function () { $('koppelFout').textContent = 'Geen verbinding met JARVIS.'; })
      .then(function () { $('koppelKnop').disabled = false; });
  }

  // ----- start -----
  function start() {
    pasAan();
    window.addEventListener('resize', pasAan);
    tik();
    setInterval(tik, 10000);

    Array.prototype.forEach.call($('koppelRol').querySelectorAll('button'), function (b) {
      b.addEventListener('click', function () { kiesRol(b.getAttribute('data-rol')); });
    });
    $('koppelForm').addEventListener('submit', koppel);
    $('invoer').addEventListener('submit', function (e) { e.preventDefault(); });

    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js').catch(function () { /* zonder vertrouwd certificaat geen SW */ });
    }

    api('/api/sessie').then(function (r) {
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
      zetVerbonden(false);
      startPolling();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
