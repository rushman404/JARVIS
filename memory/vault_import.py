"""
JARVIS — Vault -> geheugen (Fase 14, Obsidian Stap 3)
====================================================

Brengt memories terug uit de Obsidian-vault naar memory.json.

DIT IS DE ENIGE PLEK waar de vault en het geheugen elkaar raken
----------------------------------------------------------------
Stap 1 en 2 zitten in memory/obsidian.py en die blijven volledig
vrij van memory.json: obsidian.py importeert NIETS uit memory.memory
of memory.store, en dat blijft zo. Om de bestaande conflictlogica te
kunnen hergebruiken moest er ergens een brug komen, en die brug is
dít bestand.

    memory/obsidian.py   -> alleen Markdown op schijf (obsidian.py
    memory/vault_import.py  -> dit bestand; voegt de geheugenkant toe

Volledig handmatig, altijd op verzoek
-------------------------------------
Er is geen enkele automatische synchronisatie:

  * een notitie die je in Obsidian schrijft komt vanzelf nergens aan
  * een memory die je onthoudt komt vanzelf niet in de vault
  * JARVIS scant de vault nooit op de achtergrond

Elke functie hier is iets wat een caller bewust aanroept. Er zit
geen watcher, geen timer, geen synchronisatieloop.

Gebruik van de bestaande conflictlogica
--------------------------------------
Er is bewust GEEN nieuwe versie van de conflictlogica geschreven.
Deze module doet precies drie dingen met Memory 2.0:

  1. mem.has_conflict()      om een conflict te herkennen
  2. mem.resolve_conflict()  om een bevestigd conflict toe te passen
  3. mem.remember()          om een nieuwe memory op te slaan

Daarmee geldt exact dezelfde regel als bij onthouden in een
gesprek: een andere waarde wordt nooit stilzwijgend overschreven.
Het enige verschil is dat je hier, anders dan bij onthouden, niet
kunt antwoorden met "ja"; je moet de keuze expliciet aan de
gebruiker voorleggen en daarna resolve_conflict() aanroepen.

Typegrens
---------
Een memory-waarde kan van elk type zijn. Bij het exporteren
(stap 2) wordt True de tekst "ja", een lijst wordt "- regel". Op
zichzelf is dat niet terug te lezen naar hetzelfde type, en een
notitie met "ja" zou dan een conflict opleveren met een memory die
True bewaart.

Daarom schrijft stap 2 twee velden mee in de frontmatter:

    value_type : str | bool | int | float | list | dict | null
    value_json : alleen bij niet-'str'-waarden de compacte JSON

Bij het importeren wordt de leesbare body geparseerd volgens
value_type, en value_json wint als de body nog exact de gerenderde
waarde is. Heeft de notitie geen (bruikbare) value_type — een
handgeschreven notitie, of een notitie uit een oudere versie — dan
blijft het oude stringgedrag staan.

Een memory met waarde None wordt niet langer stilzwijgend
overgeslagen: die krijgt `value_type: null` en komt gewoon terug.
"""

import json

from datetime import datetime

from memory import memory as mem
from memory import obsidian as ob


# =============================================================
# Frontmatter lezen
# =============================================================

def parse_frontmatter(text):
    """
    Splits Markdown in YAML-frontmatter en body.

    De frontmatter wordt met de standaardbibliotheek gelezen: per
    regel op het eerste ':' splitsen en quotes eraf halen. Dat is
    geen volledige YAML-parser, en dat is hier een voordeel: er is
    geen extra package nodig en er kan niets onverwachts gebeuren.

    Geeft (metadata, body) terug. metadata is altijd een dict; ook
    bij een notitie zonder frontmatter, dan is die leeg.

    LIJSTEN (Stap 7). De meeste velden zijn een tekstregel, maar
    `related` is een lijst. Die wordt in YAML als blocksequence
    geschreven:

        related:
          - gaming_pc
          - monitor

    De parser leest die vorm, en ook de compacte inline-vorm
    `related: [gaming_pc, monitor]`, want die schrijft een mens
    sneller. Een lijst komt als een echte lijst van strings terug;
    alle andere waarden blijven tekst, zoals ze altijd waren.
    """

    if not isinstance(text, str):
        return {}, ""

    tekst = text.lstrip("\ufeff")

    if not tekst.startswith("---"):
        return {}, tekst.strip()

    # De eerste '---' is het begin van de frontmatter, de tweede
    # het einde. Een '---' halverwege de body (een horizontale
    # streep) zou dus ook matchen, maar dan is er in de body geen
    # 'memory_key' en eindigt het import-spoor als 'geen memory'.
    delen = tekst.split("---", 2)

    if len(delen) < 3:
        return {}, tekst.strip()

    metadata = {}

    regels = delen[1].splitlines()

    index = 0

    while index < len(regels):

        regel = regels[index].strip()

        index += 1

        if not regel or regel.startswith("#") or ":" not in regel:
            continue

        sleutel, waarde = regel.split(":", 1)

        sleutel = sleutel.strip()
        waarde = waarde.strip()

        if waarde:

            inline = _inline_lijst(waarde)

            metadata[sleutel] = inline if inline is not None else _unquote(waarde)

            continue

        # Lege waarde: het kan een blocksequence zijn.
        items = []

        while index < len(regels):

            volgende = regels[index]
            gestript = volgende.strip()

            if not gestript.startswith("- "):
                break

            items.append(_unquote(gestript[2:].strip()))
            index += 1

        if items:
            metadata[sleutel] = items

    return metadata, delen[2].strip()


