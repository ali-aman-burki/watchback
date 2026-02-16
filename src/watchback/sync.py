import os
import json
import time
import shutil
import logging
import hashlib
import threading

from pathlib import Path
from datetime import datetime

from PySide6.QtCore import QThread, Signal
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logger = logging.getLogger("watchback")

def file_hash(path: Path, chunk_size=1024 * 1024):
	h = hashlib.sha256()
	with open(path, "rb") as f:
		while True:
			chunk = f.read(chunk_size)
			if not chunk:
				break
			h.update(chunk)
	return h.hexdigest()


def object_path(mirror: Path, h: str) -> Path:
	return mirror / "objects" / h[:2] / h


def store_object(mirror: Path, src: Path) -> str:
	h = file_hash(src)
	opath = object_path(mirror, h)

	if not opath.exists():
		opath.parent.mkdir(parents=True, exist_ok=True)
		shutil.copy2(src, opath)

	return h

def gc_objects(mirror: Path):
	objects_root = mirror / "objects"
	snapshots_root = mirror / "snapshots"
	versions_root = mirror / "versions"

	if not objects_root.exists():
		return

	live_hashes = set()

	if snapshots_root.exists():
		for snap in snapshots_root.glob("*.json"):
			try:
				with open(snap, "r") as f:
					data = json.load(f)

				files = data.get("files", {})
				if isinstance(files, dict):
					live_hashes.update(files.values())
			except Exception:
				pass

	if versions_root.exists():
		for root, _, files in os.walk(versions_root):
			for f in files:
				if not f.endswith(".json"):
					continue
				path = Path(root) / f
				try:
					with open(path, "r") as vf:
						meta = json.load(vf)
					h = meta.get("hash")
					if h:
						live_hashes.add(h)
				except Exception:
					pass

	removed = 0

	for root, _, files in os.walk(objects_root):
		for f in files:
			obj = Path(root) / f
			h = obj.name
			if h not in live_hashes:
				try:
					obj.unlink()
					removed += 1
				except Exception as e:
					logger.warning(f"Failed to delete object {obj}: {e}")

	if removed:
		logger.info(f"Garbage collection removed {removed} unreferenced objects from {mirror}")

def version_file(mirror: Path, rel_path: Path, dst: Path):
	if not dst.exists() or dst.is_dir():
		return

	timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")

	h = store_object(mirror, dst)

	vmeta = mirror / "versions" / rel_path / f"{timestamp}.json"
	vmeta.parent.mkdir(parents=True, exist_ok=True)

	with open(vmeta, "w") as f:
		json.dump({
			"hash": h,
			"size": dst.stat().st_size
		}, f)
	
	logger.info(f"Version created: {rel_path}")

def files_differ(src: Path, dst: Path) -> bool:
	if not dst.exists():
		return True
	if src.stat().st_size != dst.stat().st_size:
		return True
	if abs(src.stat().st_mtime - dst.stat().st_mtime) > 1:
		return True
	return False

def build_snapshot(current_root: Path, mirror: Path):
	files = {}

	for root, _, filenames in os.walk(current_root):
		for f in filenames:
			full = Path(root) / f
			rel = full.relative_to(current_root)
			h = store_object(mirror, full)
			files[str(rel)] = h

	return {
		"timestamp": datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
		"files": files
	}


def snapshot_hash(snapshot):
	encoded = json.dumps(snapshot["files"], sort_keys=True).encode()
	return hashlib.sha256(encoded).hexdigest()


def last_snapshot_hash(snapshots_dir: Path):
	snaps = sorted(snapshots_dir.glob("*.json"))
	if not snaps:
		return None

	last = snaps[-1]
	with open(last, "r") as f:
		data = json.load(f)

	return snapshot_hash(data)

def parse_ts(name: str):
	try:
		return datetime.strptime(name, "%Y-%m-%d_%H-%M-%S").timestamp()
	except Exception:
		return None


def cleanup_snapshots(mirror: Path, retention_seconds: int):
	sdir = mirror / "snapshots"
	if not sdir.exists():
		return

	cutoff = time.time() - retention_seconds
	removed = 0

	for snap in sdir.glob("*.json"):
		try:
			if snap.stat().st_mtime < cutoff:
				snap.unlink(missing_ok=True)
				removed += 1
		except Exception as e:
			logger.warning(f"Failed to delete snapshot {snap}: {e}")

	if removed:
		logger.info(f"Removed {removed} old snapshots from {mirror}")



def cleanup_versions(mirror: Path, retention_seconds: int):
	vroot = mirror / "versions"
	if not vroot.exists():
		return

	cutoff = time.time() - retention_seconds
	removed = 0

	for root, _, files in os.walk(vroot):
		for f in files:
			ts = parse_ts(f)
			if ts and ts < cutoff:
				try:
					(Path(root) / f).unlink()
					removed += 1
				except Exception as e:
					logger.warning(f"Failed to delete version {f}: {e}")

	if removed:
		logger.info(f"Removed {removed} old versions from {mirror}")

