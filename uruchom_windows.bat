@echo off
rem Symulacja GEM: tworzy srodowisko Pythona, pobiera dane ze stooq i otwiera raport.
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py) || (set PY=python)
if not exist .venv (
  echo Tworze srodowisko Pythona...
  %PY% -m venv .venv || goto :nopython
)
call .venv\Scripts\activate.bat
python -m pip install -q --disable-pip-version-check -r requirements.txt
python run_gem.py %*
if exist reports\gem_raport.html start "" reports\gem_raport.html
pause
exit /b

:nopython
echo Nie znaleziono Pythona. Zainstaluj go z https://www.python.org/downloads/ (zaznacz "Add python.exe to PATH") i uruchom ten plik ponownie.
pause
