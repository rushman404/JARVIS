"""Fase 25, M3 — privacy-poort en Gemini aangesloten op het brein.

Gemini en Ollama zijn altijd nep. De kern: in een Gemini-verzoek staat nooit
het geheugen, de context, een bestandspad, een e-mailadres of uw woonplaats.
"""

import json
import time
import types

import pytest

import config
from core import gemini, llm, privacy_poort

WOONPLAATS = "Badhoevedorp"
GEHEUGEN = {
    "woonplaats": WOONPLAATS,
    "opleiding": "MBO niveau 4 ICT",
    "favoriete_game": "Valorant",
}


@pytest.fixture(autouse=True)
def poort(monkeypatch):
    import memory.memory as mem

    monkeypatch.setattr(mem, "get_all_memory", lambda: dict(GEHEUGEN))
    monkeypatch.setattr(config, "THUIS_ADRES", "Hoofdweg 12, Badhoevedorp")
    privacy_poort._reset()
    yield
    privacy_poort._reset()


@pytest.fixture
def gemini_nep(monkeypatch):
    """Gemini 'aan' met een nep-functie die elk verzoek bewaart."""

    verzoeken = []
    staat = {"antwoord": "Rayleigh-verstrooiing, sir.", "tool_calls": None}

    def chat(messages, **kw):
        verzoeken.append({"messages": [dict(m) if isinstance(m, dict) else m for m in messages], **kw})
        antwoord = gemini.Antwoord(staat["antwoord"])
        if staat["tool_calls"]:
            antwoord["message"]["tool_calls"] = staat["tool_calls"]
        return antwoord

    def chat_stream(messages, **kw):
        verzoeken.append({"messages": list(messages), "stream": True, **kw})
        yield staat["antwoord"]

    monkeypatch.setattr(config, "GEMINI_API_KEY", "nep-sleutel")
    monkeypatch.setattr(gemini, "chat", chat)
    monkeypatch.setattr(gemini, "chat_stream", chat_stream)
    llm._reset_brein()
    return types.SimpleNamespace(verzoeken=verzoeken, staat=staat)


def _alles(verzoek):
    return json.dumps(verzoek["messages"], ensure_ascii=False, default=str) + json.dumps(
        verzoek.get("tools"), default=str)


# ---------------------------------------------------------------------
# beslis(): vooraf
# ---------------------------------------------------------------------

@pytest.mark.parametrize("vraag", [
    "waarom is de lucht blauw?",
    "wat is de hoofdstad van frankrijk",
    "open spotify",
    "zet de lampen in de woonkamer op rood",
    "zet mijn lampen aan",
    "speel muziek op mijn pc",
    "sluit hem",
    "wie won de laatste formule 1 race",
    "ik wil weten hoe zwarte gaten werken",
    "open valorant",
    "hoeveel is 12 keer 7",
])
def test_mag_naar_cloud(vraag):
    assert privacy_poort.beslis(vraag).cloud, privacy_poort.beslis(vraag).reden


@pytest.mark.parametrize("vraag, reden", [
    ("heb ik nieuwe mail?", "mail"),
    ("vat mijn e-mails samen", "mail"),
    ("wat staat er in mijn agenda", "agenda"),
    ("wanneer is mijn volgende afspraak", "agenda"),
    ("heb ik nieuwe dm's", "berichten"),
    ("wat stuurde sem", "berichten"),
    ("open het bestand rapport.docx", "bestanden"),
    ("wat staat er in mijn downloads", "bestanden"),
    ("open c:\\users\\rushi\\cv.pdf", "bestanden"),
    ("wat zie je op mijn scherm", "scherm"),
    ("wat is mijn favoriete game", "geheugen"),
    ("onthoud dat ik van pizza hou", "geheugen"),
    ("weet je nog wat ik zei", "geheugen"),
    ("waar woon ik", "geheugen"),
    ("ik woon in haarlem", "persoonlijk feit"),
    ("wat vroeg ik net", "geschiedenis"),
    ("hoe laat moet ik weg naar de tandarts", "locatie"),
    ("wat is er hier in de buurt te doen", "locatie"),
    ("hoe is het weer in badhoevedorp", "gevoelige geheugenwaarde"),
    ("hoe ver is het van hoofdweg naar amsterdam", "gevoelige geheugenwaarde"),
    ("wat vind je van mijn vriendin", "persoonlijk ('mijn vriendin')"),
    ("stuur iets naar rushil@example.com", "persoonsgegevens"),
    ("mijn postcode is 1171 ab", "persoonlijk ('mijn postcode')"),
    ("bel 06 12345678", "persoonsgegevens"),
])
def test_blijft_lokaal(vraag, reden):
    besluit = privacy_poort.beslis(vraag)
    assert not besluit.cloud
    assert besluit.reden == reden


