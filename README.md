# micro for Unraid

An Unraid plugin that installs [micro](https://micro-editor.github.io/), a modern and intuitive terminal-based text editor, so it is available in the Unraid web terminal and over SSH.

```
$ micro /boot/config/plugins/user.scripts/scripts/nightly/script
```

## Why

Unraid ships `vi` and nothing friendlier. Editing a User Script, a config file under `/boot`, or a compose file on a share usually means either fighting `vi` or copying the file to another machine. `micro` is a nano-like successor that behaves the way modern users expect: `Ctrl+S` saves, `Ctrl+Q` quits, `Ctrl+C`/`Ctrl+V` copy and paste, the mouse works, and there is syntax highlighting for 100+ languages out of the box.

It ships upstream as a single statically linked binary with no runtime dependencies, which makes it a clean fit for Unraid's RAM-disk root filesystem.

## Install

**Community Applications (recommended)**

Search for **Micro** in *Apps*, or install from the Unraid Web UI: *Plugins → Install Plugin* and paste

```
https://raw.githubusercontent.com/zwinout/unraid-micro/main/micro.plg
```

## Usage

After installing, open the Unraid web terminal (*Tools → Terminal*) or SSH in and run:

```
micro                      # empty buffer
micro /path/to/file        # open a file
micro +42 /path/to/file    # open at line 42
```

Press `Ctrl+E` for the command bar, `Ctrl+G` for help, and `Ctrl+Q` to quit. `micro --help` lists the flags.

Keybindings, if you are coming from `nano`:

| Action | Key |
| --- | --- |
| Save | `Ctrl+S` |
| Quit | `Ctrl+Q` |
| Find | `Ctrl+F` |
| Replace | `Ctrl+H` |
| Command bar | `Ctrl+E` |
| Help | `Ctrl+G` |
| Copy / paste | `Ctrl+C` / `Ctrl+V` |

## Where things live

| Item | Path |
| --- | --- |
| Binary | `/usr/local/bin/micro` |
| Man page | `/usr/local/share/man/man1/micro.1` |
| Settings and plugins | `/boot/config/plugins/micro/config` |
| Cached release archive | `/boot/config/plugins/micro/` |

Unraid's root filesystem is a RAM disk, so anything written to `/root` disappears on reboot. The plugin therefore redirects micro's configuration directory (`/root/.config/micro`) to the flash drive, which means your `settings.json`, `bindings.json`, custom syntax files and Lua plugins survive a reboot.

If your shell sets `XDG_CONFIG_HOME`, micro will prefer `$XDG_CONFIG_HOME/micro` over the redirect — either unset it or set `MICRO_CONFIG_HOME=/boot/config/plugins/micro/config` to keep using the persistent location.

## How it works

1. Unraid downloads the upstream release archive once to `/boot/config/plugins/micro/` (declared as a `<FILE>` in `micro.plg`).
2. On install and on every boot, the installer verifies that archive against micro's published SHA256 for the bundled release. A mismatch aborts the install and deletes the bad archive.
3. If the archive is missing or fails verification, the installer downloads it itself via `curl` (falling back to `wget`) and re-verifies. If that also fails, nothing is installed rather than something unverified.
4. The binary is extracted to `/usr/local/bin/micro` and the man page to `/usr/local/share/man/man1/`.
5. Archives cached by earlier plugin versions are cleaned up.

Nothing runs as a daemon; the plugin is a binary install plus a symlink.

## Updating

The plugin pins **one micro release** — currently 2.0.15 — together with that
release's SHA256. It does not fetch "latest" at install time. That is deliberate:
a pinned version plus a checksum is what makes the install reproducible and lets
the plugin refuse to install a binary it cannot verify.

Two different updates follow from that:

**Updating the plugin** works the way any Unraid plugin does. *Plugins → Check
for Updates* compares the `version` attribute of `micro.plg`; a newer one is
offered for install. Community Apps picks up plugin version bumps automatically,
so no template change is ever needed — see *Updating Your Plugin* in the
[CA docs](https://plugin-docs.mstrhakr.com/docs/distribution/community-applications.html).

**Updating micro itself** is a maintainer action, not something the plugin does
on your server. A new upstream micro release reaches you only when the plugin's
version is bumped to pin it, so the plugin is never more current than its last
release. If you are running an older plugin and want a newer micro, check for a
plugin update first; if there is not one, upstream's release is newer than what
this plugin pins, and an issue on the repository is the right nudge.

To bump the pin, run the script in the build tooling:

```
python3 bump_micro.py --push
```

It asks the GitHub API for micro's latest release, cross-checks the asset's
SHA256 against the publisher's own `.sha` file, requires the two to agree,
rewrites the `microver` and `microsha` entities, bumps the plugin version,
prepends a `<CHANGES>` entry, re-runs the install/remove test suite, and only
then commits and pushes. It refuses to pin anything it could not download and
verify.

If you want this to happen without anyone remembering to run it, the repository
can carry a scheduled GitHub Actions workflow that runs the same script weekly —
that needs the `workflow` scope on the pushing token, which the current one does
not have.

## Uninstall

*Plugins → Installed Plugins → micro → Remove*. This deletes the binary, the man page and the symlink. Your settings in `/boot/config/plugins/micro/config` are deliberately left in place so that reinstalling keeps them; delete that directory by hand if you want a clean slate.

## Notes

- Verified against the upstream statically linked `linux64` build. Unraid's web terminal is `xterm.js`, which micro drives correctly, including true colour and mouse events.
- `micro` is developed by Zachary Yedidia and contributors and is MIT licensed; see <https://github.com/micro-editor/micro>. This plugin only packages it for Unraid.
- Unraid is a registered trademark of Lime Technology, Inc. This plugin is not affiliated with Lime Technology.

## License

MIT — see [LICENSE](LICENSE).
