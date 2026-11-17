"""Control your PC with hand gestures from a webcam."""
import sys

if hasattr(sys, "set_lazy_imports_filter"):  # Python 3.15+
    # PySide6 replaces builtins.__import__, after which Python 3.15's lazy imports never resolve when reached from
    # another module, and MediaPipe then fails on concurrent.futures.ThreadPoolExecutor. So: make every import from
    # here on eager, and repair the standard library's only lazily exported public names in case something imported
    # concurrent.futures before this ran (a frozen build loads Qt first). Remove once PySide6 handles lazy imports.
    sys.set_lazy_imports_filter(lambda *args: False)
    import concurrent.futures
    from concurrent.futures.process import ProcessPoolExecutor
    from concurrent.futures.thread import ThreadPoolExecutor

    concurrent.futures.ProcessPoolExecutor, concurrent.futures.ThreadPoolExecutor = ProcessPoolExecutor, ThreadPoolExecutor
