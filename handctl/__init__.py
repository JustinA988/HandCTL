"""Control your PC with hand gestures from a webcam."""
import concurrent.futures

# shortcut: on Python 3.15, importing PySide6 6.12 leaves this lazy attribute unresolvable, which breaks
# MediaPipe; resolving it before Qt loads avoids that. Remove once PySide6 handles 3.15 lazy imports.
concurrent.futures.ThreadPoolExecutor
