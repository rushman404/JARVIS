# Fase 8 & 9 Live Test Vragen
Draai JARVIS (python main.py) en voer deze vragen in.

---

## Fase 8 — Web Fetch (pagina's lezen)

| # | Vraag | Wat je verwacht |
|---|---|---|
| 1 | `lees deze pagina https://nl.wikipedia.org/wiki/Nederland` | Informatie over Nederland (taal, hoofdstad, etc.) |
| 2 | `wat staat er op https://nl.wikipedia.org/wiki/Amsterdam` | Tekst over Amsterdam |
| 3 | `lees deze pagina https://ditbestaatniet9999.nl` | Nette foutmelding (geen crash) |

---

## Fase 9 — Web Agent (zoeken + antwoord)

### Directe vragen
| # | Vraag | Wat je verwacht |
|---|---|---|
| 4 | `google naar de hoofdstad van Australië` | **Canberra** (of wiki-artikel met Canberra erin) |
| 5 | `wat is het weer vandaag` | Temperatuur + weer in Amsterdam |
| 6 | `wat is het weer in Utrecht` | Temperatuur + weer in Utrecht |
| 7 | `wanneer kwam de eerste iPhone uit` | **2007** (geen Discord-sluiting!) |

### Openingstijden
| # | Vraag | Wat je verwacht |
|---|---|---|
| 8 | `zoek de openingstijden van de Albert Heijn in Badhoevedorp op` | Openingstijden met uren |
| 9 | `hoe laat sluit de Jumbo in Haarlem` | Openingstijden / sluitingstijd |

### Vergelijkingen
| # | Vraag | Wat je verwacht |
|---|---|---|
| 10 | `vergelijk de RTX 4070 met de RTX 4060` | **🏆 WINNAAR: ...** + waarom + tips |
| 11 | `vergelijk de iPhone 15 met de Samsung S24` | Duidelijk oordeel welke beter is + waarom |

### Browser (niet web-agent)
| # | Vraag | Wat je verwacht |
|---|---|---|
| 12 | `zoek op youtube naar spider-man` | Browser opent YouTube-zoekresultaten |
| 13 | `zoek op wikipedia naar Python` | Browser opent Wikipedia-zoekresultaten |

---

## FAQ

**De vergelijking faalt?**
→ DDG kan tijdelijk geblokkeerd zijn (202 rate-limit). Even 30s wachten en opnieuw proberen.
Vergelijkingen zijn afhankelijk van twee leesbare bronnen; sommige sites blokkeren bots.

**"Wanneer kwam de eerste iPhone uit" sluit Discord?**
→ Gefixt! De vraag gaat nu naar de web-agent i.p.v. sluiting.

**Weer toont een stad in de VS (Londen → Gabon)?**
→ Known issue: Open-Meteo geocoder is imperfect. Amsterdam/Utrecht werken prima.

**Wikipedia-artikel is incompleet?**
→ De fallback pakt het eerste relevante artikel; niet altijd perfect voor samengestelde vragen.

---

## Tips voor testen
- **Start JARVIS opnieuw** na codewijzigingen (`python main.py`)
- **Even wachten** na meerdere DuckDuckGo-verzoeken (rate-limit)
- **Weer werkt altijd** — Open-Meteo is rate-limit-vrij
- **Wikipedia werkt meestal** — gratis, geen rate-limit