def _inline_lijst(waarde):
    """
    Leest een inline YAML-lijst: [a, b] of ["a", "b"].

    Geeft een lijst van strings terug, of None als de tekst geen
    inline lijst is. Bewust streng: alleen als het echt een lijst
    is lezen we hem zo, anders laten we de tekst staan.
    """

    if not waarde or not waarde.startswith("["):

        return None

    if not waarde.endswith("]"):

        return None

    binnen = waarde[1:-1].strip()

    if not binnen:

        return []

    return [_unquote(stuk.strip()) for stuk in binnen.split(",")
            if stuk.strip()]


def _unquote(text):
    """
    Haalt eventuele quotes van een frontmatter-waarde af.

    Ondersteunt zowel YAML-double-quotes ("...") als YAML-single-quotes
    ('...'). De Obsidian-schrijflaag zet een waarde tussen dubbele
    quotes, maar vervangt binnenin alle dubbele quotes door enkele,
    omdat een echte escape hier niet in de korte parser hoort.
    """

    if len(text) >= 2 and text[0] == text[-1] == '"':

        return text[1:-1].replace("'", '"')

    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1]

    return text


def read_note(name):
    """
    Leest een notitie en geeft {'metadata': ..., 'body': ...} terug.

    Geeft None terug als de notitie er niet is. Gooit ObsidianError
    bij een ongeldige notitienaam, net als de rest van de laag.
    """

    inhoud = ob.read_note(name)

    if inhoud is None:
        return None

    metadata, body = parse_frontmatter(inhoud)

    return {"metadata": metadata, "body": body}


# =============================================================
# Notitie -> memory
# =============================================================

def _extract_value(body):
    """
    Haalt de waarde uit het blockquote onder de titel.

    Stap 2 schrijft de waarde zo:

        > blauw

    Een lijst of dict wordt door format_value() over meerdere regels
    verdeeld en staat dus als:

        > - regel een
        > - regel twee

    We nemen alle opeenvolgende '>'-regels samen, zodat dat
    woordelijk hetzelfde terugkomt.
    """

    regels = []
    bezig = False

    for regel in body.splitlines():
        if regel.startswith(">"):
            bezig = True

            regels.append(regel[1:].strip())

            continue

        if bezig:
            break

    return "\n".join(regels).strip()


def _to_float(waarde, standaard):
    """Maakt een getal uit een frontmatter-waarde."""

    try:
        return float(waarde)
    except (TypeError, ValueError):
        return standaard


def _to_int(waarde, standaard):
    """Maakt een geheel getal uit een frontmatter-waarde."""

    try:
        return int(float(waarde))
    except (TypeError, ValueError):
        return standaard


def _waarde_uit_regels(tekst):
    """
    Leest de '- item' / '- sleutel: waarde'-regels van format_value()
    terug naar een lijst of een dict.

    De elementen blijven strings; het type komt van de waarde zelf
    (value_type) of van het meegestuurde value_json.
    """

    regels = [regel.strip()[1:].strip()
              for regel in str(tekst).splitlines()
              if regel.strip().startswith("- ")]

    if regels and all(":" in regel for regel in regels):
        return {r.split(":", 1)[0].strip(): r.split(":", 1)[1].strip()
                for r in regels}

    return regels


def _converteer_waarde(tekst, value_type, value_json):
    """
    Zet de body-tekst terug naar het memory-type dat value_type noemt.

    Volgorde:
      1. value_json wint als de body nog exact de gerenderde waarde is
         (de gebruiker heeft de leesbare body dus niet aangeraakt).
      2. anders wordt de body geparseerd volgens value_type.
      3. bij ontbrekende, onbekende of onleesbare value_type blijft het
         bestaande stringgedrag staan: een handgeschreven notitie zonder
         value_type levert gewoon een string, zoals altijd.
    """

    if value_type in (None, "", "str"):
        return tekst

    if value_type == "null":
        return None

    # 1. Machine-leesbare kopie, zolang de body niet is bewerkt
    if value_json:
        try:
            origineel = json.loads(value_json)

        except (TypeError, ValueError):
            origineel = None

        if origineel is not None or value_json == "null":
            if ob.format_value(origineel) == (tekst or ""):
                return origineel

    # 2. Uit de leesbare body, volgens value_type
    if value_type == "bool":
        if tekst is None:
            return None

        laag = str(tekst).strip().lower()

        if laag in ("ja", "true", "1", "yes", "on", "aan"):
            return True

        if laag in ("nee", "false", "0", "no", "off", "uit"):
            return False

        return tekst

    if value_type == "int":
        return _to_int(tekst, tekst)

    if value_type == "float":
        return _to_float(tekst, tekst)

    if value_type in ("list", "dict"):
        return _waarde_uit_regels(tekst or "")

    # Onbekend type: veilig terugvallen op de bestaande string.
    return tekst


