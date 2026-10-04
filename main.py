import sys
from PySide6.QtWidgets import QApplication
from ui.dashboard import BatteryDashboard

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Battery Analyzer")
    window = BatteryDashboard()
    window.show()
    sys.exit(app.exec())
