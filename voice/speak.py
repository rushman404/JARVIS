"""JARVIS spraakuitvoer.

Standaard spreekt JARVIS via **Piper** (lokaal, snel, per zin). Ontbreekt
Piper of het stemmodel, dan valt hij automatisch terug op **pyttsx3**, zodat
JARVIS altijd blijft praten.

Beide paden delen dezelfde microfoon-mute en dezelfde spraak-lock:

- ``_SPEAK_LOCK`` zorgt dat er nooit twee dingen door elkaar klinken
  (de proactieve engine spreekt vanuit een eigen thread).
- De microfoon blijft gedempt zolang JARVIS zelf geluid maakt, zodat hij
  zichzelf niet opneemt.

Naast ``speak()`` (blokkerend) is er ``speak_stream()``: die spreekt tekst
uit terwijl die binnenkomt, zodat JARVIS begint te praten vóór het
taalmodel klaar is met genereren.
"""

import logging
import re
import threading

import numpy as np
import pyttsx3
import sounddevice as sd

import status
from config import BEEP_ENABLED, PIPER_STREAM_MIN_CHARS
from voice import piper_tts

logger = logging.getLogger(__name__)


engine = pyttsx3.init()
voices = engine.getProperty("voices")
dutch_voice = next((v for v in voices if "dutch" in v.name.lower() or "nederlands" in v.name.lower()), None)
if dutch_voice:
    engine.setProperty("voice", dutch_voice.id)
else:
    logger.warning("Geen Nederlandse stem gevonden voor pyttsx3.")

# pyttsx3 is niet thread-safe: de engine deelt microfoon-mute en interne
# state. De proactieve engine (Fase 16) spreekt vanuit een eigen thread,
# dus alle spreek-aanroepen lopen via deze lock zodat JARVIS nooit
# tegelijkertijd twee dingen door elkaar heen uitspreekt.
_SPEAK_LOCK = threading.RLock()

SAMPLE_RATE = 16000

# Huidig spreekvolume (0.0 - 1.0). Geldt voor zowel Piper als pyttsx3 en
# wordt gebruikt voor de nachtmodus (Fase 16).
_volume = 1.0

# Zinseinde voor streaming: punt/vraagteken/uitroepteken (al dan niet
# herhaald), eventueel gevolgd door sluitende aanhalingstekens of haakjes.
_SENTENCE_END = re.compile(r"[.!?…]+[\"'\u2019\u201d)\]]*\s")

# Lange tekst zonder zinseinde wordt hierop afgekapt (bij het laatste
# spatie-teken), zodat JARVIS niet te lang blijft wachten op één stuk.
_MAX_CHUNK_CHARS = 200

# Barge-in (Fase 17, B1): een globaal "stop"-signaal waarmee een
# onderbreking (stem of sneltoets) het uitspreken meteen afbreekt. Wordt aan
# het begin van elke nieuwe spreek-aanroep gewist.
_STOP = threading.Event()

# True zolang JARVIS daadwerkelijk geluid maakt. De barge-in-monitor gebruikt
# dit om alleen tijdens het praten op uw stem te letten.
_spreek_actief = threading.Event()


def set_volume(waarde):
    """Stelt het spreekvolume in (0.0 tot 1.0).

    Wordt gebruikt voor de nachtmodus (Fase 16): 's nachts spreekt
    JARVIS zachter. Ongeldige waarden worden genegeerd.
    """
    global _volume
    try:
        waarde = float(waarde)
    except (TypeError, ValueError):
        return
    _volume = max(0.0, min(1.0, waarde))
    try:
        with _SPEAK_LOCK:
            engine.setProperty("volume", _volume)
    except Exception as error:
        logger.warning("Kon volume niet instellen: %s", error)


def is_speaking():
    """Of JARVIS op dit moment praat (gebruikt door de barge-in-monitor)."""
    return _spreek_actief.is_set()