def note_to_memory(name):
    """
    Zet één notitie om naar de gegevens van een memory.

    Geeft een dict terug met:
        key        : de memory-sleutel
        category   : de Memory 2.0-categorie uit de frontmatter,
                     met terugval op de categorie-detectie van
                     Memory 2.0 als de notitie er geen heeft
        value      : de waarde, teruggezet naar het type dat
                     value_type noemt (of een string als de notitie
                     geen bruikbare value_type heeft)
        priority   : de prioriteit (1.0 als de notitie er geen heeft)
        metadata   : de ruwe frontmatter

    Geeft None terug als de notitie geen memory-notitie is: een
    handgeschreven notitie (zoals Obsidians Welkom.md) heeft geen
    'memory_key' en wordt dus overgeslagen in plaats van mislukt.
    """

    data = read_note(name)

    if data is None:
        return None

    metadata = data["metadata"]
    sleutel = (metadata.get("memory_key") or "").strip()

    if not sleutel:
        return None

    categorie = (metadata.get("category") or "").strip()

    if not categorie:
        categorie = mem.get_category(sleutel, "")

    ruwe_waarde = _extract_value(data["body"])

    # Let op: hier wordt de TEKST geoordeeld, niet de waarde. False en 0
    # zijn geldige memory-waarden en moeten niet als "leeg" worden
    # weggegooid.
    lege_tekst = not (ruwe_waarde or "").strip()

    value_type = (metadata.get("value_type") or "").strip().lower() or None

    waarde = _converteer_waarde(
        ruwe_waarde,
        value_type,
        (metadata.get("value_json") or "").strip(),
    )

    if lege_tekst and value_type != "null":
        return None

    return {
        "key": sleutel,
        "category": categorie,
        "value": waarde,
        "priority": _to_float(metadata.get("priority"), 1.0),
        "metadata": metadata,
        "note_name": name,
        # Metadata-contract (Stap 7). None/[] betekent "niet in de
        # notitie", niet "leeg": het geheugen is de enige bron van
        # waarheid en een ontbrekend veld mag niets overschrijven.
        "created": (metadata.get("created") or "").strip() or None,
        "updated": (metadata.get("updated") or "").strip() or None,
        "usage_count": _to_int(metadata.get("usage_count"), None),
        "related": _note_related(metadata.get("related")),
    }


def _note_related(waarde):
    """
    Leest de `related`-lijst uit de frontmatter.

    Geeft een schone lijst van strings terug: geen duplicaten, geen
    lege regels, en altijd een lijst (ook [] als er niets stond).
    """

    if isinstance(waarde, str):
        waarde = [waarde]

    if not isinstance(waarde, (list, tuple)):
        return []

    schoon = []

    for item in waarde:

        if not isinstance(item, str):
            continue

        item = item.strip()

        if item and item not in schoon:
            schoon.append(item)

    return sorted(schoon)


def _lookup(key, category=None):
    """
    Zoekt de huidige entry op via de flexibele sleutelmatch van
    Memory 2.0.

    Dit is de ENIGE plek waar we een privát helper uit memory.py
    gebruiken, en dat is nodig om één ding te kunnen onderscheiden:
    has_conflict() geeft voor "bestaat nog niet" en voor "staat er al
    met dezelfde waarde" allebei (False, None, None). Bij het
    importeren is dat verschil belangrijk: de eerste moet worden
    opgeslagen, de tweede niet.

    De alternatieven waren de matchlogica hier dupliceren (dan loopt
    het twee keer uit elkaar) of 'unchanged' en 'nieuw' als hetzelfde
    behandelen (dan wordt een nieuwe memory stilzwijgend genegeerd).
    """

    gevonden_categorie, opgeslagen_sleutel, entry = mem._find_existing(
        key, category
    )

    return {
        "exists": entry is not None,
        "category": gevonden_categorie,
        "stored_key": opgeslagen_sleutel,
        "value": mem._unwrap(entry) if entry is not None else None,
    }


# =============================================================
# Plannen (schrijft nooit iets)
# =============================================================

def plan_import(name):
    """
    Berekent wat het importeren van deze notitie zou doen.

    Schrijft nooit iets, ook niet in memory.json. De 'action' is:

        new        : de memory bestaat nog niet
        conflict   : er staat een ANDERE waarde; beslissing nodig
        unchanged  : de waarde is identiek; er valt niets te doen
        skip       : geen memory-notitie, of onleesbaar

    Geeft altijd een dict terug met 'ok', 'action' en 'reason'.
    """

    plan = {
        "ok": False,
        "note_name": name,
        "key": None,
        "category": None,
        "value": None,
        "priority": 1.0,
        "action": "skip",
        "reason": "",
        "memory_value": None,
        "current_category": None,
        "created": None,
        "usage_count": None,
        "related": [],
    }

    notitie = note_to_memory(name)

    if notitie is None:
        inhoud = ob.read_note(name)

        if inhoud is None:
            plan["reason"] = "notitie bestaat niet"
        elif "memory_key" not in parse_frontmatter(inhoud)[0]:
            plan["reason"] = "geen memory-notitie (geen memory_key)"
        else:
            plan["reason"] = "geen bruikbare waarde"

        return plan

    plan["ok"] = True
    plan["key"] = notitie["key"]
    plan["category"] = notitie["category"]
    plan["value"] = notitie["value"]
    plan["priority"] = notitie["priority"]
    plan["created"] = notitie["created"]
    plan["usage_count"] = notitie["usage_count"]
    plan["related"] = notitie["related"]

    huidig = _lookup(notitie["key"], notitie["category"])

    plan["memory_value"] = huidig["value"]
    plan["current_category"] = huidig["category"]

    if not huidig["exists"]:
        plan["action"] = "new"
    elif str(huidig["value"]) != str(notitie["value"]):
        plan["action"] = "conflict"
    else:
        plan["action"] = "unchanged"

    return plan


def plan_import_all(subfolder=""):
    """
    Plannen voor alle memory-notities in (een map van) het vault.

    Schrijft nooit iets. Handgeschreven notities worden overgeslagen
    en daar niet eens voor meegeteld in de telling.
    """

    if not ob.vault_exists():
        return []

    plannen = []

    for notitie in ob.list_notes(subfolder):
        plan = plan_import(notitie)

        if plan["ok"]:
            plannen.append(plan)

    return plannen


