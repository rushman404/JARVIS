from actions.file_finder import open_file
from actions.pc import open_website, open_program, close_program
from actions.media import (
    play_pause,
    next_track,
    previous_track,
    volume_up,
    volume_down,
    set_volume,
    toggle_mute,
)

from memory.memory import remember, recall, forget, memory_summary, beautify


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