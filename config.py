import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


JARVIS_NAME = "JARVIS"
USER_NAME = "Rushil"

# AI instellingen (override via omgevingsvariabelen)
AI_MODEL = os.environ.get("AI_MODEL", "qwen2.5:3b")
# Contextgrootte in tokens voor Ollama. 8192 geeft het model genoeg ruimte
# voor de systeemtekst + toolbeschrijvingen. Lager (bijv. 4096) bespaart
# geheugen en wat wachttijd, maar dan kunnen tools worden afgekapt.
AI_NUM_CTX = int(os.environ.get("AI_NUM_CTX", "8192"))
AI_TEMPERATURE_TOOLS = 0.0
AI_TEMPERATURE_CHAT = float(os.environ.get("AI_TEMPERATURE_CHAT", "0.3"))
AI_KEEP_ALIVE = os.environ.get("AI_KEEP_ALIVE", "30m")

# Home Assistant (optioneel) – via environment variables
HOME_ASSISTANT_URL = os.environ.get("HOME_ASSISTANT_URL", "")
HOME_ASSISTANT_TOKEN = os.environ.get("HOME_ASSISTANT_TOKEN", "")

# Film-modus (Fase 21): de tv (media_player) en de knop die hem aanzet
# (Wake-on-LAN-button in HA). Leeg = JARVIS zoekt ze zelf in HA (een
# webOS-/tv-mediaspeler en een wake_on_lan-knop met de naam "Tv").
FILM_TV_ENTITY = os.environ.get("FILM_TV_ENTITY", "").strip()
FILM_TV_AAN_KNOP = os.environ.get("FILM_TV_AAN_KNOP", "").strip()

# Spotify (Fase 21, M5): lezen + afspelen, koppelen met scripts/spotify_koppelen.py.
# De client-id is niet geheim (PKCE, geen client-secret). De redirect-URI
# moet precies zo in de Spotify-app staan.
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
SPOTIFY_REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback").strip()
# Op welk Spotify-apparaat JARVIS afspeelt (deel van de naam, bijv. de naam
# van de game-pc). Leeg = het actieve apparaat, anders een computer.
SPOTIFY_APPARAAT = os.environ.get("SPOTIFY_APPARAAT", "").strip()

# Gemini (Fase 25): het slimme brein in de cloud, Ollama blijft de terugval.
# De API-sleutel (gratis via aistudio.google.com) is geheim: alleen in .env,
# nooit in een log, audit of URL. Het denkniveau ("minimal", "low",
# "medium", "high"; leeg = standaard van het model) bepaalt de snelheid.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite").strip() or "gemini-3.1-flash-lite"
# Google Zoeken via Gemini zit niet in de gratis laag; alleen aanzetten met
# een betaald account. Anders zoekt DuckDuckGo en vat Gemini samen.
GEMINI_ZOEKEN = os.environ.get("GEMINI_ZOEKEN", "0").strip().lower() in ("1", "true", "yes", "on")
GEMINI_DENKNIVEAU = os.environ.get("GEMINI_DENKNIVEAU", "low").strip()
try:
    GEMINI_TIMEOUT = float(os.environ.get("GEMINI_TIMEOUT", "15") or 15)
except ValueError:
    GEMINI_TIMEOUT = 15.0

# Gmail (Fase 23, M2): lezen, koppelen met scripts/gmail_koppelen.py (zie
# docs/gmail.md). Client-id en -secret komen uit uw eigen Google Cloud-app
# ("Desktop-app"); Google noemt dat secret zelf niet geheim voor desktop-apps,
# maar het hoort toch alleen in .env.
GMAIL_CLIENT_ID = os.environ.get("GMAIL_CLIENT_ID", "").strip()
GMAIL_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "").strip()
GMAIL_REDIRECT_URI = os.environ.get("GMAIL_REDIRECT_URI", "http://127.0.0.1:8889/callback").strip()
# Belangrijke mail: afzenders (deel van naam of adres, komma's ertussen),
# bijv. "school,@hr.nl,mama". Met GMAIL_LABEL_BELANGRIJK=1 telt ook het
# label "Belangrijk" van Gmail zelf.
GMAIL_BELANGRIJKE_AFZENDERS = [
    a.strip().lower() for a in os.environ.get("GMAIL_BELANGRIJKE_AFZENDERS", "").split(",") if a.strip()
]
GMAIL_LABEL_BELANGRIJK = os.environ.get("GMAIL_LABEL_BELANGRIJK", "1").strip().lower() in ("1", "true", "ja", "aan")
# Uit zichzelf melden bij nieuwe belangrijke mail (niet 's nachts of in de
# stille modus); elke zoveel minuten kijken.
GMAIL_MELDEN = os.environ.get("GMAIL_MELDEN", "1").strip().lower() in ("1", "true", "ja", "aan")
GMAIL_CHECK_MINUTEN = max(2, int(os.environ.get("GMAIL_CHECK_MINUTEN", "5") or 5))
# iCloud-agenda (Fase 23, M4): CalDAV met een app-specifiek wachtwoord van
# Apple (NIET uw gewone wachtwoord); zie docs/agenda.md. ICLOUD_AGENDA = de
# naam van de agenda waarin JARVIS nieuwe afspraken zet (leeg = de eerste).
ICLOUD_GEBRUIKER = os.environ.get("ICLOUD_GEBRUIKER", "").strip()
ICLOUD_APP_WACHTWOORD = os.environ.get("ICLOUD_APP_WACHTWOORD", "").strip()
ICLOUD_AGENDA = os.environ.get("ICLOUD_AGENDA", "").strip()
ICLOUD_CALDAV_URL = os.environ.get("ICLOUD_CALDAV_URL", "https://caldav.icloud.com/").strip()
# Herinneringen (Fase 23, M5): zoveel minuten vóór een afspraak (of vóór het
# vertrek als er een locatie bij staat); 0 = geen herinneringen. Reistijd
# vanaf THUIS_ADRES (leeg = de weerplaats); een schatting zonder files.
AGENDA_HERINNERINGEN = os.environ.get("AGENDA_HERINNERINGEN", "1").strip().lower() in ("1", "true", "ja", "aan")
AGENDA_HERINNERING_MINUTEN = max(0, int(os.environ.get("AGENDA_HERINNERING_MINUTEN", "15") or 15))
THUIS_ADRES = os.environ.get("THUIS_ADRES", "").strip()