def test_niet_gevoelige_geheugenwaarde_mag():
    # Een favoriete game is geen persoonsgegeven; "open valorant" mag.
    assert privacy_poort.beslis("start valorant").cloud


def test_lege_vraag_lokaal():
    assert not privacy_poort.beslis("  ").cloud


def test_naar_cloud_alleen_met_gemini(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    assert not privacy_poort.naar_cloud("waarom is de lucht blauw")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "x")
    llm._reset_brein()
    assert privacy_poort.naar_cloud("waarom is de lucht blauw")
    assert not privacy_poort.naar_cloud("heb ik nieuwe mail")


# ---------------------------------------------------------------------
# controleer(): vlak voor verzending
# ---------------------------------------------------------------------

def _v(*inhoud, rol="user"):
    return [{"role": "system", "content": "Je bent JARVIS."}] + [{"role": rol, "content": i} for i in inhoud]


@pytest.mark.parametrize("berichten, reden", [
    (_v("JARVIS-CONTEXT EN GEHEUGEN\n1. DIT GESPREK ..."), "lokaal contextblok"),
    (_v("JARVIS-GEHEUGEN (wat ik over de gebruiker weet)"), "lokaal contextblok"),
    (_v("open C:\\Users\\rushi\\geheim.txt"), "bestandspad"),
    (_v("mail rushil@example.com"), "e-mailadres"),
    (_v("ik woon in Badhoevedorp"), "gevoelige geheugenwaarde"),
    (_v("Hoofdweg"), "gevoelige geheugenwaarde"),
    (_v("resultaat", rol="tool"), "rol"),
])
def test_controleer_houdt_tegen(berichten, reden):
    veilig, waarom = privacy_poort.controleer(berichten)
    assert not veilig
    assert waarom.startswith(reden)


def test_vermelding_in_instructie_is_geen_lek():
    # De vaste toolinstructie noemt het blok bij naam; dat is geen data.
    instructie = 'Gebruik "1. DIT GESPREK" uit het blok "JARVIS-CONTEXT EN GEHEUGEN".'
    assert privacy_poort.controleer([{"role": "system", "content": instructie},
                                     {"role": "user", "content": "sluit hem"}]) == (True, "")


def test_controleer_laat_gewone_vraag_door():
    assert privacy_poort.controleer(_v("waarom is de lucht blauw", "en de zee?")) == (True, "")


def test_controleer_tools():
    goed = [{"type": "function", "function": {"name": "open_program"}},
            {"type": "function", "function": {"name": "game_pc_open_program"}}]
    assert privacy_poort.controleer(_v("open spotify"), goed) == (True, "")
    for naam in ("recall", "remember", "list_files", "screenshot", "search_files", "open_file",
                 "discord_dms", "browser_get_content", "ui_type_text", "game_pc_list_files"):
        veilig, _ = privacy_poort.controleer(_v("x"), [{"type": "function", "function": {"name": naam}}])
        assert not veilig, naam


def test_cloud_tools_filtert_lees_tools():
    tools = [{"type": "function", "function": {"name": n}}
             for n in ("open_program", "recall", "control_home_assistant", "list_files", "web_search")]
    assert [t["function"]["name"] for t in privacy_poort.cloud_tools(tools)] == [
        "open_program", "control_home_assistant", "web_search"]


