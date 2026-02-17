import os
import json
import shutil
import logging
from pathlib import Path
from datetime import datetime
from zipfile import ZipFile, ZIP_DEFLATED

logger = logging.getLogger("watchback")

def object_path(mirror: Path, h: str) -> Path:
    return mirror / "objects" / h[:2] / h


class MirrorService:
	@staticmethod
	def is_watchback_mirror(path: str) -> bool:
		mirror = Path(path)
		if not mirror.exists() or not mirror.is_dir():
			return False

		layout_entries = ["current", "versions", "snapshots", "objects"]
		present = [mirror / name for name in layout_entries]
		return any(entry.exists() for entry in present)

class FileVersionService:
	@staticmethod
	def list_all_versioned_files(mirror: str):
		mirror = Path(mirror)
		vroot = mirror / "versions"

		if not vroot.exists():
			return []

		results = []

		for root, _, files in os.walk(vroot):
			if not files:
				continue

			root_path = Path(root)
			rel = root_path.relative_to(vroot)

			if any(f.endswith(".json") for f in files):
				results.append(str(rel))

		return sorted(results, key=str.lower)

	@staticmethod
	def _version_dir(mirror: Path, rel_path: Path) -> Path:
		return mirror / "versions" / rel_path

	@staticmethod
	def list_versions(mirror: str, rel_path: str):
		mirror = Path(mirror)
		rel_path = Path(rel_path)

		vdir = FileVersionService._version_dir(mirror, rel_path)
		if not vdir.exists():
			return []

		versions = sorted(p.name for p in vdir.iterdir() if p.is_file())
		return versions

	@staticmethod
	def get_version_path(mirror: str, rel_path: str, timestamp: str) -> Path:
		mirror = Path(mirror)
		rel_path = Path(rel_path)
		return mirror / "versions" / rel_path / timestamp

	@staticmethod
	def restore_version(mirror: str, ground: str, rel_path: str, timestamp: str, progress_cb=None):
		if progress_cb:
			progress_cb(0)

		mirror = Path(mirror)
		ground = Path(ground)
		rel_path = Path(rel_path)

		meta_path = FileVersionService.get_version_path(
			mirror, rel_path, timestamp
		)
		if not meta_path.exists():
			raise FileNotFoundError("Version not found")

		with open(meta_path, "r") as f:
			meta = json.load(f)

		h = meta["hash"]
		src = object_path(mirror, h)

		if not src.exists():
			raise FileNotFoundError("Object missing")

		dst = ground / rel_path
		dst.parent.mkdir(parents=True, exist_ok=True)

		shutil.copy2(src, dst)

		if progress_cb:
			progress_cb(100)
		
		logger.info(f"Version restored: {rel_path} @ {timestamp}")

	@staticmethod
	def export_version(mirror: str, rel_path: str, timestamp: str, out_path: str, progress_cb=None):
		if progress_cb:
			progress_cb(0)

		mirror = Path(mirror)
		rel_path = Path(rel_path)

		meta_path = FileVersionService.get_version_path(
			mirror, rel_path, timestamp
		)
		if not meta_path.exists():
			raise FileNotFoundError("Version not found")

		with open(meta_path, "r") as f:
			meta = json.load(f)

		h = meta["hash"]
		src = object_path(mirror, h)

		if not src.exists():
			raise FileNotFoundError("Object missing")

		shutil.copy2(src, out_path)

		if progress_cb:
			progress_cb(100)
		
		logger.info(f"Version exported: {rel_path} @ {timestamp} -> {out_path}")

