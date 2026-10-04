from __future__ import annotations
import csv
import os
import platform
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import psutil

try:
    import wmi
except Exception:
    wmi = None


@dataclass
class BatterySnapshot:
    timestamp: str
    percent: float | None
    plugged: bool | None
    status: str
    seconds_left: int | None
    design_capacity_mwh: float | None
    full_charge_capacity_mwh: float | None
    remaining_capacity_mwh: float | None
    voltage_v: float | None
    current_a: float | None
    power_w: float | None
    cycle_count: int | None
    temperature_c: float | None

    @property
    def health(self):
        if self.design_capacity_mwh and self.full_charge_capacity_mwh:
            return max(0.0, min(100.0,
                self.full_charge_capacity_mwh / self.design_capacity_mwh * 100.0))
        return None

    @property
    def wear(self):
        h = self.health
        return 100.0 - h if h is not None else None


class BatteryMonitor:
    def __init__(self, history_file="data/battery_history.csv"):
        self.history_file = Path(history_file)
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        self._wmi = None
        self._last_report = None

        if platform.system() == "Windows" and wmi:
            try:
                self._wmi = wmi.WMI(namespace=r"root\cimv2")
            except Exception:
                self._wmi = None

    @staticmethod
    def _number(value):
        try:
            if value is None or str(value).strip() == "":
                return None
            return float(value)
        except Exception:
            return None

    def _powercfg_report(self):
        # Cache the report for 60 seconds; generating batteryreport every 2 seconds is unnecessary.
        import time
        if self._last_report and time.time() - self._last_report[0] < 60:
            return self._last_report[1]
        """
        Uses Microsoft's built-in batteryreport command.
        The report is generated as HTML. We parse the capacity table
        without requiring an internet connection.
        """
        if platform.system() != "Windows":
            return {}

        try:
            with tempfile.TemporaryDirectory() as td:
                out = Path(td) / "battery-report.html"
                cmd = ["powercfg", "/batteryreport", "/output", str(out)]
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
                if r.returncode != 0 or not out.exists():
                    return {}

                html = out.read_text(encoding="utf-8", errors="ignore")
                from html.parser import HTMLParser

                class Parser(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.in_td = False
                        self.in_th = False
                        self.cells = []
                        self.row = []

                    def handle_starttag(self, tag, attrs):
                        if tag == "td" or tag == "th":
                            self.in_td = True

                    def handle_endtag(self, tag):
                        if tag == "td" or tag == "th":
                            self.in_td = False
                        if tag == "tr":
                            if self.row:
                                self.cells.append(self.row)
                            self.row = []

                    def handle_data(self, data):
                        if self.in_td:
                            s = " ".join(data.split())
                            if s:
                                self.row.append(s)

                parser = Parser()
                parser.feed(html)

                design = None
                full = None
                cycles = None

                for row in parser.cells:
                    joined = " | ".join(row).lower()
                    if "design capacity" in joined:
                        nums = []
                        for x in row:
                            x = x.replace(",", "").replace("mWh", "").strip()
                            n = self._number(x)
                            if n is not None:
                                nums.append(n)
                        if nums:
                            design = nums[-1]

                    if "full charge capacity" in joined:
                        nums = []
                        for x in row:
                            x = x.replace(",", "").replace("mWh", "").strip()
                            n = self._number(x)
                            if n is not None:
                                nums.append(n)
                        if nums:
                            full = nums[-1]

                    if "cycle count" in joined:
                        nums = []
                        for x in row:
                            n = self._number(x.replace(",", ""))
                            if n is not None:
                                nums.append(n)
                        if nums:
                            cycles = int(nums[-1])

                result = {"design": design, "full": full, "cycle": cycles}
                self._last_report = (time.time(), result)
                return result
        except Exception:
            return {}

    def _wmi_values(self):
        result = {
            "design": None, "full": None, "remaining": None,
            "voltage": None, "current": None, "cycle": None,
            "temperature": None
        }

        if not self._wmi:
            return result

        # Standard Win32_Battery
        try:
            rows = self._wmi.Win32_Battery()
            if rows:
                b = rows[0]
                result["remaining"] = self._number(
                    getattr(b, "EstimatedChargeRemaining", None))

                # Win32_Battery DesignVoltage is millivolts.
                dv = self._number(getattr(b, "DesignVoltage", None))
                if dv:
                    result["voltage"] = dv / 1000.0
        except Exception:
            pass

        # Microsoft battery WMI classes where supported.
        try:
            rows = self._wmi.BatteryStaticData()
            if rows:
                b = rows[0]
                result["design"] = self._number(
                    getattr(b, "DesignedCapacity", None))
                result["full"] = self._number(
                    getattr(b, "FullChargeCapacity", None))
        except Exception:
            pass

        try:
            rows = self._wmi.BatteryStatus()
            if rows:
                b = rows[0]
                result["remaining"] = self._number(
                    getattr(b, "RemainingCapacity", None)) or result["remaining"]

                v = self._number(getattr(b, "Voltage", None))
                if v:
                    result["voltage"] = v / 1000.0 if v > 100 else v

                cur = self._number(getattr(b, "Current", None))
                if cur is not None:
                    # Common Windows ACPI class reports mA.
                    result["current"] = cur / 1000.0
        except Exception:
            pass

        try:
            rows = self._wmi.BatteryCycleCount()
            if rows:
                result["cycle"] = self._number(
                    getattr(rows[0], "CycleCount", None))
        except Exception:
            pass

        return result

    def snapshot(self):
        p = psutil.sensors_battery()
        w = self._wmi_values()
        report = self._powercfg_report()

        # Prefer batteryreport for design/full capacity.
        design = report.get("design") or w.get("design")
        full = report.get("full") or w.get("full")
        cycle = report.get("cycle") or w.get("cycle")

        if p is None:
            return BatterySnapshot(
                datetime.now().isoformat(timespec="seconds"),
                None, None, "Battery unavailable", None,
                design, full, w["remaining"], w["voltage"],
                w["current"], None,
                int(cycle) if cycle is not None else None,
                w["temperature"])

        if p.power_plugged:
            status = "Charging" if p.percent < 99.5 else "Fully Charged"
        else:
            status = "Discharging"

        # If WMI doesn't give a live remaining capacity, estimate from
        # percentage and full-charge capacity.
        remaining = w["remaining"]
        if remaining is None and full is not None and p.percent is not None:
            remaining = full * p.percent / 100.0

        power = None
        if w["voltage"] is not None and w["current"] is not None:
            power = abs(w["voltage"] * w["current"])

        return BatterySnapshot(
            datetime.now().isoformat(timespec="seconds"),
            float(p.percent),
            bool(p.power_plugged),
            status,
            int(p.secsleft) if isinstance(p.secsleft, int) and p.secsleft >= 0 else None,
            design, full, remaining,
            w["voltage"], w["current"], power,
            int(cycle) if cycle is not None else None,
            w["temperature"])

    def log(self, s):
        new = not self.history_file.exists()
        with self.history_file.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(asdict(s).keys()))
            if new:
                writer.writeheader()
            writer.writerow(asdict(s))

    @staticmethod
    def fmt_time(seconds):
        if seconds is None:
            return "N/A"
        h, rem = divmod(seconds, 3600)
        m = rem // 60
        return f"{h}h {m:02d}m" if h else f"{m}m"

    def capabilities(self):
        s = self.snapshot()
        return {
            "Capacity": s.design_capacity_mwh is not None and s.full_charge_capacity_mwh is not None,
            "Voltage": s.voltage_v is not None,
            "Current": s.current_a is not None,
            "Power": s.power_w is not None,
            "Cycle Count": s.cycle_count is not None,
            "Temperature": s.temperature_c is not None,
        }
