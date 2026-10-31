# Koopadvies mini-pc (het brein van JARVIS)

Voor Black Friday 2026 (vrijdag 27 november). De mini-pc wordt het brein (Fase 19):
hij draait JARVIS de hele dag, met Ollama als terugval, straks Whisper
(Fase 33, lokaal verstaan) en later misschien een lokaal beeldmodel ("zien").
Budget ongeveer €400. Prijzen veranderen snel, dus de bedragen hieronder zijn
een indicatie; vergelijk altijd even (bijvoorbeeld via Tweakers Pricewatch).

## Wat JARVIS nodig heeft

| Onderdeel | Gebruikt ongeveer |
|---|---|
| JARVIS zelf (Python, dashboard, agent-verbinding) | 0,5–1 GB RAM, weinig CPU |
| Ollama met `qwen2.5:3b` (terugval en "voor wie is deze zin?") | 3–4 GB RAM; antwoordt vlot op een moderne 8-core |
| Whisper `small` (Fase 33) | ±1 GB RAM; op een 8-core snel genoeg voor korte opdrachten |
| Whisper `medium` (beter Nederlands) | ±2–3 GB RAM; trager, alleen met een snelle CPU |
| Later: lokaal beeldmodel (scherm begrijpen) | 5–8 GB RAM |
| Windows 11 zelf | 4–6 GB RAM |

Bij elkaar zit u met alles aan rond de 16 GB. Daarom is **32 GB** verstandig:
dan blijft er ruimte over en hoeft Ollama niet steeds opnieuw te laden.

## Eisen

**Moet**
- **CPU:** AMD Ryzen 7 met 8 kernen (Zen 3 of nieuwer), bijvoorbeeld de 5825U,
  6800H, 7735HS, 7840HS of 8845HS. Of een vergelijkbare Intel Core i7/Ultra 7.
  Whisper en Ollama draaien op de CPU, dus meer kernen helpt direct.
- **Geheugen:** 32 GB (16 GB is het minimum). Liefst twee losse SO-DIMM-latjes,
  zodat u later kunt uitbreiden.
- **Opslag:** NVMe-SSD van 512 GB of meer (1 TB is fijn voor backups en modellen).
- **Windows 11** met licentie erbij (Home is genoeg).
- **Netwerk:** bekabeld (Ethernet, liefst 2.5 Gbit) naast wifi; het brein staat
  het liefst aan een kabel.
- **Stil:** hij staat altijd aan, dus let op "stil" of "silent mode" in reviews.

**Fijn om te hebben**
- Een tweede M.2-slot (voor extra opslag).
- Ingebouwde Radeon 680M/780M: niet nodig voor JARVIS, wel handig voor later.
- Een zuinig stroomverbruik in rust (rond 10 W). Aan staat hij toch al.

**Niet nodig**
- Een losse NVIDIA-videokaart (te duur en te luid voor een brein).
- Een grote behuizing of veel USB-poorten: de microfoon gaat via USB of de iPad.

## Waar u op let bij Black Friday

1. **Barebone of compleet?** Een "barebone" heeft géén RAM, SSD of Windows.
   Neem een complete versie, tenzij het samen goedkoper is.
2. **RAM-hoeveelheid in de naam:** "32GB/1TB" is wat u wilt; "16GB/512GB" kan,
   als hij later uit te breiden is.
3. **Windows-licentie:** moet erbij zitten (staat vaak als "Windows 11 Pro" in
   de titel).
4. **Garantie en retour:** koop bij een Nederlandse winkel of via Amazon.nl met
   30 dagen retour, niet bij een onbekende verkoper.
5. **Reviews over geluid en warmte:** sommige goedkope modellen hebben een
   luidruchtige ventilator.
6. **Prijsgeschiedenis:** kijk of de "korting" echt is (Tweakers laat de
   prijsgeschiedenis zien).

## Richting voor ±€400

Merken die vaak in deze prijsklasse zitten met een Ryzen 7 en 32 GB:
**Beelink** (SER-serie), **Minisforum** (UM-serie), **GMKtec** (K- en
M-serie) en **ACEMAGIC**. Een Ryzen 7 7735HS of 8845HS met 32 GB en 1 TB
komt rond Black Friday vaak binnen of net boven het budget. Een Ryzen 7
5825U met 32 GB is goedkoper en voor JARVIS ook prima; alleen Whisper
`medium` en een beeldmodel worden daar trager.

## Na de aankoop

Volg `docs/mini_pc_brein.md` (Fase 19). Kort samengevat:
1. Windows bijwerken, auto-login instellen, de pc een vast IP-adres geven in de router.
2. `scripts\install_brein.ps1` draaien en `python scripts\brein_check.py` (de dokter).
3. Op de oude pc `brein_export.py`, op de mini-pc `brein_import.py`: het
   geheugen, de koppelingen en de certificaten gaan mee, en de iPad hoeft niets
   opnieuw te koppelen.
4. Whisper aanzetten (Fase 33) en `ollama pull qwen2.5:3b`.
