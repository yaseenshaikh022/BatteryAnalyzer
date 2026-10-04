# Battery Analyzer

A Windows-first Python laptop battery diagnostics application.

## Features
- Live battery percentage and charging/discharging status
- Design capacity and full-charge capacity when Windows WMI exposes them
- Battery health and wear calculation
- Voltage, current and power when exposed by WMI
- Estimated runtime from Windows/psutil
- Live battery % and voltage charts
- CSV history logging
- Charge/discharge test sessions
- Export test/history data to Excel
- Automatic capability detection; unavailable telemetry is shown as N/A

## Install

Windows 10/11 + Python 3.10+ recommended.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Important hardware limitation
Battery telemetry is hardware/firmware dependent. Windows may expose capacity but not voltage/current/cycle count/temperature on a particular laptop. The application never invents missing values.

## Battery health
Health is calculated as:

Full Charge Capacity / Design Capacity × 100

Wear is:

100 - Health

This is an engineering estimate, not a replacement for an OEM battery diagnostic.

## Test behavior
A test records telemetry over time. The app does not force a laptop to discharge or charge. For a controlled discharge test, unplug AC and click Start Discharge Test. For a charge test, connect AC and click Start Charge Test.

Keep the laptop awake during tests for best results.
