@echo off
rem Symulacja GEM: tworzy srodowisko Pythona, pobiera dane ze stooq i otwiera raport.
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist run_gem.py goto :notextracted
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

:notextracted
echo Brakuje plikow projektu obok tego skryptu. Najpierw rozpakuj archiwum:
echo kliknij prawym przyciskiem na GEM-symulacja.zip, wybierz "Wyodrebnij wszystko",
echo a potem uruchom uruchom_windows.bat z rozpakowanego folderu.
pause
exit /b

:nopython
echo Nie znaleziono Pythona. Zainstaluj go z https://www.python.org/downloads/ (zaznacz "Add python.exe to PATH") i uruchom ten plik ponownie.
pause
