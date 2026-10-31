"""Storingslog: wat er misgaat met verstaan en het wake word (Fase 32).

Alleen **aantallen** per dag, lokaal in ``memory/storingen.json`` (60 dagen).
Nooit wat u zei en nooit geluid.

Soorten (zie :data:`SOORTEN`):

* ``beurt`` — een opname ging naar de spraakherkenning;
* ``verstaan`` — er kwam tekst uit (met de duur in ``duur_verstaan``);
* ``tweede_poging`` — de eerste poging lukte niet, er volgde een tweede;
* ``niet_verstaan`` — ook de tweede poging leverde niets op;
* ``google_fout`` — de spraakherkenning (Google) was niet bereikbaar;
* ``wakker`` — het wake word werd herkend;
* ``vals_alarm`` — wakker geworden, maar daarna niets gezegd;
* ``bijna_wakker`` — "JARVIS" bijna herkend (score net onder de drempel);
* ``whisper`` — een beurt verstaan door Whisper (Fase 33);
* ``whisper_terugval`` — Whisper kon niet, Google nam het over.

:func:`overzicht` zet deze week naast vorige week voor de iPad.
"""

import json
import logging
import os
import threading
from datetime import date, datetime, timedelta

logger = logging.getLogger("jarvis.storingen")

STORINGEN_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "memory", "storingen.json")
BEWAAR_DAGEN = 60

SOORTEN = ("beurt", "verstaan", "tweede_poging", "niet_verstaan", "google_fout",
           "wakker", "vals_alarm", "bijna_wakker", "whisper", "whisper_terugval")

_lock = threading.Lock()


def _lees(pad=None):
    try:
        with open(pad or STORINGEN_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _schrijf(data, pad=None, vandaag=None):
    pad = pad or STORINGEN_FILE
    grens = ((vandaag or date.today()) - timedelta(days=BEWAAR_DAGEN)).isoformat()
    data = {dag: v for dag, v in data.items() if dag >= grens}
    os.makedirs(os.path.dirname(pad), exist_ok=True)
    tijdelijk = pad + ".tmp"
    with open(tijdelijk, "w", encoding="utf-8") as f:
        json.dump(data, f, sort_keys=True)
    os.replace(tijdelijk, pad)


def tel(soort, duur=None, pad=None, nu=None):
    """Telt één gebeurtenis; ``duur`` (seconden) gaat bij ``verstaan`` mee.

    Faalt stil: het storingslog mag zelf nooit een storing veroorzaken.
    """

    if soort not in SOORTEN:
        return
    try:
        dag = (nu or datetime.now()).date().isoformat()
        with _lock:
            data = _lees(pad)
            regel = data.setdefault(dag, {})
            regel[soort] = int(regel.get(soort, 0)) + 1
            if duur is not None and soort == "verstaan":
                regel["duur_verstaan"] = round(float(regel.get("duur_verstaan", 0.0)) + float(duur), 3)
            _schrijf(data, pad, (nu or datetime.now()).date())
    except Exception:
        logger.debug("Kon de storing niet tellen.", exc_info=True)


def _optellen(data, van, tot):
    som = {s: 0 for s in SOORTEN}
    som["duur_verstaan"] = 0.0
    dag = van
    while dag <= tot:
        regel = data.get(dag.isoformat()) or {}
        for sleutel in som:
            som[sleutel] += regel.get(sleutel, 0) or 0
        dag += timedelta(days=1)
    return som


def _procent(deel, geheel):
    return round(100.0 * deel / geheel) if geheel else None


def _week(som):
    return {
        "beurten": som["beurt"],
        "niet_verstaan": som["niet_verstaan"],
        "niet_verstaan_pct": _procent(som["niet_verstaan"], som["beurt"]),
        "tweede_poging": som["tweede_poging"],
        "tweede_poging_pct": _procent(som["tweede_poging"], som["beurt"]),
        "google_fout": som["google_fout"],
        "verstaan_gem": round(som["duur_verstaan"] / som["verstaan"], 1) if som["verstaan"] else None,
        "wakker": som["wakker"],
        "vals_alarm": som["vals_alarm"],
        "vals_alarm_pct": _procent(som["vals_alarm"], som["wakker"]),
        "bijna_wakker": som["bijna_wakker"],
        "whisper": som["whisper"],
        "whisper_terugval": som["whisper_terugval"],
    }


def overzicht(pad=None, vandaag=None):
    """Deze week (laatste 7 dagen) en de week daarvoor, plus per dag."""

    vandaag = vandaag or date.today()
    data = _lees(pad)
    deze = _optellen(data, vandaag - timedelta(days=6), vandaag)
    vorige = _optellen(data, vandaag - timedelta(days=13), vandaag - timedelta(days=7))
    dagen = []
    for i in range(6, -1, -1):
        dag = vandaag - timedelta(days=i)
        regel = data.get(dag.isoformat()) or {}
        dagen.append({"dag": dag.isoformat(), "beurten": regel.get("beurt", 0),
                      "niet_verstaan": regel.get("niet_verstaan", 0),
                      "vals_alarm": regel.get("vals_alarm", 0)})
    return {"deze_week": _week(deze), "vorige_week": _week(vorige), "dagen": dagen}


def wis(pad=None):
    with _lock:
        _schrijf({}, pad)
