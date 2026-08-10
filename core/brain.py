from core.calculator import calculate
from core.information import get_information
from core.ai import ask_ai

def process_command(command):

    command = command.lower().strip()

    print(f"🧠 Brain kreeg: {command}")

    # =========================
    # TIJD EN DATUM
    # =========================

    info = get_information(command)

    if info:
        return info


    # =========================
    # REKENEN
    # =========================

    result = calculate(command)

    if result is not None:
        return f"Het antwoord is {result}."


    # =========================
    # BEGROETING
    # =========================

    if any(word in command for word in [
        "hallo",
        "hoi",
        "goedemorgen",
        "goedemiddag",
        "goedenavond"
    ]):
        return "Hallo Rushil. Waarmee kan ik je helpen?"

    # =========================
    # AI OPDRACHT
    # =========================

    return ask_ai(command)