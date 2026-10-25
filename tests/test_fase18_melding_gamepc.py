"""Fase 18 — timermeldingen (toast) op de game-pc in plaats van het brein."""

from core.result_validation import ToolResult
from remote import allowlist
from remote import tools as remote_tools
from voice import notify


def _doel(monkeypatch, waarde):
    import config

    monkeypatch.setattr(config, "PC_TARGET", waarde, raising=False)


def test_allowlist_accepteert_melding_met_leestekens():
    schoon, fout = allowlist.validate_call(
        "show_notification",
        {"title": "JARVIS", "message": "Sir, het is 14:05: uw timer 'pizza' is afgelopen."},
    )
    assert fout is None
    assert schoon["message"].startswith("Sir, het is 14:05")


def test_allowlist_weigert_stuurtekens_en_te_lang():
    schoon, _ = allowlist.validate_call(
        "show_notification", {"title": "JARVIS", "message": "regel\nnog een"}
    )
    assert schoon is None
    schoon, _ = allowlist.validate_call(
        "show_notification", {"title": "JARVIS", "message": "x" * 301}
    )
    assert schoon is None


def test_melding_staat_in_basisprofiel():
    assert allowlist.is_allowed_in_profiel("show_notification", allowlist.PROFIEL_BASIS)


def test_game_pc_doel_stuurt_toast_naar_agent(monkeypatch):
    _doel(monkeypatch, "game-pc")
    aanroepen = []

    def nep_remote(naam, argumenten=None, question=None):
        aanroepen.append((naam, argumenten))
        return ToolResult(True, "Melding getoond.")

    lokaal = []
    monkeypatch.setattr(remote_tools, "execute_remote_tool", nep_remote)
    monkeypatch.setattr(notify, "toon_toast", lambda *a: lokaal.append(a) or True)

    assert notify.toon_melding("JARVIS", "Sir, uw timer\n'thee' is afgelopen.") is True
    assert aanroepen == [
        (
            "game_pc_show_notification",
            {"title": "JARVIS", "message": "Sir, uw timer 'thee' is afgelopen."},
        )
    ]
    assert lokaal == []


def test_agent_onbereikbaar_valt_terug_op_lokaal(monkeypatch):
    _doel(monkeypatch, "game-pc")
    monkeypatch.setattr(
        remote_tools,
        "execute_remote_tool",
        lambda *a, **k: ToolResult(False, "niet bereikbaar", error_kind="remote_config"),
    )
    lokaal = []
    monkeypatch.setattr(notify, "toon_toast", lambda *a: lokaal.append(a) or True)

    assert notify.toon_melding("JARVIS", "Uw timer is afgelopen.") is True
    assert lokaal == [("JARVIS", "Uw timer is afgelopen.")]


def test_lokaal_doel_toont_toast_hier(monkeypatch):
    _doel(monkeypatch, "local")

    def mag_niet(*a, **k):
        raise AssertionError("mag niet naar de game-pc")

    monkeypatch.setattr(remote_tools, "execute_remote_tool", mag_niet)
    lokaal = []
    monkeypatch.setattr(notify, "toon_toast", lambda *a: lokaal.append(a) or True)

    assert notify.toon_melding("JARVIS", "Hallo") is True
    assert lokaal == [("JARVIS", "Hallo")]


def test_lange_tekst_wordt_ingekort_voor_de_allowlist():
    tekst = notify._melding_tekst("a" * 500, 300)
    assert len(tekst) == 300
    schoon, fout = allowlist.validate_call(
        "show_notification", {"title": "JARVIS", "message": tekst}
    )
    assert fout is None


def test_agent_voert_show_notification_lokaal_uit(monkeypatch):
    from core import ai

    getoond = []
    monkeypatch.setattr(notify, "toon_toast", lambda t, m: getoond.append((t, m)) or True)

    uit = ai._dispatch_local_tool(
        "show_notification", {"title": "JARVIS", "message": "Test"}, ""
    )
    assert "getoond" in str(uit)
    assert getoond == [("JARVIS", "Test")]