# Discord-DM's (Fase 23, M6): via de Windows-meldingen op de game-pc. Nieuwe
# DM's voorlezen bij binnenkomst (niet 's nachts, stil, film of game).
DISCORD_MELDEN = os.environ.get("DISCORD_MELDEN", "1").strip().lower() in ("1", "true", "ja", "aan")

# Welzijn (Fase 27, M3): water (elk uur), ogen (45 min) en pauze (90 min),
# hooguit één melding per uur; niet in een potje, focus, film of 's nachts.
WELZIJN_MELDEN = os.environ.get("WELZIJN_MELDEN", "1").strip().lower() in ("1", "true", "ja", "aan")
# Fase 31: binnen de minuut doorluisteren zinnen voor iemand anders herkennen
# en dan stil stoppen; 0 = alles wat hij hoort is voor JARVIS (zoals vóór Fase 31).
GESPREK_HERKENNEN = os.environ.get("GESPREK_HERKENNEN", "1").strip().lower() in ("1", "true", "ja", "aan")
# Fase 30: Self-Evolution; zondagnacht de herkenning (alleen
# config/commando_voorbeelden.json) laten verbeteren door Gemini; 0 = alleen op verzoek.
ZELFVERBETERING = os.environ.get("ZELFVERBETERING", "1").strip().lower() in ("1", "true", "ja", "aan")
# Fase 29: gewoontes leren (lampen, muziek) en vooraf voorstellen; 0 = uit.
PATRONEN_LEREN = os.environ.get("PATRONEN_LEREN", "1").strip().lower() in ("1", "true", "ja", "aan")
# Fase 28, M1: zo vaak kijkt JARVIS of de game-pc klaar is met updaten/downloaden.
GAMEPC_KLAAR_CHECK_SECONDEN = max(20, int(os.environ.get("GAMEPC_KLAAR_CHECK_SECONDEN", "60") or 60))
DISCORD_CHECK_SECONDEN = max(20, int(os.environ.get("DISCORD_CHECK_SECONDEN", "60") or 60))

# Onder elk antwoord (M3), bijv. "Groet,\nRushil"; een \n wordt een nieuwe regel.
GMAIL_ONDERTEKENING = os.environ.get("GMAIL_ONDERTEKENING", "").strip().replace("\\n", "\n")

# Games (Fase 21, M6): staat de game-pc uit, dan drukt JARVIS op deze
# Wake-on-LAN-knop in HA (leeg = zelf zoeken: een button met "game pc" in
# de naam) en wacht hij zo lang (seconden) tot de agent er is.
GAME_PC_AAN_KNOP = os.environ.get("GAME_PC_AAN_KNOP", "").strip()
GAME_PC_OPSTART_SECONDEN = int(os.environ.get("GAME_PC_OPSTART_SECONDEN", "180"))

# Bevestigingen verlopen na 20 seconden
CONFIRM_TTL_SECONDS = 20

# Wachttijd (seconden) voordat de pc echt afsluit/herstart. De gebruiker
# hoort deze tijd en kan binnen dat venster "annuleer afsluiten" zeggen.
POWER_COUNTDOWN_SECONDS = int(os.environ.get("POWER_COUNTDOWN_SECONDS", "20"))

# --- Standaarddoel PC-bediening (Fase 15B) ---
# 'local'   = bedien deze pc (standaard; werkt zonder game-pc-agent)
# 'game-pc' = stuur PC-commando's naar de game-pc-agent (REMOTE_CLIENT_*)
#             Zet dit alleen als de agent op de game-pc draait EN de client
#             hier is geconfigureerd; anders krijg je bij het opstarten een
#             melding en werken game-pc-commando's niet.
PC_TARGET = os.environ.get("PC_TARGET", "local")

# Spraakinvoer instellingen
WACHT_OP_SPRAAK_SECONDEN = 10
MAX_OPNAME_SECONDEN = 15
BEEP_ENABLED = True

# Microfoonapparaat voor de gedeelde audiostream (None = standaardapparaat).
# Overschrijfbaar via de omgevingsvariabele MIC_DEVICE.
# Let op: een numerieke waarde wordt omgezet naar int. Anders zou
# sounddevice de waarde als apparaatnaam interpreteren en klagen met
# "No input device matching '7'".
_mic_device = (os.environ.get("MIC_DEVICE") or "").strip()
MIC_DEVICE = int(_mic_device) if _mic_device.isdigit() else (_mic_device or None)

# Executor instellingen
EXECUTOR_MAX_WORKERS = 4

# --- Bestanden zoeken en openen ---

# Document-/mediatypes waarin JARVIS zoekt als de gebruiker geen extensie
# noemt (en die hij zonder waarschuwing mag openen).
FILE_ALLOWED_EXTENSIONS = frozenset([
    ".txt", ".md", ".pdf", ".rtf",
    ".doc", ".docx", ".odt",
    ".xls", ".xlsx", ".ods", ".csv",
    ".ppt", ".pptx", ".odp",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg",
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg",
    ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".zip", ".rar", ".7z", ".tar", ".gz",
])

