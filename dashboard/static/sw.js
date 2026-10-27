/* Service worker van het JARVIS-dashboard (Fase 18).
 *
 * Eerst het netwerk, de cache alleen als er geen verbinding is. Zo ziet u na
 * een update meteen de nieuwe versie (eerder kwam de oude CSS/JS uit de
 * cache en zag u de update pas bij de tweede keer openen). Thuis op wifi is
 * het netwerk snel genoeg.
 *
 * API-verzoeken (/api/*) en het profiel gaan ALTIJD naar het netwerk en
 * worden nooit gecachet: daar zit live- en sessiedata in.
 */
'use strict';

var CACHE = 'jarvis-shell-23.2';
var SHELL = [
  '/',
  '/styles.css?v=23.2',
  '/app.js?v=23.2',
  '/manifest.webmanifest',
  '/fonts/orbitron-latin-500-normal.woff2',
  '/fonts/orbitron-latin-700-normal.woff2',
  '/fonts/rajdhani-latin-500-normal.woff2',
  '/fonts/rajdhani-latin-600-normal.woff2',
  '/fonts/rajdhani-latin-700-normal.woff2',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/apple-touch-icon.png'
];

self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(SHELL); }).then(function () {
    return self.skipWaiting();
  }));
});

self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (namen) {
    return Promise.all(namen.filter(function (n) { return n !== CACHE; }).map(function (n) {
      return caches.delete(n);
    }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener('fetch', function (e) {
  var url = new URL(e.request.url);
  if (url.origin !== self.location.origin || e.request.method !== 'GET') { return; }
  if (url.pathname.indexOf('/api/') === 0 || url.pathname === '/profiel.mobileconfig') { return; }

  e.respondWith(fetch(e.request).then(function (antwoord) {
    if (antwoord && antwoord.ok) {
      var kopie = antwoord.clone();
      caches.open(CACHE).then(function (c) { c.put(e.request, kopie); });
    }
    return antwoord;
  }).catch(function () {
    // Offline: de gecachte versie, en voor een pagina de shell.
    return caches.match(e.request).then(function (gevonden) {
      return gevonden || (e.request.mode === 'navigate' ? caches.match('/') : undefined);
    });
  }));
});
