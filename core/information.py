from datetime import datetime
import re


def get_information(command):

    text = (command or "").lower().strip()

    # Tijdsvragen herkennen. Let op: geen losse substring "tijd",
    # anders wordt "openingstijden" ook als tijd herkend.
    if (
        "hoe laat" in text
        or "wat is de tijd" in text
        or "welke tijd" in text
        or "wat voor tijd" in text
        or text == "tijd"
        or text == "laat"
        or re.search(r"\btijd\s+is\s+het\b", text)
        or re.search(r"hoe\s+laat\s+is\s+het", text)
        or re.search(r"laat\s+is\s+het", text)
    ):
        current_time = datetime.now().strftime("%H:%M")
        return f"Het is {current_time}."

    if (
        ("datum" in text or re.search(r"\bdag\b", text))
        and "weer" not in text
    ) or (
        re.search(r"welke\s+dag", text)
        or "de datum" in text
        or "wat is de datum" in text
        or text == "vandaag"
        or re.search(r"wat\s+voor\s+(dag|datum)", text)
    ):
        date = datetime.now().strftime("%d-%m-%Y")
        return f"Vandaag is het {date}."

    return None