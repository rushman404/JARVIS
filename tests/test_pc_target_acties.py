"""Fase 15B (stap F) — pariteitstest voor de pc-actie-classificatie.

Kernbelofte: geen enkel PC-commando draait nog stil op het brein als het
doel ``game-pc`` is.

Deze test bewaakt dat:

* elke functie uit ``actions.*`` (en de PC-functies uit ``core.tools``)
  die ``core/brain.py`` importeert, in de classificatietabel
  (:data:`core.pc_target.PC_ACTIES`) staat;
* elke ``remote``-actie een bestaande twin heeft die de agent ook echt
  mag uitvoeren (volgens de allowlist);
* een ``geblokkeerde`` actie geen twin heeft.

Zo faalt de test zodra iemand een nieuwe directe ``actions.*``-aanroep aan
brain.py toevoegt zonder classificatie.
"""

import ast
import os

from core import pc_target
from remote import allowlist, tools as remote_tools


BRAIN_PAD = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "core",
    "brain.py",
)


def _geimporteerde_pc_functies():
    """Alle namen die brain.py uit actions.* / core.tools importeert."""

    with open(BRAIN_PAD, encoding="utf-8") as bestand:
        boom = ast.parse(bestand.read())

    namen = set()

    for knoop in ast.walk(boom):
        if not isinstance(knoop, ast.ImportFrom):
            continue

        module = knoop.module or ""

        if not (module == "core.tools" or module.split(".")[0] == "actions"):
            continue

        for alias in knoop.names:
            namen.add(alias.asname or alias.name)

    return namen


def _agent_acties_van_twin(twin):
    """De agent-acties die een twin-verzoek mag uitvoeren."""

    soort, agent_tool, _ = remote_tools._SPECS[twin]

    if soort == remote_tools._MEDIA:
        return set(remote_tools.MEDIA_ACTIES.values())

    return {agent_tool}


def test_elke_brain_actie_is_geclassificeerd():
    geimporteerd = _geimporteerde_pc_functies()

    ontbreekt = sorted(naam for naam in geimporteerd if naam not in pc_target.PC_ACTIES)

    assert ontbreekt == [], (
        "Deze uit actions.* geïmporteerde functies missen een classificatie "
        f"in core.pc_target.PC_ACTIES: {ontbreekt}"
    )


def test_classificatie_gebruikt_alleen_bekende_soorten():
    geldig = {
        pc_target.ACTIE_REMOTE,
        pc_target.ACTIE_GEBLOKKEERD,
        pc_target.ACTIE_ONAFHANKELIJK,
    }

    for naam, (soort, _twin) in pc_target.PC_ACTIES.items():
        assert soort in geldig, naam


def test_elke_remote_actie_heeft_twin_en_allowlist_actie():
    for naam, (soort, twin) in pc_target.PC_ACTIES.items():
        if soort != pc_target.ACTIE_REMOTE:
            continue

        assert twin, f"{naam} is remote maar heeft geen twin"
        assert twin in remote_tools.REMOTE_TOOL_NAMES, (
            f"{naam}: twin {twin} staat niet in REMOTE_TOOL_NAMES"
        )
        assert twin in remote_tools._SPECS, f"{naam}: twin {twin} mist een spec"

        agent_acties = _agent_acties_van_twin(twin)

        for agent_actie in agent_acties:
            assert agent_actie in allowlist.ALLOWED_TOOLS, (
                f"{naam}: agent-actie {agent_actie} staat niet in de allowlist"
            )


def test_geblokkeerde_actie_heeft_geen_twin():
    for naam, (soort, twin) in pc_target.PC_ACTIES.items():
        if soort == pc_target.ACTIE_GEBLOKKEERD:
            assert twin is None, f"{naam} is geblokkeerd maar heeft twin {twin}"


def test_onafhankelijke_actie_heeft_geen_twin():
    for naam, (soort, twin) in pc_target.PC_ACTIES.items():
        if soort == pc_target.ACTIE_ONAFHANKELIJK:
            assert twin is None, f"{naam} is onafhankelijk maar heeft twin {twin}"


def test_remote_twin_helper_volgt_de_tabel():
    for naam, (soort, twin) in pc_target.PC_ACTIES.items():
        assert pc_target.remote_twin(naam) == twin, naam


def test_blokkade_bericht_is_duidelijk():
    bericht = pc_target.blokkade_bericht("screen_info")

    assert "game-pc" in bericht
    assert bericht.strip().endswith(".")