def apply_retention(mirror: Path, retention_seconds: int):
	if not retention_seconds:
		return

	cleanup_snapshots(mirror, retention_seconds)
	cleanup_versions(mirror, retention_seconds)

	gc_objects(mirror)

class MirrorWorker(QThread):
	status = Signal(str, str)
	progress = Signal(str, int)
	finished = Signal(str)

	def __init__(self, ground: str, mirror: str):
		super().__init__()
		self.ground = Path(ground)
		self.mirror = Path(mirror)
		self._stop_event = threading.Event()

	def current_root(self):
		return self.mirror / "current"

	def should_snapshot(self, snapshot_interval):
		snapshots_dir = self.mirror / "snapshots"
		if not snapshots_dir.exists():
			return True

		snaps = sorted(snapshots_dir.glob("*.json"))
		if not snaps:
			return True

		last = snaps[-1].stat().st_mtime
		return (time.time() - last) > snapshot_interval

	def maybe_create_snapshot(self):
		snapshots_dir = self.mirror / "snapshots"
		snapshots_dir.mkdir(parents=True, exist_ok=True)

		current = self.current_root()
		snapshot = build_snapshot(current, self.mirror)
		new_hash = snapshot_hash(snapshot)

		old_hash = last_snapshot_hash(snapshots_dir)

		if new_hash == old_hash:
			return None

		ts = snapshot["timestamp"]
		path = snapshots_dir / f"{ts}.json"

		with open(path, "w") as f:
			json.dump(snapshot, f, indent=2)
		
		logger.info(f"Snapshot created: {path}")
		return path.stat().st_mtime

	def stop(self):
		self._stop_event.set()

	def run(self):
		logger.info(f"Mirror sync started: {self.mirror}")
		try:
			self.status.emit(str(self.mirror), "SYNCING")
			self.sync_full()

			if not self._stop_event.is_set():
				self.progress.emit(str(self.mirror), 100)
				self.status.emit(str(self.mirror), "SYNCED")
			else:
				self.status.emit(str(self.mirror), "SYNCED")
			logger.info(f"Mirror sync completed: {self.mirror}")
		except Exception as e:
			self.status.emit(str(self.mirror), f"ERROR: {e}")
			logger.error(f"Mirror sync error ({self.mirror}): {e}")
		finally:
			self.finished.emit(str(self.mirror))

	def sync_full(self):
		src_files = []
		src_dirs = []

		self.current_root().mkdir(parents=True, exist_ok=True)

		for root, dirs, files in os.walk(self.ground):
			root_path = Path(root)
			src_dirs.append(root_path)

			for f in files:
				src_files.append(root_path / f)

		for d in src_dirs:
			if self._stop_event.is_set():
				return

			rel = d.relative_to(self.ground)
			dst = self.current_root() / rel
			dst.mkdir(parents=True, exist_ok=True)

		total = len(src_files)
		processed = 0

		for src in src_files:
			if self._stop_event.is_set():
				return

			rel = src.relative_to(self.ground)
			dst = self.current_root() / rel
			dst.parent.mkdir(parents=True, exist_ok=True)

			if files_differ(src, dst):
				if dst.exists():
					version_file(self.mirror, rel, dst)
				shutil.copy2(src, dst)

			processed += 1
			percent = int((processed / total) * 100) if total else 100
			self.progress.emit(str(self.mirror), percent)

		for root, _, files in os.walk(self.current_root()):
			for f in files:
				if self._stop_event.is_set():
					return

				dst = Path(root) / f
				rel = dst.relative_to(self.current_root())
				src = self.ground / rel

				if not src.exists():
					version_file(self.mirror, rel, dst)

		for root, dirs, _ in os.walk(self.current_root(), topdown=False):
			for d in dirs:
				path = Path(root) / d
				rel = path.relative_to(self.current_root())
				src = self.ground / rel

				if not src.exists():
					shutil.rmtree(path, ignore_errors=True)


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