def stop_speaking():
    """Breekt het huidige spreken meteen af (barge-in).

    Zet het globale stop-signaal en stopt de audio die nu afspeelt, zodat
    JARVIS direct stil is als u hem onderbreekt (Fase 17, B1).
    """
    _STOP.set()
    try:
        sd.stop()
    except Exception:
        pass
    ipad = _ipad_speaker()
    if ipad is not None:
        ipad.stop_afspelen()
    try:
        engine.stop()
    except Exception:
        pass


def _gestopt(stop_event=None):
    """Of het spreken moet stoppen: eigen onderbreking of meegegeven event."""
    if _STOP.is_set():
        return True
    return stop_event is not None and stop_event.is_set()


def _duck():
    """Verlaagt het systeemvolume zolang JARVIS praat (Fase 17, G)."""
    try:
        from voice import ducking

        ducking.duck()
    except Exception:
        logger.debug("Ducking mislukt", exc_info=True)


def _herstel_volume():
    """Zet het systeemvolume terug na het praten (Fase 17, G)."""
    try:
        from voice import ducking

        ducking.herstel()
    except Exception:
        logger.debug("Volume herstellen mislukt", exc_info=True)


def _mute_microphone():
    """Dempen zolang JARVIS zelf geluid maakt (pieptoon of spraak)."""
    try:
        from voice.audio_stream import get_audio_source

        source = get_audio_source()
        if source is not None:
            source.mute()
    except Exception:
        pass


def _unmute_microphone():
    try:
        from voice.audio_stream import get_audio_source

        source = get_audio_source()
        if source is not None:
            source.unmute()
    except Exception:
        pass


def _ipad_speaker():
    """De iPad als speaker (Fase 20, M5), of None.

    Alleen als het spraakpaneel verbonden is en het antwoord wil laten horen;
    anders spreekt JARVIS gewoon uit de speaker van het brein.
    """
    try:
        from voice.ipad_microfoon import peek_ipad_microfoon

        ipad = peek_ipad_microfoon()
        return ipad if ipad is not None and ipad.kan_spreken() else None
    except Exception:
        return None


def _wacht_op_ipad():
    """Pas de microfoon weer openen als de iPad uitgesproken is."""
    ipad = _ipad_speaker()
    if ipad is not None:
        ipad.wacht_tot_stil(_STOP.is_set)


def _beep(duration=0.15, frequency=800):
    """Play a short beep tone."""
    _mute_microphone()
    try:
        t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
        wave = (np.sin(2 * np.pi * frequency * t) * 32767).astype(np.int16)
        ipad = _ipad_speaker()
        if ipad is not None and ipad.speel(wave, SAMPLE_RATE, vooruit=0.0):
            ipad.wacht_tot_stil(marge=0.1)
            return
        wave = wave.reshape(-1, 1)
        sd.play(wave, SAMPLE_RATE)
        sd.wait()
    except Exception as e:
        logger.warning("Kon pieptoon niet afspelen: %s", e)
    finally:
        _unmute_microphone()


def _use_piper():
    """Of de Piper-backend gebruikt moet worden (anders pyttsx3)."""
    return piper_tts.is_available()


def _play(samples, sample_rate):
    """Speelt een int16-audiostuk af en wacht tot het klaar is.

    Is het spraakpaneel op de iPad open, dan klinkt het daar (Fase 20, M5).
    """
    ipad = _ipad_speaker()
    if ipad is not None and ipad.speel(samples, sample_rate, _STOP.is_set):
        return
    try:
        sd.play(samples, sample_rate)
        sd.wait()
    except Exception as e:
        logger.warning("Kon Piper-audio niet afspelen: %s", e)


def _say_piper(text, stop_event=None):
    """Spreekt tekst uit met Piper, stuk voor stuk (per zin).

    Wordt het spreken onderbroken (barge-in), dan stopt hij tussen de
    stukken in plaats van de hele tekst af te maken.
    """
    for samples, sample_rate in piper_tts.synthesize(text, volume=_volume):
        if _gestopt(stop_event):
            return
        _play(samples, sample_rate)


