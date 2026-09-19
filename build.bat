@echo off
REM Empaqueta StoryForge Local como un ejecutable de Windows (.exe).
REM Debe correrse en Windows, con Python 3.10+ instalado.

setlocal

echo ============================================
echo  StoryForge Local - build de Windows (.exe)
echo ============================================

echo.
echo [1/3] Instalando dependencias de Python...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

echo.
echo [2/4] Empaquetando con PyInstaller...
pyinstaller --noconfirm --clean storyforge.spec

echo.
echo [3/4] Copiando a StoryForge-App\ (carpeta fija y facil de ubicar; dist\ es
echo carpeta de trabajo de PyInstaller, se regenera en cada build)...
if exist StoryForge-App rmdir /s /q StoryForge-App
xcopy /e /i /y dist\StoryForge StoryForge-App >nul

echo.
echo [4/4] Listo.
echo El programa quedo en: StoryForge-App\StoryForge.exe
echo Copia la carpeta "models" (con tu archivo .gguf adentro) junto al .exe
echo si no lo has hecho ya, o coloca el modelo en StoryForge-App\models\
echo.
pause
