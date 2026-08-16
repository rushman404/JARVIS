import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.file_finder import open_file


results = open_file("nieuwe opname 2.mp4")
