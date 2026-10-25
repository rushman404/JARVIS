#!/usr/bin/env python3
"""Stem-proef: kies de Piper-stem die het meest "droog en kalm" klinkt (Fase 19, M5).

Spreekt dezelfde JARVIS-zinnen uit met elke Nederlandse stem en een paar
instellingen (tempo en variatie), en bewaart ze als .wav. Daarna kiest u er
één en zet u de regels die het script geeft in ``.env``.

Gebruik::

    python scripts/stem_proef.py --download        # extra stemmen ophalen (eenmalig)
    python scripts/stem_proef.py                   # alle combinaties naar .wav
    python scripts/stem_proef.py --speel           # ... en meteen afspelen
    python scripts/stem_proef.py --stem nl_NL-ronnie-medium --preset kalm --speel
    python scripts/stem_proef.py --kies nl_NL-ronnie-medium kalm   # regels voor .env

De proefstemmen komen in ``voice/models/proef/`` (niet in git), zodat ze uw
huidige stem niet vervangen. De .wav-bestanden komen in
``%USERPROFILE%\\JARVIS-stemproef``.
"""

import argparse
import os
import sys
import wave
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODELS_DIR = Path(__file__).resolve().parent.parent / "voice" / "models"
PROEF_DIR = MODELS_DIR / "proef"
UITVOER_DIR = Path.home() / "JARVIS-stemproef"

# Mannelijke Nederlandstalige stemmen uit rhasspy/piper-voices (medium =
# goede kwaliteit, ±60 MB per stem). pim is de huidige standaardstem.
KANDIDATEN = (
    "nl_NL-pim-medium",
    "nl_NL-ronnie-medium",
    "nl_BE-rdh-medium",
)

# naam: (length_scale, noise_scale, noise_w); None = de waarde van het model.
PRESETS = {
    "standaard": (1.0, None, None),
    "kalm": (1.1, 0.5, 0.6),
    "droog": (1.05, 0.35, 0.5),
    "butler": (1.15, 0.4, 0.4),
}

ZINNEN = (
    "Goedenavond, sir. Alle systemen zijn operationeel.",
    "Ik heb de lampen in de woonkamer gedimd en Spotify op dertig procent gezet.",
    "Uw timer van tien minuten is afgelopen.",
    "Als ik zo vrij mag zijn: het is twee uur 's nachts. Misschien is het tijd om te gaan slapen.",
)


def beschikbare_stemmen(models_dir=MODELS_DIR, proef_dir=PROEF_DIR):
    """``{naam: pad}`` van alle .onnx-stemmen in de modellen- en proefmap."""

    stemmen = {}
    for map_ in (models_dir, proef_dir):
        if map_.is_dir():
            for pad in sorted(map_.glob("*.onnx")):
                stemmen.setdefault(pad.stem, pad)
    return stemmen


def env_regels(stem, preset, models_dir=MODELS_DIR, stemmen=None):
    """De regels voor ``.env`` bij deze keuze (een lijst met tekst)."""

    stemmen = stemmen if stemmen is not None else beschikbare_stemmen(models_dir)
    if stem not in stemmen:
        raise KeyError(f"Stem '{stem}' niet gevonden. Beschikbaar: {', '.join(sorted(stemmen)) or 'geen'}")
    if preset not in PRESETS:
        raise KeyError(f"Preset '{preset}' bestaat niet. Kies uit: {', '.join(PRESETS)}")
    pad = stemmen[stem]
    try:
        rel = pad.relative_to(models_dir).as_posix()
    except ValueError:
        rel = str(pad)
    lengte, noise, noise_w = PRESETS[preset]
    return [
        f"PIPER_VOICE={rel}",
        f"PIPER_LENGTH_SCALE={lengte}",
        f"PIPER_NOISE_SCALE={'' if noise is None else noise}",
        f"PIPER_NOISE_W={'' if noise_w is None else noise_w}",
    ]


