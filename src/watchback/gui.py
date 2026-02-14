from PySide6.QtWidgets import (
	QWidget, QVBoxLayout, QPushButton, QLabel, QGroupBox,
	QDialog, QLineEdit, QListWidget, QListWidgetItem,
	QFileDialog, QHBoxLayout, QMessageBox,
	QScrollArea, QFrame
)
from PySide6.QtCore import Qt, QTimer

from watchback.sync import ProfileSync
from watchback.config import save_config
from watchback.restore_gui import FileVersionDialog, SnapshotExplorerDialog

SNAPSHOT_LABEL_INTERVAL = 60000

class AddProfileDialog(QDialog):
	def __init__(self, parent=None, profile=None):
		super().__init__(parent)
		self.setWindowTitle("Add/Edit Profile")
		self.resize(400, 300)

		self.layout = QVBoxLayout()

		self.name_input = QLineEdit()
		self.name_input.setPlaceholderText("Profile name")
		self.layout.addWidget(self.name_input)

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
		self.layout.addWidget(save_btn)

		delete_btn = QPushButton("Delete Profile")
		delete_btn.clicked.connect(self.delete_profile)
		delete_btn.setStyleSheet("background-color: #5a1e1e;")
		self.layout.addWidget(delete_btn)

		self.profile_to_delete = profile
		self.delete_requested = False

		self.setLayout(self.layout)

		self.ground_index = None
		self.folder_list.itemDoubleClicked.connect(self.set_ground)

		# If editing existing profile
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
		for i, p in enumerate(profile["paths"]):
			item = QListWidgetItem(p["path"])
			self.folder_list.addItem(item)
			if p["role"] == "ground":
				self.ground_index = i
		self.update_labels()

	def add_folder(self):
		folder = QFileDialog.getExistingDirectory(self, "Select Folder")
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

		paths = []
		for i in range(self.folder_list.count()):
			path = self.folder_list.item(i).text().replace("[GROUND] ", "")
			role = "ground" if i == self.ground_index else "mirror"
			paths.append({"path": path, "role": role})

		return {"name": name, "paths": paths}


