"""COM Worker - voert COM/UIA-aanroepen uit op één eigen thread.

Elke taak krijgt een eigen concurrent.futures.Future. Het resultaat of de
originele exception komt direct terug: een mislukte COM-aanroep hoeft dus
niet te wachten tot de volledige timeout voorbij is. Bij een timeout volgt
een duidelijke TimeoutError en wordt de taak geannuleerd, zodat de worker
hem overslaat als hij er later aan toe komt.
"""
import atexit
import concurrent.futures
import queue
import threading

try:
    import pythoncom
except Exception:
    pythoncom = None

_COM_QUEUE = queue.Queue()
_COM_THREAD = None
_COM_START_LOCK = threading.Lock()
_COM_STOP = threading.Event()


class _ComTask:

    """Eén taak voor de COM-worker: functie + eigen Future + annuleer-vlag."""

    __slots__ = ("fn", "args", "kwargs", "future", "lock", "cancelled")

    def __init__(self, fn, args, kwargs):
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.future = concurrent.futures.Future()
        self.lock = threading.Lock()
        self.cancelled = False


def _com_thread_main():
    if pythoncom is not None:
        try:
            pythoncom.CoInitialize()
        except Exception:
            pass
    try:
        while not _COM_STOP.is_set():
            try:
                task = _COM_QUEUE.get(timeout=0.5)
            except queue.Empty:
                continue
            if task is None:
                break

            try:
                # Geannuleerde taken (timeout aan de aanroepende kant)
                # worden overgeslagen als ze nog niet begonnen zijn.
                with task.lock:
                    if task.cancelled:
                        task.future.cancel()
                        continue

                try:
                    result = task.fn(*task.args, **task.kwargs)
                except BaseException as error:
                    if not task.future.done():
                        task.future.set_exception(error)
                else:
                    if not task.future.done():
                        task.future.set_result(result)
            finally:
                _COM_QUEUE.task_done()
    finally:
        if pythoncom is not None:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


def _ensure_com_thread():
    global _COM_THREAD
    with _COM_START_LOCK:
        if _COM_THREAD is None or not _COM_THREAD.is_alive():
            _COM_STOP.clear()
            _COM_THREAD = threading.Thread(target=_com_thread_main, daemon=True)
            _COM_THREAD.start()
    return _COM_THREAD


def run_on_com_thread(fn, *args, timeout=10, **kwargs):
    """Voer fn(*args, **kwargs) uit op de COM-thread.

    Geeft het resultaat terug, of werpt de originele exception op (zelfde
    type en bericht). Bij een timeout volgt een TimeoutError (met
    Nederlandstalige melding) en wordt de taak geannuleerd.
    """
    _ensure_com_thread()
    task = _ComTask(fn, args, kwargs)
    _COM_QUEUE.put(task)

    try:
        return task.future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        if task.future.done():
            # De taak zelf wierp een TimeoutError: geef die ongewijzigd door.
            raise
        with task.lock:
            task.cancelled = True
        task.future.cancel()
        raise TimeoutError(
            f"COM-aanroep duurde langer dan {timeout} seconden en is geannuleerd."
        ) from None


def shutdown_com_thread():
    _COM_STOP.set()
    thread = _COM_THREAD
    # Alleen een sentinel sturen als de thread nog leeft; anders blijft die
    # in de queue staan en blokkeert hij een latere herstart.
    if thread is not None and thread.is_alive():
        try:
            _COM_QUEUE.put(None, timeout=0.1)
        except Exception:
            pass
        thread.join(timeout=1)


atexit.register(shutdown_com_thread)