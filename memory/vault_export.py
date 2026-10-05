"""
JARVIS — Memory 2.0 naar Obsidian (Fase 14, Stap 6)
===================================================

De exportrichting: memory.json -> Obsidian.

In stap 2 stond de export al in obsidian.py
(save_all_memories_to_vault), maar die was niet bereikbaar: er riep
niets hem aan behalve tests. Deze module maakt hem wél bruikbaar en
vooral VEILIG, als spiegelbeeld van vault_import.py uit stap 5.

Groot verschil met de import
---------------------------
Bij het importeren (vault -> geheugen) betekent 'ja' dat het GEHEUGEN
wordt gewijzigd. Bij het exporteren is dat omgekeerd:

    'ja'  -> alleen de Obsidian-notitie wordt herschreven
    'nee' -> de notitie blijft exact zoals hij is

memory.json is in stap 6 de BRON VAN WAARHEID en wordt door de
hele exportflow nooit geschreven. Er wordt dan ook geen remember(),
update_memory() of resolve_conflict() aangeroepen; memory.py wordt
alleen LEZEND gebruikt om de notities te berekenen.

Veiligheidsregels
-----------------
1. Er is geen enkele automatische koppeling. Zonder een commando van
   de gebruiker wordt er niets geschreven.
2. dry_run staat STANDAARD op True.
3. Een notitie waarvan de memory_key ontbreekt, of waaraan je zelf
   tekst hebt toegevoegd, wordt NOOIT overschreven.
4. Bij een verschil (drift) stopt de batch en wordt gevraagd.
5. Bij een onverwachte fout stopt de batch; de wachtrij blijft staan.
6. Nooit twee keer dezelfde notitie schrijven.

Bekende beperking
----------------
De 'Gerelateerd'-wiki-links bestaan uit alle sleutels in dezelfde
categorie. Dat is een volledige graaf, geen relaties. Echte
memory-relaties horen bij stap 7 en worden hier bewust niet
aangeraakt: ook ENTRY_META_KEYS blijft ongemoeid.
"""

from memory import memory as mem
from memory import obsidian as ob
from memory.vault_import import parse_frontmatter


# =============================================================
# Status per notitie in een exportbatch
# =============================================================

EXPORT_STATUS = {
    "create": "nieuwe notitie in de vault",
    "written": "geschreven in de vault",
    "unchanged": "onveranderd, niets gedaan",
    "waiting": "wacht op jouw ja of nee",
    "overwritten": "notitie herschreven met jouw 'ja'",
    "kept": "notitie laten staan na jouw 'nee'",
    "blocked": "niet overschreven: niet van JARVIS of eigen tekst erin",
    "planned": "zou geschreven worden (dry_run)",
    "drift_planned": "zou een verschil geven (dry_run)",
    "error": "mislukt",
    "duplicate": "al in deze batch verwerkt",
    "skip": "overgeslagen",
}


# =============================================================
# Herkennen van een door JARVIS beheerde notitie
# =============================================================

# De labels die memory_to_note() zelf in de detailslijst zet.
_DETAIL_LABELS = set(ob.FIELD_LABELS.values()) | {
    "Sleutel", "Categorie", "Vorige waarde", "Expliciet gecorrigeerd",
}

# De 'date:' in de frontmatter is de dag waarop de notitie werd
# geschreven. Die verandert elke dag, ook zonder dat er iets in het
# geheugen verandert. Vergelijken moet daarom niet op de datum
# gebeuren, anders is elke notitie de volgende dag 'drift'.
_DATUM_VELD = "date:"


def _zonder_datum(inhoud):
    """Verwijdert de 'date:'-regel uit de frontmatter, voor vergelijking."""

    regels = []
    in_frontmatter = False
    scheiding = 0

    for regel in inhoud.splitlines():
        if regel.strip() == "---":
            scheiding += 1
            in_frontmatter = scheiding == 1

            regels.append(regel)
            continue

        if in_frontmatter and regel.startswith(_DATUM_VELD):
            continue

        regels.append(regel)

    return "\n".join(regels)


