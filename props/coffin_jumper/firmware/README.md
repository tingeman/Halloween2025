# Coffin Jumper - Firmware (tiny README)

This folder contains a small MicroPython demo firmware for an ESP32 (OLED +
MQTT helpers). It includes a small CPython-only helper test harness so you can
run quick checks on your desktop before deploying to a device.

## Quick: run CPython helper checks

The module contains lightweight checks that run only on CPython (not on the
device). They validate pure helper functions like `wrap`, `draw_center` and
`publish` serialization.

1. Open a terminal and change to this directory:

   ```powershell
   cd c:\thin\02_Code\docker_projects\Halloween_2025\props\coffin_jumper\firmware
   ```

2. Run the module with your system Python:

   ```powershell
   python .\main.py
   ```

If successful you should see:

```
Running helper checks (host CPython)...
All helper checks passed.
```

These checks are intentionally small and do not require hardware.

## Deploy to MicroPython (ESP32)

Recommended: use `mpremote` (actively maintained). Alternatives: `ampy`,
`rshell`, or the Thonny IDE.

1. Create a `secrets.py` next to `main.py` with your Wi‑Fi and MQTT settings. Example:

```python
# secrets.py (example)
WIFI_SSID = "MySSID"
WIFI_PASSWORD = "MyPassword"

MQTT_HOST = "192.168.1.10"
MQTT_PORT = 1883
MQTT_USER = "device"
MQTT_PASS = "devicepass"
CLIENT_ID = "coffin_jumper_01"
```

2. Copy files and run on the device (Windows PowerShell examples):

   Using mpremote (recommended):

   ```powershell
   # copy files to device (cp form) and run
   python -m mpremote connect COM3 cp main.py :main.py
   python -m mpremote connect COM3 cp secrets.py :secrets.py

   # run main.py (executes on the device)
   python -m mpremote connect COM3 run main.py
   ```

   Using ampy (alternative):

   ```powershell
   ampy --port COM3 put main.py
   ampy --port COM3 put secrets.py
   # then use a serial REPL to run main.py or set it as boot.py
   ```

3. Monitor serial output (use your terminal emulator or `mpremote repl`):

   ```powershell
   mpremote connect COM3 repl
   ```

   ### Useful Windows tips

   - Find the device COM port (PowerShell):

      ```powershell
      # List COM ports
      [System.IO.Ports.SerialPort]::getportnames()
      # Or look in Device Manager > Ports (COM & LPT)
      ```

   - Copy a file to the device using the `cp` command form (writes to remote root):

      ```powershell
      # copy local main.py to device as /main.py
      python -m mpremote connect COM8 cp main.py :main.py
      ```

   - Remove a file from the device:

      ```powershell
      python -m mpremote connect COM8 fs rm main.py
      # fallback via REPL if fs rm fails:
      python -m mpremote connect COM8 repl
      # then in REPL: >>> import os; os.remove('main.py')
      ```

   - Start a serial monitor in a separate terminal to watch prints or errors:

      ```powershell
      python -m mpremote connect COM8 repl
      ```

   - Run the code without writing to flash (executes in RAM):

      ```powershell
      python -m mpremote connect COM8 run main.py
      ```

Notes
- The code uses `ssd1306` and `umqtt.simple` on-device; if these are missing
  the firmware uses `mip` to install optional packages at runtime — ensure your
  device has network access during the first boot if you rely on `mip`.
- The CPython helper checks are safe to run on your desktop and will not
  execute device-specific code.

If you want, I can add a `deploy.sh`/`deploy.ps1` helper script that runs the
mpremote/ampy commands for you.
