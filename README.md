# Watchback

Watchback is a small personal backup tool designed to continuously mirror important folders to one or more destinations without manual intervention. It was built after encountering several unfortunate events of losing valuable data due no backups. The goal of this project is simple: **set up backups once, and stop worrying about them.**

Watchback focuses on:

* Continuous syncing
* Multiple mirror locations
* Automatic versioning of changed or deleted files
* Periodic snapshots of file states
* A simple desktop GUI

---

## Features

* **Ground → Mirror model**

  * One source folder (ground truth)
  * One or more mirror folders
* **Real-time syncing**

  * Uses filesystem monitoring to propagate changes automatically
* **Versioning**

  * Old versions of files are stored instead of overwritten
* **Snapshots**

  * Lightweight snapshots of file structure for historical reference
* **Simple GUI**

  * Create, edit, and control backup profiles visually

---

## How It Works

Each profile contains:

* One **ground folder** (source of truth)
* One or more **mirror folders**

Each mirror contains:

```
mirror/
├── current/     # live mirrored files
├── versions/    # old versions of files
└── snapshots/   # periodic snapshot manifests
```

When files change:

* Modified files are copied to mirrors
* Old versions are moved to `versions/`
* Snapshots are created periodically if changes occurred

---

## Requirements

* Python **3.11+**
* Supported OS: Linux, macOS, Windows

---

## Installation

Clone the repository:

```bash
git clone <repo-url>
cd watchback
```

Install with pip:

```bash
pip install .
```

Or in editable (dev) mode:

```bash
pip install -e .
```

---

## Running

After installation:

```bash
watchback
```

Or directly from source:

```bash
python main.py
```

---

## Configuration

Profiles are stored at:

```
~/.watchback.json
```

Each profile defines:

* Profile name
* Ground folder
* Mirror folders

The GUI handles all configuration.

---

## Safety Notes

* This tool mirrors **from ground → mirrors only**
* Do not edit files directly inside mirror `current/` folders
* Always keep mirrors on separate drives or locations

---

## Project Status

This is a small hobby project built for personal use.
It is functional, but not intended to compete with enterprise backup software.

---

## License

This project is licensed under the MIT License – see the LICENSE file for details.

