import sys
import os
from core.result_validation import classify_tool_result

def test_main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ha_foutmeldingen = ['Kan Home Assistant niet bereiken (HTTP 400).', 'Kan Home Assistant niet bereiken (HTTP 403).', 'Kan Home Assistant niet bereiken (HTTP 500).', 'Kan Home Assistant niet bereiken (HTTP 502).', 'Kan Home Assistant niet bereiken: verbinding mislukt.', 'Kan Home Assistant niet bereiken: timeout (mislukt).', 'Kan Home Assistant niet bereiken (HTTP 400 serverfout mislukt).', 'Kan Home Assistant niet vinden (HTTP 404).', 'Kan Home Assistant niet autoriseren (HTTP 401): geen toegang.']
    for msg in ha_foutmeldingen:
        assert classify_tool_result(msg) == 'failed', f'{msg!r} -> failed'
    print()
    succesmeldingen = ['Bed lamp is nu aan.', 'Bed lamp is nu aan. (brightness 50%) (kleur: hs_color 120, 100)', 'Spotify stond al open en staat nu vooraan.', 'Ik heb een screenshot gemaakt en geopend.', 'Ik heb de muziek gepauzeerd of hervat.', 'Volume staat nu op 30%.']
    for msg in succesmeldingen:
        assert classify_tool_result(msg) == 'success', f'{msg!r} -> success'
    print()
    overige_fouten = ['Ik kan het bestand niet vinden.', 'Welk programma wil je openen?', 'Ik kon de website niet openen.', 'Fout bij het uitvoeren van de actie.']
    assert classify_tool_result('Welk programma wil je openen?') == 'uncertain', 'vraag -> uncertain'
    assert classify_tool_result('Ik kan het bestand niet vinden.') == 'failed', "'ik kan bestand niet vinden' -> failed"
    assert classify_tool_result('') == 'uncertain', 'leeg resultaat -> uncertain'
    print()