def _alleen_jarvis_inhoud(body, sleutel=None):
    """
    True als de body uitsluitend regels bevat die JARVIS zelf schrijft.

    Zo herkennen we eigen tekst. De body die memory_to_note() bouwt
    heeft een vaste vorm: de kop '# {sleutel}', een citaatregel,
    '## Details' met bekende labels, en eventueel '## Gerelateerd'
    met wiki-links. Alles wat daarbuiten valt is tekst die de
    gebruiker heeft toegevoegd, en die wordt nooit stilzwijgend
    overschreven.
    """

    kop = ("# %s" % str(sleutel).strip()) if sleutel is not None else None

    zag_details = False
    ziet_gerelateerd = False
    zag_kop = kop is None

    for regel in body.splitlines():
        tekst = regel.strip()

        if not tekst:
            continue

        if kop is not None and tekst == kop:
            zag_kop = True
            continue

        if tekst.startswith(">"):
            continue

        if tekst == "## Details":
            zag_details = True
            continue

        if tekst == "## Gerelateerd":
            ziet_gerelateerd = True
            continue

        if ziet_gerelateerd:
            # Alleen wiki-links zijn hier van JARVIS.
            if tekst.startswith("- [[") and tekst.endswith("]]"):
                continue

            return False

        if zag_details and tekst.startswith("- "):
            label = tekst[2:].split(":", 1)[0].strip()

            if label in _DETAIL_LABELS:
                continue

            return False

        # Koppen, citaatregels en de detailslijst zijn hier al
        # afgevangen; alles wat overblijft is eigen tekst.
        return False

    return zag_kop and zag_details


def _classificeer(plan, bestaande):
    """
    Bepaalt wat er met één memory-notitie moet gebeuren.

    Geeft (action, reden) terug, waarbij action één van
    create / unchanged / drift / blocked is.
    """

    if bestaande is None:
        return "create", ""

    metadata, body = parse_frontmatter(bestaande)

    memory_key = metadata.get("memory_key")

    if not memory_key:
        return "blocked", "geen memory_key: dit is geen JARVIS-notitie"

    if str(memory_key).strip() != str(plan["memory_key"]).strip():
        return "blocked", ("memory_key '%s' hoort bij een andere memory"
                           % memory_key)

    if not _alleen_jarvis_inhoud(body, memory_key):
        return "blocked", "de notitie bevat tekst die niet van JARVIS is"

    if _zonder_datum(bestaande) == _zonder_datum(plan["content"]):
        return "unchanged", "de notitie is al gelijk"

    return "drift", "de notitie wijkt af van je geheugen"


# =============================================================
# Vergelijken: de ene plek waar de notities worden bepaald
# =============================================================

def _vergelijk_alle():
    """
    Berekent voor elke memory-entry wat er met de notitie moet
    gebeuren.

    Volledig READ-ONLY: hier wordt niets geschreven, in de vault of
    in het geheugen.

    Geeft (ok, reden, records) terug. Elk record heeft de notitie,
    de memory-sleutel, de waarde, de categorie, de precieze inhoud
    die geschreven zou worden, en de action.
    """

    records = []

    if not ob.vault_exists():
        return False, "vault bestaat niet op '%s'" % ob.get_vault_path(), records

    # plan_all_memories_to_vault() rekent de notitie uit zoals die er
    # ook echt uit zou zien, inclusief het afhandelen van
    # naambotsingen. Zo vergelijken we tegen precies de inhoud die
    # een export zou wegschrijven.
    for plan in ob.plan_all_memories_to_vault(mem.load_memory()):
        if not plan["ok"] or not plan["note_name"]:
            continue

        if plan["action"] == "no-vault":
            return False, plan["reason"] or "vault bestaat niet", records

        try:
            bestaande = ob.read_note(plan["note_name"])
        except Exception as exc:
            bestaande = None
            reden = "kon de notitie niet lezen: %s" % exc
            action = "blocked"
        else:
            action, reden = _classificeer(plan, bestaande)

        records.append({
            "note_name": plan["note_name"],
            "key": plan["memory_key"],
            "category": plan["category"],
            "value": plan["value"],
            "content": plan["content"],
            "action": action,
            "reason": reden,
        })

    return True, "", records