class ProfileWidget(QGroupBox):
	def __init__(self, profile, parent_window):
		super().__init__(profile["name"])
		self.profile = profile
		self.parent_window = parent_window
		self.sync = ProfileSync(profile)
		self.mirror_progress = {}

		layout = QVBoxLayout()

		# Ground truth
		ground = next(
			p["path"] for p in profile["paths"] if p["role"] == "ground"
		)
		ground_label = QLabel(f"Ground: {ground}")
		layout.addWidget(ground_label)

		# Mirrors with status
		self.mirror_labels = {}
		mirrors = [
			p["path"] for p in profile["paths"] if p["role"] == "mirror"
		]
		for m in mirrors:
			lbl = QLabel(f"Mirror: {m} : IDLE")
			self.mirror_labels[m] = lbl
			layout.addWidget(lbl)


		self.status = QLabel("Status: IDLE")
		self.snapshot_status = QLabel("Snapshot: -")
		layout.addWidget(self.snapshot_status)

		# Buttons
		btn_row = QHBoxLayout()

		self.sync_btn = QPushButton("Sync")
		self.sync_btn.clicked.connect(self.toggle_sync)
		btn_row.addWidget(self.sync_btn)

		self.edit_btn = QPushButton("Edit")
		self.edit_btn.clicked.connect(self.edit_profile)
		btn_row.addWidget(self.edit_btn)

		self.versions_btn = QPushButton("File Versions")
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

	def set_running_style(self):
		self.setStyleSheet("""
			QGroupBox {
				background-color: #2b2b2b;
				border: 1px solid #3c3c3c;
				border-left: 2px solid #3fb950;  /* green */
				border-radius: 2px;
				margin-top: 10px;
				padding: 10px;
			}
		""")

	def set_idle_style(self):
		self.setStyleSheet("""
			QGroupBox {
				background-color: #2b2b2b;
				border: 1px solid #3c3c3c;
				border-radius: 2px;
				margin-top: 10px;
				padding: 10px;
			}
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

	def update_mirror_progress(self, path, percent):
		if path in self.mirror_labels:
			self.mirror_progress[path] = percent
			self.mirror_labels[path].setText(
				f"Mirror: {path} : [ SYNCING {percent}% ]"
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

			self.mirror_labels[path].setText(f"Mirror: {path} : {label}")

	def update_status(self, text):
		self.status.setText(f"Status: {text}")

	def update_snapshot_status(self, text):
		self.snapshot_status.setText(f"Snapshot: {text}")

	def toggle_sync(self):
		if not self.is_running:
			# Start sync
			self.sync.start(
				self.update_status,
				self.update_mirror_status,
				self.update_mirror_progress,
				self.update_snapshot_status
			)
			self.sync_btn.setText("Stop")
			self.is_running = True
			self.snapshot_timer.start()
			self.edit_btn.setEnabled(False)   # disable edit
			self.set_running_style()
		else:
			# Stop sync
			self.sync.stop(self.update_status)
			self.sync_btn.setText("Sync")
			self.is_running = False
			self.edit_btn.setEnabled(True)
			self.set_idle_style()



	def edit_profile(self):
		self.parent_window.edit_profile(self.profile)


class MainWindow(QWidget):
	def __init__(self, config):
		super().__init__()
		self.setWindowTitle("Watchback - Backup Tool")
		self.setMinimumSize(600, 450)
		self.resize(720, 520)

		self.config = config
		self.profile_widgets = []

		main_layout = QVBoxLayout()
		main_layout.setContentsMargins(12, 12, 12, 12)
		main_layout.setSpacing(10)
		self.setLayout(main_layout)

		# Scroll area
		self.scroll = QScrollArea()
		self.scroll.setWidgetResizable(True)
		self.scroll.setFrameShape(QFrame.NoFrame)
		main_layout.addWidget(self.scroll)

		# Container inside scroll area
		self.scroll_container = QWidget()
		self.scroll_layout = QVBoxLayout()
		self.scroll_layout.setAlignment(Qt.AlignTop)
		self.scroll_layout.setSpacing(12)
		self.scroll_container.setLayout(self.scroll_layout)

		self.scroll.setWidget(self.scroll_container)

		# Bottom button row
		bottom_row = QHBoxLayout()
		bottom_row.addStretch()

		self.add_btn = QPushButton("Add Profile")
		self.add_btn.clicked.connect(self.add_profile)
		bottom_row.addWidget(self.add_btn)

		main_layout.addLayout(bottom_row)

		self.refresh_ui()

	def refresh_ui(self):
		# Clear profile cards
		while self.scroll_layout.count():
			child = self.scroll_layout.takeAt(0)
			if child.widget():
				child.widget().deleteLater()

		self.profile_widgets = []

		for profile in self.config["profiles"]:
			widget = ProfileWidget(profile, self)
			self.profile_widgets.append(widget)
			self.scroll_layout.addWidget(widget)


		# Push content to top
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

			widget = ProfileWidget(profile, self)
			self.profile_widgets.append(widget)

			# Insert above stretch
			self.scroll_layout.insertWidget(
				self.scroll_layout.count() - 1,
				widget
			)


	def edit_profile(self, profile):
		# Find the widget for this profile
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
			# Delete case
			if getattr(dialog, "delete_requested", False):
				# Stop sync if running
				if widget and widget.is_running:
					widget.toggle_sync()

				# Remove from config
				self.config["profiles"] = [
					p for p in self.config["profiles"] if p is not profile
				]
				save_config(self.config)

				# Remove widget
				if widget:
					self.profile_widgets.remove(widget)
					widget.deleteLater()

				return

			# Edit case
			new_profile = dialog.get_profile()
			if not new_profile:
				QMessageBox.warning(
					self,
					"Invalid profile",
					"Profile must have a name, two folders, and one ground truth."
				)
				return

			# Replace in config
			for i, p in enumerate(self.config["profiles"]):
				if p is profile:
					self.config["profiles"][i] = new_profile
					break

			save_config(self.config)

			# Replace widget
			if widget:
				index = self.scroll_layout.indexOf(widget)
				self.profile_widgets.remove(widget)
				widget.deleteLater()

				new_widget = ProfileWidget(new_profile, self)
				self.profile_widgets.append(new_widget)
				self.scroll_layout.insertWidget(index, new_widget)


