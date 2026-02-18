import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from watchback.config import load_config, setup_logging
from watchback.gui import MainWindow

def load_stylesheet():
	stylesheet_path = Path(__file__).with_name("styles.qss")
	if not stylesheet_path.exists():
		return ""
	return stylesheet_path.read_text(encoding="utf-8")

def main():
	setup_logging()

	app = QApplication(sys.argv)
	app.setStyleSheet(load_stylesheet())

	config = load_config()
	window = MainWindow(config)
	window.show()
	sys.exit(app.exec())


if __name__ == "__main__":
	main()
