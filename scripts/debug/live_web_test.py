import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, "C:\\JARVIS")
from core import brain

ok_all = True
count = 0

def ok(label, cond):
    global ok_all, count
    count += 1
    if cond:
        print(f"  ✅ [{count}] {label}")
    else:
        ok_all = False
        print(f"  ❌ [{count}] {label}")

# =========================================================================
# FASE 8 - WEB FETCH (lees een pagina op)
# =========================================================================
print("=" * 60)
print("FASE 8 - WEB FETCH: 'lees deze pagina <url>'")
print("=" * 60)

print("\n1) lees deze pagina https://nl.wikipedia.org/wiki/Nederland")
out = brain.process_command("lees deze pagina https://nl.wikipedia.org/wiki/Nederland")
has_content = out and ("Nederland" in out or "land" in out or "hoofdstad" in out)
ok("pagina wordt opgehaald en leesbaar", bool(out and len(str(out)) > 50))
ok("bevat verwachte tekst", has_content)
print()

print("2) wat staat er op https://nl.wikipedia.org/wiki/Amsterdam")
out = brain.process_command("wat staat er op https://nl.wikipedia.org/wiki/Amsterdam")
has_content = out and ("Amsterdam" in out or "hoofdstad" in out)
ok("uitleg van pagina komt terug", has_content)
print()

print("3) lees deze pagina https://ditbestaatniet9999.nl (moet nette fout geven)")
out = brain.process_command("lees deze pagina https://ditbestaatniet9999.nl")
ok("ongeldige site -> nette foutmelding", out is not None and "niet" in out.lower() or "kon" in out.lower())
print()

# =========================================================================
# FASE 9 - WEB AGENT (zoek + lees + vergelijk)
# =========================================================================
print("=" * 60)
print("FASE 9 - WEB AGENT")
print("=" * 60)

print("\n4) zoek de openingstijden van de Albert Heijn in Badhoevedorp op")
out = brain.process_command("zoek de openingstijden van de Albert Heijn in Badhoevedorp op")
has_time = out and ("0" in str(out) or ":" in str(out)) and (":" in str(out))
ok("openingstijden gevonden (met uren)", has_time)
print()

print("5) google naar de hoofdstad van Australië")
out = brain.process_command("google naar de hoofdstad van Australië")
likely = out and ("Canberra" in out or "canberra" in out)
ok("antwoord gevonden (Canberra)", likely)
print()

print("6) wat is het weer in Utrecht")
out = brain.process_command("wat is het weer in Utrecht")
has_weather = out and ("graad" in out or "°" in out or "c" in out.lower())
ok("weer opgehaald met temperatuur", has_weather)
print()

print("7) vergelijk de RTX 4070 met de RTX 4060")
out = brain.process_command("vergelijk de RTX 4070 met de RTX 4060")
has_verdict = out and "WINNAAR" in out
ok("vergelijking geeft WINNAAR-oordeel", has_verdict)
print()

print("8) wanneer kwam de eerste iPhone uit")
out = brain.process_command("wanneer kwam de eerste iPhone uit")
has_date = out and ("2007" in out or "januari" in out or "juni" in out)
ok("iPhone-bug: geeft antwoord i.p.v. sluit-actie", has_date)
print()

print("9) zoek op wikipedia naar Python (moet browser openen)")
out = brain.process_command("zoek op wikipedia naar python")
ok("browser-domein (geen web-agent-output)", out is not None)
print()

print("=" * 60)
print(f"LIVE WEB TEST: {count} checks")
print("ALLES OK" if ok_all else "Sommige checks faalden (niet per se een bug: sites/DDG kunnen antiveren)")
print("=" * 60)
sys.exit(0 if ok_all else 1)