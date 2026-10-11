import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ollama
from core.ai import MODEL

tools = [{'type': 'function', 'function': {'name': 'open_file', 'description': 'Zoek een bestand op de computer en open het.', 'parameters': {'type': 'object', 'properties': {'filename': {'type': 'string', 'description': 'De naam van het bestand dat geopend moet worden.'}}, 'required': ['filename']}}}, {'type': 'function', 'function': {'name': 'open_website', 'description': 'Open een website in de standaard webbrowser.', 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string', 'description': 'De URL van de website, bijvoorbeeld https://www.youtube.com/'}}, 'required': ['url']}}}]

messages = [
    {'role': 'system', 'content': 'Je bent JARVIS. Als de gebruiker een bestand wil openen, gebruik open_file. Als de gebruiker een website wil openen, gebruik open_website. Gebruik nooit open_file voor websites.'},
    {'role': 'user', 'content': 'Open YouTube'},
]


def test_tools():
    """Roept ollama.chat aan met de tool-definities (gemockt, geen echte service nodig)."""
    with patch('ollama.chat') as mock_chat:
        mock_chat.return_value = {'message': {'content': 'mocked response'}}

        response = ollama.chat(model=MODEL, messages=messages, tools=tools)

    assert response is not None
    assert response['message']['content'] == 'mocked response'
    mock_chat.assert_called_once()
    assert mock_chat.call_args.kwargs['tools'] == tools