def download(stemmen=KANDIDATEN, proef_dir=PROEF_DIR, models_dir=MODELS_DIR):
    from piper.download_voices import download_voice

    proef_dir.mkdir(parents=True, exist_ok=True)
    for stem in stemmen:
        if (models_dir / f"{stem}.onnx").is_file() or (proef_dir / f"{stem}.onnx").is_file():
            print(f"  {stem}: al aanwezig")
            continue
        print(f"  {stem}: ophalen…")
        download_voice(stem, proef_dir)


def _schrijf_wav(pad, chunks):
    with wave.open(str(pad), "wb") as wav:
        rate = None
        for audio, sample_rate in chunks:
            if rate is None:
                rate = sample_rate
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
            wav.writeframes(audio.tobytes())


def maak_proef(stem_pad, preset, uitvoer_dir=UITVOER_DIR):
    """Spreekt de proefzinnen uit; geeft het pad van de .wav terug."""

    from piper import PiperVoice

    from voice.piper_tts import stem_instellingen

    lengte, noise, noise_w = PRESETS[preset]
    stem = PiperVoice.load(str(stem_pad))
    instellingen = stem_instellingen(1.0, lengte, noise, noise_w)
    tekst = " ".join(ZINNEN)
    chunks = ((c.audio_int16_array, c.sample_rate) for c in stem.synthesize(tekst, syn_config=instellingen))
    uitvoer_dir.mkdir(parents=True, exist_ok=True)
    pad = uitvoer_dir / f"{stem_pad.stem}__{preset}.wav"
    _schrijf_wav(pad, chunks)
    return pad


def speel(pad):
    import numpy as np
    import sounddevice as sd

    with wave.open(str(pad), "rb") as wav:
        audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
        sd.play(audio, wav.getframerate())
        sd.wait()


def main(argv=None):
    p = argparse.ArgumentParser(prog="stem_proef.py", description="Kies een Piper-stem voor JARVIS.")
    p.add_argument("--download", action="store_true", help="de kandidaat-stemmen ophalen (±60 MB per stem).")
    p.add_argument("--stem", action="append", help="alleen deze stem (herhaalbaar).")
    p.add_argument("--preset", action="append", choices=list(PRESETS), help="alleen deze preset (herhaalbaar).")
    p.add_argument("--speel", action="store_true", help="de proeven meteen afspelen.")
    p.add_argument("--kies", nargs=2, metavar=("STEM", "PRESET"), help="toon de regels voor .env.")
    args = p.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.download:
        print("Stemmen ophalen naar", PROEF_DIR)
        download()
        print()

    if args.kies:
        try:
            regels = env_regels(*args.kies)
        except KeyError as fout:
            print(str(fout).strip("'\""), file=sys.stderr)
            return 1
        print("Zet deze regels in .env en herstart JARVIS:\n")
        print("\n".join(regels))
        return 0

    stemmen = beschikbare_stemmen()
    if args.stem:
        onbekend = [s for s in args.stem if s not in stemmen]
        if onbekend:
            print(f"Niet gevonden: {', '.join(onbekend)}. Beschikbaar: {', '.join(stemmen)}", file=sys.stderr)
            return 1
        stemmen = {s: stemmen[s] for s in args.stem}
    if not stemmen:
        print("Geen stemmen gevonden. Draai eerst: python scripts/stem_proef.py --download", file=sys.stderr)
        return 1
    presets = args.preset or list(PRESETS)

    print(f"{len(stemmen)} stem(men) × {len(presets)} preset(s) → {UITVOER_DIR}\n")
    for naam, pad in stemmen.items():
        for preset in presets:
            wav = maak_proef(pad, preset)
            lengte, noise, noise_w = PRESETS[preset]
            print(f"  {naam:<22} {preset:<10} tempo {lengte}  klank {noise or 'model'}  ritme {noise_w or 'model'}")
            if args.speel:
                speel(wav)

    print("\nGekozen? Toon de regels voor .env met:")
    print("  python scripts/stem_proef.py --kies <stem> <preset>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
