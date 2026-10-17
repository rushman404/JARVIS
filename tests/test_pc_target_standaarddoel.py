"""PC_TARGET: standaarddoel local en directe game-pc-routing zonder LLM.

Dekt:
    - de ingebouwde standaardwaarde in config.py en .env.example is 'local';
    - met doel local en de client uit werken de snelle handlers lokaal zoals tevoren;
    - met doel game-pc en de client uit krijg je een heldere melding en
      gebeurt er NIETS lokaal (fail-closed, nooit stilletjes lokaal);
    - met doel game-pc roepen open/sluit/herstart programma, volume, media,
      status en screenshot direct de game_pc_*-tools aan, zonder LLM.
"""

import os

import pytest

import config
from core import brain, pc_target
from remote import tools as remote_tools

PROJECTMAP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _naar_laatste_pad(*delen):
    return os.path.join(PROJECTMAP, *delen)


class _Opnemer:
    """Roept op en onthoudt aanroepen; geeft een korte Nederlandse terug."""

    def __init__(self, terug="gedaan"):
        self.calls = []
        self._terug = terug

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self._terug


def _fout_bij_aanroep(boodschap):
    def _fout(*args, **kwargs):
        raise AssertionError(boodschap)

    return _fout


def _geen_llm(monkeypatch):
    """Elke LLM-aanroep laat de test meteen falen."""

    from core import llm

    monkeypatch.setattr(llm, "chat", _fout_bij_aanroep(
        "het LLM-pad mag bij dit commando niet worden gebruikt"
    ))


@pytest.fixture
def game_pc(monkeypatch):
    """Doel game-pc met een uitstaande (dus onbruikbare) client."""

    monkeypatch.setattr(config, "PC_TARGET", "game-pc")
    monkeypatch.setattr(config, "REMOTE_CLIENT_ENABLED", False)
    remote_tools._reset_client()
    yield
    remote_tools._reset_client()


@pytest.fixture
def audit_stil(monkeypatch, tmp_path):
    """Auditregels gaan naar een tijdelijk bestand, niet naar logs/."""

    import core.audit as core_audit

    monkeypatch.setattr(core_audit, "AUDIT_FILE", str(tmp_path / "audit.jsonl"))


# ---------------------------------------------------------------
# Standaardwaarde
# ---------------------------------------------------------------

def test_config_default_pc_target_is_local():
    with open(_naar_laatste_pad("config.py"), "r", encoding="utf-8") as f:
        bron = f.read()

    regel = next(
        regel for regel in bron.splitlines() if regel.startswith("PC_TARGET =")
    )

    assert '"local"' in regel, (
        "de ingebouwde standaard van PC_TARGET moet 'local' zijn"
    )


def test_env_example_zet_pc_target_lokaal():
    with open(_naar_laatste_pad(".env.example"), "r", encoding="utf-8") as f:
        regels = [
            regel.strip()
            for regel in f
            if regel.strip().startswith("PC_TARGET=")
        ]

    assert regels == ["PC_TARGET=local"], (
        ".env.example moet PC_TARGET=local actief zetten"
    )


# ---------------------------------------------------------------
# Doel local: alles werkt zoals tevoren
# ---------------------------------------------------------------

def test_local_doel_snelle_handlers_werken_lokaal(monkeypatch):
    monkeypatch.setattr(config, "PC_TARGET", "local")
    _geen_llm(monkeypatch)
    monkeypatch.setattr(
        brain, "find_program",
        lambda naam, exact_only=False: f"C:\\nep\\{naam}.exe",
    )
    monkeypatch.setattr(
        brain, "execute_tool",
        _fout_bij_aanroep("bij doel local mag execute_tool niet worden gebruikt"),
    )

    geopend = []
    monkeypatch.setattr(
        brain, "open_program_tool",
        lambda naam: geopend.append(naam) or f"{naam} geopend",
    )
    volumes = []
    monkeypatch.setattr(
        brain, "set_volume",
        lambda percent: volumes.append(percent) or f"volume {percent}",
    )
    pauzes = []
    monkeypatch.setattr(
        brain, "play_pause",
        lambda: pauzes.append(True) or "gepauzeerd",
    )

    assert brain.try_open_program("open spotify")
    assert geopend == ["spotify"]

    assert brain.try_media_command("zet het volume op 30")
    assert volumes == [30]

    assert brain.try_media_command("pauzeer de muziek")
    assert pauzes == [True]


# ---------------------------------------------------------------
# Doel game-pc: directe routing, zonder LLM
# ---------------------------------------------------------------

