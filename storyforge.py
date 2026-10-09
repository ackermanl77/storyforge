"""
Script de arranque de StoryForge Local (punto de entrada para PyInstaller).
Ejecutar con: python storyforge.py
"""
import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