class SnapshotService:
	@staticmethod
	def _snapshots_dir(mirror: Path) -> Path:
		return mirror / "snapshots"

	@staticmethod
	def list_snapshots(mirror: str):
		mirror = Path(mirror)
		sdir = SnapshotService._snapshots_dir(mirror)
		if not sdir.exists():
			return []

		snaps = sorted(p.stem for p in sdir.glob("*.json"))
		return snaps

	@staticmethod
	def _load_snapshot(mirror: Path, snapshot_ts: str):
		path = mirror / "snapshots" / f"{snapshot_ts}.json"
		if not path.exists():
			raise FileNotFoundError("Snapshot not found")

		with open(path, "r") as f:
			return json.load(f)

	@staticmethod
	def _files_under_path(file_list, rel_path: Path):
		rel_str = str(rel_path).replace("\\", "/").strip("/")

		if rel_str in ("", ".", "./"):
			return file_list

		result = []
		for f in file_list:
			if f == rel_str or f.startswith(rel_str + "/"):
				result.append(f)
		return result

	@staticmethod
	def resolve_file(mirror: str, snapshot_ts: str, rel_path: str) -> Path:
		mirror = Path(mirror)
		rel_path = str(rel_path).replace("\\", "/")

		snap = SnapshotService._load_snapshot(mirror, snapshot_ts)
		files = snap["files"]

		if rel_path not in files:
			raise FileNotFoundError("File not in snapshot")

		h = files[rel_path]
		obj = object_path(mirror, h)

		if not obj.exists():
			raise FileNotFoundError("Object missing")

		return obj

	@staticmethod
	def restore_file(mirror: str, ground: str, snapshot_ts: str, rel_path: str, progress_cb=None):
		if progress_cb:
			progress_cb(0)

		mirror = Path(mirror)
		ground = Path(ground)
		rel_path = Path(rel_path)

		src = SnapshotService.resolve_file(mirror, snapshot_ts, rel_path)
		dst = ground / rel_path

		dst.parent.mkdir(parents=True, exist_ok=True)
		shutil.copy2(src, dst)

		if progress_cb:
			progress_cb(100)

		logger.info(f"Snapshot file restored: {rel_path} from {snapshot_ts}")

	@staticmethod
	def restore_folder(mirror: str, ground: str, snapshot_ts: str, rel_path: str, progress_cb=None):
		mirror = Path(mirror)
		ground = Path(ground)
		rel_path = Path(rel_path)

		snap = SnapshotService._load_snapshot(mirror, snapshot_ts)
		files = snap["files"]

		targets = SnapshotService._files_under_path(files, rel_path)
		total = max(1, len(targets))

		for i, f in enumerate(targets, 1):
			src = SnapshotService.resolve_file(mirror, snapshot_ts, f)
			dst = ground / f
			dst.parent.mkdir(parents=True, exist_ok=True)
			shutil.copy2(src, dst)

			if progress_cb:
				percent = int((i / total) * 100)
				progress_cb(percent)
		
		logger.info(f"Snapshot folder restored: {rel_path} from {snapshot_ts}")

	@staticmethod
	def export_file(mirror: str, snapshot_ts: str, rel_path: str, out_path: str, progress_cb=None):
		if progress_cb:
			progress_cb(0)

		src = SnapshotService.resolve_file(mirror, snapshot_ts, rel_path)
		shutil.copy2(src, out_path)

		if progress_cb:
			progress_cb(100)

		logger.info(f"Snapshot file exported: {rel_path} from {snapshot_ts} -> {out_path}")

	@staticmethod
	def export_zip(mirror: str, snapshot_ts: str, rel_path: str, out_zip: str, profile_name: str = "snapshot", progress_cb=None):
		mirror = Path(mirror)
		rel_path = Path(rel_path)

		snap = SnapshotService._load_snapshot(mirror, snapshot_ts)
		files = snap["files"]

		targets = SnapshotService._files_under_path(files, rel_path)
		if not targets:
			raise FileNotFoundError("Nothing to export")

		rel_str = str(rel_path).strip("/.")
		if rel_str in ("", ".", "./"):
			root_name = profile_name
			base_prefix = ""
		else:
			root_name = Path(rel_str).name
			base_prefix = rel_str + "/"

		total = len(targets)

		with ZipFile(out_zip, "w", ZIP_DEFLATED) as zf:
			for i, f in enumerate(targets, 1):
				src = SnapshotService.resolve_file(mirror, snapshot_ts, f)

				if base_prefix and f.startswith(base_prefix):
					inner = f[len(base_prefix):]
				else:
					inner = f

				arcname = f"{root_name}/{inner}"
				zf.write(src, arcname=arcname)

				if progress_cb:
					percent = int((i / total) * 100)
					progress_cb(percent)

			info_text = (
				"Watchback Snapshot Export\n"
				"-------------------------\n"
				f"Mirror:   {mirror}\n"
				f"Snapshot: {snapshot_ts}\n"
				f"Exported: {datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}\n"
			)
			zf.writestr("snapshot_info.txt", info_text)
		
		logger.info(f"Snapshot folder exported: {rel_path} from {snapshot_ts} -> {out_zip}")

	@staticmethod
	def list_snapshot_files(mirror: str, snapshot_ts: str):
		mirror = Path(mirror)
		snap = SnapshotService._load_snapshot(mirror, snapshot_ts)
		return snap["files"]


