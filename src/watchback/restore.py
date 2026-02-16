import os
import json
import shutil
from pathlib import Path
from datetime import datetime
from zipfile import ZipFile, ZIP_DEFLATED

def object_path(mirror: Path, h: str) -> Path:
    return mirror / "objects" / h[:2] / h

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

			# if directory has version files, it represents a file path
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
	def restore_version(mirror: str, ground: str, rel_path: str, timestamp: str):
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

	@staticmethod
	def export_version(mirror: str, rel_path: str, timestamp: str, out_path: str):
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
	def restore_file(mirror: str, ground: str, snapshot_ts: str, rel_path: str):
		mirror = Path(mirror)
		ground = Path(ground)
		rel_path = Path(rel_path)

		src = SnapshotService.resolve_file(mirror, snapshot_ts, rel_path)
		dst = ground / rel_path

		dst.parent.mkdir(parents=True, exist_ok=True)
		shutil.copy2(src, dst)

	@staticmethod
	def restore_folder(mirror: str, ground: str, snapshot_ts: str, rel_path: str):
		mirror = Path(mirror)
		ground = Path(ground)
		rel_path = Path(rel_path)

		snap = SnapshotService._load_snapshot(mirror, snapshot_ts)
		files = snap["files"]

		targets = SnapshotService._files_under_path(files, rel_path)

		for f in targets:
			src = SnapshotService.resolve_file(mirror, snapshot_ts, f)
			dst = ground / f
			dst.parent.mkdir(parents=True, exist_ok=True)
			shutil.copy2(src, dst)

	@staticmethod
	def export_zip(mirror: str, snapshot_ts: str, rel_path: str, out_zip: str, profile_name: str = "snapshot"):
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

		with ZipFile(out_zip, "w", ZIP_DEFLATED) as zf:
			for f in targets:
				src = SnapshotService.resolve_file(mirror, snapshot_ts, f)

				if base_prefix and f.startswith(base_prefix):
					inner = f[len(base_prefix):]
				else:
					inner = f

				arcname = f"{root_name}/{inner}"
				zf.write(src, arcname=arcname)

			info_text = (
				"Watchback Snapshot Export\n"
				"-------------------------\n"
				f"Mirror:   {mirror}\n"
				f"Snapshot: {snapshot_ts}\n"
				f"Exported: {datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}\n"
			)

			zf.writestr("snapshot_info.txt", info_text)


	@staticmethod
	def list_snapshot_files(mirror: str, snapshot_ts: str):
		mirror = Path(mirror)
		snap = SnapshotService._load_snapshot(mirror, snapshot_ts)
		return snap["files"]
