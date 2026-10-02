@echo off
REM Empaqueta StoryForge Local como un ejecutable de Windows (.exe).
REM Debe correrse en Windows, con el py launcher. Usa Python 3.14 (el que tiene
REM la PC); para otra version: set STORYFORGE_PYVER=3.12 antes de correrlo.
REM
REM K1: el build se hace en un entorno virtual propio y limpio (.build-venv),
REM con versiones exactas (requirements-build.txt), NO en el Python compartido
REM de la PC: antes se colaban IPython, jedi, datasets, torch... de otros
REM proyectos. El venv se recrea en cada build.
REM
REM Uso:  build.bat          -> variante CUDA 13 (GPU NVIDIA, por defecto)
REM       build.bat cpu      -> variante solo CPU

setlocal
set VARIANT=%1
if "%VARIANT%"=="" set VARIANT=cuda13
set LLAMA_CPP_VERSION=0.3.35
if not defined STORYFORGE_PYVER set STORYFORGE_PYVER=3.14
if /i "%VARIANT%"=="cpu" (
    set WHEEL_INDEX=https://abetlen.github.io/llama-cpp-python/whl/cpu
) else (
    set WHEEL_INDEX=https://abetlen.github.io/llama-cpp-python/whl/cu130
)

echo ============================================
echo  StoryForge Local - build de Windows (%VARIANT%)
echo ============================================

echo.
echo [1/6] Creando entorno limpio .build-venv ...
if exist .build-venv rmdir /s /q .build-venv
py -%STORYFORGE_PYVER% -m venv .build-venv
if errorlevel 1 goto :fail
set PY=.build-venv\Scripts\python.exe

echo.
echo [2/6] Instalando dependencias con versiones exactas...
%PY% -m pip install --upgrade pip
if errorlevel 1 goto :fail
%PY% -m pip install -r requirements-build.txt
if errorlevel 1 goto :fail
%PY% -m pip install --only-binary=:all: --no-deps --index-url %WHEEL_INDEX% llama-cpp-python==%LLAMA_CPP_VERSION%
if errorlevel 1 goto :fail
if /i not "%VARIANT%"=="cpu" (
    %PY% -m pip install -r requirements-cuda.txt
    if errorlevel 1 goto :fail
)

echo.
echo [3/6] Descargando los datos de NLTK (stopwords, wordnet) para incluirlos...
%PY% -m nltk.downloader -d nltk_data stopwords wordnet omw-1.4
if errorlevel 1 goto :fail

echo.
echo [4/6] Pruebas...
%PY% -m pytest -q
if errorlevel 1 goto :fail

echo.
echo [5/6] Empaquetando con PyInstaller...
%PY% -m PyInstaller --noconfirm --clean storyforge.spec
if errorlevel 1 goto :fail

echo.
echo [6/6] Copiando a StoryForge-App\ (carpeta fija y facil de ubicar)...
REM Se borra todo lo del build anterior EXCEPTO StoryForge-App\models\: ahi es
REM donde se le dice al usuario que ponga sus modelos .gguf (varios GB).
if exist StoryForge-App (
    for /d %%D in (StoryForge-App\*) do (
        if /i not "%%~nxD"=="models" rmdir /s /q "%%D"
    )
    del /q StoryForge-App\* 2>nul
)
if exist StoryForge-App\StoryForge.exe (
    echo ERROR: no se pudo borrar el build anterior. Cierra StoryForge y vuelve a intentar.
    goto :fail
)
xcopy /e /i /y dist\StoryForge StoryForge-App >nul
if errorlevel 1 goto :fail
if not exist StoryForge-App\models mkdir StoryForge-App\models
copy /y models\README.txt StoryForge-App\models\README.txt >nul

REM dist\ quedaria como una segunda copia completa de la app y build\ es la
REM carpeta de trabajo de PyInstaller: se borran solo despues de copiar bien.
rmdir /s /q dist 2>nul
rmdir /s /q build 2>nul

echo.
echo Listo. El programa quedo en: StoryForge-App\StoryForge.exe
echo Pon tu modelo .gguf en StoryForge-App\models\ (esa carpeta se conserva
echo entre builds), o mejor en una carpeta fuera de OneDrive configurada en
echo Archivo ^> Preferencias.
echo.
pause
exit /b 0

:fail
echo.
echo *** El build fallo (ver el error arriba). No se completo StoryForge-App\. ***
pause
exit /b 1
