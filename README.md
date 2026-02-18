# Watchback
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

Simple desktop backup app: pick a source folder, pick one or more mirror folders, click `Sync`, and Watchback keeps mirrors updated.

## Quick Start

1. Install:
```bash
pip install watchback
```
2. Run:
```bash
watchback
```
3. In the app:
- Click `Add Profile`
- Add at least 2 folders
- Double-click one folder to mark it as `[GROUND]` (source of truth)
- Click `Save Profile`
- Click `Sync`

That is it. While sync is running, file changes are mirrored automatically.

## Open Existing Mirror (No Profile Needed)

If you attach a drive that already contains a Watchback mirror, you can use it directly:

1. Click `Open Mirror`
2. Select the mirror folder
3. Choose one of:
- `Explore Current`
- `Explore Versions`
- `Explore Snapshots`

You can export files from the mirror without creating a local profile first.

## What It Stores In Mirrors

Each mirror gets:

```text
mirror/
├── current/    # live copy
├── versions/   # older file versions
├── snapshots/  # periodic state history
└── objects/    # content storage used by versions/snapshots
```

## Important Notes

- Sync direction is one-way: `GROUND -> MIRROR`.
- Do not edit files inside mirror folders directly.
- Settings and logs are stored in:
  - `~/.watchback/watchback.json`
  - `~/.watchback/watchback.log`

## Requirements

- Python `3.11+`
- Linux, macOS, or Windows

## License

MIT. See `LICENSE`.
