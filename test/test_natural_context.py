# -*- coding: utf-8 -*-
"""
FASE 11.1 — Natuurlijke context-tests.

Verifieert dat verwijzingen ("hem", "het", "die", "deze", enz.)
correct gekoppeld worden aan het meest relevante recente apparaat/
programma, en dat er veilig NIET gegokt wordt zonder context.

Deterministisch: alle systeemgrenzen (PC-vensters, programma's,
Home Assistant) en entity-resolutie worden gemockt; de
HA-referentie- en PC-referentieroutes worden direct aangeroepen.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

import core.ai as _ai
import core.brain as _brain
from core.brain import (
    try_ha_reference,
    try_window_command,
    try_close_program,
    try_open_program,
)

passed = 0
failed = 0


def ok(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [OK] {label}" + (f"  | {detail}" if detail else ""))
    else:
        failed += 1
        print(f"  [X]  {label}" + (f"  | {detail}" if detail else ""))


def set_context(**kw):
    base = {
        "last_command": "", "last_result": "", "last_action": "",
        "last_calculation": "", "last_program": "", "last_file": "",
        "last_website": "", "last_ha_entity": "", "last_ha_domain": "",
        "last_ha_name": "", "pending_choice": None,
    }
    base.update(kw)
    _ai.current_context.update(base)


pc_calls = []
ha_calls = []


def fake_min(p): pc_calls.append(("minimize", p)); return f"{p} geminimaliseerd."
def fake_max(p): pc_calls.append(("maximize", p)); return f"{p} vergroot."
def fake_rest(p): pc_calls.append(("restore", p)); return f"{p} hersteld."
def fake_cls(p): pc_calls.append(("close", p)); return f"{p} gesloten."
def fake_ope(p): pc_calls.append(("open", p)); return f"{p} geopend."
def fake_ha(d, s, e, sd=None): ha_calls.append((d, s, e, sd or {})); return f"{e} is {s} (ok)."


HA_MOCKS = patch.object(_brain, "control_home_assistant_tool", side_effect=fake_ha)
CLOSE_MOCK = patch.object(_brain, "close_program_tool", side_effect=fake_cls)
OPEN_MOCK = patch.object(_brain, "open_program_tool", side_effect=fake_ope)
PC_MOCKS = [
    patch.object(_brain, "minimize_program", side_effect=fake_min),
    patch.object(_brain, "maximize_program", side_effect=fake_max),
    patch.object(_brain, "restore_window", side_effect=fake_rest),
]


print("\n=== FASE 11.1 NATUURLIJKE CONTEXT ===\n")

print("[1] PC: 'maak hem/het/die/deze kleiner' -> laatst geopend programma\n")
for ref in ["hem", "het", "die", "deze"]:
    set_context(last_program="discord")
    pc_calls.clear()
    with PC_MOCKS[0]:
        try_window_command(f"maak {ref} kleiner")
    ok(f"'maak {ref} kleiner' -> discord", pc_calls == [("minimize", "discord")], str(pc_calls))

print("\n[2] PC: 'sluit hem/het/die/deze' -> laatst geopend programma\n")
for ref in ["hem", "het", "die", "deze"]:
    set_context(last_program="discord")
    pc_calls.clear()
    with CLOSE_MOCK:
        try_close_program(f"sluit {ref}")
    ok(f"'sluit {ref}' -> discord", pc_calls == [("close", "discord")], str(pc_calls))

print("\n[3] HA: 'maak hem/het/die/deze groen' -> laatste HA-apparaat\n")
for ref in ["hem", "het", "die", "deze"]:
    set_context(last_ha_entity="light.bed_lamp", last_ha_domain="light")
    ha_calls.clear()
    with HA_MOCKS:
        try_ha_reference(f"maak {ref} groen")
    ok(f"'maak {ref} groen' -> bed_lamp groen",
       ha_calls and ha_calls[0][1] == "turn_on"
       and ha_calls[0][2] == "light.bed_lamp"
       and ha_calls[0][3].get("hs_color") == [120, 100], str(ha_calls))

print("\n[4] HA: 'zet hem/het/die/deze op 30%' -> laatste HA-apparaat\n")
for ref in ["hem", "het", "die", "deze"]:
    set_context(last_ha_entity="light.bed_lamp", last_ha_domain="light")
    ha_calls.clear()
    with HA_MOCKS:
        try_ha_reference(f"zet {ref} op 30%")
    ok(f"'zet {ref} op 30%' -> brightness 30",
       ha_calls and ha_calls[0][3].get("brightness_pct") == 30, str(ha_calls))

print("\n[5] Laatste PC-programma: open X -> sluit hem\n")
set_context(last_program="discord")
pc_calls.clear()
with CLOSE_MOCK:
    try_close_program("sluit hem")
ok("'sluit hem' -> laatst geopend (discord)", pc_calls == [("close", "discord")], str(pc_calls))
set_context(last_program="spotify")
pc_calls.clear()
with CLOSE_MOCK:
    try_close_program("sluit hem")
ok("na open Spotify is 'hem'=spotify", pc_calls == [("close", "spotify")], str(pc_calls))

print("\n[6] Laatste HA-apparaat: zet aan -> maak groen -> 30% -> uit\n")
set_context(last_ha_entity="light.bed_lamp", last_ha_domain="light")
ha_calls.clear()
with HA_MOCKS:
    try_ha_reference("maak hem groen")
    try_ha_reference("zet hem op 30%")
    try_ha_reference("doe hem uit")
ok("aan->groen->30%->uit allemaal op bed_lamp",
   all(h[2] == "light.bed_lamp" for h in ha_calls)
   and ha_calls[0][3].get("hs_color") == [120, 100]
   and ha_calls[1][3].get("brightness_pct") == 30
   and ha_calls[2][1] == "turn_off", str(ha_calls))

print("\n[7] Gemengde context: PC + HA blijven gescheiden\n")
set_context(last_program="discord", last_ha_entity="light.bed_lamp", last_ha_domain="light")
ha_calls.clear()
with HA_MOCKS:
    try_ha_reference("maak hem blauw")
ok("'maak hem blauw' -> HA bed_lamp (niet PC discord)",
   ha_calls and ha_calls[0][2] == "light.bed_lamp"
   and ha_calls[0][3].get("hs_color") == [240, 100], str(ha_calls))
pc_calls.clear()
with PC_MOCKS[0]:
    try_window_command("maak hem kleiner")
ok("'maak hem kleiner' -> PC discord (niet HA bed_lamp)",
   pc_calls == [("minimize", "discord")], str(pc_calls))

print("\n[8] Geen context -> veilig NIET gokken\n")
set_context()
pc_calls.clear()
out = try_window_command("maak hem kleiner")
ok("'maak hem kleiner' zonder context -> vraag, geen actie", out is not None and "aanpas" in out, repr(out))
ok("geen pc-actie uitgevoerd", not pc_calls, str(pc_calls))
pc_calls.clear()
out = try_close_program("sluit hem")
ok("'sluit hem' zonder context -> vraag, geen actie", "Welk programma" in out, repr(out))
ok("geen close uitgevoerd", not pc_calls, str(pc_calls))

print("\n[9] Expliciet apparaat overschrijft context\n")
set_context(last_program="discord", last_ha_entity="light.bed_lamp", last_ha_domain="light")
pc_calls.clear()
with PC_MOCKS[0]:
    try_window_command("maak Spotify kleiner")
ok("expliciete 'Spotify kleiner' -> spotify (niet discord)",
   pc_calls == [("minimize", "spotify")], str(pc_calls))

print("\n[10] Context blijft correct na meerdere acties\n")
set_context(last_program="spotify")
pc_calls.clear()
with CLOSE_MOCK:
    try_close_program("sluit hem")
ok("na open Discord+Spotify is 'hem'=spotify", pc_calls == [("close", "spotify")], str(pc_calls))

set_context(last_ha_entity="light.woonkamer", last_ha_domain="light")
ha_calls.clear()
with HA_MOCKS:
    try_ha_reference("doe hem uit")
ok("na 2 HA-acties is 'hem'=woonkamer",
   ha_calls and ha_calls[0][2] == "light.woonkamer", str(ha_calls))

print(f"\n=== RESULTAAT: {passed} geslaagd, {failed} gefaald ===")
