"""
Punto de entrada de StoryForge Local.
"""
from __future__ import annotations

import sys


def main() -> None:
    from .gui import run
    run()


if __name__ == "__main__":
    sys.exit(main())
