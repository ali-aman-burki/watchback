import subprocess
import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


def rsync_sync(source, destination):
	if not os.path.exists(source):
		raise Exception(f"Ground truth missing: {source}")

	if not os.path.exists(destination):
		os.makedirs(destination, exist_ok=True)

	cmd = [
		"rsync",
		"-a",
		"--delete",
		source.rstrip("/") + "/",
		destination.rstrip("/") + "/"
	]
	subprocess.run(
		cmd,
		check=True,
		stdout=subprocess.DEVNULL,
		stderr=subprocess.DEVNULL
	)

class SyncHandler(FileSystemEventHandler):
	def __init__(self, sync_callback):
		self.sync_callback = sync_callback
		self.last_run = 0

	def on_any_event(self, event):
		now = time.time()
		if now - self.last_run > 2:
			self.sync_callback()
			self.last_run = now


class ProfileSync:
	def __init__(self, profile):
		self.profile = profile
		self.observer = None
		self.state = "IDLE"

	def ground(self):
		for p in self.profile["paths"]:
			if p["role"] == "ground":
				return p["path"]
		return None

	def mirrors(self):
		return [p["path"] for p in self.profile["paths"] if p["role"] == "mirror"]

	def run_sync(self, mirror_callback=None):
		ground = self.ground()
		for mirror in self.mirrors():
			try:
				if mirror_callback:
					mirror_callback(mirror, "SYNCING")

				rsync_sync(ground, mirror)

				if mirror_callback:
					mirror_callback(mirror, "SYNCED")
			except Exception:
				if mirror_callback:
					mirror_callback(mirror, "ERROR")

	def start(self, status_callback, mirror_callback=None):
		try:
			self.state = "SYNCING"
			status_callback(self.state)

			self.run_sync(mirror_callback)

			# Start watcher
			handler = SyncHandler(lambda: self.run_sync(mirror_callback))
			self.observer = Observer()
			self.observer.schedule(handler, path=self.ground(), recursive=True)
			self.observer.start()

			self.state = "SYNCED"
			status_callback(self.state)

		except Exception as e:
			self.state = "ERROR"
			status_callback(f"ERROR: {e}")

	def stop(self, status_callback):
		if self.observer:
			self.observer.stop()
			self.observer.join()
		self.state = "IDLE"
		status_callback(self.state)
