from PySide6.QtWidgets import (
	QDialog, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
	QListWidget, QPushButton, QHBoxLayout, QWidget,
	QSplitter, QMessageBox, QFileDialog, QComboBox, QLabel,
)
from PySide6.QtCore import Qt
from pathlib import Path

from watchback.restore import (
	FileVersionService,
	SnapshotService,
	CurrentService,
)
from watchback.progress import run_with_progress

HOME_DIR = str(Path.home())

class FileVersionDialog(QDialog):
	def __init__(self, profile=None, parent=None, mirror_path=None, profile_name=None):
		super().__init__(parent)
		self.setWindowTitle("File Version Explorer")
		self.resize(850, 520)

		self.profile = profile
		self.profile_name = profile_name or "mirror"
		self.ground = None
		self.allow_restore = False
		if profile:
			self.profile_name = profile.get("name", self.profile_name)
			self.ground = next(
				p["path"] for p in profile["paths"] if p["role"] == "ground"
			)
			self.allow_restore = True
			self.mirrors = [
				p["path"] for p in profile["paths"] if p["role"] == "mirror"
			]
		elif mirror_path:
			self.mirrors = [mirror_path]
		else:
			self.mirrors = []

		if not self.mirrors:
			raise ValueError("No mirrors available")

		self.mirror = self.mirrors[0]

		layout = QVBoxLayout(self)
		top_row = QHBoxLayout()

		top_row.addWidget(QLabel("Mirror:"))

		self.mirror_combo = QComboBox()
		for m in self.mirrors:
			self.mirror_combo.addItem(m)
		self.mirror_combo.currentTextChanged.connect(self.on_mirror_changed)
		top_row.addWidget(self.mirror_combo)

		top_row.addStretch()

		layout.addLayout(top_row)

		splitter = QSplitter()
		layout.addWidget(splitter)

		self.tree = QTreeWidget()
		self.tree.setHeaderLabel("Files")
		self.tree.itemClicked.connect(self.on_file_selected)
		splitter.addWidget(self.tree)

		right_panel = QWidget()
		right_layout = QVBoxLayout(right_panel)

		self.version_list = QListWidget()
		right_layout.addWidget(self.version_list)

		btn_row = QHBoxLayout()

		self.restore_btn = QPushButton("Restore")
		self.restore_btn.clicked.connect(self.restore_selected)
		btn_row.addWidget(self.restore_btn)
		self.restore_btn.setVisible(self.allow_restore)

		self.export_btn = QPushButton("Export")
		self.export_btn.clicked.connect(self.export_selected)
		btn_row.addWidget(self.export_btn)

		right_layout.addLayout(btn_row)
		splitter.addWidget(right_panel)

		splitter.setStretchFactor(0, 3)
		splitter.setStretchFactor(1, 2)

		self.current_rel_path = None
		self.populate_tree()

	def on_mirror_changed(self, text):
		self.mirror = text
		self.current_rel_path = None
		self.version_list.clear()
		self.populate_tree()

	def populate_tree(self):
		self.tree.clear()

		files = FileVersionService.list_all_versioned_files(self.mirror)

		if not files:
			item = QTreeWidgetItem(["(no versioned files)"])
			self.tree.addTopLevelItem(item)
			return

		for rel in files:
			item = QTreeWidgetItem([rel])
			item.setData(0, Qt.UserRole, rel)
			self.tree.addTopLevelItem(item)


	def on_file_selected(self, item):
		rel_path = item.data(0, Qt.UserRole)
		if not rel_path:
			return

		versions = FileVersionService.list_versions(
			self.mirror, rel_path
		)

		self.version_list.clear()
		for v in reversed(versions):
			clean = v.replace(".json", "")
			self.version_list.addItem(clean)


		self.current_rel_path = rel_path

	def restore_selected(self):
		item = self.version_list.currentItem()
		if not item or not self.current_rel_path:
			return

		ts = item.text() + ".json"
		ground = self.ground
		if not ground:
			ground = QFileDialog.getExistingDirectory(
				self,
				"Select restore destination",
				HOME_DIR
			)
			if not ground:
				return

		confirm = QMessageBox.question(
			self,
			"Restore version",
			f"Restore this version of:\n{self.current_rel_path} ?",
			QMessageBox.Yes | QMessageBox.No
		)

		if confirm != QMessageBox.Yes:
			return

		run_with_progress(
			self,
			FileVersionService.restore_version,
			self.mirror,
			ground,
			self.current_rel_path,
			ts
		)

	def export_selected(self):
		item = self.version_list.currentItem()
		if not item or not self.current_rel_path:
			return

		ts = item.text() + ".json"

		out_path, _ = QFileDialog.getSaveFileName(
			self,
			"Save version as",
			str(Path(HOME_DIR) / Path(self.current_rel_path).name)
		)

		if not out_path:
			return

		run_with_progress(
			self,
			FileVersionService.export_version,
			self.mirror,
			self.current_rel_path,
			ts,
			out_path
		)

