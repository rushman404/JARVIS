import sys
import os
import tempfile
from unittest.mock import patch
from actions.file_finder import open_file, find_file

def test_main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    MP4_NAME = '2018020116551100_c.mp4'
    print('=== FASE 6: mp4-bestand zoeken ===')
    work = tempfile.mkdtemp(prefix='jarvis_finder_test_')
    mp4_path = os.path.join(work, MP4_NAME)
    with open(mp4_path, 'wb') as f:
        f.write(b'\x00\x00\x00\x18ftypmp42')
    results = find_file(MP4_NAME, [work])
    assert isinstance(results, list), f"'{MP4_NAME}' wordt gezocht zonder crash"
    assert len(results) >= 1, 'nieuwe opname mp4 gevonden'
    with patch('actions.file_finder.find_file', return_value=[mp4_path]), patch('os.startfile') as m:
        result = open_file(MP4_NAME)
        assert m.called, 'open_file opent het gevonden mp4-bestand (gemockt)'
    with patch('actions.file_finder.find_file', return_value=[mp4_path, mp4_path + '2']), patch('os.startfile') as m2:
        result = open_file(MP4_NAME)
        assert not m2.called and 'meerdere' in result, 'meerdere matches -> nette melding (geen open)'
    print()
