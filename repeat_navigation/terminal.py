"""POSIX interactive client companion; native output is byte-for-byte passthrough."""
import errno
import fcntl
import os
import pty
import select
import signal
import struct
import termios
import time
import tty
from . import config
from .engine import Engine
from .keys import Decoder
from .screen import Screen


def write_all(fd, data):
    view = memoryview(data)
    while view:
        try:
            written = os.write(fd, view)
        except InterruptedError:
            continue
        if written == 0:
            raise OSError("short terminal write")
        view = view[written:]


def run(binary, args, settings_path, settings):
    original = termios.tcgetattr(0)
    size = fcntl.ioctl(0, termios.TIOCGWINSZ, b"\0" * 8)
    rows, columns, _, _ = struct.unpack("HHHH", size)
    screen = Screen(rows or 24, columns or 80)
    decoder = Decoder()
    engine = Engine(settings["repeat_ms"] / 1000)
    enabled = settings["enabled"]
    old_handlers = {}
    child = master = None
    stopping = False
    def resize(signum=None, frame=None):
        new_size = fcntl.ioctl(0, termios.TIOCGWINSZ, b"\0" * 8)
        fcntl.ioctl(master, termios.TIOCSWINSZ, new_size)
        row_count, column_count, _, _ = struct.unpack("HHHH", new_size)
        screen.resize(row_count or 24, column_count or 80)
    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        try:
            os.kill(child, signum)  # Only the owned interactive client, never its server.
        except ProcessLookupError:
            pass
    try:
        child, master = pty.fork()
        if child == 0:
            os.execv(binary, [binary] + args)
        fcntl.ioctl(master, termios.TIOCSWINSZ, size)
        tty.setraw(0)
        for sig in (signal.SIGWINCH, signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            old_handlers[sig] = signal.signal(sig, resize if sig == signal.SIGWINCH else stop)
        last_input = last_config = time.monotonic()
        while not stopping:
            now = time.monotonic()
            if now-last_config > 1:
                try:
                    value = config.read(settings_path)
                    engine.timeout = value["repeat_ms"] / 1000
                    enabled = value["enabled"]
                except (OSError, ValueError):
                    enabled = False  # Malformed configuration disables interception.
                last_config = now
            if not enabled:
                if engine.pending:
                    write_all(master, engine.pending.raw)
                    engine.pending = None
                engine.stop()
                engine.prefix = False
                while engine.queue:
                    write_all(master, engine.queue.popleft().raw)
            readable, _, _ = select.select([0, master], [], [], 0.02)
            if master in readable:
                try:
                    data = os.read(master, 65536)
                except OSError as error:
                    if error.errno == errno.EIO:
                        break
                    raise
                if not data:
                    break
                write_all(1, data)
                screen.feed(data)
            if 0 in readable:
                data = os.read(0, 4096)
                if not data:
                    break
                last_input = now
                if enabled:
                    engine.feed(decoder.feed(data))
                else:
                    write_all(master, data)
            if enabled:
                if decoder.buffer and now-last_input >= 0.035:
                    engine.feed(decoder.feed(b"", flush=True))
                output = engine.drain(now, screen.generation, screen.prefix_visible, screen.ready, screen.scene)
                if output:
                    write_all(master, output)
        termios.tcsetattr(0, termios.TCSADRAIN, original)
        os.close(master)
        master = None
        # The PTY's close sends HUP to this client, not the independent server.
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            pid, status = os.waitpid(child, os.WNOHANG)
            if pid:
                return os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else (os.WEXITSTATUS(status) if os.WIFEXITED(status) else 128+os.WTERMSIG(status))
            time.sleep(0.02)
        os.kill(child, signal.SIGTERM)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            pid, status = os.waitpid(child, os.WNOHANG)
            if pid:
                return os.WEXITSTATUS(status) if os.WIFEXITED(status) else 128+os.WTERMSIG(status)
            time.sleep(0.02)
        os.kill(child, signal.SIGKILL)
        os.waitpid(child, 0)
        return 1
    finally:
        termios.tcsetattr(0, termios.TCSADRAIN, original)
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        if master is not None:
            os.close(master)
        if child is not None:
            try:
                pid, _ = os.waitpid(child, os.WNOHANG)
                if not pid:
                    os.kill(child, signal.SIGTERM)
            except (ChildProcessError, ProcessLookupError):
                pass