# =============================================================
# Importeren (alleen als een caller erom vraagt)
# =============================================================

def _is_iso_timestamp(tekst):
    """
    Is dit een leesbaar ISO 8601-tijdstip?

    Puur een vormcheck: het gaat erom dat er geen nonsens in het
    geheugen belandt. Met tijdzone én zonder tijdzone zijn geldig,
    want bestaande memories kunnen nog het oudere formaat hebben.
    """

    if not tekst or not isinstance(tekst, str):
        return False

    try:
        return datetime.fromisoformat(tekst) is not None

    except (ValueError, TypeError):
        return False


def _apply_metadata(plan, category, stored_key=None, source="obsidian"):
    """
    Zet de metadata uit de notitie over op de memory-entry (Stap 7).

    De WAARDE staat hier niet bij. Die loopt via remember() /
    resolve_conflict() en vraagt zo nodig eerst om bevestiging; een
    metadatawijziging is geen tweede conflictarchitectuur en mag een
    onopgelost waardeconflict nooit overschrijven.

    Per veld één regel, en waarom:

      created    : wordt ALLEEN gezet als de entry nog geen created
                   heeft en de notitie er een levert. Een bestaande
                   created is de waarheid over wanneer het feit ontstond
                   en gaat nooit verloren door een import. Ontbreekt er
                   één, dan is er geen betrouwbare bron en laten we
                   hem None, in plaats van te gokken.
      usage_count: max() van wat er staat en wat de notitie zegt, zodat
                   een import gebruiksgeschiedenis nooit verkleint.
      updated    : wordt bewust NIET geïmporteerd. Het geheugen
                   bepaalt wanneer de waarde is gewijzigd; de notitie
                   zou hier alleen een tweede, concurrerende klok zijn.
      related    : de lijst uit de notitie wordt als echte relatie
                   toegepast via add_related(): dus alleen naar sleutels
                   die echt bestaan, nooit fuzzy, nooit naar zichzelf.
                   Handmatig toegevoegde relaties in Obsidian komen zo
                   aan bij memory.json, en relaties die uit de notitie
                   zijn gehaald verdwijnen aan beide kanten.

    Geeft een dict terug met wat er is gebeurd.
    """

    resultaat = {
        "created": False,
        "usage_count": False,
        "related_added": [],
        "related_removed": [],
    }

    if not stored_key:
        return resultaat

    memory = mem.load_memory()

    entry = None

    for cat in mem.DEFAULT_CATEGORIES:

        gevonden = memory.get(cat, {}).get(stored_key)

        if isinstance(gevonden, dict):
            entry = gevonden
            break

    if entry is None:
        return resultaat

    # --- created: alleen invullen als het er nog niet is ---
    if not entry.get("created") and _is_iso_timestamp(plan.get("created")):

        entry["created"] = plan["created"]
        resultaat["created"] = True

    # --- usage_count: nooit kleiner maken ---
    uit_notitie = plan.get("usage_count")

    if isinstance(uit_notitie, int) and uit_notitie > 0:

        huidig = entry.get("usage_count") or 0

        if uit_notitie > huidig:
            entry["usage_count"] = uit_notitie
            resultaat["usage_count"] = True

    if resultaat["created"] or resultaat["usage_count"]:
        mem.save_memory(memory)

    # --- related: via de echte relatie-API ---
    gewenst = list(plan.get("related") or [])

    huidige = mem.get_related(stored_key)

    for doel in gewenst:

        if mem._normalize_key(doel) == mem._normalize_key(stored_key):
            continue

        uitkomst = mem.add_related(stored_key, doel)

        if uitkomst.get("changed"):
            resultaat["related_added"].append(uitkomst["related"])

    # Wat in het geheugen stond maar niet meer in de notitie, weghalen.
    # Ook dit is bidirectioneel: beide kanten gaan eraf.
    for doel in list(huidige):

        if mem._normalize_key(doel) in [mem._normalize_key(d) for d in gewenst]:
            continue

        uitkomst = mem.remove_related(stored_key, doel)

        if uitkomst.get("removed"):
            resultaat["related_removed"].append(uitkomst["related"])

    return resultaat


