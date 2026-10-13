"""Eén betrouwbare functie voor de bekende Windows-mappen.

get_known_folder() vraagt eerst de Windows Known-Folders-API op via
pywin32 (win32com.shell). Ontbreekt pywin32, dan volgt een ctypes-variant
met een correcte GUID-structuur, argtypes/restype en CoTaskMemFree.
Lukt een map niet (of draait het niet op Windows), dan valt hij terug op
de klassieke ~/Naam. Elk resultaat wordt gecached voor de duur van het
proces en er wordt per map maar één waarschuwing getoond.
"""
import ctypes
import os
import threading
import uuid

KNOWN_FOLDERS = {
    "Desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "Documents": "FDD39AD0-2385-4680-8777-B158B9311394",
    "Downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "Pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "Music": "4BD8D571-6D19-48D3-BE97-422220080E43",
    "Videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
}

# Naam van de pywin32-constante (shellcon.FOLDERID_*) per bekende map.
_FOLDER_ID_NAMES = {
    "Desktop": "FOLDERID_Desktop",
    "Documents": "FOLDERID_Documents",
    "Downloads": "FOLDERID_Downloads",
    "Pictures": "FOLDERID_Pictures",
    "Music": "FOLDERID_Music",
    "Videos": "FOLDERID_Videos",
}

_cache = {}
_warned = set()
_lock = threading.Lock()

_EXPECTED_ERRORS = (ImportError, AttributeError, KeyError, OSError, ValueError)
try:
    from pywintypes import error as _pywin32_pywintypes_error
    _EXPECTED_ERRORS += (_pywin32_pywintypes_error,)
except ImportError:
    pass


class _GUID(ctypes.Structure):
    """Windows GUID: Data1/2/3 little-endian + 8 ruwe bytes (Data4)."""

    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid_bytes(name):
    """De 16 bytes in Windows-geheugenindeling (little-endian) van een GUID."""
    return uuid.UUID(KNOWN_FOLDERS[name]).bytes_le


def _guid_struct(name):
    """c_ubyte-velden van een GUID-structuur invullen vanuit bytes_le."""
    guid = _GUID()
    ctypes.memmove(ctypes.byref(guid), _guid_bytes(name), ctypes.sizeof(guid))
    return guid


def _pywin32_path(name):
    """Leest de map via pywin32 (win32com.shell)."""
    from win32com.shell import shell, shellcon

    folder_id = getattr(shellcon, _FOLDER_ID_NAMES[name])
    return shell.SHGetKnownFolderPath(folder_id, 0, 0)


def _windll():
    import ctypes
    return ctypes.windll


def _resolve_via_ctypes(name):
    """Leest de map via ctypes: correcte GUID + argtypes + CoTaskMemFree."""
    windll = _windll()
    shell32 = windll.shell32
    ole32 = windll.ole32

    shell32.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree.restype = None

    path_buf = ctypes.c_wchar_p()
    hr = shell32.SHGetKnownFolderPath(
        ctypes.byref(_guid_struct(name)), 0, None, ctypes.byref(path_buf)
    )

    if hr != 0:
        raise OSError(f"SHGetKnownFolderPath voor '{name}' gaf HRESULT {hr}")

    try:
        return path_buf.value
    finally:
        if path_buf.value:
            pointer = ctypes.cast(path_buf, ctypes.c_void_p)
            ole32.CoTaskMemFree(pointer)


def _fallback(name):
    return os.path.expanduser(f"~/{name}")


def _warn_eens(name):
    with _lock:
        if name in _warned:
            return
        _warned.add(name)
    print(f"⚠️ Kon Windows-map '{name}' niet ophalen; ik gebruik de standaardmap.")


def get_known_folder(name):
    """Geeft het echte pad van een bekende map (Desktop, Documenten, enz.).

    Volgorde: pywin32 -> ctypes-authentbinding -> ~/Naam. Cachet het
    resultaat per map voor de duur van het proces.
    """

    if name not in KNOWN_FOLDERS:
        return _fallback(name)

    with _lock:
        if name in _cache:
            return _cache[name]

    path = None
    try:
        path = _pywin32_path(name)
    except _EXPECTED_ERRORS:
        try:
            path = _resolve_via_ctypes(name)
        except _EXPECTED_ERRORS:
            path = None

    if not path:
        path = _fallback(name)
        _warn_eens(name)

    with _lock:
        _cache.setdefault(name, path)

    return path