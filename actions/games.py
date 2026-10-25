"""Games op de game-pc: bibliotheek lezen en starten (Fase 21, M6).

* **Steam:** de bibliotheekmappen uit ``libraryfolders.vdf`` en per game een
  ``appmanifest_<id>.acf``; starten met ``steam://rungameid/<id>``.
  Geen Steam-account of API-sleutel nodig.
* **Riot:** de Riot Client uit ``RiotClientInstalls.json``; Valorant en
  League of Legends als ze geïnstalleerd zijn; starten met
  ``--launch-product=<product> --launch-patchline=live``.

Een game heet hier ``{"naam": ..., "id": "steam:227300" | "riot:valorant"}``.
``start_game`` start alleen een id die echt in de eigen bibliotheek staat:
het brein kan dus nooit een willekeurig pad of commando laten uitvoeren.
"""

import glob
import json
import os
import re

from core.result_validation import ToolResult

STEAM_STANDAARD = r"C:\Program Files (x86)\Steam"
RIOT_DATA = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Riot Games")

# Geen echte games: hulppakketten van Steam.
_STEAM_GEEN_GAME = re.compile(
    r"(redistributable|steamworks|proton|steam linux runtime|steamvr|soundtrack|dedicated server|sdk)",
    re.IGNORECASE,
)
_STEAM_GEEN_ID = {"228980", "1070560", "1391110", "1628350", "250820"}

RIOT_PRODUCTEN = {
    "valorant": "VALORANT",
    "league_of_legends": "League of Legends",
}


# -----------------------------------------------------------------
# Steam
# -----------------------------------------------------------------

def steam_pad():
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as sleutel:
            pad, _ = winreg.QueryValueEx(sleutel, "SteamPath")
            if pad:
                return os.path.normpath(pad)
    except Exception:
        pass
    return STEAM_STANDAARD if os.path.isdir(STEAM_STANDAARD) else None


def steam_bibliotheken(steam):
    mappen = [steam]
    vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
    try:
        tekst = open(vdf, encoding="utf-8", errors="replace").read()
    except OSError:
        return mappen
    for pad in re.findall(r'"path"\s+"([^"]+)"', tekst):
        pad = os.path.normpath(pad.replace("\\\\", "\\"))
        if pad.lower() not in (m.lower() for m in mappen):
            mappen.append(pad)
    return mappen


def lees_manifest(tekst):
    """``(appid, naam)`` uit een appmanifest, of None."""

    appid = re.search(r'"appid"\s+"(\d+)"', tekst)
    naam = re.search(r'"name"\s+"([^"]+)"', tekst)
    if not appid or not naam:
        return None
    return appid.group(1), naam.group(1)


def steam_games(steam=None):
    steam = steam or steam_pad()
    if not steam:
        return []
    games = {}
    for map_ in steam_bibliotheken(steam):
        for pad in glob.glob(os.path.join(map_, "steamapps", "appmanifest_*.acf")):
            try:
                gevonden = lees_manifest(open(pad, encoding="utf-8", errors="replace").read())
            except OSError:
                continue
            if not gevonden:
                continue
            appid, naam = gevonden
            if appid in _STEAM_GEEN_ID or _STEAM_GEEN_GAME.search(naam):
                continue
            games[appid] = {"naam": naam, "id": f"steam:{appid}"}
    return sorted(games.values(), key=lambda g: g["naam"].lower())


# -----------------------------------------------------------------
# Riot
# -----------------------------------------------------------------

def riot_client(data=RIOT_DATA):
    try:
        with open(os.path.join(data, "RiotClientInstalls.json"), encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        return None
    for sleutel in ("rc_default", "rc_live"):
        pad = info.get(sleutel)
        if pad and os.path.isfile(pad):
            return pad
    return None


def riot_games(data=RIOT_DATA, client=None):
    client = client if client is not None else riot_client(data)
    if not client:
        return []
    uit = []
    for product, naam in RIOT_PRODUCTEN.items():
        if os.path.isdir(os.path.join(data, "Metadata", f"{product}.live")):
            uit.append({"naam": naam, "id": f"riot:{product}"})
    return uit


# -----------------------------------------------------------------
# Lijst, zoeken en starten
# -----------------------------------------------------------------

def alle_games():
    return steam_games() + riot_games()


def game_lijst():
    games = alle_games()
    return ToolResult(ok=True, message=f"{len(games)} games gevonden.", data={"games": games})


def _norm(tekst):
    t = str(tekst or "").lower()
    t = re.sub(r"[™®©:'’.,!?\-–_()]", " ", t)
    return " ".join(t.split())


def zoek_game(gevraagd, games, drempel=86):
    """De game uit ``games`` die bij de gesproken naam past, of None.

    Eerst exact, dan het begin ("euro truck" → "Euro Truck Simulator 2"),
    dan vaag (rapidfuzz), zodat spraakfoutjes niet meteen falen.
    """

    doel = _norm(gevraagd)
    if not doel or not games:
        return None
    # Ook zonder spaties: spraak maakt van "BeamNG" vaak "beam ng".
    compact = doel.replace(" ", "")
    for g in games:
        if _norm(g["naam"]) == doel or _norm(g["naam"]).replace(" ", "") == compact:
            return g
    begin = [g for g in games if len(compact) >= 4 and (
        _norm(g["naam"]).startswith(doel) or _norm(g["naam"]).replace(" ", "").startswith(compact))]
    if len(begin) == 1:
        return begin[0]
    try:
        from rapidfuzz import fuzz, process

        keuzes = {i: _norm(g["naam"]) for i, g in enumerate(games)}
        beste = process.extractOne(doel, keuzes, scorer=fuzz.ratio)
        if beste and beste[1] >= drempel:
            return games[beste[2]]
        beste = process.extractOne(doel, keuzes, scorer=fuzz.token_set_ratio)
        if beste and beste[1] >= 95 and len(doel) >= 5:
            return games[beste[2]]
    except Exception:
        pass
    return None


def start_game(game_id, games=None, openen=None, starten=None, rc=None):
    """Start een game uit de eigen bibliotheek (alleen bekende id's)."""

    games = alle_games() if games is None else games
    game = next((g for g in games if g["id"] == game_id), None)
    if game is None:
        return ToolResult(ok=False, message="Die game staat niet op deze pc.", error_kind="niet_gevonden")
    soort, sleutel = game_id.split(":", 1)
    try:
        if soort == "steam":
            (openen or os.startfile)(f"steam://rungameid/{sleutel}")
        else:
            import subprocess

            client = rc or riot_client()
            if not client:
                return ToolResult(ok=False, message="De Riot Client is niet gevonden.", error_kind="niet_gevonden")
            (starten or subprocess.Popen)([client, f"--launch-product={sleutel}", "--launch-patchline=live"])
    except Exception as fout:
        return ToolResult(ok=False, message=f"Kon {game['naam']} niet starten: {fout}", error_kind="start_fout")
    return ToolResult(ok=True, message=f"{game['naam']} wordt gestart.", data={"naam": game["naam"]})
