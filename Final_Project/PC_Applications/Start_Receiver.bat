@echo off
cd /d "%~dp0"
python "%~dp0Morse_IR_Receiver_Studio_FINAL.py"
if errorlevel 1 (
  echo.
  echo Check that Python is installed in this environment.
  pause
)
