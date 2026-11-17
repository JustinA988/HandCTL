"""PyInstaller entry point. handctl/__main__.py uses relative imports, so it can't be frozen as a script itself."""
from handctl.__main__ import main

main()