# Uitvoerbare/gevaarlijke types: alleen openen na expliciete bevestiging.
FILE_DANGEROUS_EXTENSIONS = frozenset([
    ".exe", ".bat", ".cmd", ".ps1", ".js", ".vbs",
    ".msi", ".lnk", ".scr", ".com", ".jar", ".reg",
    # Extra risicovolle types: HTML-applicaties, Windows Script Host,
    # macro-documenten, snelkoppelingen en configuratie/installatie.
    ".hta", ".wsf", ".wsh", ".vbe", ".jse", ".url", ".pif", ".cpl",
    ".msc", ".msp", ".docm", ".xlsm", ".pptm", ".application",
    ".appref-ms", ".gadget", ".ps1xml", ".psm1", ".scf", ".inf",
])

# Fuzzy-drempel (0-100) voor bestandsnaam-matching (rapidfuzz).
FILE_FUZZY_THRESHOLD = 75

# Zoeklimieten: maximale diepte en maximale zoektijd in seconden.
FILE_MAX_DEPTH = 4
FILE_SEARCH_TIMEOUT_SECONDS = 5

# Mappen die tijdens het zoeken worden overgeslagen (kleine letters).
FILE_SKIP_DIRS = frozenset([
    "node_modules", ".git", "appdata", "$recycle.bin", "venv", ".venv",
])


# =============================================================
# FASE 15 — Game-PC Agent (remote)
# =============================================================
# De SERVER draait op de game-pc (de huidige pc) en voert alleen
# toegestane acties uit. De CLIENT draait op het brein (nu nog deze
# pc, later de mini-pc) en stuurt ondertekende opdrachten.
#
# Beveiliging is fail-closed: zonder token of certificaat start de
# server niet (zie remote_server_security_errors()).


def _env_bool(name, default=False):
    """Leest een boolean uit de omgeving (1/true/yes/on)."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name, default):
    """Leest een int uit de omgeving; valt terug op default bij onzin."""
    try:
        return int(str(os.environ.get(name, "")).strip())
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    """Leest een float uit de omgeving; valt terug op default bij onzin."""
    try:
        return float(str(os.environ.get(name, "")).strip())
    except (TypeError, ValueError):
        return default


def _env_str(name, default=""):
    """Leest een string uit de omgeving (leeg = leeg)."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip()


# --- Fase 17 — Gesprek & Dialoog: barge-in (onderbreken) ---
# Je kunt JARVIS midden in een antwoord onderbreken. Drie manieren:
# 1. Stem: de microfoon hoort u praten terwijl JARVIS praat. Omdat JARVIS'
#    eigen stem via de speakers ook in de microfoon komt, leert de monitor
#    de echo-drempel (de eerste BARGE_IN_GRACE_SECONDS van het praten) en
#    volgt die daarna de echo doorlopend (BARGE_IN_ECHO_WINDOW_SECONDS).
#    De onderbreking moet daar duidelijk bovenuit komen
#    (BARGE_IN_MIN_RMS en BARGE_IN_ECHO_RATIO).
# 2. Sneltoets: een globale toets die altijd werkt (ook als een game of
#    video focus heeft).
# 3. Uit: geen onderbreken.
# Zet BARGE_IN_ENABLED=0 om barge-in helemaal uit te zetten.
BARGE_IN_ENABLED = _env_bool("BARGE_IN_ENABLED", True)

# Woorden in de apparaatnaam van een echte headset. Een laptopmicrofoon
# telt niet mee: met speakers geeft stemdetectie valse onderbrekingen.
_HEADSET_TREFWOORDEN = (
    "headset",
    "headphone",
    "koptelefoon",
    "oordopjes",
    "earbud",
    "airpods",
)


def _detecteer_headset():
    """True als er een headset aan de microfoon hangt (faalt veilig)."""
    try:
        import sounddevice as sd

        for apparaat in sd.query_devices():
            if not int(apparaat.get("max_input_channels", 0) or 0):
                continue
            naam = str(apparaat.get("name", "")).lower()
            if any(woord in naam for woord in _HEADSET_TREFWOORDEN):
                return True
    except Exception:
        return False
    return False


def _standaard_barge_in_modus():
    """Standaardmodus van barge-in.

    Met een headset is stemdetectie handig; met speakers (of zonder
    microfoon) is de sneltoets veiliger, omdat de echo van JARVIS' eigen
    stem anders de monitor zou kunnen onderbreken. Lukt het herkennen niet,
    dan is de sneltoets het veilige antwoord.
    """
    return "stem" if _detecteer_headset() else "sneltoets"


# Hoe barge-in werkt: "stem" (microfoon), "sneltoets" (alleen de toets) of
# "uit". Zonder deze instelling: "stem" als er een headset aan de microfoon
# hangt, anders "sneltoets".
BARGE_IN_MODE = _env_str("BARGE_IN_MODE").strip().lower()
if BARGE_IN_MODE not in ("stem", "sneltoets", "uit"):
    BARGE_IN_MODE = _standaard_barge_in_modus()

# Globale sneltoets die het onderbreken activeert (notatie van het
# `keyboard`-pakket, bijvoorbeeld "ctrl+alt+j").
BARGE_IN_HOTKEY = os.environ.get("BARGE_IN_HOTKEY", "ctrl+alt+j")

# Hoe lang aan het begin van het praten de echo-drempel geleerd wordt.
BARGE_IN_GRACE_SECONDS = _env_float("BARGE_IN_GRACE_SECONDS", 0.35)

# Minimale energie (RMS) van uw stem om als onderbreking te tellen.
BARGE_IN_MIN_RMS = _env_float("BARGE_IN_MIN_RMS", 1200.0)

# Uw stem moet zo veel keer boven de geleerde echo-drempel uitkomen.
BARGE_IN_ECHO_RATIO = _env_float("BARGE_IN_ECHO_RATIO", 1.8)