def import_note(name, force=False, priority=None, source="obsidian"):
    """
    Importeert één notitie naar memory.json.

    Volledig op verzoek: deze functie doet niets tenzij je haar
    aanroept, en er is geen achtergrondproces dat haar aanroept.

    Gebruikt de bestaande Memory 2.0-conflictlogica:

      * onbekende memory   -> mem.remember()
      * identieke waarde   -> niets, en dat wordt net zo gemeld
      * andere waarde      -> NIET opgeslagen. Er komt een
                              needs_confirm-uitkomst terug met de
                              waarde uit de vault, de huidige
                              waarde, en een 'confirm_token' die je
                              aan resolve_pending() meegeeft.

    'confirm_token' is een dict, geen tekenreeks. Je hoeft dus niet
    zelf een JSON-string te onthouden om het conflict later af te
    handelen.

    Args:
        name:     de notitienaam in het vault
        force:    het conflict TOCH toepassen zonder bevestiging.
                  Alleen gebruiken nadat de gebruiker 'ja' heeft
                  gezegd; anders is de bevestigingsronde zinloos.
        priority: overschrijft de prioriteit uit de notitie
        source:   provenance die in het geheugen komt te staan

    Returns:
        een dict met 'action', 'applied', 'needs_confirm' en,
        bij een conflict, 'confirm_token'.
    """

    plan = plan_import(name)

    uitkomst = {
        "note_name": name,
        "key": plan["key"],
        "category": plan["category"],
        "value": plan["value"],
        "action": plan["action"],
        "applied": False,
        "needs_confirm": False,
        "reason": plan["reason"],
        "confirm_token": None,
        "memory_value": plan["memory_value"],
        # Metadata-contract (Stap 7): wat er met created, usage_count
        # en related is gebeurd. Standaard leeg, want bij een
        # needs_confirm wordt er niets toegepast.
        "metadata": {},
    }

    if not plan["ok"]:
        return uitkomst

    if plan["action"] == "unchanged":
        uitkomst["reason"] = "waarde is al identiek"

        # De waarde is gelijk, maar de metadata kan wél verschillen:
        # iemand kan in Obsidian alleen de `related`-lijst hebben
        # aangepast. Dat is een metadatawijziging, geen waardeconflict,
        # dus die wordt hier gewoon toegepast.
        huidig = _lookup(plan["key"], plan["category"])

        uitkomst["metadata"] = _apply_metadata(
            plan,
            huidig["category"] or plan["category"],
            stored_key=huidig["stored_key"],
            source=source,
        )

        return uitkomst

    if plan["action"] == "conflict" and not force:
        uitkomst["needs_confirm"] = True
        uitkomst["reason"] = "vault en geheugen verschillen"
        uitkomst["confirm_token"] = {
            "note_name": name,
            "key": plan["key"],
            "category": plan["current_category"] or plan["category"],
            "stored_key": _lookup(plan["key"], plan["category"])["stored_key"],
            "vault_value": plan["value"],
            "priority": priority if priority is not None else plan["priority"],
            "source": source,
            # Metadata uit dezelfde notitie meenemen. Een waardeconflict
            # en een metadatawijziging zijn twee dingen, maar zodra de
            # gebruiker de waarde bevestigt, hoort de metadata van die
            # notitie er ook bij. Anders zou de relatie-wijziging in
            # Obsidian bij een waardeconflict stilletjes verloren gaan.
            "created": plan["created"],
            "usage_count": plan["usage_count"],
            "related": plan["related"],
        }

        return uitkomst

    if plan["action"] == "conflict":
        # De bevestiging is binnen; dezelfde weg als 'onthoud, wijzig'.
        huidig = _lookup(plan["key"], plan["category"])

        mem.resolve_conflict(
            huidig["stored_key"],
            plan["value"],
            keep_old=False,
            category=huidig["category"],
            priority=priority if priority is not None else plan["priority"],
        )

        uitkomst["metadata"] = _apply_metadata(
            plan,
            huidig["category"] or plan["category"],
            stored_key=huidig["stored_key"],
            source=source,
        )

        uitkomst["applied"] = True

        return uitkomst

    # Nieuwe memory: precies het gewone onthouden-pad.
    mem.remember(
        plan["key"],
        plan["value"],
        category=plan["category"],
        source=source,
        priority=priority if priority is not None else plan["priority"],
    )

    # `created` en `related` komen uit de notitie; de waarde is nu pas
    # vastgelegd, dus dit is het moment om de metadata ernaast te zetten.
    opgeslagen = _lookup(plan["key"], plan["category"])

    uitkomst["metadata"] = _apply_metadata(
        plan,
        plan["category"],
        stored_key=opgeslagen["stored_key"] or plan["key"],
        source=source,
    )

    uitkomst["applied"] = True

    return uitkomst


def resolve_pending(token, keep_old=False):
    """
    Werkt een gemeld conflict af, na een keuze van de gebruiker.

    Args:
        token:    de 'confirm_token' uit import_note()
        keep_old: True  -> de waarde uit het geheugen blijft staan
                  False -> de waarde uit de vault wordt actueel, en de
                           oude blijft bewaard in previous_value
                  (precies zoals 'onthoud, wijzig' in een gesprek)

    Geeft hetzelfde dict terug als mem.resolve_conflict().
    """

    if not isinstance(token, dict):
        raise TypeError("confirm_token moet de dict uit import_note() zijn")

    for verplicht in ("stored_key", "vault_value"):
        if verplicht not in token:
            raise ValueError("confirm_token mist het veld %r" % verplicht)

    uitkomst = mem.resolve_conflict(
        token["stored_key"],
        token["vault_value"],
        keep_old=keep_old,
        category=token.get("category"),
        priority=token.get("priority"),
    )

    # De waarde is nu beslist. De metadata uit dezelfde notitie mag
    # daarna toegepast worden; dat is geen tweede conflictronde maar
    # het afmaken van dezelfde handeling.
    metadata = _apply_metadata(
        token,
        token.get("category"),
        stored_key=token["stored_key"],
        source=token.get("source", "obsidian"),
    )

    if metadata["created"] or metadata["usage_count"]:
        uitkomst["created"] = True

    if metadata["related_added"] or metadata["related_removed"]:
        uitkomst["related"] = metadata

    return uitkomst