class ProfileSync:
	def __init__(self, profile, on_profile_change=None):
		self.profile = profile
		self.on_profile_change = on_profile_change
		self.workers = []
		self.observer = None
		self.running = False
		self.snapshot_thread = None
		self.snapshot_stop = threading.Event()
		self.snapshot_status_cb = None
		self.last_snapshot_time = self._parse_snapshot_time(
			profile.get("last_snapshot_time")
		)
		self.snapshot_interval = profile.get("snapshot_interval", 3600)

	def _parse_snapshot_time(self, value):
		try:
			if value is None:
				return None
			return float(value)
		except (TypeError, ValueError):
			return None

	def _set_last_snapshot_time(self, ts):
		ts = self._parse_snapshot_time(ts)
		if ts is None:
			return False

		if self.last_snapshot_time is not None and ts <= self.last_snapshot_time:
			return False

		self.last_snapshot_time = ts
		self.profile["last_snapshot_time"] = ts

		if self.on_profile_change:
			try:
				self.on_profile_change()
			except Exception as e:
				logger.warning(f"Failed to persist profile update: {e}")

		return True

	def load_last_snapshot_time(self):
		latest_time = self._parse_snapshot_time(
			self.profile.get("last_snapshot_time")
		)

		for mirror in self.mirrors():
			snapshots_dir = Path(mirror) / "snapshots"
			if not snapshots_dir.exists():
				continue

			snaps = sorted(snapshots_dir.glob("*.json"))
			if not snaps:
				continue

			last = snaps[-1]
			ts = last.stat().st_mtime

			if latest_time is None or ts > latest_time:
				latest_time = ts

		if latest_time is not None:
			self.last_snapshot_time = latest_time
			self.profile["last_snapshot_time"] = latest_time


	def _emit_snapshot_status(self):
		if not self.snapshot_status_cb:
			return

		if not self.last_snapshot_time:
			self.snapshot_status_cb("Waiting for first snapshot")
			return

		now = time.time()
		age = int(now - self.last_snapshot_time)

		intervals_passed = age // self.snapshot_interval
		next_boundary = self.last_snapshot_time + (intervals_passed + 1) * self.snapshot_interval
		next_in = int(next_boundary - now)

		def fmt(seconds):
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

		if age < 60:
			age_text = "Just Now"
		else:
			age_text = f"{fmt(age)} ago"

		next_text = fmt(next_in)

		self.snapshot_status_cb(
			f"{age_text} (next in {next_text})"
		)

	def create_snapshots_now(self):
		created = False

		for mirror in self.mirrors():
			try:
				worker = MirrorWorker(self.ground(), mirror)
				snapshot_time = worker.maybe_create_snapshot()
				if snapshot_time is not None:
					created = self._set_last_snapshot_time(snapshot_time) or created

				retention = self.profile.get("retention_seconds")
				if retention:
					apply_retention(Path(mirror), retention)
			except Exception:
				pass

		if created:
			self._emit_snapshot_status()


	def snapshot_loop(self):
		while not self.snapshot_stop.is_set():
			if not self.running:
				time.sleep(1)
				continue

			now = time.time()

			if not self.last_snapshot_time:
				next_time = now
			else:
				age = now - self.last_snapshot_time
				intervals_passed = int(age // self.snapshot_interval)
				next_time = (
					self.last_snapshot_time
					+ (intervals_passed + 1) * self.snapshot_interval
				)

			sleep_for = max(1, int(next_time - now))

			if self.snapshot_stop.wait(sleep_for):
				break

			created = False

			for mirror in self.mirrors():
				try:
					worker = MirrorWorker(self.ground(), mirror)

					snapshot_time = worker.maybe_create_snapshot()
					if snapshot_time is not None:
						created = self._set_last_snapshot_time(snapshot_time) or created

					retention = self.profile.get("retention_seconds")
					if retention:
						apply_retention(Path(mirror), retention)

				except Exception:
					pass

			self._emit_snapshot_status()


	def start_snapshot_timer(self):
		if self.snapshot_thread:
			return

		self.snapshot_stop.clear()
		self.snapshot_thread = threading.Thread(
			target=self.snapshot_loop,
			daemon=True
		)
		self.snapshot_thread.start()


	def sync_single(self, changed_path):
		ground = Path(self.ground())
		src = Path(changed_path)

		try:
			rel = src.relative_to(ground)
		except ValueError:
			return

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
							if dst.exists() and dst.is_file():
								version_file(mirror, rel, dst)

							dst.parent.mkdir(parents=True, exist_ok=True)
							shutil.copy2(src, dst)

				else:
					if dst.exists():
						if dst.is_dir():
							shutil.rmtree(dst)
						else:
							version_file(mirror, rel, dst)
							dst.unlink(missing_ok=True)

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

		if not self.workers and self.running:
			self.create_snapshots_now()
			self.start_snapshot_timer()

	def start(self, status_cb, mirror_status_cb, progress_cb=None, snapshot_status_cb=None):
		self.snapshot_status_cb = snapshot_status_cb

		if self.observer:
			self.stop(None)
		
		self.running = True
		self.load_last_snapshot_time()

		if self.last_snapshot_time:
			self._emit_snapshot_status()
		else:
			if self.snapshot_status_cb:
				self.snapshot_status_cb("Waiting for first snapshot")

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

		handler = ChangeHandler(self.sync_single, lambda: self.running)
		self.observer = Observer()
		self.observer.schedule(handler, ground, recursive=True)
		self.observer.start()

		status_cb("SYNCING")

		logger.info(f"Profile sync engine started: {self.profile['name']}")

	def stop(self, status_cb):
		self.running = False
		self.snapshot_stop.set()
		if self.snapshot_thread:
			self.snapshot_thread.join(timeout=1)
			self.snapshot_thread = None

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

		if self.snapshot_status_cb:
			if self.last_snapshot_time:
				age = int(time.time() - self.last_snapshot_time)
				mins = age // 60
				hours = mins // 60
				mins = mins % 60
				self.snapshot_status_cb(f"stopped (last: {hours}h {mins}m ago)")
			else:
				self.snapshot_status_cb("stopped")

		logger.info(f"Profile sync engine stopped: {self.profile['name']}")
		
