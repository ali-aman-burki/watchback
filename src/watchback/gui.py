import logging
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
	QWidget, QVBoxLayout, QPushButton, QLabel, QGroupBox,
	QDialog, QLineEdit, QListWidget, QListWidgetItem,
	QFileDialog, QHBoxLayout, QMessageBox,
	QScrollArea, QFrame, QSizePolicy, QToolButton
)
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices

from watchback.sync import ProfileSync
from watchback.config import save_config, LOG_PATH
from watchback.restore import MirrorService
from watchback.restore_gui import (
	FileVersionDialog,
	SnapshotExplorerDialog,
	CurrentExplorerDialog,
)

logger = logging.getLogger("watchback")

SNAPSHOT_LABEL_INTERVAL = 60000
HOME_DIR = str(Path.home())

class AddProfileDialog(QDialog):
	def __init__(self, parent=None, profile=None):
		super().__init__(parent)
		self.setWindowTitle("Add/Edit Profile")
		self.resize(400, 300)

		self.layout = QVBoxLayout()

		header_style = "color: #9aa0a6;"

		name_label = QLabel("Profile Name")
		name_label.setStyleSheet(header_style)
		self.layout.addWidget(name_label)

		self.name_input = QLineEdit()
		self.name_input.setPlaceholderText("Profile name")
		self.layout.addWidget(self.name_input)

		interval_label = QLabel("Snapshot Interval (minutes)")
		interval_label.setStyleSheet(header_style)
		self.layout.addWidget(interval_label)

		self.interval_input = QLineEdit()
		self.interval_input.setPlaceholderText("Default: 60")
		self.layout.addWidget(self.interval_input)

		retention_label = QLabel("Retention (days)")
		retention_label.setStyleSheet(header_style)
		self.layout.addWidget(retention_label)

		self.retention_input = QLineEdit()
		self.retention_input.setPlaceholderText("Empty = unlimited")
		self.layout.addWidget(self.retention_input)

		folders_label = QLabel("Folders (Ground + Mirrors)")
		folders_label.setStyleSheet(header_style)
		self.layout.addWidget(folders_label)

		self.folder_list = QListWidget()
		self.layout.addWidget(self.folder_list)

		btn_row = QHBoxLayout()

		add_folder_btn = QPushButton("Add Folder")
		add_folder_btn.clicked.connect(self.add_folder)
		btn_row.addWidget(add_folder_btn)

		remove_folder_btn = QPushButton("Remove Selected")
		remove_folder_btn.clicked.connect(self.remove_selected)
		btn_row.addWidget(remove_folder_btn)

		self.layout.addLayout(btn_row)

		self.ground_label = QLabel("Double-click a folder to set as ground truth")
		self.layout.addWidget(self.ground_label)

		save_btn = QPushButton("Save Profile")
		save_btn.clicked.connect(self.accept)
		save_btn.setStyleSheet("""
			QPushButton {
				background-color: #2563eb;
				border: 1px solid #2f6fef;
				font-weight: 600;
				color: #e7ebf3;
			}
			QPushButton:hover {
				background-color: #2f6fef;
			}
		""")
		self.layout.addWidget(save_btn)

		if profile:
			delete_btn = QPushButton("Delete Profile")
			delete_btn.clicked.connect(self.delete_profile)
			delete_btn.setStyleSheet("""
				QPushButton {
					background-color: #b91c1c;
					border: 1px solid #dc2626;
					font-weight: 600;
					color: #fef2f2;
				}
				QPushButton:hover {
					background-color: #dc2626;
				}
			""")
			self.layout.addWidget(delete_btn)

		self.profile_to_delete = profile
		self.delete_requested = False

		self.setLayout(self.layout)

		self.ground_index = None
		self.folder_list.itemDoubleClicked.connect(self.set_ground)

		if profile:
			self.load_profile(profile)

	def delete_profile(self):
		confirm = QMessageBox.question(
			self,
			"Delete profile",
			"Are you sure you want to delete this profile?",
			QMessageBox.Yes | QMessageBox.No
		)
		if confirm == QMessageBox.Yes:
			self.delete_requested = True
			self.accept()

	def load_profile(self, profile):
		self.name_input.setText(profile["name"])

		interval = profile.get("snapshot_interval", 3600)
		minutes = interval / 60
		self.interval_input.setText(str(round(minutes, 3)).rstrip("0").rstrip("."))

		ret = profile.get("retention_seconds")
		if ret:
			days = ret / 86400
			self.retention_input.setText(str(round(days, 3)).rstrip("0").rstrip("."))

		for i, p in enumerate(profile["paths"]):
			item = QListWidgetItem(p["path"])
			self.folder_list.addItem(item)
			if p["role"] == "ground":
				self.ground_index = i
		self.update_labels()

	def add_folder(self):
		folder = QFileDialog.getExistingDirectory(
			self,
			"Select Folder",
			HOME_DIR
		)
		if folder:
			item = QListWidgetItem(folder)
			self.folder_list.addItem(item)

	def remove_selected(self):
		row = self.folder_list.currentRow()
		if row >= 0:
			self.folder_list.takeItem(row)

	def set_ground(self, item):
		self.ground_index = self.folder_list.row(item)
		self.update_labels()

	def update_labels(self):
		for i in range(self.folder_list.count()):
			text = self.folder_list.item(i).text().replace("[GROUND] ", "")
			if i == self.ground_index:
				self.folder_list.item(i).setText(f"[GROUND] {text}")
			else:
				self.folder_list.item(i).setText(text)

	def get_profile(self):
		name = self.name_input.text().strip()
		if not name:
			return None

		if self.folder_list.count() < 2:
			return None

		if self.ground_index is None:
			return None

		interval_text = self.interval_input.text().strip()
		if interval_text:
			try:
				minutes = float(interval_text)
				interval = max(60, int(minutes * 60))
			except ValueError:
				return None
		else:
			interval = 3600

		retention_text = self.retention_input.text().strip()
		if retention_text:
			try:
				days = float(retention_text)
				if days <= 0:
					return None
				retention_seconds = int(days * 86400)

			except ValueError:
				return None
		else:
			retention_seconds = None

		paths = []
		for i in range(self.folder_list.count()):
			path = self.folder_list.item(i).text().replace("[GROUND] ", "")
			role = "ground" if i == self.ground_index else "mirror"
			paths.append({"path": path, "role": role})

		profile = {
			"name": name,
			"snapshot_interval": interval,
			"paths": paths
		}

		if retention_seconds:
			profile["retention_seconds"] = retention_seconds

		return profile


