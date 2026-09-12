# Contributing

Maintainer notes for the `micro` Unraid plugin. Users don't need anything on this page —
see [README.md](README.md).

## Repository layout

```
micro.plg                      the Unraid plugin manifest (installer + remover inline)
plugins/micro.xml              Community Applications wrapper
ca_profile.xml                 Community Applications repository profile
icon.png / icon.svg            micro's own logo, rendered from the upstream release
tools/validate_plugin.py       the test suite
tools/bump_micro.py            re-pins the plugin to a new upstream release
.github/workflows/ci.yml       runs the test suite on every push and PR
.github/workflows/bump-micro.yml   daily upstream check, re-pins and pushes if needed
```

## Running the tests

```bash
python3 tools/validate_plugin.py
```

No dependencies beyond the standard library plus `bash`, `sha256sum` and `tar`. It
reads the pinned version and SHA256 out of `micro.plg`, so it always tests what
actually ships, then runs four install scenarios against the genuine upstream archive
(cold cache, warm cache, corrupt cache, unreachable download) and removes it again.

What it is really guarding:

- **XML well-formedness.** The install scripts live as raw text inside `<INLINE>`, so a
  bare `&` or `<` anywhere in them — `2>&1` and `&&` are the usual culprits — breaks the
  entire plugin at parse time, not just the script. This is checked mechanically and
  then confirmed with a real parser.
- **Sandbox isolation.** Each script is rewritten into a temp root before running. The
  rewrite must be a single pass: doing it as a sequence of `str.replace` calls
  re-matches text an earlier pass inserted and silently mangles every path.
- **Failing closed.** An unreachable download has to exit non-zero with nothing
  installed, never install something unverified.

## Bumping the pinned micro version

```bash
python3 tools/bump_micro.py            # show what would change, write nothing
python3 tools/bump_micro.py --check    # exit 0 if current, 3 if a newer release exists
python3 tools/bump_micro.py --write    # apply, then run the test suite
python3 tools/bump_micro.py --write --push
```

The script refuses to pin anything it cannot corroborate. It takes the new archive's
SHA256 from **three** independent sources — the GitHub API `digest` field, micro's own
published `.sha` file, and its own hash of the downloaded bytes — and requires all three
to agree before writing. It then rewrites the `microver` / `microsha` entities, bumps
the plugin version, updates the "Currently bundles" line in the README, prepends a
`<CHANGES>` entry, and runs the test suite. If the suite fails it restores `micro.plg`
and exits non-zero.

### Version numbering

Plugin versions are `YYYY.MM.DD`. Unraid only offers an update when the `version`
attribute changes, so a second release on the same day gets a `.1`, `.2` suffix; the
script handles that automatically. Community Applications picks up version bumps with
no template change.

### This is automated

`.github/workflows/bump-micro.yml` runs the same script daily at 06:23 UTC and pushes
the result, so nobody has to remember. It can also be triggered by hand from the
**Actions** tab, with a "report only" checkbox that skips the commit.

Two things to know:

- GitHub **disables scheduled workflows after 60 days without repository activity**. If
  micro goes quiet for two months, no bumps means no commits means no activity — the
  schedule switches itself off and has to be re-enabled from the Actions tab.
- The workflow pushes straight to `main` rather than opening a pull request. That is
  deliberate: the test suite gates it, and the point is that nobody hand-reviews a
  checksum bump. Switch it to a PR if that changes.

To exercise the automation without touching `main`, push a deliberately stale pin to a
scratch branch and dispatch against it — `workflow_dispatch` can target any ref as long
as the workflow exists on the default branch:

```bash
git checkout -B verify/bump
# edit microver/microsha in micro.plg to an older release
git commit -am "stale pin" && git push -u origin verify/bump
gh workflow run bump-micro.yml --ref verify/bump
# once green, confirm the branch re-pinned itself, then delete it
```

That is how the automation was originally verified, and it is worth redoing whenever
the workflow changes.

## Editing the installer

Everything that runs on a user's server is inside `micro.plg`. Two rules:

1. **No bare `&` or `<` inside `<INLINE>`.** See above. Run the test suite after any
   edit — it checks this before it does anything else.
2. **Assume the root filesystem is wiped on every boot.** Unraid re-runs the
   `Method="install"` block at every startup, so it must be idempotent and cheap.
   Anything that should survive a reboot belongs under `/boot/config/plugins/micro/`.

The `<FILE Run=... Method="remove">` block must undo the install. It deliberately leaves
user settings in place so a reinstall keeps them.

## Community Applications

Submission requirements, all checked by a human reviewer:

- Public repo with an OSI-approved `LICENSE` at the root.
- `ca_profile.xml` with a **non-empty `<Profile>`** — an empty one is a hard gate that
  blocks submission.
- `plugins/micro.xml` with `PluginURL` matching the `pluginURL` attribute in `micro.plg`
  **exactly**. The test suite compares the two after entity expansion, the way Unraid's
  parser sees them.
- An icon of at least 256x256. `icon.png` is rendered from micro's own `micro.svg`, taken
  from the release tarball; the artwork is unmodified, only the Inkscape editor metadata
  is stripped when re-emitting it.
- A **support link**. `<Support>` (in `micro.plg` and `plugins/micro.xml`) and `<Forum>`
  in `ca_profile.xml` point at this repository's issue tracker. The CA field reference
  accepts that — it describes `<Support>` as a URL "for forums, issues, or project help".
  CA's *listing requirements* nevertheless describe a forum support thread for plugins,
  so a reviewer may ask for one. If that happens: create a thread in the Unraid **Plugin
  Support** subforum, repoint `<Support>` in `micro.plg`, `plugins/micro.xml` and
  `ca_profile.xml`, and add the link to the README's Support section.
- **No starter placeholder values** anywhere in the shipped templates. The suite's section
  6 mirrors CA's "Starter defaults removed" check, scanning `micro.plg`, `ca_profile.xml`
  and `plugins/*.xml` for the starter repo's placeholder strings, and reports anything it
  finds as a pending item with a summary line.

Then submit through the Community Applications flow, and expect questions about the
SHA256 pinning and the flash-drive config redirect — both are documented in the README's
*How it works* equivalent sections.

## Regenerating the icon

The icon is built from micro's upstream logo, which is the source of truth:

```bash
uv run --with cairosvg --with pillow python make_icon.py
```

`micro-upstream-logo.svg` is `micro.svg` as shipped in the release tarball. Re-emit its
`d` attributes byte-identically; strip only editor metadata. Assert the corner alpha is
0, because CA wants a cut-out and a renderer defaulting to an opaque backdrop is easy to
miss.