# Aantal aaneengesloten spraakframes (30 ms per stuk) voor een onderbreking.
BARGE_IN_FRAMES = _env_int("BARGE_IN_FRAMES", 8)

# Venster waarin het lopende gemiddelde van de eigen stem (de echo) wordt
# bijgehouden. Binnen dit venster volgt de echo-drempel de echo, zodat een
# luidere zinsdeel van JARVIS zichzelf niet meer onderbreekt.
BARGE_IN_ECHO_WINDOW_SECONDS = _env_float("BARGE_IN_ECHO_WINDOW_SECONDS", 1.5)


# --- Fase 16 — Proactieve JARVIS ---
# Nachtmodus: gedurende deze uren reageert JARVIS alleen nog op het wake
# word en spreekt hij zachter. Start en eind mogen door middernacht
# heen lopen (standaard 23:00 - 07:00).
NACHTMODUS_START = _env_int("NACHTMODUS_START", 23)
NACHTMODUS_EIND = _env_int("NACHTMODUS_EIND", 7)

# Volume (0.0 - 1.0) dat JARVIS 's nachts gebruikt; overdag vol volume.
NACHTMODUS_VOLUME = _env_float("NACHTMODUS_VOLUME", 0.4)

# Standaard spreekvolume (0.0 - 1.0) overdag.
DAGVOLUME = _env_float("DAGVOLUME", 1.0)

# Hoe vaak de proactieve engine controleert of er iets te melden is
# (seconden). Lager = sneller reageren, iets meer CPU.
PROACTIVE_TICK_SECONDEN = _env_int("PROACTIVE_TICK_SECONDEN", 30)

# Auto-slaap: na zoveel minuten zonder activiteit (geen commando én de pc
# niet in gebruik) gaat JARVIS automatisch in de stille modus. De eerstvolgende
# activiteit haalt hem er weer uit. 0 = uit.
AUTOSLAAP_MINUTEN = _env_int("AUTOSLAAP_MINUTEN", 30)

# Hoeveel seconden muis/toetsenbord-inactiviteit nog als "de pc is in
# gebruik" telt (alleen op Windows; elders onbekend).
PC_IDLE_DREMPEL_SECONDEN = _env_int("PC_IDLE_DREMPEL_SECONDEN", 300)

# Plaats waarvoor de dagstart-samenvatting het weer ophaalt.
WEER_PLAATS = os.environ.get("JARVIS_WEER_PLAATS", "Amsterdam")

# Nieuwsbronnen voor het nieuwscommando (komma-gescheiden sleutels uit
# actions.nieuws.FEEDS; standaard NOS en Tweakers). Alleen op aanvraag.
NIEUWS_BRONNEN = os.environ.get("JARVIS_NIEUWS_BRONNEN", "nos,tweakers")

# Hoeveel koppen JARVIS per nieuwsbron toont.
NIEUWS_MAX_PER_BRON = _env_int("JARVIS_NIEUWS_MAX", 5)


# --- Fase 17 — Gesprek & Dialoog: Piper TTS (lokaal) ---
# Piper is de standaard spraakmotor: lokaal, snel en streaming-capabel.
# Staat Piper uit of ontbreekt het stemmodel, dan valt JARVIS automatisch
# terug op pyttsx3 (zie voice/speak.py).
PIPER_ENABLED = _env_bool("PIPER_ENABLED", True)

# Map met Piper-stemmodellen. Leeg = <projectmap>/voice/models.
# Download een stem met:
#   python scripts/download_piper_voice.py nl_NL-pim-medium
PIPER_MODELS_DIR = os.environ.get("PIPER_MODELS_DIR", "")

# Naam of pad van het te gebruiken .onnx-stemmodel. Leeg = het eerste
# .onnx-model in PIPER_MODELS_DIR (alfabetisch).
PIPER_VOICE = os.environ.get("PIPER_VOICE", "")

# Spreeksnelheid als length_scale: < 1.0 spreekt sneller, > 1.0 langzamer.
PIPER_LENGTH_SCALE = _env_float("PIPER_LENGTH_SCALE", 1.0)

# Variatie (Fase 19, M5; kies ze met scripts/stem_proef.py). Leeg = de
# waarde uit het stemmodel zelf.
#   PIPER_NOISE_SCALE: variatie in de klank (lager = vlakker, droger).
#   PIPER_NOISE_W:     variatie in het ritme (lager = gelijkmatiger, kalmer).
PIPER_NOISE_SCALE = _env_float("PIPER_NOISE_SCALE", None)
PIPER_NOISE_W = _env_float("PIPER_NOISE_W", None)
# Spreker binnen een meersprekermodel (bijv. nl_NL-mls-medium heeft er 52).
# Leeg = de eerste spreker. Alleen gebruikt als het model meerdere sprekers heeft.
PIPER_SPEAKER = _env_int("PIPER_SPEAKER", None)

# Tijdens streaming spreekt JARVIS een zin pas uit als er minstens zoveel
# tekens zijn opgebouwd (of als de zin echt eindigt). Zo blijft de spraak
# natuurlijk klinken terwijl het model nog genereert.
PIPER_STREAM_MIN_CHARS = _env_int("PIPER_STREAM_MIN_CHARS", 40)

# Streaming antwoord (Fase 17, A3): JARVIS begint met praten zodra het
# taalmodel de eerste volledige zin heeft, in plaats van te wachten tot het
# hele antwoord klaar is. Zet dit uit (STREAM_ANTWOORD=0) om terug te gaan
# naar het oude, blokkerende gedrag (handig om latency te vergelijken).
STREAM_ANTWOORD = _env_bool("STREAM_ANTWOORD", True)


