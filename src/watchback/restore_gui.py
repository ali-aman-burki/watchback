from PySide6.QtWidgets import (
	QDialog, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
	QListWidget, QPushButton, QHBoxLayout, QWidget,
	QSplitter, QMessageBox, QFileDialog, QComboBox, QLabel,
)
from PySide6.QtCore import Qt, QTimer
from pathlib import Path
import logging
import queue
import threading

from watchback.restore import (
	FileVersionService,
	SnapshotService,
	CurrentService,
)
from watchback.progress import run_with_progress

HOME_DIR = str(Path.home())
logger = logging.getLogger("watchback")


class SnapshotFilesLoader:
	def __init__(self, mirror: str, snapshot: str, token: int, out_queue):
		self.mirror = mirror
		self.snapshot = snapshot
		self.token = token
		self.out_queue = out_queue

	def run(self):
		try:
			raw_files = SnapshotService.list_snapshot_files(self.mirror, self.snapshot)
			if isinstance(raw_files, dict):
				files = list(raw_files.keys())
			else:
				files = list(raw_files)
			files.sort()
			self.out_queue.put(
				{
					"token": self.token,
					"mirror": self.mirror,
					"snapshot": self.snapshot,
					"files": files,
					"error": None,
				}
			)
		except Exception as e:
			self.out_queue.put(
				{
					"token": self.token,
					"mirror": self.mirror,
					"snapshot": self.snapshot,
					"files": None,
					"error": str(e),
				}
			)

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
		self.tree.itemClicked.connect(self.on_item_selected)
		self.tree.itemExpanded.connect(self.on_item_expanded)
		layout.addWidget(self.tree)

		self.list_widget = QListWidget()
		self.list_widget.itemClicked.connect(self.on_list_item_selected)
		self.list_widget.hide()
		layout.addWidget(self.list_widget)

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
		self._snapshot_files_cache = {}
		self._snapshot_load_errors = {}
		self._snapshot_dir_children_cache = {}
		self._snapshot_load_queue = queue.Queue()
		self._snapshot_load_token = 0
		self._snapshot_loads_in_flight = set()
		self._tree_widget_key = None
		self._list_widget_key = None
		self._load_poll_timer = QTimer(self)
		self._load_poll_timer.setInterval(50)
		self._load_poll_timer.timeout.connect(self._drain_snapshot_load_queue)
		self._load_poll_timer.start()

		self.load_snapshots()

	def toggle_view(self):
		if self.view_mode == "tree":
			self.view_mode = "list"
			self.toggle_btn.setText("Switch to Tree View")
			logger.info("[SnapshotExplorer] Toggle view -> list")
		else:
			self.view_mode = "tree"
			self.toggle_btn.setText("Switch to List View")
			logger.info("[SnapshotExplorer] Toggle view -> tree")

		self._apply_view_visibility()
		self.populate_tree()

	def load_snapshots(self):
		snaps = SnapshotService.list_snapshots(self.mirror)
		self.snapshot_combo.blockSignals(True)
		self.snapshot_combo.clear()
		self._tree_widget_key = None
		self._list_widget_key = None
		self.tree.clear()
		self.list_widget.clear()
		logger.info(f"[SnapshotExplorer] Loading snapshots for mirror: {self.mirror}")

		if not snaps:
			self.snapshot_combo.addItem("(no snapshots)")
			self.snapshot_combo.blockSignals(False)
			self.snapshot = None
			self._apply_view_visibility()
			logger.info("[SnapshotExplorer] No snapshots found")
			return

		for s in snaps:
			self.snapshot_combo.addItem(s)

		self.snapshot = snaps[-1]
		self.snapshot_combo.setCurrentText(self.snapshot)
		self.snapshot_combo.blockSignals(False)
		logger.info(f"[SnapshotExplorer] Loaded {len(snaps)} snapshots, default={self.snapshot}")
		self._apply_view_visibility()
		self.populate_tree()

	def on_mirror_changed(self, text):
		self.mirror = text
		logger.info(f"[SnapshotExplorer] Mirror changed -> {self.mirror}")
		self.load_snapshots()

	def on_snapshot_changed(self, text):
		if text == "(no snapshots)":
			self.snapshot = None
			self.tree.clear()
			self.list_widget.clear()
			self._tree_widget_key = None
			self._list_widget_key = None
			logger.info("[SnapshotExplorer] Snapshot changed -> none")
			return
		self.snapshot = text
		self.current_rel_path = ""
		self._tree_widget_key = None
		self._list_widget_key = None
		self.tree.clear()
		self.list_widget.clear()
		logger.info(f"[SnapshotExplorer] Snapshot changed -> {self.snapshot}")
		self.populate_tree()

	def populate_tree(self):
		if not self.snapshot:
			logger.info("[SnapshotExplorer] populate_tree skipped (no snapshot)")
			return

		key = (self.mirror, self.snapshot)
		files = self._snapshot_files_cache.get(key)
		if files is None:
			err = self._snapshot_load_errors.get(key)
			if err:
				if self.view_mode == "list":
					self.list_widget.clear()
					self.list_widget.addItem(f"Error: {err}")
				else:
					self.tree.clear()
					self.tree.addTopLevelItem(QTreeWidgetItem([f"Error: {err}"]))
				logger.info(f"[SnapshotExplorer] Snapshot load error for {key}: {err}")
				return
			self._set_loading_state()
			self._load_snapshot_files_async(self.mirror, self.snapshot)
			logger.info(f"[SnapshotExplorer] Cache miss for files {key}; loading async")
			return

		if self.view_mode == "list":
			if self._list_widget_key == key:
				logger.info(f"[SnapshotExplorer] Reusing cached list widget for {key}")
				return
			self.list_widget.clear()
			for f in files:
				self.list_widget.addItem(f)
			self._list_widget_key = key
			logger.info(f"[SnapshotExplorer] Built list widget for {key} ({len(files)} files)")

			return

		if self._tree_widget_key == key:
			logger.info(f"[SnapshotExplorer] Reusing cached tree widget for {key}")
			return

		self.tree.clear()
		root_item = QTreeWidgetItem(["/"])
		root_item.setData(0, Qt.UserRole, "")
		root_item.setData(0, Qt.UserRole + 1, True)
		root_item.setData(0, Qt.UserRole + 2, False)
		root_item.addChild(QTreeWidgetItem([""]))
		self.tree.addTopLevelItem(root_item)
		self._tree_widget_key = key
		logger.info(f"[SnapshotExplorer] Built tree root for {key}")
		root_item.setExpanded(True)

	def on_item_expanded(self, item):
		if self.view_mode != "tree":
			return
		if not item.data(0, Qt.UserRole + 1):
			return
		if item.data(0, Qt.UserRole + 2):
			return

		rel = item.data(0, Qt.UserRole) or ""
		files = self._snapshot_files_cache.get((self.mirror, self.snapshot))
		if files is None:
			item.takeChildren()
			item.addChild(QTreeWidgetItem(["Loading..."]))
			self._load_snapshot_files_async(self.mirror, self.snapshot)
			return

		children = self._get_dir_children(rel, files)
		item.takeChildren()

		for name, is_dir in children:
			child_rel = str(Path(rel) / name) if rel else name
			child = QTreeWidgetItem([name])
			child.setData(0, Qt.UserRole, child_rel)
			child.setData(0, Qt.UserRole + 1, is_dir)
			child.setData(0, Qt.UserRole + 2, False)
			if is_dir:
				child.addChild(QTreeWidgetItem([""]))
			item.addChild(child)

		item.setData(0, Qt.UserRole + 2, True)

	def _apply_view_visibility(self):
		is_tree = self.view_mode == "tree"
		self.tree.setVisible(is_tree)
		self.list_widget.setVisible(not is_tree)

	def _set_loading_state(self):
		if self.view_mode == "list":
			self.list_widget.clear()
			self.list_widget.addItem("Loading snapshot...")
		else:
			self.tree.clear()
			item = QTreeWidgetItem(["Loading snapshot..."])
			item.setData(0, Qt.UserRole, None)
			item.setData(0, Qt.UserRole + 1, False)
			item.setData(0, Qt.UserRole + 2, True)
			self.tree.addTopLevelItem(item)

	def _load_snapshot_files_async(self, mirror: str, snapshot: str):
		key = (mirror, snapshot)
		if key in self._snapshot_loads_in_flight:
			logger.info(f"[SnapshotExplorer] Async load already in flight for {key}")
			return

		self._snapshot_load_token += 1
		token = self._snapshot_load_token
		self._snapshot_loads_in_flight.add(key)
		logger.info(f"[SnapshotExplorer] Async load start for {key}, token={token}")

		loader = SnapshotFilesLoader(mirror, snapshot, token, self._snapshot_load_queue)
		threading.Thread(target=loader.run, daemon=True).start()

	def _drain_snapshot_load_queue(self):
		updated_current = False
		while True:
			try:
				msg = self._snapshot_load_queue.get_nowait()
			except queue.Empty:
				break

			key = (msg["mirror"], msg["snapshot"])
			self._snapshot_loads_in_flight.discard(key)

			if msg["error"] is None and msg["files"] is not None:
				self._snapshot_files_cache[key] = msg["files"]
				self._snapshot_load_errors.pop(key, None)
				logger.info(
					f"[SnapshotExplorer] Async load complete for {key}: "
					f"{len(msg['files'])} files cached"
				)
			elif msg["error"] is not None:
				self._snapshot_load_errors[key] = msg["error"]
				logger.info(f"[SnapshotExplorer] Async load failed for {key}: {msg['error']}")

			if (
				msg["token"] == self._snapshot_load_token
				and key == (self.mirror, self.snapshot)
			):
				updated_current = True

		if updated_current:
			self.populate_tree()

	def _get_dir_children(self, rel: str, files):
		cache_key = (self.mirror, self.snapshot, rel)
		cached = self._snapshot_dir_children_cache.get(cache_key)
		if cached is not None:
			logger.info(
				f"[SnapshotExplorer] Dir cache hit for "
				f"{(self.mirror, self.snapshot, rel)} ({len(cached)} children)"
			)
			return cached

		prefix = f"{rel}/" if rel else ""
		children_map = {}
		for f in files:
			if rel:
				if not f.startswith(prefix):
					continue
				tail = f[len(prefix):]
			else:
				tail = f

			if not tail:
				continue

			part, has_sep, _rest = tail.partition("/")
			if not part:
				continue

			is_dir = bool(has_sep)
			if part not in children_map or is_dir:
				children_map[part] = is_dir

		children = sorted(
			children_map.items(),
			key=lambda pair: (not pair[1], pair[0].lower(), pair[0]),
		)
		self._snapshot_dir_children_cache[cache_key] = children
		logger.info(
			f"[SnapshotExplorer] Dir cache miss for "
			f"{(self.mirror, self.snapshot, rel)} -> cached {len(children)} children"
		)
		return children

	def closeEvent(self, event):
		total_file_entries = sum(len(v) for v in self._snapshot_files_cache.values())
		logger.info(
			"[SnapshotExplorer] Closing dialog; clearing caches: "
			f"snapshot_keys={len(self._snapshot_files_cache)}, "
			f"file_entries={total_file_entries}, "
			f"dir_entries={len(self._snapshot_dir_children_cache)}, "
			f"in_flight={len(self._snapshot_loads_in_flight)}"
		)
		self._load_poll_timer.stop()
		self._snapshot_load_token += 1
		self._snapshot_loads_in_flight.clear()
		self._snapshot_files_cache.clear()
		self._snapshot_load_errors.clear()
		self._snapshot_dir_children_cache.clear()
		self._tree_widget_key = None
		self._list_widget_key = None
		logger.info("[SnapshotExplorer] Cache clear complete")
		super().closeEvent(event)

	def on_item_selected(self, item):
		rel = item.data(0, Qt.UserRole)
		if rel in ("", ".", "/"):
			rel = ""
		self.current_rel_path = rel

	def on_list_item_selected(self, item):
		rel = item.text().strip()
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
