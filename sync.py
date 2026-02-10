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
			dst = self.mirror / rel
			dst.mkdir(parents=True, exist_ok=True)

		total = len(src_files)
		processed = 0

		# Copy/update files
		for src in src_files:
			if self._stop_event.is_set():
				return

			rel = src.relative_to(self.ground)
			dst = self.mirror / rel
			dst.parent.mkdir(parents=True, exist_ok=True)

			if files_differ(src, dst):
				shutil.copy2(src, dst)

			processed += 1
			percent = int((processed / total) * 100) if total else 100
			self.progress.emit(str(self.mirror), percent)

		# Delete extra files
		for root, _, files in os.walk(self.mirror):
			for f in files:
				if self._stop_event.is_set():
					return

				dst = Path(root) / f
				rel = dst.relative_to(self.mirror)
				src = self.ground / rel

				if not src.exists():
					dst.unlink()

		# Delete extra directories
		for root, dirs, _ in os.walk(self.mirror, topdown=False):
			for d in dirs:
				path = Path(root) / d
				rel = path.relative_to(self.mirror)
				src = self.ground / rel

				if not src.exists():
					shutil.rmtree(path, ignore_errors=True)


# ---------------------------
# Watchdog handler
# ---------------------------

class ChangeHandler(FileSystemEventHandler):
	def __init__(self, trigger):
		self.trigger = trigger
		self.last = 0

	def on_any_event(self, event):
		now = time.time()
		if now - self.last > 1:
			# Run trigger in a new thread
			threading.Thread(target=self.trigger, daemon=True).start()
			self.last = now


# ---------------------------
# Profile sync controller
# ---------------------------

class ProfileSync:
	def __init__(self, profile):
		self.profile = profile
		self.workers = []
		self.observer = None

	def ground(self):
		return next(p["path"] for p in self.profile["paths"] if p["role"] == "ground")

	def mirrors(self):
		return [p["path"] for p in self.profile["paths"] if p["role"] == "mirror"]

	def _on_worker_finished(self, worker):
		if worker in self.workers:
			self.workers.remove(worker)
		worker.deleteLater()

	def start(self, status_cb, mirror_status_cb, progress_cb=None):
		ground = self.ground()

		def launch():
			self.stop(None)
			self.workers = []

			for mirror in self.mirrors():
				worker = MirrorWorker(ground, mirror)
				worker.status.connect(mirror_status_cb)
				if progress_cb:
					worker.progress.connect(progress_cb)

				worker.finished.connect(lambda _, w=worker: self._on_worker_finished(w))

				worker.start()
				self.workers.append(worker)

		launch()

		# Watchdog
		handler = ChangeHandler(launch)
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
