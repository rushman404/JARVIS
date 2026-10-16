import os
import ctypes

import config


def lock_pc():

    try:

        ctypes.windll.user32.LockWorkStation()

        return "Ik heb de pc vergrendeld."

    except Exception as error:
        print(f"Fout bij vergrendelen: {error}")
        return "Ik kon de pc niet vergrendelen."


def sleep_pc():

    try:

        # 0 = slaap (geen slaapstand/hibernate), 0 = niet forceren,
        # 0 = wake-events mogen
        if os.name == "nt":
            ctypes.windll.powrprof.SetSuspendState(0, 0, 0)
        else:
            os.system("systemctl suspend")

        return "Ik zet de pc in slaapstand."

    except Exception as error:
        print(f"Fout bij slaapstand: {error}")
        return "Ik kon de pc niet in slaapstand zetten."


def hibernate_pc():

    try:

        # 1 = sluimerstand (hibernate), 0 = niet forceren, 0 = wake-events
        if os.name == "nt":
            ctypes.windll.powrprof.SetSuspendState(1, 0, 0)
        else:
            os.system("systemctl hibernate")

        return "Ik zet de pc in sluimerstand."

    except Exception as error:
        print(f"Fout bij sluimerstand: {error}")
        return "Ik kon de pc niet in sluimerstand zetten."


def shutdown_pc():

    # Wachttijd uit config, zodat JARVIS eerst kan zeggen wat hij doet en
    # de gebruiker nog kan annuleren voordat Windows echt afsluit.
    seconds = config.POWER_COUNTDOWN_SECONDS

    os.system(f"shutdown /s /t {seconds}")

    return (
        f"Ik sluit de pc af over {seconds} seconden. "
        "Je kunt 'annuleer afsluiten' zeggen om dit te stoppen. Tot ziens!"
    )


def restart_pc():

    seconds = config.POWER_COUNTDOWN_SECONDS

    os.system(f"shutdown /r /t {seconds}")

    return (
        f"Ik herstart de pc over {seconds} seconden. "
        "Je kunt 'annuleer herstart' zeggen om dit te stoppen."
    )


def cancel_power_action():

    if os.name != "nt":
        return "Annuleren wordt alleen op Windows ondersteund."

    os.system("shutdown /a")

    return "Ik heb de geplande afsluiting of herstart geannuleerd."


def logoff_pc():

    os.system("shutdown /l")

    return "Ik meld je af."


def cancel_shutdown():
    """Annuleert een lopende shutdown of herstart (delegeert)."""
    return cancel_power_action()