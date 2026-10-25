"""Fase 19, M5 — Piper-stem afstellen (variatie-instellingen en stem-proef)."""

import importlib.util
import os
import wave

import numpy as np
import pytest

import config
from voice import piper_tts

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _proef():
    spec = importlib.util.spec_from_file_location("stem_proef", os.path.join(PROJECT, "scripts", "stem_proef.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_variatie_standaard_van_het_model():
    # Zonder instelling in .env beslist het stemmodel zelf.
    if "PIPER_NOISE_SCALE" not in os.environ:
        assert config.PIPER_NOISE_SCALE is None
    if "PIPER_NOISE_W" not in os.environ:
        assert config.PIPER_NOISE_W is None


def test_stem_instellingen():
    pytest.importorskip("piper")
    cfg = piper_tts.stem_instellingen(0.4, 1.1, 0.5, 0.6)
    assert (cfg.volume, cfg.length_scale, cfg.noise_scale, cfg.noise_w_scale) == (0.4, 1.1, 0.5, 0.6)
    leeg = piper_tts.stem_instellingen()
    assert leeg.noise_scale is None and leeg.noise_w_scale is None


def test_synthesize_geeft_variatie_door(monkeypatch):
    pytest.importorskip("piper")
    gezien = {}

    class NepStem:
        def synthesize(self, tekst, syn_config=None):
            gezien["cfg"] = syn_config
            return iter(())

    monkeypatch.setattr(piper_tts, "get_voice", lambda: NepStem())
    monkeypatch.setattr(config, "PIPER_LENGTH_SCALE", 1.15)
    monkeypatch.setattr(config, "PIPER_NOISE_SCALE", 0.4)
    monkeypatch.setattr(config, "PIPER_NOISE_W", 0.45)
    list(piper_tts.synthesize("Goedenavond, sir.", volume=0.8))
    cfg = gezien["cfg"]
    assert (cfg.length_scale, cfg.noise_scale, cfg.noise_w_scale, cfg.volume) == (1.15, 0.4, 0.45, 0.8)


def test_proefstemmen_staan_apart(tmp_path):
    mod = _proef()
    models = tmp_path / "models"
    proef = models / "proef"
    proef.mkdir(parents=True)
    (models / "nl_NL-pim-medium.onnx").write_bytes(b"x")
    (proef / "nl_BE-rdh-medium.onnx").write_bytes(b"x")
    stemmen = mod.beschikbare_stemmen(models, proef)
    assert set(stemmen) == {"nl_NL-pim-medium", "nl_BE-rdh-medium"}

    # De standaardkeuze van JARVIS (eerste .onnx in de modellenmap, niet
    # recursief) blijft pim, ook al komt rdh alfabetisch eerder.
    assert sorted(models.glob("*.onnx"))[0].stem == "nl_NL-pim-medium"


def test_env_regels(tmp_path):
    mod = _proef()
    models = tmp_path / "models"
    (models / "proef").mkdir(parents=True)
    (models / "proef" / "nl_NL-ronnie-medium.onnx").write_bytes(b"x")
    stemmen = mod.beschikbare_stemmen(models, models / "proef")
    regels = mod.env_regels("nl_NL-ronnie-medium", "kalm", models_dir=models, stemmen=stemmen)
    assert regels == [
        "PIPER_VOICE=proef/nl_NL-ronnie-medium.onnx",
        "PIPER_LENGTH_SCALE=1.1",
        "PIPER_NOISE_SCALE=0.5",
        "PIPER_NOISE_W=0.6",
        "PIPER_SPEAKER=",
    ]
    standaard = mod.env_regels("nl_NL-ronnie-medium", "standaard", models_dir=models, stemmen=stemmen)
    assert standaard[2:] == ["PIPER_NOISE_SCALE=", "PIPER_NOISE_W=", "PIPER_SPEAKER="]
    met_spreker = mod.env_regels("nl_NL-ronnie-medium", "butler", models_dir=models, stemmen=stemmen, spreker=36)
    assert met_spreker[-1] == "PIPER_SPEAKER=36"
    with pytest.raises(KeyError):
        mod.env_regels("bestaat-niet", "kalm", models_dir=models, stemmen=stemmen)
    with pytest.raises(KeyError):
        mod.env_regels("nl_NL-ronnie-medium", "luid", models_dir=models, stemmen=stemmen)


def test_piper_vindt_stem_in_proefmap(tmp_path, monkeypatch):
    (tmp_path / "proef").mkdir()
    pad = tmp_path / "proef" / "nl_NL-ronnie-medium.onnx"
    pad.write_bytes(b"x")
    monkeypatch.setattr(config, "PIPER_MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "PIPER_VOICE", "proef/nl_NL-ronnie-medium.onnx")
    assert piper_tts._resolve_model_path() == pad


def test_wav_schrijven(tmp_path):
    mod = _proef()
    pad = tmp_path / "x.wav"
    mod._schrijf_wav(pad, [(np.zeros(100, dtype=np.int16), 22050), (np.ones(50, dtype=np.int16), 22050)])
    with wave.open(str(pad), "rb") as wav:
        assert wav.getframerate() == 22050 and wav.getnframes() == 150 and wav.getsampwidth() == 2


def test_presets_zijn_redelijk():
    mod = _proef()
    for naam, (lengte, noise, noise_w) in mod.PRESETS.items():
        assert 0.8 <= lengte <= 1.3, naam
        assert noise is None or 0 < noise <= 1, naam
        assert noise_w is None or 0 < noise_w <= 1, naam
    assert "nl_NL-pim-medium" in mod.KANDIDATEN


def test_kies_zonder_stem_geeft_fout(monkeypatch, capsys):
    mod = _proef()
    monkeypatch.setattr(mod, "beschikbare_stemmen", lambda *a, **k: {})
    assert mod.main(["--kies", "nl_NL-ronnie-medium", "kalm"]) == 1
    assert mod.main([]) == 1


def test_toonhoogte_van_een_toon():
    mod = _proef()
    rate = 22050
    t = np.arange(rate) / rate
    for hz in (110, 124, 200):
        golf = (np.sin(2 * np.pi * hz * t) * 12000).astype(np.int16)
        assert abs(mod.toonhoogte(golf, rate) - hz) < 4, hz
    assert mod.toonhoogte(np.zeros(rate, dtype=np.int16), rate) is None
    assert mod.toonhoogte(np.zeros(0, dtype=np.int16), rate) is None


def test_aantal_sprekers(tmp_path):
    mod = _proef()
    pad = tmp_path / "x.onnx"
    (tmp_path / "x.onnx.json").write_text('{"num_speakers": 52}', encoding="utf-8")
    assert mod.aantal_sprekers(pad) == 52
    assert mod.aantal_sprekers(tmp_path / "geen.onnx") == 1


def test_spreker_alleen_bij_meersprekermodel(monkeypatch):
    pytest.importorskip("piper")
    from types import SimpleNamespace

    gezien = {}

    def nep(sprekers):
        class NepStem:
            config = SimpleNamespace(num_speakers=sprekers)

            def synthesize(self, tekst, syn_config=None):
                gezien["cfg"] = syn_config
                return iter(())
        return NepStem()

    monkeypatch.setattr(config, "PIPER_SPEAKER", 36)
    monkeypatch.setattr(piper_tts, "get_voice", lambda: nep(52))
    list(piper_tts.synthesize("Goedenavond, sir."))
    assert gezien["cfg"].speaker_id == 36
    monkeypatch.setattr(piper_tts, "get_voice", lambda: nep(1))
    list(piper_tts.synthesize("Goedenavond, sir."))
    assert gezien["cfg"].speaker_id is None
