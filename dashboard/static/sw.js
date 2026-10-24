/* Service worker van het JARVIS-dashboard (Fase 18).
 *
 * Cachet alleen de "shell" (HTML, CSS, JS, lettertypen, iconen), zodat het
 * scherm ook zonder verbinding opent. API-verzoeken (/api/*) en het
 * profiel gaan ALTIJD naar het netwerk en worden nooit gecachet: daar zit
 * live- en sessiedata in.
 */
'use strict';

var CACHE = 'jarvis-shell-v4';
var SHELL = [
  '/',
  '/styles.css',
  '/app.js',
  '/manifest.webmanifest',
  '/fonts/orbitron-latin-500-normal.woff2',
  '/fonts/orbitron-latin-700-normal.woff2',
  '/fonts/rajdhani-latin-500-normal.woff2',
  '/fonts/rajdhani-latin-600-normal.woff2',
  '/fonts/rajdhani-latin-700-normal.woff2',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/apple-touch-icon.png'
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

  if (e.request.mode === 'navigate') {
    // Eerst het netwerk (nieuwste versie), anders de gecachte shell.
    e.respondWith(fetch(e.request).catch(function () { return caches.match('/'); }));
    return;
  }

  e.respondWith(caches.match(e.request).then(function (gevonden) {
    var netwerk = fetch(e.request).then(function (antwoord) {
      if (antwoord && antwoord.ok) {
        var kopie = antwoord.clone();
        caches.open(CACHE).then(function (c) { c.put(e.request, kopie); });
      }
      return antwoord;
    });
    return gevonden || netwerk;
  }));
});
