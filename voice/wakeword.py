from openwakeword.model import Model
import sounddevice as sd
import numpy as np


model = Model(
    wakeword_models=[
        "hey_jarvis"
    ],
    inference_framework="onnx"
)


SAMPLE_RATE = 16000


def wait_for_wake_word():

    print("💤 JARVIS wacht op wake word...")

    while True:

        audio = sd.rec(
            int(1 * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16"
        )

        sd.wait()

        audio = np.squeeze(audio)

        prediction = model.predict(audio)

        for key, score in prediction.items():

            if score > 0.5:
                print("⚡ Wake word gedetecteerd!")
                return True