@echo off

:: Check if the COM port argument is provided
if "%1"=="" (
    echo Usage: %0 COM_PORT
    echo Example: %0 COM12
    exit /b 1
)

set COM_PORT=%1

:: Loop through all .py files in the current directory
for %%F in (*.py) do (
    echo Processing file: %%F

    :: Remove the file from the ESP32 if it exists
    python -m mpremote connect %COM_PORT% fs rm %%F 2>nul

    :: Copy the file to the ESP32
    python -m mpremote connect %COM_PORT% fs cp %%F :
)

echo All .py files have been copied to the ESP32.