class ProfileWidget(QGroupBox):
	def __init__(self, profile, parent_window):
		super().__init__()
		self.profile = profile
		self.parent_window = parent_window
		self.sync = ProfileSync(
			profile,
			on_profile_change=self.parent_window.persist_config
		)
		self.mirror_progress = {}
		self.setTitle("")
		self.setObjectName("profileCard")

		layout = QVBoxLayout()
		layout.setContentsMargins(10, 10, 10, 10)
		layout.setSpacing(6)

		header_row = QHBoxLayout()
		header_row.setContentsMargins(0, 0, 0, 0)
		header_row.setSpacing(8)
		self.title_label = QLabel(profile["name"])
		self.title_label.setObjectName("profileTitle")
		header_row.addWidget(self.title_label)

		ground = next(
			p["path"] for p in profile["paths"] if p["role"] == "ground"
		)
		self.ground_path_label = QLabel(ground)
		self.ground_path_label.setObjectName("groundPath")
		self.ground_path_label.setWordWrap(False)
		header_row.addWidget(self.ground_path_label)
		header_row.addStretch()
		self.status_chip = QLabel("IDLE")
		self.status_chip.setObjectName("statusChip")
		header_row.addWidget(self.status_chip)
		layout.addLayout(header_row)
		layout.addSpacing(6)

		self.mirror_labels = {}
		mirrors = [
			p["path"] for p in profile["paths"] if p["role"] == "mirror"
		]
		mirror_header = QLabel("Mirrors")
		mirror_header.setObjectName("sectionHeader")
		layout.addWidget(mirror_header)

		for m in mirrors:
			lbl = QLabel(f"{m}  [ IDLE ]")
			lbl.setObjectName("mirrorPath")
			lbl.setWordWrap(True)
			self.mirror_labels[m] = lbl
			layout.addWidget(lbl)
		layout.addSpacing(6)

		interval = profile.get("snapshot_interval", 3600)
		minutes = interval / 60
		if minutes >= 60:
			hours = minutes / 60
			self.interval_text = f"{round(hours, 2)}h"
		else:
			self.interval_text = f"{round(minutes, 2)}m"

		retention = profile.get("retention_seconds")
		if retention:
			days = retention / 86400
			if days >= 1:
				self.retention_text = f"{round(days, 2)}d"
			else:
				hours = retention / 3600
				self.retention_text = f"{round(hours, 2)}h"
		else:
			self.retention_text = "Unlimited"

		self.status_text = "IDLE"
		stats_header = QLabel("Stats")
		stats_header.setObjectName("sectionHeader")
		layout.addWidget(stats_header)
		self.stats_label = QLabel()
		self.stats_label.setObjectName("statsLabel")
		layout.addWidget(self.stats_label)

		btn_row = QHBoxLayout()
		btn_row.setContentsMargins(0, 2, 0, 0)
		btn_row.setSpacing(8)

		self.sync_btn = QPushButton("Sync")
		self.sync_btn.setObjectName("primaryBtn")
		self.sync_btn.clicked.connect(self.toggle_sync)
		btn_row.addWidget(self.sync_btn)

		self.edit_btn = QPushButton("Edit")
		self.edit_btn.clicked.connect(self.edit_profile)
		btn_row.addWidget(self.edit_btn)

		self.versions_btn = QPushButton("Versions")
		self.versions_btn.clicked.connect(self.open_versions)
		btn_row.addWidget(self.versions_btn)

		self.snapshot_btn = QPushButton("Snapshots")
		self.snapshot_btn.clicked.connect(self.open_snapshots)
		btn_row.addWidget(self.snapshot_btn)

		layout.addLayout(btn_row)
		self.setLayout(layout)

		self.is_running = False
		self.snapshot_timer = QTimer(self)
		self.snapshot_timer.setInterval(SNAPSHOT_LABEL_INTERVAL)
		self.snapshot_timer.timeout.connect(self.refresh_snapshot_label)

		self.refresh_stats_row()
		self.set_idle_style()

	def set_running_style(self):
		self.status_chip.setText("RUNNING")
		self.status_chip.setProperty("state", "running")
		self.status_chip.style().unpolish(self.status_chip)
		self.status_chip.style().polish(self.status_chip)
		self.setStyleSheet("""
			QGroupBox#profileCard {
				background-color: #252a33;
				border: 1px solid #404858;
				border-left: 2px solid #3fb950;
				border-radius: 7px;
			}
			QLabel { background-color: transparent; }
			QLabel#profileTitle { color: #f2f4f8; font-size: 14px; font-weight: 700; }
			QLabel#sectionHeader { color: #94a3b8; font-size: 10px; text-transform: uppercase; }
			QLabel#groundPath { color: #94a3b8; font-size: 12px; }
			QLabel#mirrorPath { color: #cbd5e1; font-size: 12px; padding: 1px 0; }
			QLabel#statsLabel { color: #b8c6da; font-size: 12px; }
			QLabel#statusChip {
				padding: 2px 7px;
				border-radius: 10px;
				color: #84e1a1;
				font-size: 10px;
				font-weight: 700;
			}
			QPushButton {
				background-color: #333a46;
				border: 1px solid #4a5365;
				border-radius: 6px;
				padding: 4px 9px;
				color: #e7ebf3;
			}
			QPushButton:hover { background-color: #3b4351; }
			QPushButton#primaryBtn {
				background-color: #2563eb;
				border-color: #2f6fef;
				font-weight: 600;
			}
			QPushButton#primaryBtn:hover { background-color: #2f6fef; }
		""")

	def set_idle_style(self):
		self.status_chip.setText("IDLE")
		self.status_chip.setProperty("state", "idle")
		self.status_chip.style().unpolish(self.status_chip)
		self.status_chip.style().polish(self.status_chip)
		self.setStyleSheet("""
			QGroupBox#profileCard {
				background-color: #252a33;
				border: 1px solid #404858;
				border-left: 2px solid #a34a4a;
				border-radius: 7px;
			}
			QLabel { background-color: transparent; }
			QLabel#profileTitle { color: #f2f4f8; font-size: 14px; font-weight: 700; }
			QLabel#sectionHeader { color: #94a3b8; font-size: 10px; text-transform: uppercase; }
			QLabel#groundPath { color: #94a3b8; font-size: 12px; }
			QLabel#mirrorPath { color: #cbd5e1; font-size: 12px; padding: 1px 0; }
			QLabel#statsLabel { color: #b8c6da; font-size: 12px; }
			QLabel#statusChip {
				padding: 2px 7px;
				border-radius: 10px;
				color: #f3a8b5;
				font-size: 10px;
				font-weight: 700;
			}
			QPushButton {
				background-color: #333a46;
				border: 1px solid #4a5365;
				border-radius: 6px;
				padding: 4px 9px;
				color: #e7ebf3;
			}
			QPushButton:hover { background-color: #3b4351; }
			QPushButton#primaryBtn {
				background-color: #2563eb;
				border-color: #2f6fef;
				font-weight: 600;
			}
			QPushButton#primaryBtn:hover { background-color: #2f6fef; }
		""")

	def open_snapshots(self):
		if self.is_running:
			QMessageBox.warning(
				self,
				"Stop sync first",
				"You must stop the sync before exploring snapshots."
			)
			return

		dialog = SnapshotExplorerDialog(self.profile, self)
		dialog.exec()

	def open_versions(self):
		if self.is_running:
			QMessageBox.warning(
				self,
				"Stop sync first",
				"You must stop the sync before exploring versions."
			)
			return

		dialog = FileVersionDialog(self.profile, self)
		dialog.exec()

	def refresh_snapshot_label(self):
		if hasattr(self.sync, "_emit_snapshot_status"):
			self.sync._emit_snapshot_status()
		self.refresh_stats_row()

	@staticmethod
	def _format_duration(seconds):
		seconds = max(0, int(seconds))
		minutes = seconds // 60
		hours = minutes // 60
		minutes = minutes % 60
		days = hours // 24
		hours = hours % 24

		if days > 0:
			return f"{days}d {hours}h"
		if hours > 0:
			return f"{hours}h {minutes}m"
		return f"{minutes}m"

	def refresh_stats_row(self):
		last_snapshot_time = self.sync.last_snapshot_time
		if last_snapshot_time:
			last_dt = datetime.fromtimestamp(last_snapshot_time).strftime("%b %d %H:%M")
			if self.is_running:
				age = int(max(0, time.time() - last_snapshot_time))
				last_text = f"{last_dt}"
			else:
				last_text = last_dt
		else:
			last_text = "-"

		if self.is_running and last_snapshot_time:
			now = time.time()
			age = int(now - last_snapshot_time)
			intervals_passed = age // self.sync.snapshot_interval
			next_boundary = last_snapshot_time + (intervals_passed + 1) * self.sync.snapshot_interval
			next_in = int(next_boundary - now)
			next_text = self._format_duration(next_in)
		elif self.is_running:
			next_text = "pending"
		else:
			next_text = "-"

		self.stats_label.setText(
			"&nbsp;<span>Snapshot Frequency: "
			f"{self.interval_text}</span>"
			'&nbsp;&nbsp;<span style="color: #e7ebf3; font-weight: 700;">•</span>&nbsp;&nbsp;'
			f"<span>Last Snapshot: {last_text}</span>"
			'&nbsp;&nbsp;<span style="color: #e7ebf3; font-weight: 700;">•</span>&nbsp;&nbsp;'
			f"<span>Next Snapshot: {next_text}</span>"
			'&nbsp;&nbsp;<span style="color: #e7ebf3; font-weight: 700;">•</span>&nbsp;&nbsp;'
			f"<span>Retention: {self.retention_text}</span>"
		)

	def update_mirror_progress(self, path, percent):
		if path in self.mirror_labels:
			self.mirror_progress[path] = percent
			self.mirror_labels[path].setText(
				f"{path}  [ SYNCING {percent}% ]"
			)

	def update_mirror_status(self, path, text):
		if path in self.mirror_labels:
			percent = self.mirror_progress.get(path, 0)

			if text.startswith("SYNCED"):
				label = f"[ SYNCED {percent}% ]"
			elif text.startswith("SYNCING"):
				label = f"[ SYNCING {percent}% ]"
			elif text.startswith("ERROR"):
				label = f"[ {text} ]"
			else:
				label = f"[ {text} ]"

			self.mirror_labels[path].setText(f"{path}  {label}")

	def update_status(self, text):
		self.status_text = text
		self.refresh_stats_row()

	def update_snapshot_status(self, text):
		self.refresh_stats_row()

	def toggle_sync(self):
		if not self.is_running:
			self.is_running = True
			try:
				self.sync.start(
					self.update_status,
					self.update_mirror_status,
					self.update_mirror_progress,
					self.update_snapshot_status
				)
			except Exception as e:
				self.is_running = False
				logger.exception(f"Failed to start sync for profile {self.profile['name']}: {e}")
				QMessageBox.critical(
					self,
					"Failed to start sync",
					f"Could not start sync for '{self.profile['name']}'.\n{e}"
				)
				return

			self.sync_btn.setText("Stop")
			logger.info(f"Sync started for profile: {self.profile['name']}")
			self.snapshot_timer.start()
			self.set_running_style()
			self.refresh_stats_row()
		else:
			self.sync.stop(self.update_status)
			self.sync_btn.setText("Sync")
			self.is_running = False
			logger.info(f"Sync stopped for profile: {self.profile['name']}")
			self.snapshot_timer.stop()
			self.set_idle_style()
			self.refresh_stats_row()

			for path, lbl in self.mirror_labels.items():
				lbl.setText(f"{path}  [ SYNC STOPPED ]")
				self.mirror_progress[path] = 0

	def edit_profile(self):
		if self.is_running:
			QMessageBox.warning(
				self,
				"Stop sync first",
				"You must stop the sync before editing this profile."
			)
			return

		self.parent_window.edit_profile(self.profile)


