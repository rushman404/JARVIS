from faster_whisper import WhisperModel


MODEL_SIZE = "small"

model = WhisperModel(
    MODEL_SIZE,
    device="cpu",
    compute_type="int8"
)


def transcribe(audio, sample_rate=16000):
    segments, info = model.transcribe(
        audio,
        language="nl",
        beam_size=5
    )

    text = ""

    for segment in segments:
        text += segment.text

    return text.strip()