def test_llm_stuurt_onveilig_verzoek_niet(gemini_nep, monkeypatch):
    lokaal = []
    monkeypatch.setattr(llm.ollama, "chat", lambda **kw: lokaal.append(kw) or types.SimpleNamespace(
        message=types.SimpleNamespace(content="lokaal", tool_calls=None)))
    antwoord = llm.chat(_v("ik woon in Badhoevedorp"), cloud=True)
    assert antwoord.message.content == "lokaal"
    assert gemini_nep.verzoeken == []
    assert lokaal


def test_llm_stream_onveilig_niet_naar_gemini(gemini_nep, monkeypatch):
    monkeypatch.setattr(llm.ollama, "chat", lambda **kw: iter([{"message": {"content": "lokaal"}}]))
    assert "".join(llm.chat_stream(_v("JARVIS-GEHEUGEN (wat ik weet): x"), cloud=True)) == "lokaal"
    assert gemini_nep.verzoeken == []


# ---------------------------------------------------------------------
# Wat Gemini krijgt
# ---------------------------------------------------------------------

def test_persona_alleen_naam_en_aanspreekvorm():
    tekst = privacy_poort.persona()
    assert config.USER_NAME in tekst and "'u'" in tekst
    assert WOONPLAATS not in tekst


def test_cloud_geschiedenis_alleen_gemini_beurten():
    privacy_poort.onthoud_cloud_beurt("Wat is de hoofdstad van Frankrijk?", "Parijs.")
    berichten = privacy_poort.cloud_berichten("En van Duitsland?")
    assert [b["content"] for b in berichten[1:]] == [
        "Wat is de hoofdstad van Frankrijk?", "Parijs.", "En van Duitsland?"]


def test_cloud_geschiedenis_maximaal_en_verloopt(monkeypatch):
    for i in range(10):
        privacy_poort.onthoud_cloud_beurt(f"vraag {i}", f"antwoord {i}")
    assert len(privacy_poort.cloud_geschiedenis()) == 2 * privacy_poort.MAX_CLOUD_BEURTEN
    nu = time.monotonic() + privacy_poort.CLOUD_GESCHIEDENIS_TTL + 1
    monkeypatch.setattr(privacy_poort.time, "monotonic", lambda: nu)
    assert privacy_poort.cloud_geschiedenis() == []


def test_laatste_programma_alleen_bij_verwijzing():
    assert privacy_poort.laatste_programma_regel("sluit hem", "Discord") == {
        "role": "system", "content": "Laatste programma in dit gesprek: Discord"}
    assert privacy_poort.laatste_programma_regel("open spotify", "Discord") is None
    assert privacy_poort.laatste_programma_regel("sluit hem", None) is None
    assert privacy_poort.laatste_programma_regel("open het", "C:\\Users\\x\\a.exe") is None


# ---------------------------------------------------------------------
# In het brein
# ---------------------------------------------------------------------

@pytest.fixture
def lokaal_geheugen(monkeypatch):
    """De lokale berichten bevatten het geheugen (zoals echt)."""

    import core.ai as ai

    blok = f"JARVIS-CONTEXT EN GEHEUGEN\n1. DIT GESPREK\nLaatste programma: Discord\nwoonplaats: {WOONPLAATS}"
    monkeypatch.setattr(ai, "build_memory_context", lambda *a, **k: blok)
    monkeypatch.setattr(ai, "extract_personal_info", lambda *a, **k: None)
    return blok


def test_gewone_vraag_naar_gemini_zonder_geheugen(gemini_nep, lokaal_geheugen):
    from core.ai import ask_ai

    antwoord = ask_ai("waarom is de lucht blauw?")
    assert antwoord == "Rayleigh-verstrooiing, sir."
    verzoek = gemini_nep.verzoeken[0]
    tekst = _alles(verzoek)
    assert WOONPLAATS not in tekst and "JARVIS-CONTEXT" not in tekst and "Discord" not in tekst
    assert verzoek["messages"][-1] == {"role": "user", "content": "waarom is de lucht blauw?"}


