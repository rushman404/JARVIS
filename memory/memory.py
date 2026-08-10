import json
import os


MEMORY_FILE = os.path.join(
    os.path.dirname(__file__),
    "memory.json"
)


def load_memory():

    if not os.path.exists(MEMORY_FILE):
        return {}

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as file:
            return json.load(file)

    except (json.JSONDecodeError, OSError):
        return {}


def save_memory(memory):

    with open(MEMORY_FILE, "w", encoding="utf-8") as file:
        json.dump(
            memory,
            file,
            indent=4,
            ensure_ascii=False
        )


def remember(key, value):

    memory = load_memory()

    memory[key] = value

    save_memory(memory)

    return True


def recall(key):

    memory = load_memory()

    return memory.get(key)


def forget(key):

    memory = load_memory()

    if key in memory:
        del memory[key]
        save_memory(memory)
        return True

    return False