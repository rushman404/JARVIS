"""Brug tussen streaming LLM-tekst en streaming spraak (Fase 17, A3).

Het taalmodel schrijft zijn antwoord in stukjes. :class:`TekstStroom`
neemt die stukjes aan en laat ze door een eigen thread uitspreken via
:func:`voice.speak.speak_stream`. Zo begint JARVIS te praten zodra de
eerste zin compleet is, terwijl het model de rest nog genereert.

De thread start pas bij het eerste stuk tekst. Kwam er niets (bijvoorbeeld
omdat het commando via een tool liep), dan blijft ``gestreamd`` False en
spreekt de hoofdlus het volledige antwoord zelf uit.
"""

import logging
import queue
import threading

from voice.speak import speak_stream

logger = logging.getLogger(__name__)

# Sentinel die de spreekthread laat stoppen met lezen.
_EINDE = object()


class TekstStroom:
    """Spreekt streaming-tekst direct uit (thread + wachtrij).

    ``stop_event`` (optioneel) wordt doorgegeven aan ``speak_stream`` en
    kan het uitspreken tussentijds afbreken (barge-in, Fase 17).
    """

    def __init__(self, stop_event=None):
        self._stop_event = stop_event
        self._queue = queue.Queue()
        self._thread = None
        self.gestreamd = False

    def schrijf(self, tekst):
        """Neemt één tekststukje aan (callback voor de LLM-laag)."""
        if not tekst:
            return

        if self._thread is None:
            self._thread = threading.Thread(
                target=self._spreek,
                name="jarvis-tekststroom",
                daemon=True,
            )
            self._thread.start()

        self.gestreamd = True
        self._queue.put(tekst)

    def _spreek(self):
        """Spreekt de wachtrij uit tot ``sluit_af`` hem sluit."""
        try:
            speak_stream(self._deltas(), self._stop_event)
        except Exception:
            logger.exception("Streaming-spraak is gestopt met een fout")

    def _deltas(self):
        while True:
            item = self._queue.get()
            if item is _EINDE:
                return
            yield item

    def sluit_af(self):
        """Wacht tot alle tekst is uitgesproken (no-op als er niets kwam)."""
        if self._thread is None:
            return
        self._queue.put(_EINDE)
        self._thread.join()
