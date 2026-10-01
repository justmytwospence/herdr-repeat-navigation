import json
import os
from pathlib import Path
import tempfile

DEFAULT = {"enabled": True, "repeat_ms": 500}


def read(path):
    if not path.exists():
        return dict(DEFAULT)
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("settings must be an object")
    result = dict(DEFAULT, **value)
    if type(result["enabled"]) is not bool:
        raise ValueError("enabled must be boolean")
    if type(result["repeat_ms"]) is not int or not 100 <= result["repeat_ms"] <= 1500:
        raise ValueError("repeat_ms must be between 100 and 1500")
    return result


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as file:
        temporary = file.name
        json.dump(value, file, indent=2)
        file.write("\n")
    try:
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def injected_path():
    directory = os.environ.get("HERDR_PLUGIN_CONFIG_DIR")
    if not directory:
        raise ValueError("run settings actions through Herdr's plugin action interface")
    return Path(directory) / "config.json"
