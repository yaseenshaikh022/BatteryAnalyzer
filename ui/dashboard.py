from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime

import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QProgressBar, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QFileDialog
)

from battery.monitor import BatteryMonitor


APP_STYLE = """
QMainWindow, QWidget { background: #101318; color: #e8edf2; }
QFrame.card { background: #181d24; border: 1px solid #29313a; border-radius: 14px; }
QLabel.title { color: #94a3b8; font-size: 12px; font-weight: 600; }
QLabel.value { color: #f8fafc; font-size: 23px; font-weight: 700; }
QLabel.big { color: #f8fafc; font-size: 42px; font-weight: 800; }
QPushButton {
    background: #27313b; color: white; border: 0; border-radius: 9px;
    padding: 10px 14px; font-weight: 600;
}
QPushButton:hover { background: #34414d; }
QPushButton:disabled { color: #64748b; }
QProgressBar { background: #252c34; border: 0; border-radius: 8px; height: 16px; }
QProgressBar::chunk { background: #55d187; border-radius: 8px; }
QTabBar::tab { background: #181d24; padding: 11px 18px; margin-right: 2px; }
QTabBar::tab:selected { background: #27313b; }
QTableWidget { background: #151a20; gridline-color: #29313a; }
"""

class MetricCard(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setProperty("class", "card")
        lay = QVBoxLayout(self)
        self.title = QLabel(title)
        self.title.setProperty("class", "title")
        self.value = QLabel("N/A")
        self.value.setProperty("class", "value")
        lay.addWidget(self.title)
        lay.addWidget(self.value)
        lay.addStretch()

    def set_value(self, value):
        self.value.setText(str(value))


class BatteryDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Battery Analyzer")
        self.resize(1180, 780)
        self.setStyleSheet(APP_STYLE)
        self.monitor = BatteryMonitor()
        self.history_x = []
        self.history_percent = []
        self.history_voltage = []
        self.test_active = False
        self.test_mode = None
        self.test_start = None
        self.test_start_percent = None
        self._build_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_data)
        self.timer.start(2000)
        self.update_data()

    def card(self, title):
        return MetricCard(title)

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)

        header = QHBoxLayout()
        title = QLabel("Battery Analyzer")
        title.setFont(QFont("Segoe UI", 25, QFont.Weight.Bold))
        header.addWidget(title)
        header.addStretch()
        self.status_label = QLabel("Detecting battery…")
        self.status_label.setStyleSheet("font-weight:700;")
        header.addWidget(self.status_label)
        root.addLayout(header)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        dashboard = QWidget()
        grid = QGridLayout(dashboard)

        self.percent_card = self.card("BATTERY LEVEL")
        self.health_card = self.card("BATTERY HEALTH")
        self.voltage_card = self.card("VOLTAGE")
        self.power_card = self.card("POWER")
        self.capacity_card = self.card("FULL CHARGE CAPACITY")
        self.design_card = self.card("DESIGN CAPACITY")
        self.runtime_card = self.card("ESTIMATED RUNTIME")
        self.cycles_card = self.card("CYCLE COUNT")

        cards = [self.percent_card, self.health_card, self.voltage_card, self.power_card,
                 self.capacity_card, self.design_card, self.runtime_card, self.cycles_card]
        for i, c in enumerate(cards):
            grid.addWidget(c, i // 4, i % 4)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        grid.addWidget(self.progress, 2, 0, 1, 4)

        self.info = QLabel("Telemetry: detecting Windows battery capabilities…")
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color:#94a3b8; padding:8px;")
        grid.addWidget(self.info, 3, 0, 1, 4)

        graph = pg.PlotWidget()
        graph.setBackground("#12161c")
        graph.showGrid(x=True, y=True, alpha=0.18)
        graph.setLabel("left", "Battery %")
        graph.setLabel("bottom", "Samples")
        self.battery_curve = graph.plot(pen=pg.mkPen(width=2))
        self.graph = graph
        grid.addWidget(graph, 4, 0, 1, 4)

        controls = QHBoxLayout()
        self.discharge_btn = QPushButton("Start Discharge Test")
        self.charge_btn = QPushButton("Start Charge Test")
        self.stop_btn = QPushButton("Stop Test")
        self.stop_btn.setEnabled(False)
        self.export_btn = QPushButton("Export History")
        self.discharge_btn.clicked.connect(lambda: self.start_test("Discharge"))
        self.charge_btn.clicked.connect(lambda: self.start_test("Charge"))
        self.stop_btn.clicked.connect(self.stop_test)
        self.export_btn.clicked.connect(self.export_history)
        for b in (self.discharge_btn, self.charge_btn, self.stop_btn, self.export_btn):
            controls.addWidget(b)
        controls.addStretch()
        grid.addLayout(controls, 5, 0, 1, 4)
        self.tabs.addTab(dashboard, "Dashboard")

        details = QWidget()
        d = QVBoxLayout(details)
        self.details_table = QTableWidget(0, 2)
        self.details_table.setHorizontalHeaderLabels(["Parameter", "Value"])
        self.details_table.horizontalHeader().setStretchLastSection(True)
        d.addWidget(self.details_table)
        self.tabs.addTab(details, "Diagnostics")

        tests = QWidget()
        t = QVBoxLayout(tests)
        self.test_label = QLabel("No test running")
        self.test_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        t.addWidget(self.test_label)
        self.test_log = QTableWidget(0, 5)
        self.test_log.setHorizontalHeaderLabels(["Time", "Mode", "Battery", "Voltage", "Power"])
        t.addWidget(self.test_log)
        self.tabs.addTab(tests, "Test Log")

        self.setCentralWidget(central)

    def update_data(self):
        s = self.monitor.snapshot()
        if s.percent is None:
            self.status_label.setText("No battery detected")
            return

        self.status_label.setText(f"{s.status}  •  {s.percent:.0f}%")
        self.percent_card.set_value(f"{s.percent:.1f}%")
        health_display = f"{s.health:.1f}%" if s.health is not None else "N/A"
        self.health_card.set_value(health_display)
        self.voltage_card.set_value(f"{s.voltage_v:.2f} V" if s.voltage_v is not None else "N/A")
        self.power_card.set_value(f"{s.power_w:.2f} W" if s.power_w is not None else "N/A")
        self.capacity_card.set_value(self.fmt_mwh(s.full_charge_capacity_mwh))
        self.design_card.set_value(self.fmt_mwh(s.design_capacity_mwh))
        self.runtime_card.set_value(self.monitor.fmt_time(s.seconds_left))
        self.cycles_card.set_value(str(s.cycle_count) if s.cycle_count is not None else "N/A")
        self.progress.setValue(round(s.percent))

        wear = f"{s.wear:.1f}% wear" if s.wear is not None else "wear N/A"
        health_text = f"{s.health:.1f}%" if s.health is not None else "N/A"
        current_text = f"{s.current_a:.2f} A" if s.current_a is not None else "N/A"
        self.info.setText(
            f"Status: {s.status} | Battery health: {health_text} "
            f"({wear}) | Current: {current_text}"
        )

        now = datetime.now().strftime("%H:%M:%S")
        self.history_x.append(len(self.history_x))
        self.history_percent.append(s.percent)
        self.history_voltage.append(s.voltage_v if s.voltage_v is not None else 0)
        self.history_x = self.history_x[-300:]
        self.history_percent = self.history_percent[-300:]
        self.history_voltage = self.history_voltage[-300:]
        self.battery_curve.setData(self.history_x, self.history_percent)
        self.monitor.log(s)

        self._fill_details(s)
        if self.test_active:
            self._append_test_row(s, now)

    @staticmethod
    def fmt_mwh(v):
        if v is None:
            return "N/A"
        return f"{v/1000:.2f} Wh"

    def _fill_details(self, s):
        rows = [
            ("Timestamp", s.timestamp),
            ("Status", s.status),
            ("Battery level", f"{s.percent:.1f}%" if s.percent is not None else "N/A"),
            ("Design capacity", self.fmt_mwh(s.design_capacity_mwh)),
            ("Full-charge capacity", self.fmt_mwh(s.full_charge_capacity_mwh)),
            ("Remaining capacity", self.fmt_mwh(s.remaining_capacity_mwh)),
            ("Health", f"{s.health:.1f}%" if s.health is not None else "N/A"),
            ("Wear", f"{s.wear:.1f}%" if s.wear is not None else "N/A"),
            ("Voltage", f"{s.voltage_v:.3f} V" if s.voltage_v is not None else "N/A"),
            ("Current", f"{s.current_a:.3f} A" if s.current_a is not None else "N/A"),
            ("Power", f"{s.power_w:.3f} W" if s.power_w is not None else "N/A"),
            ("Cycle count", s.cycle_count if s.cycle_count is not None else "N/A"),
            ("Temperature", f"{s.temperature_c:.1f} °C" if s.temperature_c is not None else "N/A"),
            ("Runtime", self.monitor.fmt_time(s.seconds_left)),
        ]
        self.details_table.setRowCount(len(rows))
        for r, (a, b) in enumerate(rows):
            self.details_table.setItem(r, 0, QTableWidgetItem(str(a)))
            self.details_table.setItem(r, 1, QTableWidgetItem(str(b)))

    def start_test(self, mode):
        self.test_active = True
        self.test_mode = mode
        self.test_start = datetime.now()
        s = self.monitor.snapshot()
        self.test_start_percent = s.percent
        self.test_log.setRowCount(0)
        self.test_label.setText(
            f"{mode} test running • started {self.test_start.strftime('%H:%M:%S')} "
            f"at {s.percent:.1f}%"
        )
        self.stop_btn.setEnabled(True)
        self.discharge_btn.setEnabled(False)
        self.charge_btn.setEnabled(False)

    def _append_test_row(self, s, now):
        r = self.test_log.rowCount()
        self.test_log.insertRow(r)
        vals = [
            now, self.test_mode,
            f"{s.percent:.1f}%" if s.percent is not None else "N/A",
            f"{s.voltage_v:.2f} V" if s.voltage_v is not None else "N/A",
            f"{s.power_w:.2f} W" if s.power_w is not None else "N/A"
        ]
        for c, v in enumerate(vals):
            self.test_log.setItem(r, c, QTableWidgetItem(v))

    def stop_test(self):
        s = self.monitor.snapshot()
        elapsed = datetime.now() - self.test_start
        delta = (s.percent - self.test_start_percent) if s.percent is not None else None
        self.test_active = False
        self.stop_btn.setEnabled(False)
        self.discharge_btn.setEnabled(True)
        self.charge_btn.setEnabled(True)
        result = f"{self.test_mode} test stopped. Duration: {str(elapsed).split('.')[0]}."
        if delta is not None:
            result += f" Battery change: {delta:+.1f}%."
        self.test_label.setText(result)

    def export_history(self):
        source = Path("data/battery_history.csv")
        if not source.exists():
            QMessageBox.information(self, "No history", "No battery history has been recorded yet.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Battery History", "battery_history.xlsx",
            "Excel Workbook (*.xlsx);;CSV (*.csv)"
        )
        if not filename:
            return
        try:
            if filename.lower().endswith(".csv"):
                Path(filename).write_bytes(source.read_bytes())
            else:
                df = pd.read_csv(source)
                df.to_excel(filename, index=False)
            QMessageBox.information(self, "Export complete", f"Saved:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))
