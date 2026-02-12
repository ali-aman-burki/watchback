import sys
from PySide6.QtWidgets import QApplication
from watchback.config import load_config
from watchback.gui import MainWindow

DARK_STYLE = """
QWidget {
    background-color: #1e1e1e;
    color: #dddddd;
    font-size: 13px;
}

QGroupBox {
    background-color: #2b2b2b;
    border: 1px solid #3c3c3c;
    border-radius: 8px;
    margin-top: 10px;
    padding: 10px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 3px 0 3px;
}

QPushButton {
    background-color: #3a3a3a;
    border: 1px solid #555555;
    border-radius: 6px;
    padding: 6px 12px;
}

QPushButton:hover {
    background-color: #4a4a4a;
}

QPushButton:pressed {
    background-color: #2a2a2a;
}

QLineEdit, QListWidget {
    background-color: #2b2b2b;
    border: 1px solid #444444;
    border-radius: 6px;
    padding: 4px;
}
"""


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)

    config = load_config()
    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