class SnapshotExplorerDialog(QDialog):
	def __init__(self, profile=None, parent=None, mirror_path=None, profile_name=None):
		super().__init__(parent)
		self.setWindowTitle("Snapshot Explorer")
		self.resize(850, 520)

		self.profile = profile
		self.profile_name = profile_name or "snapshot"
		self.ground = None
		self.allow_restore = False
		if profile:
			self.profile_name = profile.get("name", self.profile_name)
			self.ground = next(
				p["path"] for p in profile["paths"] if p["role"] == "ground"
			)
			self.allow_restore = True
			self.mirrors = [
				p["path"] for p in profile["paths"] if p["role"] == "mirror"
			]
		elif mirror_path:
			self.mirrors = [mirror_path]
		else:
			self.mirrors = []

		if not self.mirrors:
			raise ValueError("No mirrors available")

		self.mirror = self.mirrors[0]
		self.snapshot = None

		layout = QVBoxLayout(self)
		top_row = QHBoxLayout()
		top_row.addWidget(QLabel("Mirror:"))

		self.mirror_combo = QComboBox()
		for m in self.mirrors:
			self.mirror_combo.addItem(m)
		self.mirror_combo.currentTextChanged.connect(self.on_mirror_changed)
		top_row.addWidget(self.mirror_combo)

		top_row.addWidget(QLabel("Snapshot:"))

		self.snapshot_combo = QComboBox()
		self.snapshot_combo.currentTextChanged.connect(self.on_snapshot_changed)
		top_row.addWidget(self.snapshot_combo)

		top_row.addStretch()

		self.toggle_btn = QPushButton("Switch to List View")
		self.toggle_btn.clicked.connect(self.toggle_view)
		top_row.addWidget(self.toggle_btn)

		layout.addLayout(top_row)

		self.tree = QTreeWidget()
		self.tree.setHeaderLabel("Snapshot")
		layout.addWidget(self.tree)

		btn_row = QHBoxLayout()
		btn_row.addStretch()

		self.restore_btn = QPushButton("Restore")
		self.restore_btn.clicked.connect(self.restore_selected)
		btn_row.addWidget(self.restore_btn)
		self.restore_btn.setVisible(self.allow_restore)

		self.export_btn = QPushButton("Export")
		self.export_btn.clicked.connect(self.export_selected)
		btn_row.addWidget(self.export_btn)

		btn_row.addStretch()
		layout.addLayout(btn_row)


		self.current_rel_path = ""
		self.view_mode = "tree"

		self.load_snapshots()

	def toggle_view(self):
		if self.view_mode == "tree":
			self.view_mode = "list"
			self.toggle_btn.setText("Switch to Tree View")
		else:
			self.view_mode = "tree"
			self.toggle_btn.setText("Switch to List View")

		self.populate_tree()

	def load_snapshots(self):
		snaps = SnapshotService.list_snapshots(self.mirror)
		self.snapshot_combo.clear()

		if not snaps:
			self.snapshot_combo.addItem("(no snapshots)")
			self.tree.clear()
			return

		for s in snaps:
			self.snapshot_combo.addItem(s)

		self.snapshot = snaps[-1]
		self.snapshot_combo.setCurrentText(self.snapshot)
		self.populate_tree()

	def on_mirror_changed(self, text):
		self.mirror = text
		self.load_snapshots()

	def on_snapshot_changed(self, text):
		if text == "(no snapshots)":
			return
		self.snapshot = text
		self.populate_tree()

	def populate_tree(self):
		self.tree.clear()

		if not self.snapshot:
			return

		files = SnapshotService.list_snapshot_files(
			self.mirror, self.snapshot
		)

		if self.view_mode == "list":
			for f in sorted(files):
				item = QTreeWidgetItem([f])
				item.setData(0, Qt.UserRole, f)
				self.tree.addTopLevelItem(item)

			self.tree.itemClicked.connect(self.on_item_selected)
			return

		root = {}

		for f in files:
			parts = Path(f).parts
			node = root
			for part in parts:
				node = node.setdefault(part, {})

		def add_items(parent, structure, path=""):
			for name, sub in structure.items():
				rel = str(Path(path) / name) if path else name
				item = QTreeWidgetItem([name])
				item.setData(0, Qt.UserRole, rel)
				parent.addChild(item)

				if sub:
					add_items(item, sub, rel)

		root_item = QTreeWidgetItem(["/"])
		root_item.setData(0, Qt.UserRole, "")
		self.tree.addTopLevelItem(root_item)

		add_items(root_item, root)
		self.tree.expandAll()

		self.tree.itemClicked.connect(self.on_item_selected)

	def on_item_selected(self, item):
		rel = item.data(0, Qt.UserRole)
		if rel in ("", ".", "/"):
			rel = ""
		self.current_rel_path = rel

	def restore_selected(self):
		if not self.snapshot:
			return

		rel = self.current_rel_path or ""
		ground = self.ground
		if not ground:
			ground = QFileDialog.getExistingDirectory(
				self,
				"Select restore destination",
				HOME_DIR
			)
			if not ground:
				return

		confirm = QMessageBox.question(
			self,
			"Restore",
			f"Restore '{rel or '/'}' from snapshot?",
			QMessageBox.Yes | QMessageBox.No
		)

		if confirm != QMessageBox.Yes:
			return

		try:
			run_with_progress(
				self,
				SnapshotService.restore_folder,
				self.mirror,
				ground,
				self.snapshot,
				rel
			)
		except Exception as e:
			QMessageBox.warning(self, "Error", str(e))

	def export_selected(self):
		if not self.snapshot:
			return

		rel = self.current_rel_path or ""

		try:
			SnapshotService.resolve_file(
				self.mirror, self.snapshot, rel
			)

			default_name = Path(rel).name
			out_path, _ = QFileDialog.getSaveFileName(
				self,
				"Save File",
				str(Path(HOME_DIR) / default_name)
			)

			if not out_path:
				return

			run_with_progress(
				self,
				SnapshotService.export_file,
				self.mirror,
				self.snapshot,
				rel,
				out_path
			)

		except Exception:
			out_path, _ = QFileDialog.getSaveFileName(
				self,
				"Save ZIP",
				str(Path(HOME_DIR) / "snapshot.zip"),
				"Zip Files (*.zip)"
			)

			if not out_path:
				return

			try:
				run_with_progress(
					self,
					SnapshotService.export_zip,
					self.mirror,
					self.snapshot,
					rel,
					out_path,
					profile_name=self.profile_name
				)
			except Exception as e:
				QMessageBox.warning(self, "Error", str(e))


