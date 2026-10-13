import os
from datetime import datetime
from PIL import ImageGrab

from actions.paths import get_known_folder


def get_screenshot_folder():

    folder = os.path.join(
        get_known_folder("Pictures"),
        "JARVIS"
    )

    os.makedirs(folder, exist_ok=True)

    return folder


def take_screenshot(open_after=True):

    try:

        image = ImageGrab.grab()

        folder = get_screenshot_folder()

        filename = datetime.now().strftime("screenshot_%Y%m%d_%H%M%S.png")

        path = os.path.join(folder, filename)

        image.save(path)

        if open_after:
            os.startfile(path)

        return path

    except Exception as error:
        print(f"Fout bij screenshot: {error}")
        return None