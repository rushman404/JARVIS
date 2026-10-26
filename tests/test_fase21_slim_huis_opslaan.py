"""Fix 2026-10-26: ⚙ Opslaan mag de slim-huisknoppen niet wissen."""

import json
import os
import shutil
import subprocess

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(PROJECT, "dashboard", "static")

# Zo bewaart het dashboard de gekozen knoppen: een lijst entity_id's.
KNOPPEN = ["light.bed_lamp", "media_player.lg_webos_tv"]


def _functie(js, naam):
    return "function " + naam + "(" + js.split(f"function {naam}(")[1].split("\n  function ")[0]


def test_opslaan_in_de_app_neemt_de_knoppen_mee():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is niet geïnstalleerd")
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    code = (
        "var verstuurd = null;\n"
        "var el = {disabled: false, hidden: false, textContent: ''};\n"
        "function $(id) { return el; }\n"
        "function magBedienen() { return true; }\n"
        "function pasLayoutToe(c) {}\n"
        "function api(pad, opties) { verstuurd = opties.body; return {then: function () {}}; }\n"
        "var PANELEN = {links: [['tijd', 'Tijd']], rechts: [['slim_huis', 'Slim huis']]};\n"
        "var staat = {widgets: %s, concept: {meldingen: true, meldgeluid: false, kolommen: {\n"
        "  links: [{id: 'tijd', aan: true}], rechts: [{id: 'slim_huis', aan: true}]}}};\n"
        "%s\n"
        "slaInstellingenOp();\n"
        "console.log(JSON.stringify(verstuurd));\n"
    ) % (json.dumps({"versie": 2, "kolommen": {}, "instellingen": {"hardop": True},
                     "slim_huis": KNOPPEN}), _functie(js, "slaInstellingenOp"))
    uit = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=20)
    assert uit.returncode == 0, uit.stderr
    body = json.loads(uit.stdout)
    assert body["slim_huis"] == KNOPPEN
    assert body["instellingen"] == {"hardop": True, "meldingen": True, "meldgeluid": False}
    assert body["kolommen"] == {"links": ["tijd"], "rechts": ["slim_huis"]}


def test_server_houdt_de_knoppen_vast(tmp_path):
    from dashboard.api import STANDAARD_WIDGETS, DashboardAPI

    api = DashboardAPI(widgets_pad=str(tmp_path / "d.json"), fase_fn=lambda: "rust",
                       spreekt_fn=lambda: False, audit_fn=lambda **k: None)
    config = json.loads(json.dumps(STANDAARD_WIDGETS))
    config["slim_huis"] = KNOPPEN
    assert api.widgets_opslaan(config)[0] == 200
    zonder = {k: v for k, v in config.items() if k != "slim_huis"}
    assert api.widgets_opslaan(zonder)[0] == 200
    assert api.widgets()[1]["slim_huis"] == KNOPPEN