# --- Fase 17 — Gesprek & Dialoog: reactiesnelheid per taaksoort (E) ---
# JARVIS onderscheidt drie soorten opdrachten en reageert daar verschillend op:
#   * actie    — een concrete handeling (openen, sluiten, volume): hij meldt
#                meteen dat hij bezig is en komt direct met het resultaat.
#   * research — zoeken, weer, nieuws, pagina's lezen: dit mag langer duren,
#                dus hij zegt kort dat hij gaat opzoeken.
#   * gesprek  — een gewone vraag of praatje: geen extra melding nodig.
# De teksten hieronder zijn de korte meldingen die hij bij acties/research
# gebruikt. Laat een tekst leeg ("") om die melding helemaal uit te zetten.
MELDING_ACTIE = os.environ.get("MELDING_ACTIE", "Moment, ik doe het even.")

MELDING_RESEARCH = os.environ.get(
    "MELDING_RESEARCH", "Even opzoeken, een moment."
)

# Minimale tijd (seconden) dat een actie of research moet duren voordat
# JARVIS de korte melding geeft. Zo blijft een snelle actie (onder deze
# grens) stil en praat hij alleen als er echt even gewacht moet worden.
MELDING_MIN_SECONDEN = _env_float("MELDING_MIN_SECONDEN", 0.8)

# Narratie bij routines (Fase 21, M3): JARVIS vertelt per stap kort wat hij
# doet. 0 = uit (dan alleen de omschrijving). Per routine uit te zetten met
# "narratie": false in config/routines.json.
ROUTINE_NARRATIE = _env_bool("ROUTINE_NARRATIE", True)


# --- Fase 17 — Gesprek & Dialoog: automatische ducking (G) ---
# Terwijl JARVIS praat, wordt het systeemvolume van de pc tijdelijk verlaagd
# (ducking), zodat muziek of een game niet door zijn antwoord heen klinkt.
# Daarna gaat het volume automatisch terug naar de oude waarde. Zet dit uit
# met DUCKING_ENABLED=0.
DUCKING_ENABLED = _env_bool("DUCKING_ENABLED", True)

# Hoeveel procentpunt het volume omlaag gaat tijdens het praten.
DUCKING_PERCENT = _env_int("DUCKING_PERCENT", 45)

# Hoe ver het volume tijdens ducking mag zakken: dit percentage is het
# minimum. Stond het volume al lager, dan blijft het staan.
DUCKING_MIN_PERCENT = _env_int("DUCKING_MIN_PERCENT", 20)


# --- Fase 17 — Gesprek & Dialoog: meertalig (F) ---
# JARVIS praat standaard Nederlands, maar u kunt hem vragen om Engels te
# spreken ("switch to English", "praat Engels"). De keuze geldt voor de
# rest van de sessie en wordt bewaard in taal.json.
# Stem voor het Engels (leeg = geen aparte Engelse stem; JARVIS blijft dan
# met de Nederlandse stem praten, wat beter is dan helemaal niet praten).
# Download een Engelse stem met:
#   python scripts/download_piper_voice.py en_US-lessac-medium
PIPER_VOICE_EN = os.environ.get("PIPER_VOICE_EN", "")

# Engelse teksten voor de korte tussentijdse meldingen (Fase 17, E/F).
# Lege tekst zet de melding uit, net als bij de Nederlandse varianten.
MELDING_ACTIE_EN = os.environ.get("MELDING_ACTIE_EN", "One moment, doing it now.")

MELDING_RESEARCH_EN = os.environ.get(
    "MELDING_RESEARCH_EN", "Let me look that up for you."
)


# --- Fase 17 — Gesprek & Dialoog: taal volgt uw vraag ---
# JARVIS antwoordt in de taal van uw vraag, maar alleen als die vraag
# OVERDUIDELIJK in één taal is. Losse Engelse woorden in een Nederlandse zin
# ("zet even Spotify op") veranderen niets. Heeft u een taal expliciet
# vastgezet ("switch to English"), dan wint die keuze altijd en doet de
# automaat niets tot u zegt "taal mag automatisch".
# Zet dit uit met TAAL_AUTOMATISCH=0.
TAAL_AUTOMATISCH = _env_bool("TAAL_AUTOMATISCH", True)

# Hoeveel duidelijke signaalwoorden een vraag minstens moet hebben voordat
# JARVIS de taal automatisch overneemt. Hoog = streng (minder snel wisselen).
TAAL_AUTOMATISCH_DREMPEL = _env_int("TAAL_AUTOMATISCH_DREMPEL", 2)


# --- Fase 17 — Gesprek & Dialoog: niet-begrepen-drempel ---
# Hoe vaak JARVIS achter elkaar om herhaling vraagt voordat hij iets
# vriendelijks zegt ("Ik laat het even rusten..." ) in plaats van
# eindeloos door te vragen. De sessie blijft daarna gewoon open.
NIET_BEGREPEN_DREMPEL = _env_int("NIET_BEGREPEN_DREMPEL", 2)

# Wat JARVIS zegt als die drempel is bereikt. Leeg ("") zet de melding uit.
NIET_BEGREPEN_MELDING = os.environ.get(
    "NIET_BEGREPEN_MELDING",
    "Ik laat het even rusten. Roep me als je me nodig hebt.",
)


# --- Fase 17 — Gesprek & Dialoog: voorbehoud bij onzekere informatie ---
# JARVIS brengt een feit, getal of recente gebeurtenis niet als harde
# waarheid als hij er niet zeker van is. Hij zegt er dan kort iets bij
# ("volgens mijn kennis", "dat kan verouderd zijn"). De drempel blijft
# bewust laag: alleen bij echte twijfel, niet bij elke zin.
# Zet dit uit met ZEKERHEID_ENABLED=0.
ZEKERHEID_ENABLED = _env_bool("ZEKERHEID_ENABLED", True)

