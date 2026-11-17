@echo off
cd /d "%~dp0"
python "%~dp0Morse_IR_Transmitter_Studio_FINAL.py"
if errorlevel 1 (
  echo.
  echo Check that Python and pyserial are installed in this environment.
  pause
)
