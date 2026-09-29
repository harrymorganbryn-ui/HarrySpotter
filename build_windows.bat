@echo off
rem Build HarrySpotter for Windows. Double-click this file.
rem Result: dist\HarrySpotter\HarrySpotter.exe
setlocal
cd /d "%~dp0"

rem Double-clicking this inside a zip runs it alone from a temp folder, without the other files.
if not exist "HarrySpotter.py" goto :notextracted
if not exist "make_icon.py" goto :notextracted

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY goto :nopython

echo == Python:
%PY% --version || goto :nopython
%PY% -c "import tkinter" || goto :notk

echo.
echo == Installing build tools (PyInstaller, Pillow)...
%PY% -m pip install --upgrade pyinstaller pillow || goto :fail

echo.
echo == Making the Windows icon...
%PY% make_icon.py || goto :fail

echo.
echo == Building HarrySpotter.exe (takes a minute)...
%PY% -m PyInstaller --noconfirm HarrySpotter-windows.spec || goto :fail

if not exist input\mtz mkdir input\mtz
echo.
echo ==========================================================
echo  BUILD DONE:  dist\HarrySpotter\HarrySpotter.exe
echo ==========================================================
pause
exit /b 0

:notextracted
echo.
echo This looks like it was opened from inside a zip file.
echo Right-click the zip, choose "Extract All...", then run build_windows.bat
echo from the extracted HarrySpotter folder.
pause
exit /b 1

:nopython
echo.
echo Python was not found. Install Python 3.12 or newer from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH" in the installer), then double-click this file again.
pause
exit /b 1

:notk
echo.
echo This Python has no tkinter. Re-run the python.org installer, choose Modify, and tick "tcl/tk and IDLE".
pause
exit /b 1

:fail
echo.
echo BUILD FAILED - see the messages above.
pause
exit /b 1