# Wat JARVIS zegt als hij iets echt niet weet (leeg = geen vaste zin).
# De vraag hoort erbij: daarop kan de gebruiker "ja" zeggen, waarna
# core/opzoeken.py de zoekopdracht met de oorspronkelijke vraag uitvoert.
ZEKERHEID_ONBEKEND = os.environ.get(
    "ZEKERHEID_ONBEKEND",
    "Dat weet ik niet zeker. Wil je dat ik het opzoek?",
)

# Engelse variant van dezelfde zin (Fase 17, F).
ZEKERHEID_ONBEKEND_EN = os.environ.get(
    "ZEKERHEID_ONBEKEND_EN",
    "I'm not sure about that. Shall I look it up for you?",
)

# Hoe lang (seconden) een "ja" op het aanbod geldig blijft. Kort, zodat een
# "ja" op een heel ander moment niet alsnog een zoekopdracht start.
OPZOEK_CONFIRM_TTL_SECONDS = _env_int("OPZOEK_CONFIRM_TTL_SECONDS", 30)

# Commando-correctie (Fase 24, M3): vindt de lokale fuzzy-match niets, dan
# kiest het taalmodel het bedoelde commando uit de bekende lijst. Kost een
# extra AI-aanroep bij een onbekend commando; na deze tijd (seconden) wordt
# het gewoon een chatvraag.
COMMANDO_CORRECTIE_AI = _env_bool("COMMANDO_CORRECTIE_AI", True)
COMMANDO_CORRECTIE_AI_TIMEOUT = _env_float("COMMANDO_CORRECTIE_AI_TIMEOUT", 4.0)

# "Zet de muziek zachter/harder" past het volume van deze app aan, niet het
# hoofdvolume van de pc (de muziek kan via een ander apparaat spelen).
MUZIEK_APP = _env_str("MUZIEK_APP", "Spotify") or "Spotify"


# --- Fase 17 — Gesprek & Dialoog: sessie-modus (doorlopend gesprek) ---
# Zodra het wake word is gehoord, blijft JARVIS in gesprek: u hoeft niet bij
# elke beurt opnieuw "JARVIS" te zeggen. De sessie eindigt na zoveel
# seconden zonder spraak na het laatste antwoord; daarna is het wake word
# weer nodig. Fase 28, M2: één minuut (was tien; dan pikte hij te veel op
# dat niet voor hem was). Zeg "stop jarvis" of "ga slapen" om de sessie
# meteen te beëindigen.
SESSIE_TIMEOUT_SECONDEN = _env_int("SESSIE_TIMEOUT_SECONDEN", 60)


# --- Server (game-pc) ---
REMOTE_SERVER_ENABLED = _env_bool("REMOTE_SERVER_ENABLED", False)
REMOTE_SERVER_HOST = os.environ.get("REMOTE_SERVER_HOST", "0.0.0.0")
REMOTE_SERVER_PORT = _env_int("REMOTE_SERVER_PORT", 8765)
REMOTE_SERVER_TOKEN = os.environ.get("REMOTE_SERVER_TOKEN", "")
REMOTE_SERVER_CERT_FILE = os.environ.get("REMOTE_SERVER_CERT_FILE", "")
REMOTE_SERVER_KEY_FILE = os.environ.get("REMOTE_SERVER_KEY_FILE", "")

# Komma-gescheiden lijst met toegestane client-IP-adressen.
# Standaard leeg: dan wordt alleen toegestaan vanaf een privé-adres
# (192.168.x.x, 10.x.x.x, 172.16-31.x.x, 127.x.x.x of ::1).
# Vul hier het IP-adres van de mini-pc in, bijvoorbeeld:
#   REMOTE_SERVER_ALLOWED_IPS=192.168.1.50
# Publieke IP-adressen worden ALTIJD geweigerd, ook als ze hier staan.
def _parse_ips(value):
    """Zet een komma-gescheiden lijst om in een tuple van IP-adressen."""

    return tuple(ip.strip() for ip in (value or "").split(",") if ip.strip())


REMOTE_SERVER_ALLOWED_IPS = _parse_ips(os.environ.get("REMOTE_SERVER_ALLOWED_IPS", ""))

# Maximaal aantal gelijktijdige verbindingen naar de server (0 = geen limiet).
REMOTE_MAX_CONNECTIONS = _env_int("REMOTE_MAX_CONNECTIONS", 32)

# Maximaal aantal gelijktijdige verbindingen per client-IP (0 = geen limiet).
# Voorkomt dat één apparaat alle verbindingsplekken oprekt.
REMOTE_MAX_CONNECTIONS_PER_IP = _env_int("REMOTE_MAX_CONNECTIONS_PER_IP", 4)

# Limiet voor IP-adressen die expliciet in REMOTE_SERVER_ALLOWED_IPS staan
# (0 = geen limiet). Standaard hoger dan de gewone per-IP limiet, zodat het
# brein met EXECUTOR_MAX_WORKERS parallelle opdrachten plus een extra
# statuscheck kan draaien zonder zichzelf af te kappen. Bij een lege
# allowlist geldt voor iedereen minimaal EXECUTOR_MAX_WORKERS + 4.
REMOTE_MAX_CONNECTIONS_PER_ALLOWED_IP = _env_int(
    "REMOTE_MAX_CONNECTIONS_PER_ALLOWED_IP", 12
)

# Totale deadline voor de TLS-handshake in seconden (niet per leesactie).
# Een handshake die langer duurt wordt afgebroken.
REMOTE_HANDSHAKE_DEADLINE_SECONDS = _env_float("REMOTE_HANDSHAKE_DEADLINE_SECONDS", 5.0)

# Uitzonderingen op de server-denylist van programma's (ui_launch_app en
# open_program). Standaard leeg: dan worden ALLE programma's op de
# denylist (cmd, powershell, regedit, ...) geweigerd. Vul hier expliciet
# programma's in die je wél toe wilt staan, gescheiden door komma's,
# hoofdletterongevoelig (bijv. "cmd,powershell").
def _parse_program_list(value):
    return tuple(p.strip().lower() for p in (value or "").split(",") if p.strip())


