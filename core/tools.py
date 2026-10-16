import os

from actions.file_finder import open_file
from actions.pc import open_website, minimize_program, maximize_program, restore_window
from actions.media import (
    play_pause,
    next_track,
    previous_track,
    volume_up,
    volume_down,
    set_volume,
    toggle_mute,
    stop_media,
)
from actions.system import system_summary
from actions.status import get_pc_status
from actions.screenshot import take_screenshot
from actions.file_manager import create_folder, create_file, list_folder, copy_file, move_file, rename_file, open_folder, search_files, get_recent_files, recycle_file, empty_recycle_bin
from actions.power import (
    lock_pc,
    sleep_pc,
    hibernate_pc,
    shutdown_pc,
    restart_pc,
    logoff_pc,
)
from actions.browser import (browser_search, browser_back, browser_forward,
    browser_refresh, browser_new_tab, browser_close_tab,
    get_browser_url, get_browser_title, get_browser_content)
from actions.pc import open_program, close_program, restart_program, get_program_status, find_program_location
from actions.web import fetch_url, format_fetch_result, duckduckgo_search, format_search_results, search_and_fetch, format_search_and_fetch, format_weather, format_wikipedia
from actions.ui_automation import (
    list_windows,
    find_window,
    activate_window,
    list_elements,
    find_element,
    click_element,
    type_text,
    get_value,
    set_value,
    launch_app,
)
from actions.audio import (
    list_sessions,
    get_session_volume,
    set_session_volume,
    set_session_mute,
    toggle_session_mute,
    list_output_devices,
    get_default_output,
    set_default_output,
    find_or_create_session,
)

from memory.memory import remember, recall, forget, memory_summary, beautify, touch_usage

from core.home_assistant import (
    get_home_assistant_entities_tool,
    control_home_assistant_tool,
)


def open_file_tool(filename):
    result = open_file(filename)

    # open_file() geeft in álle gevallen een string terug (succes én
    # mislukking). Alleen bij een echte "Ik open ..." zin claimen we
    # succes; bij "niet vinden", "meerdere" of "kon niet openen"
    # geven we de echte melding terug zodat deze niet als succes
    # wordt geclassificeerd.
    if result.startswith("Ik open"):
        return f"Ik open {filename}."

    return result


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

    touch_usage(key)

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


def media_stop_tool():
    return stop_media()


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


def restart_program_tool(program):
    return restart_program(program)


def program_status_tool(program):
    return get_program_status(program)


def find_program_location_tool(program):
    return find_program_location(program)


def browser_search_tool(query, site="google"):
    return browser_search(query, site)


def web_fetch_tool(url):
    result = fetch_url(url)
    return format_fetch_result(result)


def web_search_tool(query):
    result = duckduckgo_search(query)
    return format_search_results(result)


def web_search_and_fetch_tool(query, max_pages=1):
    result = search_and_fetch(query, max_pages=max_pages)
    return format_search_and_fetch(result)


def weather_tool(location=""):
    from actions.web import get_weather
    return get_weather(location)


def wikipedia_tool(query):
    from actions.web import wikipedia_lookup
    return wikipedia_lookup(query)


def browser_back_tool():
    return browser_back()


def browser_forward_tool():
    return browser_forward()


def browser_refresh_tool():
    return browser_refresh()


def browser_new_tab_tool():
    return browser_new_tab()


def browser_close_tab_tool():
    return browser_close_tab()


def rename_file_tool(old_name, new_name):
    return rename_file(old_name, new_name)


def open_folder_tool(location=""):
    return open_folder(location)


def search_files_tool(query):
    return search_files(query)


def recent_files_tool(count=10):
    return get_recent_files(count)


# =============================================================
# UI Automation tools (Fase 10)
# =============================================================

def ui_list_windows_tool(filter_text=""):
    return list_windows(title_substring=filter_text or None)


def ui_find_window_tool(title=None, process_id=None):
    return find_window(title_substring=title, process_id=process_id)


def ui_activate_window_tool(handle):
    return activate_window(handle)


def ui_list_elements_tool(handle, name_filter=""):
    return list_elements(handle, name_filter=name_filter or None)


def ui_find_element_tool(handle, name=None, control_type=None):
    return find_element(handle, name=name, control_type=control_type)


def ui_click_element_tool(handle, name=None, control_type=None):
    return click_element(handle, name=name, control_type=control_type)


def ui_type_text_tool(handle, text, element_name=None):
    return type_text(handle, text, element_name=element_name)


def ui_get_value_tool(handle, name=None, control_type=None):
    return get_value(handle, name=name, control_type=control_type)


def ui_set_value_tool(handle, value, name=None, control_type=None):
    return set_value(handle, value, name=name, control_type=control_type)


def ui_launch_app_tool(path, args=None):
    return launch_app(path, args=args)


# =============================================================
# Verwijderen (prullenbak) en power (Fase 15B)
# =============================================================

POWER_ACTIONS = {
    "shutdown": shutdown_pc,
    "restart": restart_pc,
    "sleep": sleep_pc,
    "hibernate": hibernate_pc,
    "lock": lock_pc,
    "logoff": logoff_pc,
}


def recycle_file_tool(filename):
    return recycle_file(filename)


def empty_recycle_bin_tool():
    return empty_recycle_bin()


def power_tool(action):

    actie = str(action or "").strip().lower()
    functie = POWER_ACTIONS.get(actie)

    if functie is None:
        return (
            "Ik ken die stroomactie niet. Kies uit: "
            + ", ".join(sorted(POWER_ACTIONS))
            + "."
        )

    return functie()


# =============================================================
# Audio tools (Fase 11)
# =============================================================

def audio_list_sessions_tool():
    return list_sessions()


def audio_get_session_volume_tool(app_name):
    return get_session_volume(app_name)


def audio_set_session_volume_tool(app_name, volume):
    return set_session_volume(app_name, volume)


def audio_set_session_mute_tool(app_name, muted):
    return set_session_mute(app_name, muted)


def audio_toggle_session_mute_tool(app_name):
    return toggle_session_mute(app_name)


def audio_list_outputs_tool():
    return list_output_devices()


def audio_get_default_output_tool():
    return get_default_output()


def audio_set_default_output_tool(device_name):
    return set_default_output(device_name)


# =============================================================
# Browser Reading tools (Fase 12)
# =============================================================

def browser_get_url_tool():
    return get_browser_url()


def browser_get_title_tool():
    return get_browser_title()


def browser_get_content_tool(max_items=50):
    return get_browser_content(max_items=max_items)


# =============================================================
# PC Status tool (Fase 12)
# =============================================================

def pc_status_tool():
    return get_pc_status()