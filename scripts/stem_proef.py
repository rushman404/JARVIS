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

    # Meersprekermodel (nl_NL-mls-medium, 52 sprekers): per spreker een korte
    # proef, gesorteerd op hoe dicht de toonhoogte bij een voorbeeldstem ligt.
    python scripts/stem_proef.py --sprekers nl_NL-mls-medium --preset butler --zoals nl_BE-rdh-medium
    python scripts/stem_proef.py --kies nl_NL-mls-medium butler --spreker 12

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


def env_regels(stem, preset, models_dir=MODELS_DIR, stemmen=None, spreker=None):
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
        f"PIPER_SPEAKER={'' if spreker is None else spreker}",
    ]


def toonhoogte(audio, rate, frame_s=0.04):
    """Geschatte gemiddelde toonhoogte (Hz) van stemhebbende stukken.

    Eenvoudige autocorrelatie per frame van 40 ms (bereik 60-400 Hz); stille
    frames tellen niet mee. Genoeg om lage en hoge stemmen te sorteren.
    """

    import numpy as np

    x = np.asarray(audio, dtype=np.float64)
    if x.size == 0:
        return None
    x = x / (np.max(np.abs(x)) or 1.0)
    n = int(rate * frame_s)
    kort, lang = int(rate / 400), int(rate / 60)
    drempel = 0.1 * np.sqrt(np.mean(x ** 2)) * 3
    hoogtes = []
    for start in range(0, x.size - n, n):
        frame = x[start:start + n]
        if np.sqrt(np.mean(frame ** 2)) < drempel:
            continue
        frame = frame - frame.mean()
        ac = np.correlate(frame, frame, mode="full")[n - 1:]
        if ac[0] <= 0 or lang >= ac.size:
            continue
        lag = kort + int(np.argmax(ac[kort:lang]))
        if ac[lag] / ac[0] > 0.3:
            hoogtes.append(rate / lag)
    return float(np.median(hoogtes)) if hoogtes else None


def aantal_sprekers(stem_pad):
    import json

    try:
        with open(str(stem_pad) + ".json", encoding="utf-8") as f:
            return int(json.load(f).get("num_speakers") or 1)
    except (OSError, ValueError, TypeError):
        return 1


PROEF_KORT = "Goedenavond, sir. Ik heb de lampen gedimd. Misschien is het tijd om te gaan slapen."


def _synth(stem, tekst, instellingen):
    import numpy as np

    stukken, rate = [], 22050
    for c in stem.synthesize(tekst, syn_config=instellingen):
        stukken.append(c.audio_int16_array)
        rate = c.sample_rate
    return (np.concatenate(stukken) if stukken else np.zeros(0, dtype=np.int16)), rate


def sprekers_proef(stem_pad, preset, uitvoer_dir=UITVOER_DIR, referentie_pad=None):
    """Per spreker een korte proef; geeft ``[(spreker, hz, pad)]``, de beste eerst.

    Met ``referentie_pad`` wordt gesorteerd op het verschil in toonhoogte met
    die stem (met dezelfde preset); anders van laag naar hoog.
    """

    from piper import PiperVoice

    from voice.piper_tts import stem_instellingen

    lengte, noise, noise_w = PRESETS[preset]
    doel = None
    if referentie_pad is not None:
        ref = PiperVoice.load(str(referentie_pad))
        doel = toonhoogte(*_synth(ref, PROEF_KORT, stem_instellingen(1.0, lengte, noise, noise_w)))

    stem = PiperVoice.load(str(stem_pad))
    map_ = uitvoer_dir / stem_pad.stem
    map_.mkdir(parents=True, exist_ok=True)
    uit = []
    for spreker in range(aantal_sprekers(stem_pad)):
        audio, rate = _synth(stem, PROEF_KORT, stem_instellingen(1.0, lengte, noise, noise_w, spreker))
        pad = map_ / f"spreker-{spreker:02d}__{preset}.wav"
        _schrijf_wav(pad, [(audio, rate)])
        uit.append((spreker, toonhoogte(audio, rate), pad))
    if doel is not None:
        uit.sort(key=lambda r: abs((r[1] or 1e9) - doel))
    else:
        uit.sort(key=lambda r: r[1] or 1e9)
    return uit, doel


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
    p.add_argument("--spreker", type=int, help="met --kies: het sprekernummer (meersprekermodel).")
    p.add_argument("--sprekers", metavar="STEM", help="per spreker van een meersprekermodel een proef.")
    p.add_argument("--zoals", metavar="STEM", help="met --sprekers: sorteer op gelijkenis met deze stem.")
    args = p.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.download:
        print("Stemmen ophalen naar", PROEF_DIR)
        download()
        print()

    if args.kies:
        try:
            regels = env_regels(*args.kies, spreker=args.spreker)
        except KeyError as fout:
            print(str(fout).strip("'\""), file=sys.stderr)
            return 1
        print("Zet deze regels in .env en herstart JARVIS:\n")
        print("\n".join(regels))
        return 0

    stemmen = beschikbare_stemmen()
    if args.sprekers:
        if args.sprekers not in stemmen:
            print(f"Niet gevonden: {args.sprekers}. Beschikbaar: {', '.join(stemmen)}", file=sys.stderr)
            return 1
        if args.zoals and args.zoals not in stemmen:
            print(f"Niet gevonden: {args.zoals}.", file=sys.stderr)
            return 1
        preset = (args.preset or ["butler"])[0]
        lijst, doel = sprekers_proef(stemmen[args.sprekers], preset,
                                     referentie_pad=stemmen[args.zoals] if args.zoals else None)
        if doel:
            print(f"Toonhoogte van {args.zoals} ({preset}): {doel:.0f} Hz. Het dichtst erbij eerst:\n")
        for spreker, hz, pad in lijst:
            print(f"  spreker {spreker:>2}  {('%.0f Hz' % hz) if hz else '?':>7}  {pad}")
        print(f"\nGekozen? python scripts/stem_proef.py --kies {args.sprekers} {preset} --spreker <nummer>")
        return 0
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
