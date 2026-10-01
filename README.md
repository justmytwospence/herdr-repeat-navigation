# Herdr Repeat Navigation

A Herdr plugin with a POSIX client companion for tmux-style **timed navigation repeat**.
Herdr 0.9.3's prefix is one-shot. Server plugin hooks cannot intercept client keys,
so linking the manifest provides settings actions; the companion wraps the interactive
client's input. No Ghostty injection, server focus API, persistent mode, or automatic
agent acknowledgement is involved.

Requires Herdr 0.9.3+, Python 3.9+, macOS or Linux, and a terminal with enhanced
keyboard reporting (such as Ghostty) for distinct Ctrl-h/j events.

## Navigation

The companion expects these native bindings on every connected server:

| Initial chord | Action | Repeat without another prefix |
|---|---|---|
| Ctrl-b Ctrl-j / Ctrl-k | next / previous space | j / k |
| Ctrl-b Ctrl-n / Ctrl-p | next / previous tab/window within the space | n / p |
| Ctrl-b Ctrl-h / Ctrl-l | previous / next pane, through any split layout | h / l |
| Ctrl-b Alt-h / Alt-l | previous / next tab/window | h / l |
| Ctrl-b h/j/k/l | directional pane focus | h/j/k/l |
| Ctrl-b n/p | space aliases | n/p |

Repeat expires **500 ms after the last navigation**, automatically. No Esc is needed.
Only the current group's letters repeat. Other typing, Enter, paste or mouse input
ends repeat immediately and passes through. Within that short window, its letters
are navigation rather than text, just as with a tmux repeat table.

Explicit Ctrl-b starts a fresh prefix command. Ctrl-b Enter, Ctrl-b Space, and
other non-navigation commands keep their native behavior. Ctrl-b Ctrl-b retains
literal-prefix passthrough. Close, split, swap, rename and acknowledgement actions
are never repeated automatically.

The companion waits for the native PREFIX footer before arming or replaying navigation;
if no acknowledgement arrives, it degrades to ordinary input. This avoids treating
popup, authentication or other modal text entry as navigation. Terminal output is
forwarded unchanged; there is no extra modal screen or output overlay.

Navigation stays in whichever server the native client currently selects. The same
wrapper works for local clients, `--session`, `session attach`, and `--remote` clients.
Ordinary CLI commands and redirected/non-TTY invocations exec the real binary without
PTY wrapping or settings queries.

## Installation

```sh
herdr plugin install justmytwospence/herdr-repeat-navigation
herdr plugin config-dir repeat-navigation
herdr plugin list --plugin repeat-navigation --json
```

For development, link the checkout instead:

```sh
herdr plugin link ~/Projects/herdr-repeat-navigation
~/Projects/herdr-repeat-navigation/bin/herdr-repeat --binary "$(command -v herdr)" -- --session default
```

For a pinned dotfiles checkout, launch through its `bin/herdr-repeat`, or link that
launcher into PATH. Shell integration may route interactive `herdr` attachments through
it; always pass the real binary with `--binary`, and never replace the native executable.
The companion refuses to intercept when the native plugin registration is absent or
disabled. `--settings /path/config.json` is an explicit override for isolated tests.

Existing native clients must **detach and reattach through the companion** once.
Do not stop the server: workspaces, shells and running agents remain alive.

## Settings

`config.json` in the directory printed by `herdr plugin config-dir repeat-navigation`:

```json
{"enabled": true, "repeat_ms": 500}
```

`repeat_ms` accepts 100–1500. Malformed settings disable interception rather than
breaking the native client. Open companions poll this file once a second.

```sh
herdr plugin action invoke repeat-navigation.status
herdr plugin action invoke repeat-navigation.disable
herdr plugin action invoke repeat-navigation.enable
```

These actions affect companions on **that host**. Native `herdr plugin disable`
prevents interception on future attachments; the settings action also affects open
companions. Linking is per user and settings are not automatically synchronized by
Herdr. Install the plugin and shell integration on every machine where clients run.

## Verification

```sh
python3 -B -m unittest discover -s tests -v
HERDR_REPEAT_LIVE=1 python3 -B -m unittest discover -s tests -v
```

Live acceptance creates its own config, state, server and PTY client. It checks
spaces, windows, vertical-split panes, timeout without Esc, popup input passthrough,
and detach without stopping the server. It never uses live user sessions.
