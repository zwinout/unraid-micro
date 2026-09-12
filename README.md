# micro for Unraid

[![Plugin tests](https://github.com/zwinout/unraid-micro/actions/workflows/ci.yml/badge.svg)](https://github.com/zwinout/unraid-micro/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Installs [micro](https://micro-editor.github.io/), a modern terminal text editor, on
Unraid — so you can edit files straight from the web terminal or over SSH instead of
copying them to another machine.

```
$ micro /boot/config/plugins/user.scripts/scripts/nightly/script
```

Currently bundles **micro 2.0.15**, pinned and checksum-verified.

## Why

Unraid gives you `vi` and nothing friendlier. Editing a User Script, a config file
under `/boot`, or a compose file on a share usually means either fighting `vi` or
copying the file elsewhere.

micro behaves the way you'd expect: `Ctrl+S` saves, `Ctrl+Q` quits, `Ctrl+C`/`Ctrl+V`
copy and paste, the mouse works, and syntax highlighting covers
[130+ languages](https://github.com/micro-editor/micro/tree/master/runtime/syntax) out
of the box. It ships upstream as a single statically linked binary with no
dependencies, which is exactly what Unraid's RAM-disk root filesystem wants.

## Install

**Community Applications (recommended)** — search for *Micro* in **Apps** and click
Install.

**Manually** — go to **Plugins → Install Plugin** and paste:

```
https://raw.githubusercontent.com/zwinout/unraid-micro/main/micro.plg
```

## Requirements

| | |
| --- | --- |
| Unraid | 6.12.0 or newer |
| Architecture | x86_64 |
| Internet | needed at install time; after that the verified archive is cached on the flash drive, so reboots work offline |

## Usage

Open the Unraid web terminal (**Tools → Terminal**) or SSH in:

```
micro                      # empty buffer
micro /path/to/file        # open a file
micro +42 /path/to/file    # open at line 42
micro main.go config.json  # open several files as tabs
```

micro has a nano-like menu bar at the bottom of the screen showing the common
keys, so you don't have to memorise anything. The ones worth knowing:

| Action | Key |
| --- | --- |
| Save | `Ctrl+S` |
| Quit (close file; quits micro on the last one) | `Ctrl+Q` |
| Open a file | `Ctrl+O` |
| Find / find next / find previous | `Ctrl+F` / `Ctrl+N` / `Ctrl+P` |
| Go to line | `Ctrl+L` |
| Command bar | `Ctrl+E` |
| Help | `Ctrl+G` or `F1` |
| Run a shell command | `Ctrl+B` |
| Copy / cut / paste | `Ctrl+C` / `Ctrl+X` / `Ctrl+V` |
| Cut line / duplicate line | `Ctrl+K` / `Ctrl+D` |
| Undo / redo / select all | `Ctrl+Z` / `Ctrl+Y` / `Ctrl+A` |

There is **no** default key for find-and-replace — press `Ctrl+E` and type
`replace`, then Enter. Every binding is rebindable via `bindings.json` (see below).

If you're coming from `nano`, the muscle memory maps across almost directly:

| Action | micro | nano |
| --- | --- | --- |
| Save | `Ctrl+S` | `Ctrl+O` |
| Quit | `Ctrl+Q` | `Ctrl+X` |
| Find | `Ctrl+F` | `Ctrl+W` |
| Replace | `Ctrl+E`, `replace` | `Ctrl+\` |

`micro --help` lists the command-line flags, and `Ctrl+G` opens the built-in help
(including a full keybinding reference) without leaving the editor.

## Configuration

| Item | Path |
| --- | --- |
| Binary | `/usr/local/bin/micro` |
| Man page | `/usr/local/share/man/man1/micro.1` |
| Your settings, keybindings, syntax files, plugins | `/boot/config/plugins/micro/config` |
| Cached release archive | `/boot/config/plugins/micro/` |

Unraid's root filesystem is a RAM disk, so anything under `/root` is wiped on reboot.
This plugin points micro's config directory (`/root/.config/micro`) at the flash drive
instead, so your `settings.json`, `bindings.json`, custom syntax files and Lua plugins
survive restarts.

**If your shell sets `XDG_CONFIG_HOME`,** micro prefers `$XDG_CONFIG_HOME/micro` over
that redirect and your settings will stop persisting. Either unset it, or set
`MICRO_CONFIG_HOME=/boot/config/plugins/micro/config` to force the persistent
location.

Useful commands inside micro (`Ctrl+E` to open the command bar):

```
> set linenumbers true      # change a setting
> save                      # persist settings to settings.json
> plugin install <name>     # install a Lua plugin
> help options              # see every option
```

Settings only persist after `> save`.

## Verifying the install

```
micro --version
```

You should see the release named above. During installation Unraid's plugin manager
shows the installer output, which should include a line like:

```
[micro] cached archive micro-2.0.15-linux64-static.tar.gz passed SHA256 verification
```

## Updating

Updates arrive through Unraid's normal plugin update check — **Plugins → Check for
Updates**. Nothing to do by hand, and no Community Applications re-approval is needed
for a version bump.

The plugin pins **one specific micro release together with its SHA256** rather than
fetching "latest" at install time. That is deliberate: a pinned version plus a
checksum is what lets it refuse to install a binary it cannot verify. `micro --version`
always tells you exactly which build you are running.

Upstream releases are picked up automatically — a scheduled job in this repository
re-pins the plugin when micro publishes something new, but only after confirming the
new archive's checksum against three independent sources and passing the
install/remove test suite. See [CONTRIBUTING.md](CONTRIBUTING.md) if you're curious how
that works.

## Uninstall

**Plugins → Installed Plugins → micro → Remove**. This deletes the binary, the man
page and the config symlink.

Your settings in `/boot/config/plugins/micro/config` are deliberately left alone, so
reinstalling keeps them. Delete that directory yourself if you want a clean slate.

## Security

Since this plugin installs a third-party binary, here is exactly what it does:

- Downloads micro's official release archive from
  [github.com/micro-editor/micro](https://github.com/micro-editor/micro/releases) —
  nothing from anywhere else.
- Verifies it against micro's published SHA256 **before installing anything**, and
  aborts with nothing installed if the check fails.
- Writes only to `/usr/local/bin/micro`, `/usr/local/share/man/man1/micro.1`,
  `/root/.config/micro` (a symlink) and `/boot/config/plugins/micro/`.
- Runs **no daemon or background process**, and makes no network requests after
  installation.
- Is straightforward to audit: the entire installer is a shell script inside
  [`micro.plg`](micro.plg).

## Troubleshooting

**`micro: command not found`** — the install didn't complete. Check that
`/usr/local/bin/micro` exists; if not, reinstall from **Plugins → Install Plugin** and
read the installer output for an `[micro] ERROR:` line. The most common cause is the
flash drive's archive cache being missing while GitHub is unreachable; installing again
with a working connection fixes it.

**Settings don't survive a reboot** — almost always `XDG_CONFIG_HOME`; see
[Configuration](#configuration).

**Colours or the mouse behave oddly in the web terminal** — the web terminal is
`xterm.js`, which micro drives correctly including true colour and mouse events. If
your browser intercepts a drag as a text selection, hold `Shift` while dragging. In the
built-in help, `> help options` lists terminal-related settings such as `truecolor`.

## Support

- **Bug reports and feature requests:**
  [open an issue](https://github.com/zwinout/unraid-micro/issues).
- When reporting a problem, `micro --version` and your Unraid version are the two
  things that help most.

micro itself is developed by Zachary Yedidia and contributors — bug reports about the
editor rather than the packaging belong [upstream](https://github.com/micro-editor/micro).

## Credits and license

- [micro](https://github.com/micro-editor/micro) — MIT, by Zachary Yedidia and
  contributors. This plugin packages it for Unraid; it doesn't modify it.
- Plugin code and packaging — MIT, see [LICENSE](LICENSE).
- Unraid is a registered trademark of Lime Technology, Inc. This plugin is an
  independent project and is not affiliated with or endorsed by Lime Technology.