class MirrorToolsDialog(QDialog):
	def __init__(self, mirror_path, parent=None):
		super().__init__(parent)
		self.mirror_path = mirror_path
		self.profile_name = Path(mirror_path).name
		self.setWindowTitle("Mirror Tools")
		self.resize(420, 220)

		layout = QVBoxLayout(self)

		info = QLabel(
			"Opened mirror:\n"
			f"{self.mirror_path}"
		)
		info.setWordWrap(True)
		layout.addWidget(info)

		current_btn = QPushButton("Explore Current")
		current_btn.clicked.connect(self.open_current)
		layout.addWidget(current_btn)

		versions_btn = QPushButton("Explore Versions")
		versions_btn.clicked.connect(self.open_versions)
		layout.addWidget(versions_btn)

		snapshots_btn = QPushButton("Explore Snapshots")
		snapshots_btn.clicked.connect(self.open_snapshots)
		layout.addWidget(snapshots_btn)

		close_btn = QPushButton("Close")
		close_btn.clicked.connect(self.accept)
		layout.addWidget(close_btn)

	def open_current(self):
		dialog = CurrentExplorerDialog(
			self.mirror_path,
			profile_name=self.profile_name,
			parent=self
		)
		dialog.exec()

	def open_versions(self):
		dialog = FileVersionDialog(
			mirror_path=self.mirror_path,
			profile_name=self.profile_name,
			parent=self
		)
		dialog.exec()

	def open_snapshots(self):
		dialog = SnapshotExplorerDialog(
			mirror_path=self.mirror_path,
			profile_name=self.profile_name,
			parent=self
		)
		dialog.exec()

