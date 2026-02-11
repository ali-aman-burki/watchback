import os
import shutil
import threading
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


# ---------------------------
# Utilities
# ---------------------------

def files_differ(src: Path, dst: Path) -> bool:
	if not dst.exists():
		return True
	if src.stat().st_size != dst.stat().st_size:
		return True
	if abs(src.stat().st_mtime - dst.stat().st_mtime) > 1:
		return True
	return False


# ---------------------------
# Mirror worker
# ---------------------------

class MirrorWorker(QThread):
	status = Signal(str, str)      # mirror_path, status
	progress = Signal(str, int)    # mirror_path, percent
	finished = Signal(str)

	def __init__(self, ground: str, mirror: str):
		super().__init__()
		self.ground = Path(ground)
		self.mirror = Path(mirror)
		self._stop_event = threading.Event()

	def current_root(self):
		return self.mirror / "current"

	def version_path(self, path: Path) -> Path:
		rel = path.relative_to(self.current_root())
		timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
		return self.mirror / ".versions" / rel / timestamp

	def version_file(self, path: Path):
		if not path.exists() or path.is_dir():
			return

		vpath = self.version_path(path)
		vpath.parent.mkdir(parents=True, exist_ok=True)
		shutil.move(str(path), str(vpath))


	def stop(self):
		self._stop_event.set()

	def run(self):
		try:
			self.status.emit(str(self.mirror), "SYNCING")
			self.sync_full()

			if not self._stop_event.is_set():
				self.progress.emit(str(self.mirror), 100)
				self.status.emit(str(self.mirror), "SYNCED")
			else:
				self.status.emit(str(self.mirror), "SYNCED")

		except Exception as e:
			self.status.emit(str(self.mirror), f"ERROR: {e}")
		finally:
			self.finished.emit(str(self.mirror))

	def sync_full(self):
		src_files = []
		src_dirs = []

		self.current_root().mkdir(parents=True, exist_ok=True)

		# Scan ground
		for root, dirs, files in os.walk(self.ground):
			root_path = Path(root)
			src_dirs.append(root_path)

			for f in files:
				src_files.append(root_path / f)

		# Create directories first (including empty ones)
		for d in src_dirs:
			if self._stop_event.is_set():
				return

			rel = d.relative_to(self.ground)
			dst = self.current_root() / rel
			dst.mkdir(parents=True, exist_ok=True)

		total = len(src_files)
		processed = 0

		# Copy/update files
		for src in src_files:
			if self._stop_event.is_set():
				return

			rel = src.relative_to(self.ground)
			dst = self.current_root() / rel
			dst.parent.mkdir(parents=True, exist_ok=True)

			if files_differ(src, dst):
				if dst.exists():
					self.version_file(dst)
				shutil.copy2(src, dst)

			processed += 1
			percent = int((processed / total) * 100) if total else 100
			self.progress.emit(str(self.mirror), percent)

		# Delete extra files
		for root, _, files in os.walk(self.current_root()):
			for f in files:
				if self._stop_event.is_set():
					return

				dst = Path(root) / f
				rel = dst.relative_to(self.current_root())
				src = self.ground / rel

				if not src.exists():
					self.version_file(dst)

		# Delete extra directories
		for root, dirs, _ in os.walk(self.current_root(), topdown=False):
			for d in dirs:
				path = Path(root) / d
				rel = path.relative_to(self.current_root())
				src = self.ground / rel

				if not src.exists():
					shutil.rmtree(path, ignore_errors=True)


# ---------------------------
# Watchdog handler
# ---------------------------

class ChangeHandler(FileSystemEventHandler):
	def __init__(self, trigger, is_running):
		self.trigger = trigger
		self.is_running = is_running
		self.pending = set()
		self.lock = threading.Lock()
		self.timer = None

	def _flush(self):
		with self.lock:
			paths = list(self.pending)
			self.pending.clear()
			self.timer = None

		if not self.is_running():
			return

		for p in paths:
			self.trigger(p)

	def on_any_event(self, event):
		if event.is_directory and event.event_type == "modified":
			return

		with self.lock:
			self.pending.add(event.src_path)

			if self.timer is None:
				self.timer = threading.Timer(0.2, self._flush)
				self.timer.daemon = True
				self.timer.start()

# ---------------------------
# Profile sync controller
# ---------------------------

class ProfileSync:
	def __init__(self, profile):
		self.profile = profile
		self.workers = []
		self.observer = None
		self.running = False

	def sync_single(self, changed_path):
		ground = Path(self.ground())
		src = Path(changed_path)

		try:
			rel = src.relative_to(ground)
		except ValueError:
			return  # outside ground, ignore

		for mirror in self.mirrors():
			mirror = Path(mirror)
			current_root = mirror / "current"
			current_root.mkdir(parents=True, exist_ok=True)
			dst = current_root / rel

			try:
				if src.exists():
					if src.is_dir():
						dst.mkdir(parents=True, exist_ok=True)
					else:
						if files_differ(src, dst):
							if dst.exists():
								# version old file
								timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
								vpath = (
									mirror
									/ ".versions"
									/ rel
									/ timestamp
								)
								vpath.parent.mkdir(parents=True, exist_ok=True)
								shutil.move(str(dst), str(vpath))

							dst.parent.mkdir(parents=True, exist_ok=True)
							shutil.copy2(src, dst)
				else:
					if dst.exists():
						if dst.is_dir():
							shutil.rmtree(dst)
						else:
							# version deleted file
							timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
							vpath = (
								mirror
								/ ".versions"
								/ rel
								/ timestamp
							)
							vpath.parent.mkdir(parents=True, exist_ok=True)
							shutil.move(str(dst), str(vpath))
			except Exception:
				pass

	def ground(self):
		return next(p["path"] for p in self.profile["paths"] if p["role"] == "ground")

	def mirrors(self):
		return [p["path"] for p in self.profile["paths"] if p["role"] == "mirror"]

	def _on_worker_finished(self, worker):
		if worker in self.workers:
			self.workers.remove(worker)
		worker.deleteLater()

	def start(self, status_cb, mirror_status_cb, progress_cb=None):
		if self.observer:
			self.stop(None)
		
		self.running = True

		ground = self.ground()
		self.workers = []

		for mirror in self.mirrors():
			worker = MirrorWorker(ground, mirror)
			worker.status.connect(mirror_status_cb)
			if progress_cb:
				worker.progress.connect(progress_cb)

			worker.finished.connect(lambda _, w=worker: self._on_worker_finished(w))

			worker.start()
			self.workers.append(worker)

		# Watchdog for incremental updates
		handler = ChangeHandler(self.sync_single, lambda: self.running)
		self.observer = Observer()
		self.observer.schedule(handler, ground, recursive=True)
		self.observer.start()

		status_cb("SYNCING")


	def stop(self, status_cb):
		for w in list(self.workers):
			w.stop()
			w.wait()

		if self.observer:
			obs = self.observer
			self.observer = None
			obs.stop()
			try:
				obs.join()
			except RuntimeError:
				pass

		if status_cb:
			status_cb("IDLE")
		
		self.running = False