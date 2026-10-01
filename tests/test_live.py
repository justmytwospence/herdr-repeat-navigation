"""HERDR_REPEAT_LIVE=1 python3 -B -m unittest tests.test_live -v."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from repeat_navigation.keys import CTRL, chord
from repeat_navigation.screen import Screen

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("HERDR_REPEAT_LIVE") == "1" and shutil.which("herdr"),
                     "set HERDR_REPEAT_LIVE=1 for isolated native client acceptance")
class LiveTest(unittest.TestCase):
    def test_timed_spaces_windows_panes_expiry_popup_passthrough_and_detach(self):
        native = shutil.which("herdr")
        with tempfile.TemporaryDirectory(prefix="repeat-nav-", dir="/tmp") as directory:
            base = Path(directory)
            cfg = base/"config/herdr"
            cfg.mkdir(parents=True)
            modal = base/"modal.py"
            capture = base/"modal-input"
            modal.write_text('import os,tty\nfrom pathlib import Path\ntty.setraw(0)\nprint("MODAL INPUT READY", flush=True)\n'
                             +'p=Path('+repr(str(capture))+')\nwhile True:\n b=os.read(0,4096)\n if not b or b == bytes([4]): break\n with p.open("ab") as f: f.write(b)\n')
            config_path = cfg/"config.toml"
            config_path.write_text('''onboarding = false
[ui.toast]
delivery = "off"
[ui.sound]
enabled = false
[keys]
prefix = "ctrl+b"
next_workspace = "prefix+ctrl+j"
previous_workspace = "prefix+ctrl+k"
next_tab = "prefix+ctrl+n"
previous_tab = "prefix+ctrl+p"
cycle_pane_next = "prefix+ctrl+l"
cycle_pane_previous = "prefix+ctrl+h"
[[keys.command]]
key = "prefix+t"
type = "popup"
command = %s
height = 8
''' % json.dumps(shlex.join([sys.executable, "-B", str(modal)])))
            settings = base/"repeat.json"
            settings.write_text('{"enabled":true,"repeat_ms":500}')
            env = {k:v for k,v in os.environ.items() if not k.startswith("HERDR_")}
            env.update(XDG_CONFIG_HOME=str(base/"config"), XDG_STATE_HOME=str(base/"state"),
                       HERDR_CONFIG_PATH=str(config_path), TERM="xterm-256color", HERDR_DISABLE_SOUND="1")
            session = "repeat-live"
            socket = cfg/"sessions"/session/"herdr.sock"
            log = open(base/"server.log", "w+")
            server = subprocess.Popen([native,"--session",session,"server"],env=env,
                                      stdout=log,stderr=log,stdin=subprocess.DEVNULL)
            client = master = None
            def cli(*args):
                result = subprocess.run([native,"--session",session,*args],env=env,capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                return json.loads(result.stdout)["result"] if result.stdout.strip() else {}
            try:
                deadline=time.monotonic()+10
                while not socket.exists() and server.poll() is None and time.monotonic()<deadline: time.sleep(.05)
                if not socket.exists():
                    log.seek(0); self.fail(log.read())
                spaces=[cli("workspace","create","--label","repeat-space-"+str(i),"--cwd",directory,"--no-focus") for i in range(4)]
                cli("workspace","focus",spaces[0]["workspace"]["workspace_id"])
                wid=spaces[-1]["workspace"]["workspace_id"]
                tabs=[spaces[-1]["tab"]]
                panes=[spaces[-1]["root_pane"]]
                for i in range(3):
                    created=cli("tab","create","--workspace",wid,"--cwd",directory,"--label","repeat-window-"+str(i),"--no-focus")
                    tabs.append(created["tab"]); panes.append(created["root_pane"])
                bottom=cli("pane","split",panes[-1]["pane_id"],"--direction","down","--no-focus")["pane"]
                master,slave=pty.openpty()
                fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack("HHHH",35,140,0,0))
                def tty(): os.setsid(); fcntl.ioctl(0,termios.TIOCSCTTY,0)
                client=subprocess.Popen([sys.executable,"-B",str(ROOT/"repeat.py"),"run","--binary",native,
                                         "--settings",str(settings),"--","--session",session],env=env,
                                        stdin=slave,stdout=slave,stderr=slave,preexec_fn=tty)
                os.close(slave)
                screen=Screen(35,140)
                output=b""
                def pump(seconds=.1):
                    nonlocal output
                    end=time.monotonic()+seconds
                    while time.monotonic()<end:
                        if select.select([master],[],[],.03)[0]:
                            chunk=os.read(master,65536); output+=chunk; screen.feed(chunk)
                            if b"\x1b[6n" in chunk: os.write(master,b"\x1b[1;1R")
                def expect(**values):
                    end=time.monotonic()+8
                    snapshot={}
                    while time.monotonic()<end:
                        pump(.05); snapshot=cli("api","snapshot")["snapshot"]
                        if all(snapshot.get(k)==v for k,v in values.items()): break
                    self.assertTrue(all(snapshot.get(k)==v for k,v in values.items()),
                                    (values,{k:v for k,v in snapshot.items() if k.startswith("focused")},
                                     "\n".join("".join(row) for row in screen.cells[-3:]),output[-1500:]))
                pump(1)
                # One prefix, a Ctrl-j, then two unmodified repeats: three spaces.
                os.write(master,b"\x02"+chord("j",CTRL)+b"jj")
                expect(focused_workspace_id=wid)
                pump(.65)
                os.write(master,b"\x02\x0enn")
                expect(focused_tab_id=tabs[-1]["tab_id"])
                pump(.65)
                os.write(master,b"\x02"+chord("l",CTRL)+b"hl")
                expect(focused_pane_id=bottom["pane_id"])
                pump(.65)
                before=cli("api","snapshot")["snapshot"]["focused_pane_id"]
                os.write(master,b"l")  # Timeout: literal shell text, never another hop.
                pump(.2)
                self.assertEqual(cli("api","snapshot")["snapshot"]["focused_pane_id"],before)
                read=subprocess.run([native,"--session",session,"pane","read",before,"--source","recent-unwrapped","--lines","8"],
                                    env=env,capture_output=True,text=True,timeout=10)
                self.assertEqual(read.returncode,0,read.stderr)
                self.assertIn(" l",read.stdout)
                os.write(master,b"\x03")  # Cancel input in the owned test shell.
                os.write(master,b"\x02t")
                end=time.monotonic()+8
                def visible(): return "\n".join("".join(row) for row in screen.cells)
                while "MODAL INPUT READY" not in visible() and time.monotonic()<end: pump(.1)
                self.assertIn("MODAL INPUT READY",visible())
                pump(.3)
                os.write(master,b"\x02j")
                pump(.2)
                os.write(master,b"j")
                pump(.25)
                self.assertEqual(capture.read_bytes(),b"\x02jj")
                os.write(master,b"\x04")  # Our recorder's explicit exit key.
                pump(.8)
                os.write(master,b"\x02q")
                end=time.monotonic()+5
                while client.poll() is None and time.monotonic()<end:
                    try: pump(.05)
                    except OSError: break  # PTY EOF after the native client detaches.
                self.assertEqual(client.wait(timeout=2),0)
                self.assertEqual(len(cli("workspace","list")["workspaces"]),4)
                client = None  # Detach left the server and its shells alive.
            finally:
                if master is not None: os.close(master)
                if client is not None:
                    client.terminate()
                    try: client.wait(timeout=5)
                    except subprocess.TimeoutExpired: client.kill(); client.wait(timeout=3)
                if socket.exists():
                    subprocess.run([native,"--session",session,"server","stop"],env=env,
                                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
                try: server.wait(timeout=5)
                except subprocess.TimeoutExpired: server.kill(); server.wait(timeout=3)
                log.close()