def compare_memory_to_vault():
    """
    Vergelijkt memory.json met de vault. VOLLEDIG READ-ONLY.

    Schrijft nooit iets: geen notitie, geen byte, geen mtime. Er is
    geen enkele automatische koppeling; dit is alleen een overzicht
    vóórdat er misschien iets gebeurt.

    Geeft een dict terug met:

        ok           : is de vergelijking uitgevoerd?
        reason       : toelichting als dat niet zo was
        vault_path   : welk vault is bekeken
        notes        : per memory-entry een record met note_name,
                       key, value, category, action en reason
        create       : memories waarvoor nog geen notitie bestaat
        unchanged    : notities die al gelijk zijn
        drift        : notities die afwijken en bevestiging vragen
        blocked      : notities die nooit automatisch overschreven
                       worden
        counts       : een telling per groep
    """

    rapport = {
        "ok": False,
        "reason": "",
        "vault_path": ob.get_vault_path(),
        "notes": [],
        "create": [],
        "unchanged": [],
        "drift": [],
        "blocked": [],
        "counts": {"create": 0, "unchanged": 0, "drift": 0,
                   "blocked": 0, "total": 0},
    }

    ok, reden, records = _vergelijk_alle()

    rapport["ok"] = ok
    rapport["reason"] = reden

    for record in records:
        regel = {
            "note_name": record["note_name"],
            "key": record["key"],
            "category": record["category"],
            "value": record["value"],
            "action": record["action"],
            "label": EXPORT_STATUS.get(record["action"], record["action"]),
            "reason": record["reason"],
        }

        rapport["notes"].append(regel)
        rapport[record["action"]].append(regel)

    for groep in ("create", "unchanged", "drift", "blocked"):
        rapport["counts"][groep] = len(rapport[groep])

    rapport["counts"]["total"] = len(rapport["notes"])

    return rapport


# =============================================================
# Batch-export
# =============================================================
#
# Zelfde opzet als de batch-import uit stap 5: een toestandmachine
# met geen verborgen lus. start_export() draait tot de eerste drift
# en staat daarna stil; resolve_paused_export() hervat pas nadat de
# gebruiker 'ja' of 'nee' heeft gezegd.
#
# Invarianten:
#
#   1. GEEN DUBBELE WRITE: state["processed"] bevat elke notitie die
#      klaar is.
#   2. GEHEUGEN BLIJFT VROEG: dit bestand roept nooit remember(),
#      update_memory() of resolve_conflict() aan. memory.py wordt
#      alleen gebruikt om te LEZEN.
#   3. VEILIG STOPPEN: bij een onverwachte fout stopt de batch en
#      blijft de wachtrij staan.
#   4. NOOIT STILZWIJGEND OVERSCHRIJVEN: een 'blocked' notitie wordt
#      nooit geschreven, ook niet als iemand 'ja' zou zeggen.
# =============================================================

def _resultaat(record, status, reden=""):
    """Eén resultaatregel voor de batch."""

    return {
        "note_name": record["note_name"],
        "key": record["key"],
        "category": record["category"],
        "value": record["value"],
        "status": status,
        "label": EXPORT_STATUS.get(status, status),
        "reason": reden if reden else record.get("reason", ""),
    }


def _counts(state):
    """Telt de statussen in de huidige state."""

    telling = {status: 0 for status in EXPORT_STATUS}

    for result in state["results"]:
        telling[result["status"]] = telling.get(result["status"], 0) + 1

    telling["total"] = len(state["results"])

    return telling


def start_export(dry_run=True):
    """
    Start een export van memory.json naar de vault. Alleen op
    expliciete vraag van de gebruiker.

    LET OP: dry_run staat STANDAARD op True. Dan wordt er NIETS
    geschreven en krijg je alleen het plan terug.

    Met dry_run=False worden de onproblematige memories meteen
    geschreven, tot de eerste drift. Daar stopt de batch: die komt
    terug als 'waiting', met een 'confirm' dat je meegeeft aan
    resolve_paused_export() zodra de gebruiker 'ja' of 'nee' heeft
    gezegd.

    De 'state' die je terugkrijgt is JSON-geschikt als je
    export_state_for_storage() gebruikt.

    Returns:
        een dict met 'results', 'queue', 'processed', 'confirm',
        'paused', 'done', 'stopped', 'dry_run', 'counts' en 'error'
    """

    state = {
        "dry_run": bool(dry_run),
        "results": [],
        "queue": [],
        "processed": [],
        "confirm": None,
        "paused": False,
        "done": False,
        "stopped": False,
        "error": None,
        "counts": {},
        # De berekende notities, inclusief de exact te schrijven
        # inhoud. Bewust privé: dit is intern en te groot om in het
        # context-bestand te bewaren.
        "_plans": {},
    }

    ok, reden, records = _vergelijk_alle()

    if not ok:
        state["stopped"] = True
        state["done"] = True
        state["error"] = reden
        state["counts"] = _counts(state)

        return state

    for record in records:
        state["_plans"][record["note_name"]] = record
        state["queue"].append(record["note_name"])

    return _advance_export(state)


