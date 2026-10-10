import os
import ctypes


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


def shutdown_pc():

    # 5 seconden wachttijd, zodat JARVIS nog kan zeggen wat hij doet
    os.system("shutdown /s /t 5")

    return "Ik sluit de pc af over 5 seconden. Je kunt 'annuleer afsluiten' zeggen om dit te stoppen. Tot ziens!"


def restart_pc():

    # 5 seconden wachttijd, zodat JARVIS nog kan zeggen wat hij doet
    os.system("shutdown /r /t 5")

    return "Ik herstart de pc over 5 seconden. Je kunt 'annuleer herstart' zeggen om dit te stoppen."


def cancel_power_action():
    os.system("shutdown /a")
    return "Ik heb de geplande afsluiting of herstart geannuleerd."


def logoff_pc():

    os.system("shutdown /l")

    return "Ik meld je af."


def cancel_shutdown():
    """Annuleert een lopende shutdown of herstart (shutdown /a)."""
    if os.name == "nt":
        os.system("shutdown /a")
        return "Afsluiten/herstarten is geannuleerd."
    return "Annuleren wordt alleen op Windows ondersteund."