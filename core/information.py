from datetime import datetime


def get_information(command):

    if "tijd" in command or "laat" in command or "hoe laat" in command:
        current_time = datetime.now().strftime("%H:%M")
        return f"Het is {current_time}."

    if "datum" in command or "dag" in command or "vandaag" in command:
        date = datetime.now().strftime("%d-%m-%Y")
        return f"Vandaag is het {date}."

    return None