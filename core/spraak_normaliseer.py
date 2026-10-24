"""Spraaknormalisatie: repareer typische spraakherkenningsfouten.

Google's spraakherkenning schrijft woorden zoals ze klinken. Een bestandsnaam
met een underscore komt er dan als "jarvis laag streepje test.txt" uit, en
"in downloads" wordt "en download". Het brein zoekt vervolgens naar een
bestand dat letterlijk zo heet en vindt niets.

Deze module zet zulke stukken terug naar wat de gebruiker bedoelde, vóórdat
het commando wordt verwerkt:

* "laag streepje" / "lag streepje" / "onderstreping" / "underscore" -> "_"
* "punt txt" -> ".txt" (alleen bij bekende bestandsextensies)
* "en/in/uit download(s)" -> "in downloads" (alleen in een bestandsopdracht)

De regels zijn bewust smal: ze raken alleen tekst die over bestanden gaat.
Een gewone vraag ("wat is het punt") blijft dus ongemoeid.
"""

import re

# Extensies die we na het woord "punt" herkennen. Bewust een korte lijst:
# bij twijfel liever niets vervangen dan een gewone zin verminken.
_EXTENSIES = (
    "txt", "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "csv",
    "json", "log", "md", "py", "ps1", "bat", "jpg", "jpeg", "png", "gif",
    "bmp", "mp3", "wav", "mp4", "mkv", "zip", "rar", "7z",
)

_ONDERSTREEP = re.compile(
    r"\b(?:laag|lage|lag|laagje)\s+streepje\b|\bonderstrep(?:ing|ingen)\b"
    r"|\bunderscore(?:\s+teken)?\b",
    re.IGNORECASE,
)

_PUNT_EXTENSIE = re.compile(
    r"\bpunt\s+(" + "|".join(_EXTENSIES) + r")\b",
    re.IGNORECASE,
)

_DOWNLOAD = re.compile(r"\b(?:en|in|uit|vanuit)\s+downloads?\b", re.IGNORECASE)
_DOWNLOAD_MAP = re.compile(r"\bdownload\s*map\b", re.IGNORECASE)

# Een bestandsopdracht: alleen dan herschrijven we "en download" naar
# "in downloads". Zo blijft "download het bestand" gewoon een download.
_BESTAND_CONTEXT = re.compile(
    r"\b(?:bestand|file|open|zoek|toon|map|folder)\b|\.(?:"
    + "|".join(_EXTENSIES)
    + r")\b",
    re.IGNORECASE,
)


def normaliseer_spraak(tekst):
    """Repareer spraakruis in een commando; geeft altijd een string terug."""

    if not tekst or not isinstance(tekst, str):
        return tekst

    resultaat = tekst

    # 1) Underscore-woorden -> "_"
    resultaat = _ONDERSTREEP.sub("_", resultaat)

    # 2) "punt txt" -> ".txt"
    resultaat = _PUNT_EXTENSIE.sub(lambda m: "." + m.group(1).lower(), resultaat)

    # 3) Downloads-map (alleen in een bestandsopdracht)
    if _BESTAND_CONTEXT.search(resultaat):
        resultaat = _DOWNLOAD.sub("in downloads", resultaat)
        resultaat = _DOWNLOAD_MAP.sub("in downloads", resultaat)

    # 4) Spaties rond de underscore en voor de punt opruimen, zodat er
    #    "jarvis_test.txt" staat in plaats van "jarvis _ test . txt".
    resultaat = re.sub(r"\s*_\s*", "_", resultaat)
    resultaat = re.sub(r"\s+\.\s*", ".", resultaat)
    resultaat = re.sub(r"\s{2,}", " ", resultaat)

    return resultaat.strip()
