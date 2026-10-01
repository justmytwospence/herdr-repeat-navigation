import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from repeat_navigation import config
from repeat_navigation.cli import interactive
from repeat_navigation.engine import Engine
from repeat_navigation.keys import ALT, CTRL, Decoder, chord, navigation
from repeat_navigation.screen import Screen

ROOT = Path(__file__).resolve().parents[1]


class DecoderTest(unittest.TestCase):
    def test_control_disambiguation_kitty_release_and_alt(self):
        d = Decoder()
        tokens = d.feed(chord("j", CTRL) + b"\n\x08" + b"\x1b[106;5:3u\x1bl")
        self.assertEqual((tokens[0].key, tokens[0].mods), ("j", CTRL))
        self.assertEqual(tokens[1].key, "enter")
        self.assertEqual(tokens[2].key, "backspace")
        self.assertFalse(tokens[3].press)
        self.assertEqual((tokens[4].key, tokens[4].mods), ("l", ALT))

    def test_chunked_paste_is_opaque_and_bytes_preserved(self):
        d = Decoder()
        source = b"\x1b[200~jjj\x02" + chord("j", CTRL) + b"\x1b[201~x"
        tokens = []
        for byte in source:
            tokens += d.feed(bytes([byte]))
        self.assertEqual(b"".join(t.raw for t in tokens), source)
        self.assertFalse(any(navigation(t) for t in tokens))

    def test_escape_replies_mouse_arrows_and_malformed_input(self):
        d = Decoder()
        self.assertEqual(d.feed(b"\x1b"), [])
        self.assertEqual(d.feed(b"", flush=True)[0].key, "esc")
        tokens = d.feed(b"\x1b[1;1R\x1b[<0;1;1M\x1b[B")
        self.assertEqual([t.kind for t in tokens], ["reply", "mouse", "key"])
        d.feed(b"\x1b[" + b"1"*8192)
        self.assertLess(len(d.buffer), 8192)
        self.assertIsNone(navigation(Decoder().feed(b"\x1b[57364;5u")[0]))


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.e = Engine()
        self.d = Decoder()

    def feed(self, data, now, generation=1, prefix=False):
        self.e.feed(self.d.feed(data))
        return self.e.drain(now, generation, prefix)

    def start(self, key="j", mods=CTRL):
        raw = chord(key, mods)
        self.assertEqual(self.feed(b"\x02"+raw, 0), b"\x02")
        self.assertEqual(self.e.drain(.02, 2, True), raw)

    def test_repeats_pair_and_expires_without_escape(self):
        self.start()
        self.assertEqual(self.feed(b"jk", .1, 3), b"\x02")
        self.assertEqual(self.e.drain(.12, 4, True), chord("j", CTRL)+b"\x02")
        self.assertEqual(self.e.drain(.14, 5, True), chord("k", CTRL))
        self.assertEqual(self.feed(b"j", .7, 6), b"j")

    def test_windows_panes_directional_and_space_aliases(self):
        for key, mods, opposite in (("n", CTRL, "p"), ("h", CTRL, "l"),
                                     ("l", ALT, "h"), ("j", 0, "k"), ("n", 0, "p")):
            self.setUp()
            self.start(key, mods)
            self.assertEqual(self.feed(opposite.encode(), .1, 3), b"\x02")
            self.assertEqual(self.e.drain(.12, 4, True), chord(opposite, mods))

    def test_other_typing_enter_mouse_and_paste_resume_immediately(self):
        for data in (b"hello\r", b"\r", b"\x1b[<0;1;1M", b"\x1b[200~jjj\x1b[201~"):
            self.setUp(); self.start()
            self.assertEqual(self.feed(data, .1, 3), data)
            self.assertFalse(self.e.mapping)

    def test_prefix_passthrough_other_commands_and_no_modal_hijacking(self):
        self.assertEqual(self.feed(b"\x02\x02", 0), b"\x02\x02")
        self.assertEqual(self.feed(b"\x02\r", .1), b"\x02\r")
        self.assertEqual(self.feed(b"\x02 ", .2), b"\x02 ")
        self.assertEqual(self.feed(b"\x02j", .3, 2), b"\x02")
        self.assertEqual(self.e.drain(.44, 3, False), b"j")
        self.assertEqual(self.feed(b"j", .45, 4), b"j")
        self.assertFalse(self.e.mapping)

    def test_replies_and_releases_do_not_change_repeat(self):
        self.start()
        source = b"\x1b[1;1R\x1b[106;5:3u"
        self.assertEqual(self.feed(source, .1, 3), source)
        self.assertTrue(self.e.mapping)
        self.assertEqual(self.feed(b"\x1b", .2, 3), b"")
        self.e.feed(self.d.feed(b"", flush=True))
        self.assertEqual(self.e.drain(.24, 3, False), b"")
        self.assertFalse(self.e.mapping)

    def test_waits_for_a_completed_focus_paint_before_rapid_repeats(self):
        self.e.feed(self.d.feed(b"\x02"+chord("j",CTRL)+b"j"))
        self.assertEqual(self.e.drain(0,1,False,scene=10),b"\x02")
        self.assertEqual(self.e.drain(.02,2,True,scene=10),chord("j",CTRL))
        self.assertEqual(self.e.drain(.04,3,False,scene=10),b"")
        self.assertEqual(self.e.drain(.06,4,False,scene=11),b"\x02")
        self.assertEqual(self.e.drain(.08,5,True,scene=11),chord("j",CTRL))

    def test_large_bursts_degrade_to_literal_not_a_long_navigation_backlog(self):
        data=b"\x02"+b"j"*200
        self.assertEqual(self.feed(data,0),data)
        self.assertFalse(self.e.queue)
        self.assertFalse(self.e.mapping)

    def test_paste_like_text_is_not_rewritten_without_a_prefix(self):
        data = b"jjkk\x1b[200~\x02jj\x1b[201~"
        self.assertEqual(self.feed(data, 0), data)
        self.assertFalse(self.e.mapping)


