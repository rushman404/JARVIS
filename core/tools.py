import os

from actions.file_finder import open_file
from actions.pc import open_website, open_program, close_program, minimize_program, maximize_program, restore_window
from actions.media import (
    play_pause,
    next_track,
    previous_track,
    volume_up,
    volume_down,
    set_volume,
    toggle_mute,
)
from actions.system import system_summary
from actions.screenshot import take_screenshot
from actions.file_manager import create_folder, create_file, list_folder, copy_file, move_file

from memory.memory import remember, recall, forget, memory_summary, beautify

from core.home_assistant import (
    get_home_assistant_entities_tool,
    control_home_assistant_tool,
)


def open_file_tool(filename):
    result = open_file(filename)

    if result:
        return f"Ik open {filename}."

    return f"Ik kon {filename} niet openen."


def open_website_tool(url):
    result = open_website(url)

    if result:
        return f"Ik open {url}."

    return f"Ik kon de website niet openen."


def open_program_tool(program):
    result = open_program(program)

    return result


def close_program_tool(program):
    return close_program(program)


def remember_tool(key, value):
    remember(key, value)

    return f"Ik onthoud dat {key} {value}."


def recall_tool(key):
    value = recall(key)

    if value is None:
        return f"Ik heb niets opgeslagen over {key}."

    return f"Volgens mijn geheugen is {key.replace('_', ' ')}: {beautify(value)}."


def forget_tool(key):
    removed = forget(key)

    if removed:
        return f"Ik heb {key} vergeten."

    return f"Ik had niets opgeslagen over {key}."


def media_play_pause_tool():
    return play_pause()


def media_next_tool():
    return next_track()


def media_previous_tool():
    return previous_track()


def media_volume_up_tool():
    return volume_up()


def media_volume_down_tool():
    return volume_down()


def media_set_volume_tool(percent):
    return set_volume(percent)


def media_mute_tool():
    return toggle_mute()


def system_info_tool():
    return system_summary()


def screenshot_tool():

    path = take_screenshot()

    if path:
        return f"Ik heb een screenshot gemaakt en geopend: {os.path.basename(path)}."

    return "Ik kon geen screenshot maken."


def create_folder_tool(name, location=""):
    return create_folder(name, location)


def create_file_tool(name, location=""):
    return create_file(name, location)


def list_files_tool(location):
    return list_folder(location)


def copy_file_tool(filename, location):
    return copy_file(filename, location)


def move_file_tool(filename, location):
    return move_file(filename, location)


def minimize_window_tool(program):
    return minimize_program(program)


def maximize_window_tool(program):
    return maximize_program(program)


def restore_window_tool(program):
    return restore_window(program)