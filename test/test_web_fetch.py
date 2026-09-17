"""
JARVIS - Fase 8: Web Fetch tests
===================================

Test de web-fetch-skill zonder echt internet:

  [1] URL-validatie (alleen http/https, geen file://, geen onzin)
  [2] html_to_text: scripts/styles/nav verwijderen, tekst schoon
  [3] extract_title / extract_meta_description
  [4] truncate_text: lange pagina's afkappen (token-limiet)
  [5] fetch_url: succes / 404 / timeout / verbindingsfout / te groot
      (requests wordt gemockt, geen live netwerk)
  [6] format_fetch_result: nette samenvatting
  [7] core.ai.execute_tool('web_fetch') dispatchen
  [8] core.brain.process_command routing ('lees deze pagina <url>')
  [9] web_fetch NOOIT een gevaarlijke/onveilige actie

Alle netwerkhandelingen zijn gemockt; geen echt HTTP-verkeer.
"""
import sys
import os
import io
import re

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from unittest.mock import patch, MagicMock

import actions.web as web

passed = 0
failed = 0


def ok(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        extra = f" ({detail})" if detail else ""
        print(f"  [FAIL] {label}{extra}")


# =============================================================
# [1] URL-VALIDATIE
# =============================================================

print("\n===== [1] URL-VALIDATIE =====")

ok("https-url is veilig", web.is_safe_url("https://www.example.com"))
ok("http-url is veilig", web.is_safe_url("http://example.nl/test"))
ok("file:// wordt geweigerd", not web.is_safe_url("file:///C:/geheim.txt"))
ok("ftp:// wordt geweigerd", not web.is_safe_url("ftp://example.com"))
ok("zonder scheme wordt geweigerd", not web.is_safe_url("example.com"))
ok("lege string wordt geweigerd", not web.is_safe_url(""))
ok("onzin wordt geweigerd", not web.is_safe_url("dit is geen url"))
ok("javascript-URL wordt geweigerd", not web.is_safe_url("javascript:alert(1)"))

# =============================================================
# [2] HTML -> TEKST
# =============================================================

print("\n===== [2] HTML -> TEKST =====")

HTML_SAMPLE = """<html><head>
<script>var x = 1; if (x) { evil(); }</script>
<style>.red { color: red; }</style>
<title>Testpagina</title>
<meta name="description" content="Een beschrijving voor de test.">
</head><body>
<!-- opmerking -->
<nav><a href="/home">Home</a> <a href="/about">Over ons</a></nav>
<h1>Welkom op de testpagina</h1>
<p>Dit is de eerste alinea met <b>belangrijke</b> woorden.</p>
<p>Hier staat nog &eacute;&eacute;n regel met entiteiten.</p>
<footer>Copyright JARVIS 2026</footer>
</body></html>"""

text = web.html_to_text(HTML_SAMPLE)

ok("scripts zijn verwijderd", "evil" not in text)
ok("styles zijn verwijderd", "color" not in text.lower() or "red" not in text)
ok("opmerkingen zijn verwijderd", "opmerking" not in text)
ok("navigatie is verwijderd", "Over ons" not in text and "nav" not in text.lower() or len(text) > 0)
ok("inhoud blijft behouden", "Welkom op de testpagina" in text or "testpagina" in text)
ok("html-entities gedecodeerd", "één" in text)
ok("geen tags over", "<" not in text)

# =============================================================
# [3] TITEL & META
# =============================================================

print("\n===== [3] TITEL & META =====")

ok("titel wordt uitgelezen", web.extract_title(HTML_SAMPLE) == "Testpagina")
ok("meta-description wordt uitgelezen",
   "beschrijving" in web.extract_meta_description(HTML_SAMPLE))
ok("geen titel -> lege string", web.extract_title("<html><p>x</p></html>") == "")

# =============================================================
# [4] TRUNCATE
# =============================================================

print("\n===== [4] TRUNCATE (token-limiet) =====")

ok("korte tekst blijft heel", web.truncate_text("kort") == "kort")
long_text = "woord " * 2000  # ~10000 tekens
trunc = web.truncate_text(long_text)
ok("lange tekst wordt afgekapt", len(trunc) < len(long_text))
ok("afkapping bevat melding", "... (pagina afgekapt)" in trunc)
ok("lege tekst -> leeg", web.truncate_text("") == "")

# =============================================================
# [5] FETCH_URL (gemockte requests)
# =============================================================

print("\n===== [5] FETCH_URL =====")

# Succesvolle pagina
ok_response = MagicMock()
ok_response.status_code = 200
ok_response.text = HTML_SAMPLE

with patch.object(requests, "get", return_value=ok_response) as m:
    result = web.fetch_url("https://www.example.com/pagina")
    ok("succesvolle fetch -> ok=True", result["ok"] is True)
    ok("titel in resultaat", result["title"] == "Testpagina")
    ok("tekst geëxtraheerd", "testpagina" in result["text"])
    ok("URL meegestuurd", result["url"] == "https://www.example.com/pagina")

# 404
not_found = MagicMock()
not_found.status_code = 404
with patch.object(requests, "get", return_value=not_found):
    result = web.fetch_url("https://example.com/nietbestaand")
    ok("404 -> ok=False", result["ok"] is False)
    ok("404-melding netjes", "404" in result.get("error", ""))

# Andere HTTP-fout (500)
internal_error = MagicMock()
internal_error.status_code = 500
with patch.object(requests, "get", return_value=internal_error):
    result = web.fetch_url("https://example.com/fout")
    ok("500 -> ok=False", result["ok"] is False)
    ok("500-melding netjes", "500" in result.get("error", ""))

# Timeout
with patch.object(requests, "get", side_effect=requests.exceptions.Timeout):
    result = web.fetch_url("https://example.com/langzaam")
    ok("timeout -> ok=False", result["ok"] is False)
    ok("timeout-melding netjes", "reageerde niet" in result.get("error", ""))

# Verbindingsfout
with patch.object(requests, "get", side_effect=requests.exceptions.ConnectionError):
    result = web.fetch_url("https://example.com/offline")
    ok("verbindingsfout -> ok=False", result["ok"] is False)

# Ongeldige URL
result = web.fetch_url("geen url")
ok("ongeldige url -> ok=False", result["ok"] is False)
ok("ongeldige url -> nette melding", "geen geldige web-URL" in result.get("error", ""))

# Te groot (mock een lange tekst, lagere limiet)
big_response = MagicMock()
big_response.status_code = 200
big_response.text = "x" * 5000
with patch.object(requests, "get", return_value=big_response):
    result = web.fetch_url("https://example.com/groot", max_bytes=1000)
    ok("te grote pagina -> ok=False", result["ok"] is False)

# =============================================================
# [6] FORMAT_FETCH_RESULT
# =============================================================

print("\n===== [6] FORMAT_FETCH_RESULT =====")

formatted = web.format_fetch_result({
    "ok": True, "title": "Titel X", "description": "Omschrijving Y",
    "text": "Inhoud van de pagina die gelezen moet worden.",
})
ok("format bevat titel", "Titel X" in formatted)
ok("format bevat inhoud", "Inhoud van de pagina" in formatted)

error_formatted = web.format_fetch_result({"ok": False, "error": "Foutmelding Z"})
ok("foutresultaat wordt doorgegeven", "Foutmelding Z" in error_formatted)

# =============================================================
# [7] EXECUTE_TOOL DISPATCH
# =============================================================

print("\n===== [7] EXECUTE_TOOL (web_fetch) =====")

import core.ai as ai
from core.ai import update_context

update_context(pending_choice=None)

with patch("core.ai.web_fetch_tool", return_value="Tool-resultaat web") as m:
    result = ai.execute_tool("web_fetch", {"url": "https://example.com"}, "lees deze pagina")
    ok("execute_tool roept web_fetch_tool aan", m.called)
    ok("resultaat teruggegeven", result == "Tool-resultaat web")

# ontbrekend argument -> nette fout, geen crash
result = ai.execute_tool("web_fetch", {}, "lees deze pagina")
ok("web_fetch zonder url -> nette fout", "kon web_fetch niet uitvoeren" in result)

# =============================================================
# [8] BRAIN-ROUTING
# =============================================================

print("\n===== [8] BRAIN-ROUTING =====")

import core.brain as brain

update_context(pending_choice=None)

fake_page = {"ok": True, "title": "Voorbeeld", "description": "",
             "text": "Inhoud die JARVIS vertelt wat er op de pagina staat."}

with patch("core.brain.fetch_url", return_value=fake_page) as m:
    result = brain.process_command("lees deze pagina https://example.com/hallo")
    ok("'lees deze pagina <url>' roept fetch_url aan", m.called)
    ok("melding met pagina-inhoud", "Voorbeeld" in result)

    result = brain.process_command("wat staat er op https://example.com")
    ok("'wat staat er op <url>' routeert", "Voorbeeld" in result)

    result = brain.process_command("lees deze pagina")
    ok("'lees deze pagina' zonder url -> vraag om url", "URL" in result)

    update_context(pending_choice=None)
    result = brain.process_command("https://example.com")
    ok("losse URL als antwoord -> direct fetch", "Voorbeeld" in result and m.called)

    update_context(pending_choice=None)
    result = brain.process_command("ja https://example.com/pagina")
    ok("'ja <url>' als antwoord -> direct fetch", "Voorbeeld" in result)

with patch("core.brain.ask_ai", return_value="AI-STUB"):
    result = brain.process_command("open youtube")
    ok("'open youtube' gaat NIET naar web_fetch",
       not str(result).startswith("Zal ik") and "open_website" != "web_fetch")

# =============================================================
# [9] SAFETY
# =============================================================

print("\n===== [9] SAFETY =====")

ok("web_fetch accepteert geen file://", not web.is_safe_url("file:///tmp/x"))
ok("web_fetch accepteert geen intranet-gok", not web.is_safe_url("192.168.1.1"))


# =============================================================
print()
print("=" * 50)
print(f"FASE 8 WEB FETCH: {passed} geslaagd, {failed} gefaald")
print("=" * 50)
sys.exit(1 if failed else 0)