class CurrentService:
	@staticmethod
	def _current_root(mirror: Path) -> Path:
		return mirror / "current"

	@staticmethod
	def list_current_files(mirror: str):
		mirror = Path(mirror)
		croot = CurrentService._current_root(mirror)

		if not croot.exists():
			return []

		results = []
		for root, _, files in os.walk(croot):
			root_path = Path(root)
			for name in files:
				full = root_path / name
				rel = full.relative_to(croot)
				results.append(str(rel))

		return sorted(results, key=str.lower)

	@staticmethod
	def _resolve_current_path(mirror: str, rel_path: str) -> Path:
		mirror = Path(mirror)
		croot = CurrentService._current_root(mirror)

		rel = Path(rel_path) if rel_path else Path(".")
		target = (croot / rel).resolve()
		root_resolved = croot.resolve()

		if target != root_resolved and root_resolved not in target.parents:
			raise ValueError("Invalid current path")

		if not target.exists():
			raise FileNotFoundError("Path not found in current")

		return target

	@staticmethod
	def export_current_file(mirror: str, rel_path: str, out_path: str, progress_cb=None):
		if progress_cb:
			progress_cb(0)

		src = CurrentService._resolve_current_path(mirror, rel_path)
		if not src.is_file():
			raise IsADirectoryError("Selected path is not a file")

		shutil.copy2(src, out_path)

		if progress_cb:
			progress_cb(100)

		logger.info(f"Current file exported: {rel_path} -> {out_path}")

	@staticmethod
	def export_current_zip(
		mirror: str,
		rel_path: str,
		out_zip: str,
		profile_name: str = "current",
		progress_cb=None
	):
		mirror = Path(mirror)
		croot = CurrentService._current_root(mirror)

		base = Path(rel_path) if rel_path else Path(".")
		src_base = CurrentService._resolve_current_path(str(mirror), str(base))

		if src_base.is_file():
			targets = [src_base]
			root_name = src_base.name
		else:
			targets = []
			for root, _, files in os.walk(src_base):
				root_path = Path(root)
				for name in files:
					targets.append(root_path / name)

			if base in (Path("."), Path("")):
				root_name = profile_name
			else:
				root_name = base.name

		if not targets:
			raise FileNotFoundError("Nothing to export")

		total = len(targets)

		with ZipFile(out_zip, "w", ZIP_DEFLATED) as zf:
			for i, full in enumerate(targets, 1):
				if src_base.is_file():
					arcname = root_name
				else:
					inner = full.relative_to(src_base)
					arcname = f"{root_name}/{inner}"

				zf.write(full, arcname=arcname)

				if progress_cb:
					progress_cb(int((i / total) * 100))

		logger.info(f"Current export zip created: {rel_path} -> {out_zip}")
