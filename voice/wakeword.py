import logging

import numpy as np

from voice.audio_stream import get_audio_source

logger = logging.getLogger(__name__)


FRAME_SAMPLES = 1280  # 80 ms at 16 kHz
COOLDOWN_SECONDS = 1.5

# Het openWakeWord-model wordt pas bij het eerste gebruik geladen (lazy), niet
# bij het importeren. Zo faalt `import voice.wakeword` niet in CI of tests
# wanneer de modelbestanden nog niet gedownload zijn.
model = None
_model_unavailable = False


def get_model():
    """Laadt (lazy) het openWakeWord-model. Geeft None als het niet lukt.

    De modelbestanden (o.a. hey_jarvis) moeten eenmalig gedownload zijn met
    `python -c "from openwakeword.utils import download_models; download_models()"`.
    Ontbreken ze, dan loggen we een waarschuwing en werkt de wake-word-detectie
    niet — in plaats van dat het importeren van deze module crasht.
    """
    global model, _model_unavailable

    if model is not None:
        return model
    if _model_unavailable:
        return None

    try:
        from openwakeword.model import Model

        model = Model(
            wakeword_models=["hey_jarvis"],
            inference_framework="onnx",
        )
        return model
    except Exception as exc:
        logger.warning(
            "Wake word-model niet beschikbaar (%s). Download de modellen met: "
            "python -c \"from openwakeword.utils import download_models; download_models()\".",
            exc,
        )
        _model_unavailable = True
        return None


# Module-variabele zodat de cooldown meerdere aanroepen van
# wait_for_wake_word() overleeft. Als lokale variabele begon hij bij elke
# aanroep op 0 en deed de cooldown niets. De waarde is een tijdstempel in
# de audiotijdlijn (het tijdstip van de laatste detectie).
last_detection = 0.0


def wait_for_wake_word(audio_source=None):
    """Wacht op het wake word. Geeft géén audio terug.

    Leest frames uit de gedeelde AudioSource en geeft bij detectie alleen
    het tijdstip van de detectie terug ({"detected_at": ...}), zodat de
    opname daarna precies vanaf dat moment begint. Audio van vóór de
    detectie (het wake word zelf) wordt nooit doorgegeven.

    Lukt wachten niet (geen audiobron, geen model, of de bron is gestopt),
    dan komt er een dict terug met "detected_at": None en een "status"
    ("geen_bron", "geen_model" of "bron_gestopt") — nooit stil None. De
    aanroeper kan zo fail-closed beslissen om géén audio te verwerken.
    """
    global last_detection

    source = audio_source if audio_source is not None else get_audio_source()
    if source is None:
        logger.warning(
            "Geen audiobron beschikbaar; er kan niet op het wake word gewacht worden."
        )
        return {
            "detected_at": None,
            "status": "geen_bron",
            "error": "Geen audiobron: de microfoonstroom is niet gestart.",
        }

    model = get_model()
    if model is None:
        logger.warning("Geen wake word-model beschikbaar; wake word wordt overgeslagen.")
        return {
            "detected_at": None,
            "status": "geen_model",
            "error": (
                "Het wake word-model ontbreekt. Download het met: "
                "python -c \"from openwakeword.utils import download_models; download_models()\"."
            ),
        }

    logger.info("💤 JARVIS wacht op wake word...")

    # Na een commando begint het wake word na het laatst verwerkte punt,
    # niet bij de oude detectie: zo scant hij al verwerkte audio niet opnieuw.
    cursor = source.get_cursor()
    if cursor is not None and cursor > last_detection:
        after_ts = cursor
    else:
        after_ts = last_detection

    while True:
        result = source.read_frame(after_ts=after_ts, timeout=0.5)
        if result is None:
            # De bron is gestopt: er kan nooit meer audio bij komen. Direct
            # terugkeren in plaats van in een strakke lus te blijven draaien.
            if not source.is_running():
                logger.warning("Audiobron gestopt; wachten op wake word afgebroken.")
                return {"detected_at": None, "status": "bron_gestopt"}
            continue

        ts, block = result
        after_ts = ts

        # Cooldown na een eerdere detectie (in de audiotijdlijn).
        if ts - last_detection < COOLDOWN_SECONDS:
            continue

        audio_frame = np.squeeze(block)

        # Lege frames overslaan
        if audio_frame.size == 0:
            continue

        prediction = model.predict(audio_frame)

        for key, score in prediction.items():
            if score > 0.5:
                logger.info("⚡ Wake word gedetecteerd!")
                model.reset()
                last_detection = ts
                return {"detected_at": ts, "audio": None}
