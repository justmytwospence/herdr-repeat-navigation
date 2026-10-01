import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from . import config

ID = "repeat-navigation"


def interactive(args):
    if args[:2] == ["session", "attach"]:
        return len(args) == 3
    i = 0
    while i < len(args):
        if args[i] in ("--session", "--remote", "--remote-keybindings") and i+1 < len(args):
            i += 2
        elif args[i] == "--handoff":
            i += 1
        else:
            return False
    return True


def registration(binary):
    result = subprocess.run([binary, "plugin", "list", "--plugin", ID, "--json"],
                            capture_output=True, text=True, timeout=3, check=True)
    plugins = json.loads(result.stdout)["result"]["plugins"]
    if not any(p["plugin_id"] == ID and p["enabled"] for p in plugins):
        return None
    result = subprocess.run([binary, "plugin", "config-dir", ID], capture_output=True,
                            text=True, timeout=3, check=True)
    return Path(result.stdout.strip()) / "config.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Herdr timed-repeat client companion")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--binary", default=shutil.which("herdr"))
    run.add_argument("--settings", type=Path)
    run.add_argument("args", nargs=argparse.REMAINDER)
    action = sub.add_parser("action")
    action.add_argument("name", choices=("status", "enable", "disable"))
    args = parser.parse_args(argv)
    if args.command == "action":
        path = config.injected_path()
        value = config.read(path)
        if args.name != "status":
            value["enabled"] = args.name == "enable"
            config.write(path, value)
        print(json.dumps(dict(value, scope="wrapped clients on this host; no server keyboard hooks")))
        return 0
    native = args.args[1:] if args.args[:1] == ["--"] else args.args
    binary = args.binary
    if not binary or not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        parser.error("--binary must name the real Herdr executable")
    # Tooling, output redirection and ordinary CLI commands never get a PTY,
    # registration queries, input interception, or changed native argv.
    if not interactive(native) or not os.isatty(0) or not os.isatty(1):
        os.execv(binary, [binary] + native)
    try:
        path = args.settings or registration(binary)
        value = config.read(path) if path else {"enabled": False}
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print("repeat-navigation: settings unavailable; using native Herdr", file=sys.stderr)
        value = {"enabled": False}
    if not value["enabled"]:
        os.execv(binary, [binary] + native)
    from .terminal import run as client
    return client(binary, native, path, value)