REMOTE_EXTRA_ALLOWED_PROGRAMS = _parse_program_list(
    os.environ.get("REMOTE_EXTRA_ALLOWED_PROGRAMS", "")
)

# Serverprofiel: "basis" (standaard) of "werkstation".
# Basis staat alleen programma's/games, vensters, media/volume,
# audio (uitlezen en per app bedienen), status en screenshot toe.
# Alles daarboven (bestanden wijzigen, UI-automatisering, power,
# browser) is alleen beschikbaar met REMOTE_SERVER_PROFILE=werkstation.
REMOTE_SERVER_PROFILE = os.environ.get("REMOTE_SERVER_PROFILE", "basis").strip().lower()

# --- Client (brein) ---
REMOTE_CLIENT_ENABLED = _env_bool("REMOTE_CLIENT_ENABLED", False)
REMOTE_CLIENT_HOST = os.environ.get("REMOTE_CLIENT_HOST", "127.0.0.1")
REMOTE_CLIENT_PORT = _env_int("REMOTE_CLIENT_PORT", 8765)
REMOTE_CLIENT_TOKEN = os.environ.get("REMOTE_CLIENT_TOKEN", "")
REMOTE_CLIENT_CA_FILE = os.environ.get("REMOTE_CLIENT_CA_FILE", "")
REMOTE_CLIENT_TIMEOUT = _env_float("REMOTE_CLIENT_TIMEOUT", 5.0)

# --- Dashboard (Fase 18) ---
# Zie docs/fase18_dashboard_design.md §10. Fail-closed: zonder beide
# tokens en zonder certificaat start de dashboard-server niet.
_PROJECT_MAP = os.path.dirname(os.path.abspath(__file__))

DASHBOARD_ENABLED = _env_bool("DASHBOARD_ENABLED", False)
# Bindt op het LAN (de iPad moet erbij kunnen), maar alleen via HTTPS.
DASHBOARD_HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
# Poort van de dashboard-server (HTTPS, iPad). Moet verschillen van
# REMOTE_SERVER_PORT: twee servers kunnen niet op dezelfde poort luisteren.
DASHBOARD_PORT = _env_int("DASHBOARD_PORT", 8780)
# kijk-token: alleen lezen. bedien-token: lezen én schrijven/goedkeuren.
DASHBOARD_VIEW_TOKEN = os.environ.get("DASHBOARD_VIEW_TOKEN", "")
DASHBOARD_CONTROL_TOKEN = os.environ.get("DASHBOARD_CONTROL_TOKEN", "")
DASHBOARD_CERT_FILE = os.environ.get("DASHBOARD_CERT_FILE", "")
DASHBOARD_KEY_FILE = os.environ.get("DASHBOARD_KEY_FILE", "")
# Het .mobileconfig-profiel (alleen het publieke CA-certificaat) dat de
# server op /profiel.mobileconfig aanbiedt; leeg of ontbrekend = niet.
DASHBOARD_PROFILE_FILE = os.environ.get(
    "DASHBOARD_PROFILE_FILE",
    os.path.join(_PROJECT_MAP, "certs", "jarvis-dashboard.mobileconfig"),
)
# Zelfde regel als de remote-server: publieke adressen altijd geweigerd;
# leeg = alleen privé-adressen. Vul het IP van de iPad in voor extra zekerheid.
DASHBOARD_ALLOWED_IPS = _parse_ips(os.environ.get("DASHBOARD_ALLOWED_IPS", ""))
# LAN-adres van deze pc voor de Host/Origin-controle. Leeg = automatisch.
DASHBOARD_LAN_IP = os.environ.get("DASHBOARD_LAN_IP", "").strip()
# Extra toegestane Host-headers (host:poort) en Origins, komma-gescheiden.
# Standaard: <lan-ip>:<poort>, localhost:<poort> en 127.0.0.1:<poort>.
DASHBOARD_ALLOWED_HOSTS = _parse_ips(os.environ.get("DASHBOARD_ALLOWED_HOSTS", ""))
DASHBOARD_ALLOWED_ORIGINS = _parse_ips(os.environ.get("DASHBOARD_ALLOWED_ORIGINS", ""))
# Verzoeken per IP per venster. Ruimer dan de remote-server (60): de PWA
# ververst de tegels elke 5 s en pollt bij een SSE-storing elke 2 s, en
# Safari én de beginscherm-app op dezelfde iPad delen één IP (Fase 19).
DASHBOARD_RATE_LIMIT = _env_int("DASHBOARD_RATE_LIMIT", 300)
DASHBOARD_RATE_WINDOW_SECONDS = _env_int("DASHBOARD_RATE_WINDOW_SECONDS", 60)
# Koppelcode: 8 cijfers, standaard 5 minuten geldig, één keer bruikbaar.
DASHBOARD_PAIR_CODE_TTL_SECONDS = _env_int("DASHBOARD_PAIR_CODE_TTL_SECONDS", 300)
# Gekoppelde apparaten: alleen de hash van hun token + rol.
DASHBOARD_DEVICES_FILE = os.environ.get(
    "DASHBOARD_DEVICES_FILE",
    os.path.join(_PROJECT_MAP, "config", "dashboard_devices.json"),
)

# --- Fase 20 — Welke microfoon luistert ---
# "auto": de pc-microfoon, behalve zolang het spraakpaneel op de iPad
#         (spraak.html in Safari) geluid stuurt; dan de iPad.
# "ipad": alleen de iPad (de pc-microfoon wordt niet geopend).
# "pc":   alleen de pc-microfoon (de iPad mag niet verbinden).
MIC_BRON = (os.environ.get("MIC_BRON", "auto").strip().lower() or "auto")
if MIC_BRON not in ("auto", "ipad", "pc"):
    MIC_BRON = "auto"

