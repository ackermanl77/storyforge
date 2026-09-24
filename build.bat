@echo off
REM Empaqueta StoryForge Local como un ejecutable de Windows (.exe).
REM Debe correrse en Windows, con Python 3.10+ instalado.

setlocal

echo ============================================
echo  StoryForge Local - build de Windows (.exe)
echo ============================================

echo.
echo [1/4] Instalando dependencias de Python...
python -m pip install --upgrade pip
if errorlevel 1 goto :fail
python -m pip install -r requirements.txt
if errorlevel 1 goto :fail
python -m pip install pyinstaller
if errorlevel 1 goto :fail

echo.
echo [2/4] Empaquetando con PyInstaller...
pyinstaller --noconfirm --clean storyforge.spec
if errorlevel 1 goto :fail

echo.
echo [3/4] Copiando a StoryForge-App\ (carpeta fija y facil de ubicar; dist\ es
echo carpeta de trabajo de PyInstaller, se regenera en cada build)...
REM Se borra todo lo del build anterior EXCEPTO StoryForge-App\models\: ahi es
REM donde se le dice al usuario que ponga sus modelos .gguf (varios GB), y
REM antes un "rmdir /s /q StoryForge-App" los borraba en cada build.
if exist StoryForge-App (
    for /d %%D in (StoryForge-App\*) do (
        if /i not "%%~nxD"=="models" rmdir /s /q "%%D"
    )
    del /q StoryForge-App\* 2>nul
)
REM rmdir/del no siempre fijan errorlevel si fallan: si el .exe viejo sigue
REM ahi, casi seguro es porque StoryForge esta abierto.
if exist StoryForge-App\StoryForge.exe (
    echo ERROR: no se pudo borrar el build anterior. Cierra StoryForge y vuelve a intentar.
    goto :fail
)
xcopy /e /i /y dist\StoryForge StoryForge-App >nul
if errorlevel 1 goto :fail

REM dist\ quedaria como una segunda copia completa de la app (~800 MB) y build\
REM es la carpeta de trabajo de PyInstaller (se regenera con --clean de todos
REM modos): se borran solo despues de copiar bien. Si algo falla antes, se
REM conservan para poder revisar el error.
rmdir /s /q dist 2>nul
rmdir /s /q build 2>nul

echo.
echo [4/4] Listo.
echo El programa quedo en: StoryForge-App\StoryForge.exe
echo Copia la carpeta "models" (con tu archivo .gguf adentro) junto al .exe
echo si no lo has hecho ya, o coloca el modelo en StoryForge-App\models\
echo (esa carpeta se conserva entre builds).
echo.
pause
exit /b 0

:fail
echo.
echo *** El build fallo (ver el error arriba). No se completo StoryForge-App\. ***
pause
exit /b 1