class CurrentExplorerDialog(QDialog):
	def __init__(self, mirror_path, profile_name=None, parent=None):
		super().__init__(parent)
		self.setWindowTitle("Current Explorer")
		self.resize(850, 520)

		self.mirror = mirror_path
		self.profile_name = profile_name or "current"
		self.current_rel_path = ""

		layout = QVBoxLayout(self)
		top_row = QHBoxLayout()
		top_row.addWidget(QLabel("Mirror:"))
		top_row.addWidget(QLabel(self.mirror))
		top_row.addStretch()
		layout.addLayout(top_row)

		self.tree = QTreeWidget()
		self.tree.setHeaderLabel("Current")
		self.tree.itemClicked.connect(self.on_item_selected)
		layout.addWidget(self.tree)

		btn_row = QHBoxLayout()
		btn_row.addStretch()

		self.export_btn = QPushButton("Export")
		self.export_btn.clicked.connect(self.export_selected)
		btn_row.addWidget(self.export_btn)

		btn_row.addStretch()
		layout.addLayout(btn_row)

		self.populate_tree()

	def populate_tree(self):
		self.tree.clear()

		files = CurrentService.list_current_files(self.mirror)
		if not files:
			item = QTreeWidgetItem(["(no files in current)"])
			self.tree.addTopLevelItem(item)
			return

		root = {}
		for f in files:
			parts = Path(f).parts
			node = root
			for part in parts:
				node = node.setdefault(part, {})

		def add_items(parent, structure, path=""):
			for name, sub in structure.items():
				rel = str(Path(path) / name) if path else name
				item = QTreeWidgetItem([name])
				item.setData(0, Qt.UserRole, rel)
				parent.addChild(item)
				if sub:
					add_items(item, sub, rel)

		root_item = QTreeWidgetItem(["/"])
		root_item.setData(0, Qt.UserRole, "")
		self.tree.addTopLevelItem(root_item)
		add_items(root_item, root)
		self.tree.expandAll()

	def on_item_selected(self, item):
		rel = item.data(0, Qt.UserRole)
		if rel in ("", ".", "/"):
			rel = ""
		self.current_rel_path = rel

	def export_selected(self):
		rel = self.current_rel_path or ""
		try:
			selected_path = CurrentService._resolve_current_path(self.mirror, rel)

			if selected_path.is_dir():
				out_path, _ = QFileDialog.getSaveFileName(
					self,
					"Save ZIP",
					str(Path(HOME_DIR) / "current.zip"),
					"Zip Files (*.zip)"
				)

				if not out_path:
					return

				run_with_progress(
					self,
					CurrentService.export_current_zip,
					self.mirror,
					rel,
					out_path,
					profile_name=self.profile_name
				)
				return

			default_name = Path(rel).name if rel else "current"
			out_path, _ = QFileDialog.getSaveFileName(
				self,
				"Save File",
				str(Path(HOME_DIR) / default_name)
			)
			if not out_path:
				return

			run_with_progress(
				self,
				CurrentService.export_current_file,
				self.mirror,
				rel,
				out_path
			)
		except FileNotFoundError:
			QMessageBox.warning(self, "Error", "Selected path no longer exists in current")
		except ValueError:
			QMessageBox.warning(self, "Error", "Invalid selection")