def import_all(subfolder="", force=False, dry_run=True, priority=None,
               source="obsidian"):
    """
    Importeert alle memory-notities uit (een map van) het vault.

    LET OP: dry_run staat STANDAARD op True. Dan wordt er niets
    geschreven, alleen een plan. Met dry_run=False worden de
    onproblematische notities daadwerkelijk geïmporteerd.

    Conflicten worden NOOIT stilzwijgend opgelost, ook niet met
    dry_run=False. Ze komen terecht in 'conflicts', met een token
    per stuk, zodat je ze één voor één aan de gebruiker kunt
    voorleggen en daarna resolve_pending() kunt aanroepen.

    Args:
        subfolder: map in het vault; leeg = het hele vault
        force:     conflicten zonder bevestiging toepassen (zie
                   import_note(); alleen na akkoord van de gebruiker)
        dry_run:   True = alleen een plan, schrijft niets (standaard)
        priority:  overschrijft de prioriteit uit elke notitie
        source:    provenance die in het geheugen komt te staan

    Returns:
        een dict met 'count', 'imported', 'conflicts', 'plans'.
    """

    plannen = plan_import_all(subfolder)

    for plan in plannen:
        plan["dry_run"] = bool(dry_run)
        plan["applied"] = False

    geimporteerd = []
    conflicten = []

    if not dry_run:
        for plan in plannen:
            if plan["action"] == "unchanged":
                continue

            uitkomst = import_note(plan["note_name"], force=force,
                                   priority=priority, source=source)

            plan["applied"] = uitkomst["applied"]

            if uitkomst["needs_confirm"]:
                conflicten.append(uitkomst)
            elif uitkomst["applied"]:
                geimporteerd.append(plan["note_name"])

    telling = {
        "gevonden": len(plannen),
        "nieuw": sum(1 for p in plannen if p["action"] == "new"),
        "onveranderd": sum(1 for p in plannen if p["action"] == "unchanged"),
        "conflict": sum(1 for p in plannen if p["action"] == "conflict"),
        "geimporteerd": len(geimporteerd),
    }

    return {
        "dry_run": bool(dry_run),
        "count": telling,
        "imported": geimporteerd,
        "conflicts": conflicten,
        "plans": plannen,
    }


def compare_vault_to_memory(subfolder=""):
    """
    Vergelijkt de vault met memory.json. VOLLEDIG READ-ONLY.

    Schrijft nooit iets, naar de vault of naar het geheugen. Deze
    analyse is er om een overzicht te geven vóór er ook maar iets
    gebeurt.

    Geeft een dict terug met:

        ok             : is de analyse uitgevoerd?
        vault_exists   : bestaat het vault wel?
        subfolder      : de geanalyseerde map (leeg = hele vault)
        notes          : per memory-notitie een record met
                         note_name, key, value, category en action
        new            : notities die nog niet in het geheugen staan
        conflicts      : notities waarvan de waarde verschilt
        unchanged      : notities waarvan de waarde gelijk is
        counts         : een telling per groep
    """

    rapport = {
        "ok": False,
        "reason": "",
        "vault_exists": ob.vault_exists(),
        "vault_path": ob.get_vault_path(),
        "subfolder": subfolder,
        "notes": [],
        "new": [],
        "conflicts": [],
        "unchanged": [],
        "counts": {"new": 0, "conflict": 0, "unchanged": 0, "total": 0},
    }

    if not rapport["vault_exists"]:
        rapport["reason"] = "vault bestaat niet"

        return rapport

    rapport["ok"] = True

    alle_notities = ob.list_notes(subfolder)

    for notitie in alle_notities:
        try:
            plan = plan_import(notitie)
        except Exception as exc:
            rapport["reason"] = "ongeldige notitie: %s" % exc
            continue

        if not plan["ok"]:
            continue

        record = {
            "note_name": plan["note_name"],
            "key": plan["key"],
            "value": plan["value"],
            "category": plan["category"],
            "memory_value": plan["memory_value"],
            "action": plan["action"],
        }

        rapport["notes"].append(record)

        if plan["action"] == "new":
            rapport["new"].append(record)
        elif plan["action"] == "conflict":
            rapport["conflicts"].append(record)
        elif plan["action"] == "unchanged":
            rapport["unchanged"].append(record)

    rapport["counts"] = {
        "new": len(rapport["new"]),
        "conflict": len(rapport["conflicts"]),
        "unchanged": len(rapport["unchanged"]),
        "total": len(rapport["notes"]),
    }

    return rapport


# =============================================================
# Batch-import (Stap 5)
# =============================================================
#
# De batch is een TOESTANDSDACHINE. Er zit geen verborgen lus in
# memory.json en geen achtergrondproces; alles gebeurt doordat een
# caller resolve_paused_batch() aanroept nadat de gebruiker 'ja' of
# 'nee' heeft gezegd.
#
#   start_batch()  -> state met een wachtrij, draait tot het eerste
#                     conflict en staat daarna stil (geen schrijfactie)
#   resolve_paused_batch()
#                 -> resolve_conflict() voor dát ene conflict en gaat
#                    daarna gecontroleerd verder met de wachtrij
#
# DrieInvarianten:
#
#   1. GEEN DUBBELE IMPORT: state["processed"] bevat elke notitie die
#      klaar is. Verwerkt een notitie zichzelf nog eens, dan wordt dat
#      expliciet overgeslagen (status "dubbel", die niet op de wachtrij
#      hoeft te staan).
#   2. CONFLICTEN LOPEN ALLEMAAL VIA resolve_conflict(): zowel 'ja' als
#      'nee'. Bij 'nee' wordt het conflict als afgehandeld vastgelegd
#      met de afgewezen waarde ernaast, net als bij onthouden in een
#      gesprek. Er wordt nooit met force=True gewerkt.
#   3. VEILIG STOPPEN: bij een onverwachte fout stopt de batch. De
#      resterende wachtrij blijft staan, zodat niets als 'verwerkt'
#      geldt wat niet is gebeurd.
# =============================================================

