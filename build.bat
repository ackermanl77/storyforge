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
echo [1/7] Creando entorno limpio .build-venv ...
if exist .build-venv rmdir /s /q .build-venv
py -%STORYFORGE_PYVER% -m venv .build-venv
if errorlevel 1 goto :fail
set PY=.build-venv\Scripts\python.exe

echo.
echo [2/7] Instalando dependencias con versiones exactas...
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
echo [3/7] Descargando los datos de NLTK (stopwords, wordnet) para incluirlos...
%PY% -m nltk.downloader -d nltk_data stopwords wordnet
if errorlevel 1 goto :fail

echo.
echo [4/7] Pruebas con cobertura...
%PY% -m pytest --cov=app --cov-report=term-missing --cov-report=xml:coverage.xml -q
if errorlevel 1 goto :fail

echo.
echo [5/7] Empaquetando con PyInstaller...
%PY% -m PyInstaller --noconfirm --clean storyforge.spec
if errorlevel 1 goto :fail

echo.
echo [6/7] Compilando instalador de Inno Setup (opcional)...
REM Inno Setup 6: instalacion para todos, para el usuario actual o en el PATH.
REM Si no esta, se avisa y se sigue: StoryForge-App\ igual queda listo.
set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC for %%I in (ISCC.exe) do if not "%%~$PATH:I"=="" set "ISCC=%%~$PATH:I"
if not defined ISCC (
    echo AVISO: no se encontro Inno Setup 6 ^(ISCC.exe^); se omite el instalador.
    goto :copy_app
)
for /f %%V in ('%PY% -c "import app; print(app.__version__)"') do set APP_VERSION=%%V
"%ISCC%" /DAppVersion=%APP_VERSION% /DBuildVariant=%VARIANT% installer\StoryForge.iss
if errorlevel 1 goto :fail

:copy_app

echo.
echo [7/7] Copiando a StoryForge-App\ (carpeta fija y facil de ubicar)...
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

REM dist\installer\ conserva el .exe del instalador; solo se borra la copia
REM onedir ya espejada a StoryForge-App\.
rmdir /s /q dist\StoryForge 2>nul
rmdir /s /q build 2>nul

echo.
echo Listo. El programa quedo en: StoryForge-App\StoryForge.exe
if defined ISCC echo Instalador generado en: dist\installer\
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