def test_vervolgvraag_krijgt_alleen_gemini_beurt(gemini_nep, lokaal_geheugen):
    from core.ai import ask_ai

    ask_ai("wat is de hoofdstad van frankrijk?")
    gemini_nep.staat["antwoord"] = "Berlijn, sir."
    ask_ai("en van duitsland?")
    inhoud = [m["content"] for m in gemini_nep.verzoeken[1]["messages"][1:]]
    assert inhoud == ["wat is de hoofdstad van frankrijk?", "Rayleigh-verstrooiing, sir.", "en van duitsland?"]


def test_streaming_via_gemini(gemini_nep, lokaal_geheugen):
    from core.ai import ask_ai

    stukken = []
    assert ask_ai("waarom is de lucht blauw?", on_tekst=stukken.append) == "Rayleigh-verstrooiing, sir."
    assert gemini_nep.verzoeken[0]["stream"] is True
    assert WOONPLAATS not in _alles(gemini_nep.verzoeken[0])


def test_persoonlijke_vraag_nooit_naar_gemini(gemini_nep, lokaal_geheugen, monkeypatch):
    from core.ai import ask_ai

    monkeypatch.setattr(llm.ollama, "chat", lambda **kw: types.SimpleNamespace(
        message=types.SimpleNamespace(content="U woont in Badhoevedorp.", tool_calls=None)))
    assert "Badhoevedorp" in ask_ai("waar woon ik?")
    assert gemini_nep.verzoeken == []


def test_terugval_krijgt_lokale_berichten(gemini_nep, lokaal_geheugen, monkeypatch):
    from core.ai import ask_ai

    def kapot(messages, **kw):
        raise gemini.GeminiFout("weg", gemini.NETWERK)

    gezien = []
    monkeypatch.setattr(gemini, "chat", kapot)
    monkeypatch.setattr(llm.ollama, "chat", lambda **kw: gezien.append(kw["messages"]) or types.SimpleNamespace(
        message=types.SimpleNamespace(content="Lokaal antwoord.", tool_calls=None)))
    assert ask_ai("waarom is de lucht blauw?") == "Lokaal antwoord."
    assert any("JARVIS-CONTEXT" in str(m.get("content")) for m in gezien[0])
    # Een lokaal antwoord komt niet in de Gemini-geschiedenis.
    assert privacy_poort.cloud_geschiedenis() == []


def test_actie_via_gemini_alleen_bedien_tools(gemini_nep, lokaal_geheugen, monkeypatch):
    import core.ai as ai

    gemini_nep.staat["antwoord"] = "Dat doe ik niet."
    ai.update_context(last_program="Discord")
    ai.ask_ai("zet de lampen in de woonkamer op rood")
    verzoek = gemini_nep.verzoeken[0]
    namen = {t["function"]["name"] for t in verzoek["tools"]}
    assert namen and namen <= privacy_poort.CLOUD_TOOLS
    tekst = _alles(verzoek)
    assert WOONPLAATS not in tekst and "woonplaats:" not in tekst
    assert privacy_poort.controleer(verzoek["messages"], verzoek["tools"]) == (True, "")
    # Geen verwijzing in de vraag: dan ook geen programmanaam mee.
    assert "Laatste programma" not in tekst


def test_actie_met_verwijzing_krijgt_alleen_programmanaam(gemini_nep, lokaal_geheugen):
    import core.ai as ai

    gemini_nep.staat["antwoord"] = "Welk programma bedoelt u?"
    ai.update_context(last_program="Discord")
    ai.ask_ai("sluit hem opnieuw af en open het opnieuw")
    if gemini_nep.verzoeken:  # de vaste routers kunnen het al afvangen
        tekst = _alles(gemini_nep.verzoeken[0])
        assert "Laatste programma in dit gesprek: Discord" in tekst
        assert WOONPLAATS not in tekst


