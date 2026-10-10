import time
import collections

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
FRAME_SAMPLES = 1280  # 80 ms at 16 kHz
COOLDOWN_SECONDS = 1.5
RINGBUFFER_SECONDS = 2.0


def _get_ringbuffer_size():
    """Return ringbuffer size in frames for ~RINGBUFFER_SECONDS."""
    frames = int(RINGBUFFER_SECONDS * SAMPLE_RATE / FRAME_SAMPLES)
    if frames < 1:
        frames = 1
    return frames


def wait_for_wake_word():
    """Wait for wake word using continuous stream with ringbuffer.
    
    Returns:
        dict: Contains 'audio' (numpy array) - audio after wake word
              to prepend to recording, or empty if none.
    """
    print("💤 JARVIS wacht op wake word...")

    ringbuffer = collections.deque(maxlen=_get_ringbuffer_size())
    last_detection = 0

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=FRAME_SAMPLES) as stream:
        while True:
            # Check cooldown
            if time.time() - last_detection < COOLDOWN_SECONDS:
                # Still in cooldown - read and discard to keep stream flowing
                try:
                    block, _ = stream.read(FRAME_SAMPLES)
                    ringbuffer.append(block.copy())
                except Exception:
                    pass
                continue

            try:
                block, _ = stream.read(FRAME_SAMPLES)
            except Exception:
                time.sleep(0.01)
                continue

            if block is None:
                continue

            ringbuffer.append(block.copy())
            audio_frame = np.squeeze(block)

            # Skip empty frames
            if audio_frame.size == 0:
                continue

            prediction = model.predict(audio_frame)

            for key, score in prediction.items():
                if score > 0.5:
                    print("⚡ Wake word gedetecteerd!")
                    model.reset()
                    last_detection = time.time()

                    # Extract audio after wake word from ringbuffer
                    # Ringbuffer contains last ~2 seconds; wake word was just detected
                    # in current frame - take everything in buffer after the wake event?
                    # We need audio right after wake word - buffer has recent history
                    # Concatenate all buffered frames
                    if ringbuffer:
                        buffer_audio = np.concatenate(list(ringbuffer), axis=0)
                        # Remove the last frame (current one with wake word) and
                        # return the rest as post-wake audio
                        if buffer_audio.shape[0] > FRAME_SAMPLES:
                            post_audio = buffer_audio[:-FRAME_SAMPLES]
                            if post_audio.shape[0] > 0:
                                return {"audio": post_audio}
                    return {"audio": np.array([], dtype=np.int16)}
    return {"audio": np.array([], dtype=np.int16)}