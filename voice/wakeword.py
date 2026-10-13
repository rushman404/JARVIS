import logging
import time

from openwakeword.model import Model
import numpy as np

from voice.audio_stream import get_audio_source

logger = logging.getLogger(__name__)


model = Model(
    wakeword_models=[
        "hey_jarvis"
    ],
    inference_framework="onnx"
)


FRAME_SAMPLES = 1280  # 80 ms at 16 kHz
COOLDOWN_SECONDS = 1.5

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
    """
    global last_detection

    source = audio_source if audio_source is not None else get_audio_source()
    if source is None:
        return None

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