@pytest.mark.parametrize(
    "zin,handler,verwacht_tool,verwachte_args",
    [
        (
            "open spotify", "try_open_program",
            "game_pc_open_program", {"program": "spotify"},
        ),
        (
            "sluit discord", "try_close_program",
            "game_pc_close_program", {"program": "discord"},
        ),
        (
            "zet het volume op 30", "try_media_command",
            "game_pc_set_volume", {"percent": 30},
        ),
        (
            "pauzeer de muziek", "try_media_command",
            "game_pc_media", {"action": "play_pause"},
        ),
        (
            "herstart spotify", "try_restart_program",
            "game_pc_restart_program", {"program": "spotify"},
        ),
        (
            "draait spotify?", "try_program_status",
            "game_pc_program_status", {"program": "spotify"},
        ),
        (
            "maak een screenshot", "try_screenshot",
            "game_pc_screenshot", {},
        ),
        (
            "geef me een pc status", "try_system_info",
            "game_pc_status", {},
        ),
    ],
)
def test_game_pc_handlers_roepen_remote_tool_zonder_llm(
    game_pc, monkeypatch, zin, handler, verwacht_tool, verwachte_args
):
    _geen_llm(monkeypatch)

    opnemer = _Opnemer()
    monkeypatch.setattr(brain, "execute_tool", opnemer)

    # Lokale acties mogen nooit worden uitgevoerd bij doel game-pc.
    for naam in (
        "open_program_tool", "close_program_tool", "set_volume",
        "play_pause", "restart_program", "get_program_status",
        "pc_status_tool", "take_screenshot",
    ):
        monkeypatch.setattr(
            brain, naam, _fout_bij_aanroep(f"lokaal '{naam}' mag niet bij doel game-pc")
        )

    resultaat = getattr(brain, handler)(zin)

    assert resultaat is not None, f"{handler} gaf niets terug voor {zin!r}"
    assert opnemer.calls == [( (verwacht_tool, verwachte_args, zin), {} )], (
        f"{handler} moet {verwacht_tool} aanroepen met {verwachte_args}"
    )


# ---------------------------------------------------------------
# Doel game-pc + client uit: heldere melding, niets lokaal
# ---------------------------------------------------------------

def test_game_pc_doel_client_uit_melding_en_niets_lokaal(
    game_pc, monkeypatch, audit_stil
):
    # Find_program slaagt, zodat het OUDE (lokaal-vallende) gedrag de test
    # zou laten falen: er mag niets lokaals gebeuren bij doel game-pc.
    monkeypatch.setattr(
        brain, "find_program",
        lambda naam, exact_only=False: f"C:\\nep\\{naam}.exe",
    )
    monkeypatch.setattr(
        brain, "open_program_tool",
        _fout_bij_aanroep("er mag niets lokaals worden geopend bij doel game-pc"),
    )

    resultaat = brain.try_open_program("open spotify")

    assert resultaat is not None, "er moet een melding terugkomen"
    assert "game-pc-agent is niet beschikbaar" in str(resultaat).lower()


# ---------------------------------------------------------------
# Opstartmelding bij onbruikbare game-pc-configuratie
# ---------------------------------------------------------------

def test_configuratiemelding_bij_game_pc_zonder_client(monkeypatch):
    monkeypatch.setattr(config, "PC_TARGET", "game-pc")
    monkeypatch.setattr(config, "REMOTE_CLIENT_ENABLED", False)

    melding = pc_target.remote_client_configuratie_fout()

    assert melding, "er moet een opstartmelding zijn als het doel game-pc is maar de client uitstaat"
    assert "game-pc" in melding.lower()


def test_configuratiemelding_bij_onvolledige_client(monkeypatch):
    monkeypatch.setattr(config, "PC_TARGET", "game-pc")
    monkeypatch.setattr(config, "REMOTE_CLIENT_ENABLED", True)
    monkeypatch.setattr(config, "REMOTE_CLIENT_TOKEN", "kort")
    monkeypatch.setattr(config, "REMOTE_CLIENT_CA_FILE", "")

    melding = pc_target.remote_client_configuratie_fout()

    assert melding, "onvolledige client-configuratie bij doel game-pc moet een melding geven"


def test_geen_configuratiemelding_bij_local_doel(monkeypatch):
    monkeypatch.setattr(config, "PC_TARGET", "local")
    monkeypatch.setattr(config, "REMOTE_CLIENT_ENABLED", False)

    assert pc_target.remote_client_configuratie_fout() is None