def _schrijf_notitie(note_name, inhoud, sleutel=None):
    """
    Schrijft één notitie, met een laatste veiligheidscontrole.

    Er wordt NIET blind geschreven: vlak voor het schrijven kijken
    we nog eens of de bestaande notitie nog steeds een JARVIS-notitie
    is met een passende memory_key. Sinds het vergelijken kan er
    iets veranderd zijn, en dan schrijven we liever niets.
    """

    if inhoud is None:
        return False

    # resolve_note_path() gooit ObsidianError op alles wat onveilig
    # is, dus ook op een pad dat uit de memory-sleutel komt.
    ob.resolve_note_path(note_name)

    bestaande = ob.read_note(note_name)

    if bestaande is not None:
        metadata, body = parse_frontmatter(bestaande)

        memory_key = metadata.get("memory_key")

        if not memory_key:
            raise ValueError(
                "de notitie heeft geen memory_key meer; ik schrijf er "
                "niet overheen"
            )

        if sleutel is not None and str(memory_key).strip() != str(sleutel).strip():
            raise ValueError(
                "de notitie hoort bij een andere memory; ik schrijf er "
                "niet overheen"
            )

        if not _alleen_jarvis_inhoud(body, memory_key):
            raise ValueError(
                "de notitie bevat eigen tekst; ik schrijf er niet "
                "overheen"
            )

    return bool(ob.write_note(note_name, inhoud, overwrite=True))


def _vault_waarde(note_name):
    """Leest de huidige waarde uit een bestaande notitie."""

    try:
        inhoud = ob.read_note(note_name)
    except Exception:
        return None

    if inhoud is None:
        return None

    _, body = parse_frontmatter(inhoud)

    for regel in body.splitlines():
        tekst = regel.strip()

        if tekst.startswith("> "):
            return tekst[2:].strip()

    return None


def _advance_export(state):
    """
    Draait de wachtrij tot de eerste drift, of tot het einde.

    Schrijft 'create'-notities, laat 'unchanged' en 'blocked' staan
    en stopt bij 'drift' met een 'confirm'.
    """

    while state["queue"]:
        note_name = state["queue"][0]

        # Invariant 1: nooit dezelfde notitie twee keer verwerken.
        if note_name in state["processed"]:
            state["queue"].pop(0)
            state["results"].append(_resultaat(
                state["_plans"][note_name], "duplicate",
                "stond al in de wachtrij van deze batch",
            ))
            continue

        record = state["_plans"][note_name]
        action = record["action"]

        if state["dry_run"]:
            status = {
                "create": "planned",
                "unchanged": "unchanged",
                "drift": "drift_planned",
                "blocked": "blocked",
            }.get(action, "skip")

            state["queue"].pop(0)
            state["processed"].append(note_name)
            state["results"].append(_resultaat(record, status))

            continue

        if action == "unchanged":
            state["queue"].pop(0)
            state["processed"].append(note_name)
            state["results"].append(_resultaat(record, "unchanged"))

            continue

        if action == "blocked":
            # Invariant 4: hier wordt nooit iets geschreven.
            state["queue"].pop(0)
            state["processed"].append(note_name)
            state["results"].append(_resultaat(record, "blocked"))

            continue

        if action == "drift":
            # Nog niet afgerond, dus nog niet in 'processed'. Deze
            # notitie blijft de kop van de wachtrij tot de gebruiker
            # geantwoord heeft.
            state["results"].append(_resultaat(
                record, "waiting", "wacht op bevestiging",
            ))
            state["confirm"] = {
                "note_name": note_name,
                "key": record["key"],
                "category": record["category"],
                "memory_value": record["value"],
                "vault_value": _vault_waarde(note_name),
            }
            state["paused"] = True
            state["counts"] = _counts(state)

            return state

        # action == "create": de gewone weg.
        try:
            geschreven = _schrijf_notitie(note_name, record["content"],
                                          record["key"])
        except Exception as exc:
            state["queue"].pop(0)
            state["results"].append(_resultaat(
                record, "error",
                "fout bij schrijven: %s: %s" % (type(exc).__name__, exc),
            ))
            state["stopped"] = True
            state["error"] = "%s: %s" % (type(exc).__name__, exc)
            state["done"] = True
            state["counts"] = _counts(state)

            return state

        state["queue"].pop(0)

        if not geschreven:
            state["results"].append(_resultaat(
                record, "error", "de notitie is niet geschreven",
            ))
            state["stopped"] = True
            state["error"] = "de notitie is niet geschreven"
            state["done"] = True
            state["counts"] = _counts(state)

            return state

        state["processed"].append(note_name)
        state["results"].append(_resultaat(record, "written"))

    state["done"] = True
    state["paused"] = False
    state["confirm"] = None
    state["counts"] = _counts(state)

    return state