def _say_pyttsx3(text):
    """Spreekt tekst uit met pyttsx3 (terugvaloptie)."""
    engine.say(text)
    engine.runAndWait()


def _say(text, stop_event=None):
    """Spreekt tekst uit met de actieve backend.

    De aanroeper houdt ``_SPEAK_LOCK`` al vast. Lukt Piper niet, dan valt
    JARVIS binnen dezelfde aanroep terug op pyttsx3.
    """
    if _gestopt(stop_event):
        return
    if _use_piper():
        try:
            _say_piper(text, stop_event)
            return
        except Exception as e:
            logger.warning("Piper-spraak mislukt (%s); val terug op pyttsx3.", e)
    if _gestopt(stop_event):
        return
    _say_pyttsx3(text)


def _take_sentence(buffer, min_chars=None):
    """Haalt het eerste volledige zin(tje) uit ``buffer``.

    Geeft ``(zin, rest)`` terug. ``zin`` is None als er nog geen zin klaar
    is. Een zin telt pas mee vanaf ``min_chars`` tekens, zodat korte
    tussenstukken ('Dhr.', '3.14') niet onnodig worden afgekapt.
    """
    if min_chars is None:
        min_chars = PIPER_STREAM_MIN_CHARS
    if len(buffer) < min_chars:
        return None, buffer

    match = _SENTENCE_END.search(buffer, min_chars - 1)
    if match is not None:
        end = match.end()
        return buffer[:end].strip(), buffer[end:]

    if len(buffer) >= _MAX_CHUNK_CHARS:
        cut = buffer.rfind(" ", 0, _MAX_CHUNK_CHARS)
        if cut <= 0:
            cut = _MAX_CHUNK_CHARS
        return buffer[:cut].strip(), buffer[cut:].lstrip()

    return None, buffer


def _speak_deltas(deltas, stop_event=None):
    """Spreekt tekststukjes uit zodra er een zin compleet is."""
    buffer = ""
    for stuk in deltas:
        if _gestopt(stop_event):
            return
        if not stuk:
            continue
        buffer += stuk
        zin, buffer = _take_sentence(buffer)
        while zin:
            if _gestopt(stop_event):
                return
            status.spreekt(zin)
            _say(zin, stop_event)
            zin, buffer = _take_sentence(buffer)

    rest = buffer.strip()
    if rest and not _gestopt(stop_event):
        status.spreekt(rest)
        _say(rest, stop_event)


def speak_stream(deltas, stop_event=None):
    """Spreekt tekst uit terwijl die binnenkomt (streaming LLM-output).

    ``deltas`` is een iterator van tekststukjes, bijvoorbeeld de opbrengst
    van ``core.llm.chat_stream``. JARVIS wacht niet op de hele tekst, maar
    spreekt elke zin uit zodra die compleet is. Met ``stop_event`` kan het
    uitspreken tussentijds worden afgebroken (barge-in, Fase 17).
    """
    _STOP.clear()
    _mute_microphone()
    _spreek_actief.set()
    _duck()
    try:
        with _SPEAK_LOCK:
            _speak_deltas(deltas, stop_event)
            _wacht_op_ipad()
    finally:
        _spreek_actief.clear()
        status.klaar_met_spreken()
        _herstel_volume()
        _unmute_microphone()


def speak(text=None, beep_only=False):
    """Speak text or optionally play beep instead."""
    if beep_only:
        if BEEP_ENABLED:
            _beep()
        return

    if text is None:
        if BEEP_ENABLED:
            _beep()
        return

    status.spreekt(text)

    _STOP.clear()
    _mute_microphone()
    _spreek_actief.set()
    _duck()
    try:
        with _SPEAK_LOCK:
            _say(text)
            _wacht_op_ipad()
    finally:
        _spreek_actief.clear()
        status.klaar_met_spreken()
        _herstel_volume()
        _unmute_microphone()