def test_agent_plan_zonder_geheugen_en_ha_lijst(gemini_nep, monkeypatch):
    import core.agent as agent_mod

    monkeypatch.setattr(agent_mod, "build_memory_context", lambda *a, **k: f"JARVIS-GEHEUGEN woonplaats: {WOONPLAATS}")
    monkeypatch.setattr(agent_mod, "_live_ha_devices", lambda: "person.rushil: thuis (Badhoevedorp)")
    gemini_nep.staat["antwoord"] = json.dumps({"steps": []})
    agent_mod.Agent()._generate_plan("open discord en zet muziek aan")
    tekst = _alles(gemini_nep.verzoeken[0])
    assert WOONPLAATS not in tekst and "person.rushil" not in tekst and "JARVIS-GEHEUGEN" not in tekst
    assert gemini_nep.verzoeken[0]["json_mode"] is True


def test_agent_plan_persoonlijk_blijft_lokaal(gemini_nep, monkeypatch):
    import core.agent as agent_mod

    monkeypatch.setattr(llm.ollama, "chat", lambda **kw: types.SimpleNamespace(
        message=types.SimpleNamespace(content='{"steps": []}', tool_calls=None)))
    agent_mod.Agent()._generate_plan("open mijn agenda en lees mijn mail voor")
    assert gemini_nep.verzoeken == []


def test_opzoeken_met_google_zoeken(gemini_nep):
    from core import opzoeken

    def chat(messages, **kw):
        gemini_nep.verzoeken.append({"messages": messages, **kw})
        return gemini.Antwoord("Verstappen won, sir.", bronnen=[
            {"url": "https://a.nl", "titel": "a.nl"}, {"url": "https://b.nl", "titel": "b.nl"},
            {"url": "https://c.nl", "titel": "c.nl"}])

    gemini.chat = chat  # monkeypatch van gemini_nep wordt na de test hersteld
    assert opzoeken.zoek_met_gemini("wie won de laatste race") == "Verstappen won, sir. (Bron: a.nl, b.nl)"
    assert gemini_nep.verzoeken[-1]["zoeken"] is True


def test_opzoeken_persoonlijk_of_zonder_gemini_geeft_none(gemini_nep, monkeypatch):
    from core import opzoeken

    assert opzoeken.zoek_met_gemini("wat staat er in mijn agenda") is None
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    assert opzoeken.zoek_met_gemini("wie won de laatste race") is None
    assert gemini_nep.verzoeken == []


def test_opzoeken_bij_storing_geen_ollama_gok(gemini_nep, monkeypatch):
    from core import opzoeken

    def kapot(messages, **kw):
        raise gemini.GeminiFout("op", gemini.LIMIET)

    monkeypatch.setattr(gemini, "chat", kapot)
    monkeypatch.setattr(llm.ollama, "chat", lambda **kw: pytest.fail("Ollama mag hier niet raden"))
    assert opzoeken.zoek_met_gemini("wie won de laatste race") is None


def test_commando_correctie_via_gemini(gemini_nep):
    from core import commando_correctie as cc

    gemini_nep.staat["antwoord"] = json.dumps({"commando": "open discord", "zekerheid": 90})
    k = cc.ai_kandidaat("open dat chat programma", namen=["discord", "spotify"])
    assert k.commando == "open discord"
    assert gemini_nep.verzoeken[0]["json_mode"] is True


def test_commando_correctie_persoonlijk_lokaal(gemini_nep, monkeypatch):
    from core import commando_correctie as cc

    monkeypatch.setattr(llm.ollama, "chat", lambda **kw: types.SimpleNamespace(
        message=types.SimpleNamespace(content="{}", tool_calls=None)))
    cc.ai_kandidaat("open mijn cv bestand", namen=["discord"])
    assert gemini_nep.verzoeken == []


def test_controleer_tool_met_persoonlijke_beschrijving():
    tool = {"type": "function", "function": {"name": "open_program",
                                             "description": "Bijv. de lamp in Badhoevedorp."}}
    veilig, reden = privacy_poort.controleer(_v("open spotify"), [tool])
    assert not veilig and "persoonlijke gegevens" in reden
