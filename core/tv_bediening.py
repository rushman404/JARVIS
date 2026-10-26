"""De tv bedienen met de stem (Fase 21, M2).

Pauze en verder, volume ("zet de tv op 20"), dempen, volgende aflevering,
een andere app of bron openen en de tv aan/uit, rechtstreeks via Home
Assistant (LG webOS). Alles is laag risico: geen ja/nee-vraag.

Zinnen met "tv" gaan altijd naar de tv. Korte zinnen zonder "tv"
("pauze", "speel verder") gaan alleen naar de tv als de film-modus aanstaat;
anders blijven ze de muziek op de pc bedienen, zoals altijd.
"volgende aflevering" betekent op de pc niets en gaat dus altijd naar de tv.

Het verschil met de film-modus: "zet YouTube op de tv" start de film-modus
(pc stil, terugzetten na de film); "open YouTube op de tv" of "schakel de
tv naar HDMI 1" wisselt alleen de app of bron.
"""

import re

from core import filmmodus

_TV = r"(?:de\s+)?(?:tv|televisie)"
_GETAL = r"(\d{1,3})(?:\s*(?:procent|%))?"
STAP = 0.05  # harder/zachter: 5 procent per keer

# (soort, patroon). Volgorde telt: de eerste die past wint.
PATRONEN = [
    ("aan", rf"^(?:zet|doe)\s+{_TV}\s+aan$|^{_TV}\s+aan$"),
    ("uit", rf"^(?:zet|doe|schakel)\s+{_TV}\s+uit$|^{_TV}\s+uit$"),
    ("volume", rf"^zet\s+{_TV}\s+(?:volume\s+)?(?:op|naar)\s+{_GETAL}$"),
    ("volume", rf"^(?:zet\s+)?(?:het\s+)?(?:volume\s+van\s+{_TV}|{_TV}\s*volume)\s+(?:op|naar)\s+{_GETAL}$"),
    ("harder", rf"^(?:zet\s+)?{_TV}\s+(?:harder|luider)$|^(?:zet\s+)?(?:het\s+)?(?:volume\s+van\s+{_TV}|{_TV}\s*volume)\s+(?:omhoog|harder)$"),
    ("zachter", rf"^(?:zet\s+)?{_TV}\s+(?:zachter|stiller)$|^(?:zet\s+)?(?:het\s+)?(?:volume\s+van\s+{_TV}|{_TV}\s*volume)\s+(?:omlaag|zachter)$"),
    ("demp", rf"^(?:demp|mute)\s+{_TV}$|^{_TV}\s+(?:dempen|stil|op\s+stil)$|^zet\s+{_TV}\s+op\s+stil$"),
    ("ontdemp", rf"^(?:ontdemp|unmute)\s+{_TV}$|^(?:zet\s+)?(?:het\s+)?geluid\s+van\s+{_TV}\s+(?:weer\s+)?aan$|^{_TV}\s+geluid\s+(?:weer\s+)?aan$"),
    ("pauze", rf"^(?:pauzeer|pauze|stop)\s+{_TV}$|^{_TV}\s+(?:op\s+)?pauze$|^zet\s+{_TV}\s+op\s+pauze$"),
    ("verder", rf"^(?:hervat|speel)\s+{_TV}(?:\s+verder)?$|^{_TV}\s+(?:verder|hervatten)$|^speel\s+verder\s+op\s+{_TV}$"),
    ("volgende", r"^(?:(?:start|speel|ga\s+naar|naar)\s+(?:de\s+)?)?volgende\s+aflevering$"),
    ("app", rf"^(?:open|start)\s+(.+?)\s+op\s+{_TV}$"),
    ("app", rf"^(?:schakel|zet)\s+{_TV}\s+(?:op|naar)\s+(.+)$"),
]

# Alleen als de film-modus aanstaat: korte zinnen zonder "tv".
FILM_PATRONEN = [
    ("pauze", r"^(?:pauze|pauzeer|pauzeer\s+de\s+film|zet\s+de\s+film\s+op\s+pauze|film\s+pauze)$"),
    ("verder", r"^(?:speel\s+verder|hervat|hervat\s+de\s+film|speel\s+de\s+film\s+verder|film\s+verder)$"),
]

_GECOMPILEERD = [(s, re.compile(p)) for s, p in PATRONEN]
_FILM_GECOMPILEERD = [(s, re.compile(p)) for s, p in FILM_PATRONEN]


def herken(tekst, film_aan=None):
    """``(soort, waarde)`` of None. ``film_aan`` None = zelf nakijken."""

    t = filmmodus._schoon(tekst)
    if not t:
        return None
    for soort, patroon in _GECOMPILEERD:
        m = patroon.match(t)
        if not m:
            continue
        waarde = m.group(1) if m.groups() else None
        if soort == "app" and filmmodus.herken(t) is not None:
            # "zet de tv op Disney+" is de film-modus (M1).
            return None
        return soort, waarde
    if film_aan is None:
        film_aan = filmmodus.lees_toestand() is not None
    if film_aan:
        for soort, patroon in _FILM_GECOMPILEERD:
            if patroon.match(t):
                return soort, None
    return None