# Status per notitie in een batch.
BATCH_STATUS = {
    "new": "nieuw in het geheugen",
    "imported": "geimporteerd",
    "unchanged": "onveranderd, niets gedaan",
    "waiting": "wacht op jouw ja of nee",
    "accepted": "conflict opgelost met de vault-waarde",
    "kept": "conflict afgewezen, geheugen ongewijzigd",
    "planned": "zou geimporteerd worden (dry_run)",
    "conflict_planned": "zou een conflict geven (dry_run)",
    "error": "mislukt",
    "duplicate": "al in deze batch verwerkt",
}


def _batch_record(note_name, key, category, status, value=None, reason=""):
    """Eén resultaatregel voor de batch."""

    return {
        "note_name": note_name,
        "key": key,
        "category": category,
        "value": value,
        "status": status,
        "label": BATCH_STATUS.get(status, status),
        "reason": reason,
    }


def _batch_counts(state):
    """Telt de statussen in de huidige state."""

    telling = {status: 0 for status in BATCH_STATUS}

    for result in state["results"]:
        telling[result["status"]] = telling.get(result["status"], 0) + 1

    telling["total"] = len(state["results"])

    return telling


def start_batch(subfolder="", dry_run=True, priority=None, source="obsidian"):
    """
    Start een batch-import. Alleen als de gebruiker erom vraagt.

    LET OP: dry_run staat STANDAARD op True. Dan wordt er NIETS
    geschreven en krijg je alleen het plan terug.

    Met dry_run=False worden de onproblematische notities meteen
    geimporteerd, tot de eerste tegenstrijdigheid. Daar stopt de
    batch: het conflict komt terug als 'waiting', met een 'confirm'
    dat je aan resolve_paused_batch() meegeeft als de gebruiker 'ja' of
    'nee' heeft gezegd.

    De 'state' die je terugkrijgt is volledig JSON-geschikt en kan dus
    ongewijzigd in het pending_choice van brain.py bewaard worden.

    Returns:
        een dict met 'results', 'queue', 'processed', 'confirm',
        'paused', 'done', 'stopped' en 'count'.
    """

    vergelijking = compare_vault_to_memory(subfolder)

    state = {
        "subfolder": subfolder,
        "priority": priority,
        "source": source,
        "dry_run": bool(dry_run),
        "results": [],
        "queue": [],
        "processed": [],
        "confirm": None,
        "paused": False,
        "done": False,
        "stopped": False,
        "error": None,
    }

    if not vergelijking["ok"]:
        state["stopped"] = True
        state["error"] = vergelijking["reason"]
        state["count"] = _batch_counts(state)

        return state

    # Alle memory-notities komen in de wachtrij, zodat iedere notitie
    # een eigen statusregel krijgt. 'unchanged' wordt onderweg
    # afgevakt zonder te schrijven; dat is het enige verschil met
    # Stap 3, waar die stilletjes overgeslagen werden.
    state["queue"] = [record["note_name"] for record in vergelijking["notes"]]

    if dry_run:
        return _dry_run_batch(state, vergelijking)

    return _advance_batch(state)


def _dry_run_batch(state, vergelijking):
    """
    Vult de state met wat er ZOU gebeuren, zonder iets te schrijven.
    """

    status = {"new": "planned", "conflict": "conflict_planned"}

    for record in vergelijking["notes"]:
        if record["action"] == "unchanged":
            status[record["action"]] = "unchanged"

        state["results"].append(_batch_record(
            record["note_name"],
            record["key"],
            record["category"],
            status.get(record["action"], "planned"),
            value=record["value"],
            reason="dry_run: er is niets geschreven",
        ))

        state["processed"].append(record["note_name"])

    state["queue"] = []
    state["done"] = True
    state["count"] = _batch_counts(state)

    return state


def _advance_batch(state):
    """
    Verwerk de wachtrij tot: het eerste conflict, het einde, of een fout.

    Deze functie schrijft nooit twee keer dezelfde notitie, want
    state["processed"] groeit mee met elke afgeronde notitie.
    """

    while state["queue"]:
        notitie = state["queue"][0]

        #Invariant 1: nooit dezelfde notitie twee keer verwerken.
        if notitie in state["processed"]:
            state["queue"].pop(0)
            state["results"].append(_batch_record(
                notitie, None, None, "duplicate",
                reason="stond al in de wachtrij van deze batch",
            ))
            continue

        try:
            plan = plan_import(notitie)
        except Exception as exc:
            state["queue"].pop(0)
            state["results"].append(_batch_record(
                notitie, None, None, "error",
                reason="onleesbare notitie: %s: %s" % (type(exc).__name__, exc),
            ))
            state["stopped"] = True
            state["error"] = "%s: %s" % (type(exc).__name__, exc)
            state["done"] = True
            state["count"] = _batch_counts(state)

            return state

        if not plan["ok"]:
            state["queue"].pop(0)
            state["results"].append(_batch_record(
                notitie, plan["key"], plan["category"], "unchanged",
                reason=plan["reason"],
            ))
            state["processed"].append(notitie)
            continue

        if plan["action"] == "unchanged":
            state["queue"].pop(0)
            state["results"].append(_batch_record(
                notitie, plan["key"], plan["category"], "unchanged",
                value=plan["value"],
                reason="waarde is al identiek",
            ))
            state["processed"].append(notitie)
            continue

        if plan["action"] == "conflict":
            # De conflictnotitie is NIET afgerond en komt dus niet in
            # state["processed"]; hij blijft de kop van de wachtrij tot
            # de gebruiker heeft geantwoord.
            state["results"].append(_batch_record(
                notitie, plan["key"], plan["category"], "waiting",
                value=plan["value"],
                reason="wacht op bevestiging",
            ))
            state["confirm"] = _confirm_from_plan(plan, state)
            state["paused"] = True
            state["count"] = _batch_counts(state)

            return state

        # Een nieuwe memory: het gewone onthouden-pad.
        try:
            uitkomst = import_note(notitie, priority=state.get("priority"),
                                   source=state.get("source", "obsidian"))
        except Exception as exc:
            state["queue"].pop(0)
            state["results"].append(_batch_record(
                notitie, plan["key"], plan["category"], "error",
                reason="fout bij importeren: %s: %s" % (type(exc).__name__, exc),
            ))
            state["stopped"] = True
            state["error"] = "%s: %s" % (type(exc).__name__, exc)
            state["done"] = True
            state["count"] = _batch_counts(state)

            return state

        state["queue"].pop(0)

        if uitkomst.get("needs_confirm"):
            # Onverwacht, want 'new' hoort geen conflict te geven. We
            # stoppen liever dan dat we hier stilzwijgend doorheen
            # schrijven.
            state["results"].append(_batch_record(
                notitie, plan["key"], plan["category"], "error",
                value=plan["value"],
                reason="onverwacht conflict bij een nieuwe memory",
            ))
            state["stopped"] = True
            state["error"] = "onverwacht conflict bij %s" % notitie
            state["done"] = True
            state["count"] = _batch_counts(state)

            return state

        state["results"].append(_batch_record(
            notitie, plan["key"], plan["category"],
            "imported" if uitkomst.get("applied") else "error",
            value=plan["value"],
            reason=uitkomst.get("reason", ""),
        ))
        state["processed"].append(notitie)

    state["done"] = True
    state["paused"] = False
    state["confirm"] = None
    state["count"] = _batch_counts(state)

    return state


