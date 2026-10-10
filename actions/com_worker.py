# COM Worker - executes COM/UIA calls on a single dedicated thread
import threading
import time
import queue

try:
    import pythoncom
except Exception:
    pythoncom = None

_COM_QUEUE = queue.Queue()
_COM_THREAD = None
_COM_STOP = threading.Event()


def _com_thread_main():
    if pythoncom is not None:
        try:
            pythoncom.CoInitialize()
        except Exception:
            pass
    try:
        while not _COM_STOP.is_set():
            try:
                item = _COM_QUEUE.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            fn, args, kwargs, result_q, error_q = item
            try:
                res = fn(*args, **kwargs)
                try:
                    result_q.put(res)
                except Exception:
                    pass
            except Exception as e:
                try:
                    error_q.put(e)
                except Exception:
                    pass
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
    if _COM_THREAD is None or not _COM_THREAD.is_alive():
        _COM_THREAD = threading.Thread(target=_com_thread_main, daemon=True)
        _COM_THREAD.start()


def run_on_com_thread(fn, *args, timeout=10, **kwargs):
    _ensure_com_thread()
    result_q = queue.Queue()
    error_q = queue.Queue()
    _COM_QUEUE.put((fn, args, kwargs, result_q, error_q))
    try:
        # wait for result
        try:
            res = result_q.get(timeout=timeout)
            return res
        except queue.Empty:
            # timeout - try to get error if any
            try:
                err = error_q.get(timeout=0)
                raise err
            except Exception:
                raise TimeoutError('COM call timed out')
    except Exception:
        raise


def shutdown_com_thread():
    _COM_STOP.set()
    try:
        _COM_QUEUE.put(None, timeout=0.1)
    except Exception:
        pass
    if _COM_THREAD is not None:
        _COM_THREAD.join(timeout=1)