def _norm(tekst):
    return re.sub(r"[^a-z0-9+]", "", str(tekst or "").lower())


def zoek_bron(gevraagd, bronnen):
    """De bron van de tv die bij de gevraagde naam past, of None."""

    sleutel = filmmodus.dienst_uit(gevraagd)
    if sleutel:
        for woord in filmmodus.DIENSTEN[sleutel][0]:
            for b in bronnen:
                if woord in str(b).lower():
                    return b
    doel = _norm(gevraagd)
    if not doel:
        return None
    for b in bronnen:
        if _norm(b) == doel:
            return b
    for b in bronnen:
        if _norm(b).startswith(doel) or doel in _norm(b):
            return b
    try:
        from rapidfuzz import fuzz, process

        beste = process.extractOne(doel, {b: _norm(b) for b in bronnen}, scorer=fuzz.ratio)
        if beste and beste[1] >= 80:
            return beste[2]
    except Exception:
        pass
    return None


class TvBediening:
    def __init__(self, film=None):
        self.film = film

    def _film(self):
        return self.film or filmmodus.get_filmmodus()

    def voer_uit(self, soort, waarde=None, kort=False):
        """``kort``: een zin zonder "tv" (alleen tijdens de film-modus).
        Staat de tv dan uit, dan hoort de zin bij de pc (None)."""
        film = self._film()
        ha = film.ha
        tv, knop = film._zoek_tv()
        if not tv:
            # Geen mediaspeler gevonden: de gewone HA-afhandeling (bijv. een
            # tv-stekker) mag het dan proberen.
            return None
        staat = ha.staat(tv) or {}
        aan = staat.get("state") in filmmodus.AAN_STATEN
        attrs = staat.get("attributes") or {}

        if soort == "aan":
            if aan:
                return "De tv staat al aan, sir."
            return "Tv staat aan." if film._tv_aan(tv, knop) else "De tv reageert niet, sir."
        if not aan:
            if kort:
                return None
            return "De tv staat uit, sir."
        if soort == "uit":
            return "Tv uit." if ha.dienst("media_player", "turn_off", {"entity_id": tv}) else _mislukt()

        if soort in ("volume", "harder", "zachter"):
            if soort == "volume":
                niveau = max(0, min(100, int(waarde))) / 100
            else:
                huidig = attrs.get("volume_level")
                if not isinstance(huidig, (int, float)):
                    dienst = "volume_up" if soort == "harder" else "volume_down"
                    ok = ha.dienst("media_player", dienst, {"entity_id": tv})
                    return ("Tv harder." if soort == "harder" else "Tv zachter.") if ok else _mislukt()
                stap = STAP if soort == "harder" else -STAP
                niveau = max(0.0, min(1.0, round(huidig + stap, 2)))
            if not ha.dienst("media_player", "volume_set", {"entity_id": tv, "volume_level": niveau}):
                return _mislukt()
            return f"Tv-volume op {round(niveau * 100)}."

        if soort in ("demp", "ontdemp"):
            stil = soort == "demp"
            if not ha.dienst("media_player", "volume_mute", {"entity_id": tv, "is_volume_muted": stil}):
                return _mislukt()
            return "Tv gedempt." if stil else "Tv-geluid staat weer aan."

        if soort == "pauze":
            return "Tv gepauzeerd." if ha.dienst("media_player", "media_pause", {"entity_id": tv}) else _mislukt()
        if soort == "verder":
            return "Tv speelt verder." if ha.dienst("media_player", "media_play", {"entity_id": tv}) else _mislukt()

        if soort == "volgende":
            # Netflix en Disney+ tonen aan het einde een knop "Volgende
            # aflevering" die al geselecteerd is: OK op de afstandsbediening.
            if ha.dienst("webostv", "button", {"entity_id": tv, "button": "ENTER"}):
                return "Volgende aflevering, sir."
            return _mislukt()

        if soort == "app":
            bron = zoek_bron(waarde, attrs.get("source_list") or [])
            if not bron:
                return f"{str(waarde).strip().capitalize()} vind ik niet op de tv, sir."
            if not ha.dienst("media_player", "select_source", {"entity_id": tv, "source": bron}):
                return _mislukt()
            return f"{bron} op de tv."
        return None


def _mislukt():
    return "Dat lukte niet op de tv, sir."


def voer_uit(tekst):
    """Voor de brain-router: het antwoord, of None als het niet over de tv gaat."""

    gevonden = herken(tekst)
    if gevonden is None:
        return None
    kort = herken(tekst, film_aan=False) is None
    return TvBediening().voer_uit(*gevonden, kort=kort)
