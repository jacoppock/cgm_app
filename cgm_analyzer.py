import sys

from PyQt5.QtWidgets import QApplication

from ui import CGMAnalyzer

if __name__ == "__main__":
    app = QApplication(sys.argv)
    analyzer = CGMAnalyzer()
    analyzer.show()
    sys.exit(app.exec_())