def _confirm_from_plan(plan, state):
    """
    Bouwt het 'confirm'-blok voor een gepauzeerd conflict.

    Vormt dezelfde velden als het confirm_token uit import_note(),
    zodat er één afhandelingspad is.
    """

    huidig = _lookup(plan["key"], plan["category"])

    return {
        "note_name": plan["note_name"],
        "key": plan["key"],
        "stored_key": huidig["stored_key"],
        "category": huidig["category"] or plan["category"],
        "vault_value": plan["value"],
        "memory_value": huidig["value"],
        "priority": state.get("priority"),
        "source": state.get("source", "obsidian"),
    }


def resolve_paused_batch(state, keep_old):
    """
    Rond het gepauzeerde conflict af en hervat daarna de batch.

    Dit is het enige plek waar een batch een conflict afhandelt, en
    dat gaat via resolve_conflict() uit memory.py: de bestaande
    Memory 2.0-logica, niet een eigen versie.

      keep_old=True  -> 'nee': het geheugen blijft zoals het is. Het
                        conflict wordt als afgehandeld vastgelegd met
                        de afgewezen waarde ernaast, zodat je er niet
                        steeds opnieuw om gevraagd wordt.
      keep_old=False -> 'ja': de vault-waarde wordt de actuele waarde
                        en de oude gaat naar previous_value.

    Daarna gaat de batch gecontroleerd verder met de volgende
    notities. Stopt de batch opnieuw bij een conflict, dan staat er
    een nieuw 'confirm' klaar.

    Geeft de bijgewerkte state terug.
    """

    if not isinstance(state, dict):
        raise TypeError("state moet de dict uit start_batch() zijn")

    confirm = state.get("confirm")

    if not state.get("paused") or not confirm:
        # Geen openstaand conflict: niets te doen, wel de batch
        # laten doorlopen als die nog niet klaar was.
        return _advance_batch(state) if not state.get("done") else state

    notitie = confirm["note_name"]

    try:
        # De bestaande logica. Nooit force=True.
        resolve_pending(
            {
                "note_name": notitie,
                "key": confirm["key"],
                "stored_key": confirm["stored_key"],
                "category": confirm["category"],
                "vault_value": confirm["vault_value"],
                "priority": confirm.get("priority"),
            },
            keep_old=keep_old,
        )
    except Exception as exc:
        state["stopped"] = True
        state["done"] = True
        state["paused"] = False
        state["confirm"] = None
        state["error"] = "%s: %s" % (type(exc).__name__, exc)
        state["count"] = _batch_counts(state)

        for result in state["results"]:
            if result["note_name"] == notitie and result["status"] == "waiting":
                result["status"] = "error"
                result["label"] = BATCH_STATUS["error"]
                result["reason"] = "conflict afhandelen mislukt: %s" % exc

        return state

    # Het conflict is nu afgehandeld: deze notitie is klaar en komt in
    # 'processed', zodat de wachtrij hem niet nog eens oppakt.
    state["processed"].append(notitie)

    for result in state["results"]:
        if result["note_name"] == notitie and result["status"] == "waiting":
            result["status"] = "kept" if keep_old else "accepted"
            result["label"] = BATCH_STATUS[result["status"]]
            result["reason"] = (
                "je hield je geheugen aan"
                if keep_old else "de waarde uit de vault is nu actueel"
            )

    state["confirm"] = None
    state["paused"] = False

    # Verwijder de afgehandelde notitie uit de kop van de wachtrij en
    # ga verder met wat er nog ligt.
    if state["queue"] and state["queue"][0] == notitie:
        state["queue"].pop(0)

    return _advance_batch(state)


def batch_is_finished(state):
    """True als er niets meer te doen is: klaar of gestopt."""

    if not isinstance(state, dict):
        return True

    return bool(state.get("done") or state.get("stopped"))