# --- Fase 19 — Backups van het brein ---
# Elke dag een zip met alle brein-bestanden (zie beheer/data.py), ook de
# geheimen (.env en certs/). Zet BACKUP_MAP het liefst op een andere schijf
# (bijv. D:\JARVIS-backups); nooit binnen de projectmap (git).
BACKUP_ENABLED = _env_bool("BACKUP_ENABLED", True)
BACKUP_MAP = os.environ.get(
    "BACKUP_MAP", os.path.join(os.path.expanduser("~"), "JARVIS-backups")
).strip()
# Tijdstip (UU:MM) van de dagelijkse backup. Gemist (pc stond uit)? Dan
# haalt JARVIS hem kort na het starten in.
BACKUP_TIJD = os.environ.get("BACKUP_TIJD", "04:00").strip()
# Bewaren: de laatste per dag voor zoveel dagen, en de laatste per week
# voor zoveel weken.
BACKUP_DAGEN = _env_int("BACKUP_DAGEN", 7)
BACKUP_WEKEN = _env_int("BACKUP_WEKEN", 4)

# --- Fase 19 — Updates ---
# JARVIS kijkt kort na het starten en daarna dagelijks op GitHub of er een
# nieuwe versie is en meldt dat. Installeren gebeurt alleen na uw "ja".
UPDATES_ENABLED = _env_bool("UPDATES_ENABLED", True)

# --- Gedeeld ---
# Hoeveel seconden mag een ondertekend verzoek oud zijn (replay-bescherming).
REMOTE_REPLAY_WINDOW_SECONDS = _env_int("REMOTE_REPLAY_WINDOW_SECONDS", 30)

# Minimale lengte van het gedeelde geheim (token).
REMOTE_MIN_TOKEN_LENGTH = 16


def remote_server_security_errors(
    enabled=None,
    token=None,
    cert_file=None,
    key_file=None,
):
    """Controleert of de server veilig geconfigureerd is (fail-closed).

    Geeft een lijst met leesbare foutmeldingen terug. Een lege lijst
    betekent: veilig genoeg om te starten. Ontbrekende beveiliging mag
    NOOIT leiden tot een onbeschermde server, dus bij twijfel is dit
    een fout.

    De parameters zijn er voor tests; zonder argumenten worden de
    waarden uit dit bestand gebruikt.
    """

    enabled = REMOTE_SERVER_ENABLED if enabled is None else enabled
    token = REMOTE_SERVER_TOKEN if token is None else token
    cert_file = REMOTE_SERVER_CERT_FILE if cert_file is None else cert_file
    key_file = REMOTE_SERVER_KEY_FILE if key_file is None else key_file

    if not enabled:
        return []

    errors = []

    if not token:
        errors.append(
            "REMOTE_SERVER_TOKEN ontbreekt: zonder gedeeld geheim start "
            "de server niet."
        )
    elif len(token) < REMOTE_MIN_TOKEN_LENGTH:
        errors.append(
            f"REMOTE_SERVER_TOKEN is te kort (minimaal "
            f"{REMOTE_MIN_TOKEN_LENGTH} tekens)."
        )

    if not cert_file:
        errors.append("REMOTE_SERVER_CERT_FILE ontbreekt: TLS is verplicht.")

    if not key_file:
        errors.append("REMOTE_SERVER_KEY_FILE ontbreekt: TLS is verplicht.")

    if cert_file and not os.path.isfile(cert_file):
        errors.append(f"Certificaatbestand niet gevonden: {cert_file}")

    if key_file and not os.path.isfile(key_file):
        errors.append(f"Sleutelbestand niet gevonden: {key_file}")

    return errors


def dashboard_security_errors(
    enabled=None,
    view_token=None,
    control_token=None,
    cert_file=None,
    key_file=None,
):
    """Controleert of de dashboard-server veilig geconfigureerd is (fail-closed).

    Net als ``remote_server_security_errors``: een lege lijst betekent
    veilig genoeg om te starten. Beide tokens zijn verplicht, moeten lang
    genoeg zijn en mogen niet gelijk zijn; TLS is verplicht.
    """

    enabled = DASHBOARD_ENABLED if enabled is None else enabled
    view_token = DASHBOARD_VIEW_TOKEN if view_token is None else view_token
    control_token = DASHBOARD_CONTROL_TOKEN if control_token is None else control_token
    cert_file = DASHBOARD_CERT_FILE if cert_file is None else cert_file
    key_file = DASHBOARD_KEY_FILE if key_file is None else key_file

    if not enabled:
        return []

    errors = []

    for naam, token in (
        ("DASHBOARD_VIEW_TOKEN", view_token),
        ("DASHBOARD_CONTROL_TOKEN", control_token),
    ):
        if not token:
            errors.append(f"{naam} ontbreekt: zonder token start het dashboard niet.")
        elif len(token) < REMOTE_MIN_TOKEN_LENGTH:
            errors.append(
                f"{naam} is te kort (minimaal {REMOTE_MIN_TOKEN_LENGTH} tekens)."
            )

    if view_token and control_token and view_token == control_token:
        errors.append(
            "DASHBOARD_VIEW_TOKEN en DASHBOARD_CONTROL_TOKEN moeten verschillen."
        )

    if not cert_file:
        errors.append("DASHBOARD_CERT_FILE ontbreekt: TLS is verplicht.")

    if not key_file:
        errors.append("DASHBOARD_KEY_FILE ontbreekt: TLS is verplicht.")

    if cert_file and not os.path.isfile(cert_file):
        errors.append(f"Certificaatbestand niet gevonden: {cert_file}")

    if key_file and not os.path.isfile(key_file):
        errors.append(f"Sleutelbestand niet gevonden: {key_file}")

    return errors
