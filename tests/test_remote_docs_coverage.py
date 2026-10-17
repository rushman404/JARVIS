"""Fase 15 — controle dat de documentatie alle remote-acties noemt.

De docs mogen niet beloven dat iets niet kan wat de allowlist wél
toestaat. Deze test faalt zodra er een actie in ``ALLOWED_TOOLS`` staat
die niet in ``docs/remote_agent.md`` genoemd wordt.
"""

from pathlib import Path

from remote.allowlist import ALLOWED_TOOLS


DOCS = Path(__file__).resolve().parent.parent / "docs" / "remote_agent.md"


def test_elke_toegestane_actie_staat_in_de_docs():
    tekst = DOCS.read_text(encoding="utf-8")

    ontbrekend = [
        naam for naam in sorted(ALLOWED_TOOLS) if naam not in tekst
    ]

    assert ontbrekend == [], (
        "Deze acties staan in ALLOWED_TOOLS maar niet in docs/remote_agent.md: "
        + ", ".join(ontbrekend)
    )