def resolve_paused_export(state, overwrite):
    """
    Rond de gepauzeerde drift af en hervat daarna de batch.

    Dit is het enige plek waar een drift wordt afgehandeld, en dat
    raakt ALLEEN de Obsidian-notitie aan:

      overwrite=True  -> 'ja': de notitie wordt herschreven met de
                         waarde uit memory.json
      overwrite=False -> 'nee': er gebeurt helemaal niets en de
                         notitie blijft precies zoals hij was

    memory.json wordt in beide gevallen NIET gewijzigd. Er wordt
    geen remember(), update_memory() of resolve_conflict() gebruikt.

    Geeft de bijgewerkte state terug.
    """

    if not isinstance(state, dict):
        raise TypeError("state moet de dict uit start_export() zijn")

    if not isinstance(state.get("_plans"), dict):
        state["_plans"] = _herbereken_plannen()

    confirm = state.get("confirm")

    if not state.get("paused") or not confirm:
        return _advance_export(state) if not state.get("done") else state

    note_name = confirm["note_name"]
    record = state["_plans"].get(note_name)

    if record is None:
        state["stopped"] = True
        state["done"] = True
        state["paused"] = False
        state["confirm"] = None
        state["error"] = ("de notitie %s staat niet meer in je geheugen"
                          % note_name)
        state["counts"] = _counts(state)

        return state

    if record["action"] == "blocked":
        # Zou niet kunnen, maar als een notitie tussen het vergelijken
        # en nu geblokkeerd is geraakt, schrijven we niets.
        _rond_notitie(state, note_name, "blocked")

        return _advance_export(state)

    if overwrite:
        try:
            geschreven = _schrijf_notitie(note_name, record["content"],
                                          record["key"])
        except Exception as exc:
            state["stopped"] = True
            state["done"] = True
            state["paused"] = False
            state["confirm"] = None
            state["error"] = "%s: %s" % (type(exc).__name__, exc)
            state["counts"] = _counts(state)

            for result in state["results"]:
                if (result["note_name"] == note_name
                        and result["status"] == "waiting"):
                    result["status"] = "error"
                    result["label"] = EXPORT_STATUS["error"]
                    result["reason"] = "notitie herschrijven mislukt: %s" % exc

            return state

        status = "overwritten" if geschreven else "error"
        reden = "" if geschreven else "de notitie is niet geschreven"

        if not geschreven:
            state["stopped"] = True
            state["error"] = reden
    else:
        # 'nee': er wordt niets aangeraakt.
        status = "kept"
        reden = "notitie laten staan"

    _rond_notitie(state, note_name, status, reden)

    return _advance_export(state)


def _rond_notitie(state, note_name, status, reden=""):
    """Zet één notitie definitief af en haal hem van de wachtrij."""

    if note_name in state["queue"]:
        state["queue"].remove(note_name)

    if note_name not in state["processed"]:
        state["processed"].append(note_name)

    for result in state["results"]:
        if result["note_name"] == note_name and result["status"] == "waiting":
            result["status"] = status
            result["label"] = EXPORT_STATUS.get(status, status)
            result["reason"] = reden or result["reason"]


def _herbereken_plannen():
    """Berekent de plannen opnieuw, zonder iets te schrijven."""

    _, _, records = _vergelijk_alle()

    return {record["note_name"]: record for record in records}


def export_is_finished(state):
    """
    Geeft betrouwbaar aan hoe verder de batch is:

        "done"    : klaar, alles afgehandeld
        "paused"  : wacht op een 'ja' of 'nee'
        "error"   : gestopt op een fout
        "running" : nog bezig (wachtrij niet leeg, geen beslissing)

    Een ongeldige of lege state telt als klaar: er viel niets te
    doen.
    """

    if not isinstance(state, dict):
        return "done"

    if state.get("stopped") or state.get("error"):
        return "error"

    if state.get("paused"):
        return "paused"

    if state.get("done") or not state.get("queue"):
        return "done"

    return "running"


def export_state_for_storage(state):
    """
    Maakt de state geschikt om in het context-bestand te bewaren.

    '_plans' gaat eruit: dat is intern en bevat de volledige
    notitie-inhoud. Bij een hervatte batch worden de plannen opnieuw
    berekend; dat raakt het geheugen niet.
    """

    if not isinstance(state, dict):
        return {}

    return {k: v for k, v in state.items() if not k.startswith("_")}


def export_state_from_storage(bewaard):
    """
    Maakt een bewaarde state weer bruikbaar voor
    resolve_paused_export().
    """

    if not isinstance(bewaard, dict):
        return {}

    state = dict(bewaard)
    state["_plans"] = _herbereken_plannen()

    return state