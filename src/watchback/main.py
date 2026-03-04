import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from watchback.config import load_config, setup_logging
from watchback.gui import MainWindow


ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def load_stylesheet():
	stylesheet_path = ASSETS_DIR / "styles.qss"
	if not stylesheet_path.exists():
		return ""
	return stylesheet_path.read_text(encoding="utf-8")


def load_app_icon():
	icon = QIcon()
	if sys.platform.startswith("win"):
		windows_icon = ASSETS_DIR / "wbicon.ico"
		if windows_icon.exists():
			icon.addFile(str(windows_icon))

	linux_icon = ASSETS_DIR / "wbicon.png"
	if linux_icon.exists():
		icon.addFile(str(linux_icon))

	return icon


def main():
	setup_logging()

	app = QApplication(sys.argv)
	app.setStyleSheet(load_stylesheet())
	app_icon = load_app_icon()
	if not app_icon.isNull():
		app.setWindowIcon(app_icon)

	config = load_config()
	window = MainWindow(config)
	if not app_icon.isNull():
		window.setWindowIcon(app_icon)
	window.show()
	sys.exit(app.exec())


if __name__ == "__main__":
	main()
