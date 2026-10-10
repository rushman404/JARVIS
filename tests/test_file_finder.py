import sys
import os
from unittest.mock import patch
from actions.file_finder import open_file, find_file

def test_main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    MP4_NAME = '2018020116551100_c.mp4'
    print('=== FASE 6: mp4-bestand zoeken ===')
    results = find_file(MP4_NAME)
    assert isinstance(results, list), f"'{MP4_NAME}' wordt gezocht zonder crash"
    assert len(results) >= 1, f'nieuwe opname mp4 gevonden'
    with patch('os.startfile') as m:
        result = open_file(MP4_NAME)
        if len(results) == 1:
            assert m.called, 'open_file opent het gevonden mp4-bestand (gemockt)'
        else:
            assert not m.called and 'meerdere' in result, 'meerdere matches -> nette melding (geen open)'
    print()
