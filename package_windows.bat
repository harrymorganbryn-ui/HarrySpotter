@echo off
rem Make HarrySpotter-3.1-Windows.zip to share. Run build_windows.bat first.
setlocal
cd /d "%~dp0"

if not exist "dist\HarrySpotter\HarrySpotter.exe" (
    echo dist\HarrySpotter\HarrySpotter.exe not found - run build_windows.bat first.
    pause
    exit /b 1
)

set "STAGE=package\HarrySpotter-3.1"
if exist package rmdir /s /q package
mkdir "%STAGE%" || goto :fail

echo == Copying the app...
xcopy /e /i /q "dist\HarrySpotter" "%STAGE%" >nul || goto :fail
copy /y README_FIRST.txt "%STAGE%\" >nul || goto :fail
rem Only the app goes in the zip - no input data, results or settings.

echo == Zipping...
if exist HarrySpotter-3.1-Windows.zip del HarrySpotter-3.1-Windows.zip
powershell -NoProfile -Command "Compress-Archive -Path 'package\HarrySpotter-3.1' -DestinationPath 'HarrySpotter-3.1-Windows.zip'" || goto :fail
rmdir /s /q package

echo.
echo ==========================================================
echo  READY TO SHARE:  HarrySpotter-3.1-Windows.zip
echo ==========================================================
pause
exit /b 0

:fail
echo PACKAGING FAILED - see the messages above.
pause
exit /b 1
