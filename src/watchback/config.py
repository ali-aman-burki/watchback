import json
import os
import logging
from pathlib import Path

BASE_DIR = Path(os.path.expanduser("~/.watchback"))
CONFIG_PATH = BASE_DIR / "watchback.json"
LOG_PATH = BASE_DIR / "watchback.log"

def ensure_base_dir():
    BASE_DIR.mkdir(parents=True, exist_ok=True)

def setup_logging():
    ensure_base_dir()

    logger = logging.getLogger("watchback")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s"
    )

    file_handler = logging.FileHandler(LOG_PATH)
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    return logger

def load_config():
    ensure_base_dir()
    setup_logging()

    if not CONFIG_PATH.exists():
        return {"profiles": []}

    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def save_config(config):
    ensure_base_dir()
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)

    logger = logging.getLogger("watchback")
    logger.info("Config saved")