class IntegrationUnitTest(unittest.TestCase):
    def test_read_only_screen_observer_handles_fragmented_prefix(self):
        s = Screen(24, 80)
        for data in (b"\x1b[?20", b"26h", b"\x1b[24;3HPR", b"EFIX esc cancel"):
            s.feed(data)
        self.assertTrue(s.ready)
        self.assertTrue(s.prefix_visible)
        s.feed(b"\x1b[24;1H\x1b[2Knormal")
        self.assertFalse(s.prefix_visible)

    def test_arg_classification_and_config_validation(self):
        for args in ([], ["--session", "homelab"], ["--remote", "nuc", "--session", "homelab"],
                     ["session", "attach", "homelab"]):
            self.assertTrue(interactive(args), args)
        for args in (["--version"], ["server"], ["agent", "list"], ["--session", "x", "api", "snapshot"],
                     ["--machine", "nuc", "workspace", "list"], ["--help"]):
            self.assertFalse(interactive(args), args)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"config.json"
            self.assertEqual(config.read(path), config.DEFAULT)
            config.write(path, {"enabled": False, "repeat_ms": 300})
            self.assertEqual(config.read(path)["repeat_ms"], 300)
            for value in ({"repeat_ms": True}, {"repeat_ms": 0}, {"enabled": "yes"}):
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError): config.read(path)

    def test_noninteractive_and_cli_passthrough_preserve_argv_output_and_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory)/"native"
            binary.write_text('#!'+sys.executable+'\nimport sys,json\nprint(json.dumps(sys.argv[1:]))\nsys.exit(7)\n')
            binary.chmod(0o755)
            for args in (["--session", "x", "api", "snapshot"], ["--remote", "nuc"]):
                result = subprocess.run([sys.executable, "-B", str(ROOT/"repeat.py"), "run", "--binary", str(binary),
                                         "--"]+args, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 7)
                self.assertEqual(json.loads(result.stdout), args)
                self.assertEqual(result.stderr, "")