class MainWindow(QWidget):
	def __init__(self, config):
		super().__init__()
		self.setWindowTitle("Watchback")
		self.setMinimumSize(600, 450)
		self.resize(720, 520)

		self.config = config
		self.profile_widgets = []

		main_layout = QVBoxLayout()
		main_layout.setContentsMargins(12, 12, 12, 12)
		main_layout.setSpacing(10)
		self.setLayout(main_layout)

		self.scroll = QScrollArea()
		self.scroll.setWidgetResizable(True)
		self.scroll.setFrameShape(QFrame.NoFrame)
		main_layout.addWidget(self.scroll)

		self.scroll_container = QWidget()
		self.scroll_layout = QVBoxLayout()
		self.scroll_layout.setAlignment(Qt.AlignTop)
		self.scroll_layout.setSpacing(12)
		self.scroll_container.setLayout(self.scroll_layout)

		self.scroll.setWidget(self.scroll_container)

		tools_btn_row = QHBoxLayout()

		clear_log_group = QWidget()
		clear_log_group_layout = QHBoxLayout(clear_log_group)
		clear_log_group_layout.setContentsMargins(0, 0, 0, 0)
		clear_log_group_layout.setSpacing(0)

		self.clear_log_btn = QPushButton("Clear Log")
		self.clear_log_btn.clicked.connect(self.clear_log)
		self.clear_log_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
		self.clear_log_btn.setStyleSheet("""
			QPushButton {
				border-top-right-radius: 0px;
				border-bottom-right-radius: 0px;
			}
		""")
		clear_log_group_layout.addWidget(self.clear_log_btn)

		self.open_location_btn = QToolButton()
		self.open_location_btn.setArrowType(Qt.RightArrow)
		self.open_location_btn.setToolTip("Open app data location")
		self.open_location_btn.clicked.connect(self.open_app_data_location)
		self.open_location_btn.setFixedWidth(28)
		self.open_location_btn.setStyleSheet("""
			QToolButton {
				background-color: #3a3a3a;
				border: 1px solid #555555;
				border-left: 0px;
				border-top-right-radius: 6px;
				border-bottom-right-radius: 6px;
			}
			QToolButton:hover {
				background-color: #4a4a4a;
			}
			QToolButton:pressed {
				background-color: #2a2a2a;
			}
		""")
		clear_log_group_layout.addWidget(self.open_location_btn)

		clear_log_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
		tools_btn_row.addWidget(clear_log_group)

		self.open_mirror_btn = QPushButton("Open Mirror")
		self.open_mirror_btn.clicked.connect(self.open_mirror)
		self.open_mirror_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
		self.open_mirror_btn.setStyleSheet("""
			QPushButton {
				background-color: #2563eb;
				border: 1px solid #2f6fef;
				font-weight: 600;
				color: #e7ebf3;
			}
			QPushButton:hover {
				background-color: #2f6fef;
			}
		""")
		tools_btn_row.addWidget(self.open_mirror_btn)

		self.add_btn = QPushButton("Add Profile")
		self.add_btn.clicked.connect(self.add_profile)
		self.add_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
		self.add_btn.setStyleSheet("""
			QPushButton {
				background-color: #2563eb;
				border: 1px solid #2f6fef;
				font-weight: 600;
				color: #e7ebf3;
			}
			QPushButton:hover {
				background-color: #2f6fef;
			}
		""")
		tools_btn_row.addWidget(self.add_btn)

		main_layout.addLayout(tools_btn_row)
		self.log_size_timer = QTimer(self)
		self.log_size_timer.setInterval(5000)
		self.log_size_timer.timeout.connect(self.refresh_log_size)
		self.log_size_timer.start()

		self.refresh_log_size()
		self.refresh_ui()

	@staticmethod
	def _format_bytes(size):
		size = float(max(0, size))
		for unit in ["B", "KB", "MB", "GB", "TB"]:
			if size < 1024 or unit == "TB":
				if unit == "B":
					return f"{int(size)}{unit}"
				return f"{size:.2f}{unit}"
			size /= 1024

	def refresh_log_size(self):
		if LOG_PATH.exists():
			size_text = self._format_bytes(LOG_PATH.stat().st_size)
		else:
			size_text = "0B"

		self.clear_log_btn.setText(f"Clear Log ({size_text})")

	def clear_log(self):
		confirm = QMessageBox.question(
			self,
			"Clear log",
			"Clear the watchback log file?",
			QMessageBox.Yes | QMessageBox.No
		)
		if confirm != QMessageBox.Yes:
			return

		LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
		try:
			with open(LOG_PATH, "w"):
				pass

			self.refresh_log_size()
		except Exception as e:
			QMessageBox.critical(self, "Log clear failed", f"Could not clear log:\n{e}")

	def open_app_data_location(self):
		if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_PATH.parent))):
			QMessageBox.warning(self, "Open failed", f"Could not open:\n{LOG_PATH.parent}")

	def refresh_ui(self):
		while self.scroll_layout.count():
			child = self.scroll_layout.takeAt(0)
			if child.widget():
				child.widget().deleteLater()

		self.profile_widgets = []

		for profile in self.config["profiles"]:
			widget = ProfileWidget(profile, self)
			self.profile_widgets.append(widget)
			self.scroll_layout.addWidget(widget)

		self.scroll_layout.addStretch()

	def add_profile(self):
		dialog = AddProfileDialog(self)
		if dialog.exec():
			profile = dialog.get_profile()
			if not profile:
				QMessageBox.warning(
					self,
					"Invalid profile",
					"You must provide:\n"
					"- A profile name\n"
					"- At least two folders\n"
					"- One ground truth folder"
				)
				return

			self.config["profiles"].append(profile)
			save_config(self.config)
			logger.info(f"Profile added: {profile['name']}")

			widget = ProfileWidget(profile, self)
			self.profile_widgets.append(widget)

			self.scroll_layout.insertWidget(
				self.scroll_layout.count() - 1,
				widget
			)

	def open_mirror(self):
		mirror = QFileDialog.getExistingDirectory(
			self,
			"Select Watchback mirror folder",
			HOME_DIR
		)
		if not mirror:
			return

		if not MirrorService.is_watchback_mirror(mirror):
			QMessageBox.warning(
				self,
				"Invalid mirror",
				"Selected folder does not look like a Watchback mirror.\n"
				"Expected entries such as current/, snapshots/, versions/, or objects/."
			)
			return

		dialog = MirrorToolsDialog(mirror, self)
		dialog.exec()


	def edit_profile(self, profile):
		widget = None
		for w in self.profile_widgets:
			if w.profile is profile:
				widget = w
				break

		if widget and widget.is_running:
			QMessageBox.warning(
				self,
				"Stop sync first",
				"You must stop the sync before editing this profile."
			)
			return

		dialog = AddProfileDialog(self, profile)
		if dialog.exec():
			if getattr(dialog, "delete_requested", False):
				if widget and widget.is_running:
					widget.toggle_sync()

				self.config["profiles"] = [
					p for p in self.config["profiles"] if p is not profile
				]
				save_config(self.config)
				logger.info(f"Profile deleted: {profile['name']}")

				if widget:
					self.profile_widgets.remove(widget)
					widget.deleteLater()

				return

			new_profile = dialog.get_profile()
			if not new_profile:
				QMessageBox.warning(
					self,
					"Invalid profile",
					"Profile must have a name, two folders, and one ground truth."
				)
				return

			if "last_snapshot_time" in profile:
				new_profile["last_snapshot_time"] = profile["last_snapshot_time"]

			for i, p in enumerate(self.config["profiles"]):
				if p is profile:
					self.config["profiles"][i] = new_profile
					break

			save_config(self.config)
			logger.info(f"Profile updated: {new_profile['name']}")


			if widget:
				index = self.scroll_layout.indexOf(widget)
				self.profile_widgets.remove(widget)
				widget.deleteLater()

				new_widget = ProfileWidget(new_profile, self)
				self.profile_widgets.append(new_widget)
				self.scroll_layout.insertWidget(index, new_widget)

	def persist_config(self):
		save_config(self.config)
