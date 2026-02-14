import json
import os

CONFIG_PATH = os.path.expanduser("~/.watchback.json")

def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {"profiles": []}
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)
