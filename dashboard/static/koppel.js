/* Lokale koppelpagina (alleen op de pc zelf; de server weigert
 * /api/koppelcode vanaf elk ander adres). Geen innerHTML: alleen textContent. */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var aftel = null;

  function toonResterend(seconden) {
    if (aftel) { clearInterval(aftel); }
    var over = seconden;
    function zet() {
      if (over <= 0) {
        $('geldig').textContent = 'Verlopen. Vraag een nieuwe code.';
        $('code').textContent = '— — — —';
        clearInterval(aftel);
        return;
      }
      var m = Math.floor(over / 60);
      var s = String(over % 60).padStart(2, '0');
      $('geldig').textContent = 'Nog ' + m + ':' + s + ' geldig.';
      over -= 1;
    }
    zet();
    aftel = setInterval(zet, 1000);
  }

  function nieuweCode() {
    $('nieuw').disabled = true;
    $('fout').textContent = '';
    fetch('/api/koppelcode', { method: 'POST', credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) {
        return r.json().catch(function () { return null; }).then(function (data) {
          if (r.status === 200 && data && data.code) {
            $('code').textContent = data.code.slice(0, 4) + ' ' + data.code.slice(4);
            toonResterend(data.geldig_seconden || 0);
          } else if (r.status === 429) {
            $('fout').textContent = 'Te veel verzoeken. Wacht even.';
          } else {
            $('fout').textContent = 'Dit werkt alleen op de pc zelf (open de pagina via localhost).';
          }
        });
      })
      .catch(function () { $('fout').textContent = 'Geen verbinding met JARVIS.'; })
      .then(function () { $('nieuw').disabled = false; });
  }

  document.addEventListener('DOMContentLoaded', function () {
    $('nieuw').addEventListener('click', nieuweCode);
  });
})();
