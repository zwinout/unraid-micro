#!/usr/bin/env python3
"""Re-pin the plugin to the newest upstream micro release.

What this does, in order, and it will not write anything until all of it holds:

1. asks the GitHub API for micro's latest release;
2. takes the published SHA256 for the linux64 static asset from *two*
   independent sources - the release asset's `digest` field and the
   publisher's own `.sha` file - and requires them to agree;
3. downloads the asset and hashes it locally, requiring that to match too;
4. rewrites the `microver` / `microsha` entities in micro.plg, bumps the
   plugin `version`, and prepends a `<CHANGES>` entry;
5. runs tools/validate_plugin.py, the full install/remove test suite;
6. with --push, commits and pushes.

A pin that cannot be verified from both sources is never written.

Usage:
    python3 tools/bump_micro.py              # show what would change
    python3 tools/bump_micro.py --check      # exit 0 if current, 3 if a newer release exists
    python3 tools/bump_micro.py --write      # apply, then test
    python3 tools/bump_micro.py --write --push
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
PLG = REPO / "micro.plg"
README = REPO / "README.md"
HARNESS = REPO / "tools" / "validate_plugin.py"

# The README quotes the bundled version. Keep the phrasing stable: the test
# suite fails if it disagrees with the .plg, so drift cannot ship silently.
BUNDLED_RE = re.compile(r"(Currently bundles \*\*micro )(\d+\.\d+\.\d+)(\*\*)")

UPSTREAM = "micro-editor/micro"
PLATFORM = "linux64-static"
UA = {"User-Agent": "unraid-micro-bump"}


def api(url: str) -> dict:
    req = urllib.request.Request(url, headers={**UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=600) as resp:
        return resp.read()


def entity(text: str, name: str) -> str:
    m = re.search(rf'<!ENTITY\s+{name}\s+"([^"]*)"', text)
    if not m:
        raise SystemExit(f"micro.plg has no <!ENTITY {name}> declaration")
    return m.group(1)


def set_entity(text: str, name: str, value: str) -> str:
    new, n = re.subn(
        rf'(<!ENTITY\s+{name}\s+)"[^"]*"', rf'\g<1>"{value}"', text, count=1
    )
    if n != 1:
        raise SystemExit(f"could not rewrite the {name} entity")
    return new


def next_plugin_version(today: str, current: str) -> str:
    """Unraid offers an update when the version string changes, and releases
    are dated, so same-day bumps get a numeric suffix."""
    if current == today:
        return f"{today}.1"
    m = re.match(rf"{re.escape(today)}\.(\d+)$", current)
    if m:
        return f"{today}.{int(m.group(1)) + 1}"
    return today


def prepend_changes(text: str, plugin_version: str, micro_version: str) -> str:
    """Add a new entry at the top of <CHANGES>, which CA displays to users."""
    entry = (
        f"{plugin_version}\n"
        f"- Update bundled micro to {micro_version}\n"
        f"- Re-pin the release archive SHA256 from the upstream release\n\n"
    )
    new, n = re.subn(r"<CHANGES>\n", f"<CHANGES>\n{entry}", text, count=1)
    if n != 1:
        raise SystemExit("could not find the <CHANGES> block to prepend to")
    return new


def set_readme_version(text: str, micro_version: str) -> str:
    """Keep the version quoted in the README in step with the pin."""
    new, n = BUNDLED_RE.subn(rf"\g<1>{micro_version}\g<3>", text, count=1)
    if n != 1:
        raise SystemExit(
            'could not find the "Currently bundles **micro X.Y.Z**" line in README.md'
        )
    return new


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="apply the change to micro.plg")
    ap.add_argument("--push", action="store_true", help="commit and push after testing")
    ap.add_argument(
        "--check",
        action="store_true",
        help="exit 0 if already pinned to the newest release, 3 if a newer one exists",
    )
    args = ap.parse_args()

    text = PLG.read_text(encoding="utf-8")
    cur_ver = entity(text, "microver")
    cur_sha = entity(text, "microsha")
    cur_pver = entity(text, "version")

    print(f"current pin  : micro {cur_ver}  ({cur_sha[:16]}...)")
    print(f"plugin ver   : {cur_pver}")
    print()

    rel = api(f"https://api.github.com/repos/{UPSTREAM}/releases/latest")
    new_ver = rel["tag_name"].lstrip("v")
    tarball = f"micro-{new_ver}-{PLATFORM}.tar.gz"
    print(f"upstream     : {rel['tag_name']}  ({rel['published_at']})")

    asset = next((a for a in rel["assets"] if a["name"] == tarball), None)
    if asset is None:
        print(f"ERROR: release {rel['tag_name']} has no {tarball} asset")
        return 1
    sha_asset = next((a for a in rel["assets"] if a["name"] == tarball + ".sha"), None)

    api_digest = (asset.get("digest") or "").removeprefix("sha256:").strip()
    published = ""
    if sha_asset is not None:
        published = download(sha_asset["browser_download_url"]).decode().split()[0].strip()

    print(f"  asset sha (API)      : {api_digest or 'not exposed'}")
    print(f"  asset sha (.sha file): {published or 'missing'}")

    if api_digest and published and api_digest != published:
        print("ERROR: the GitHub API digest and the publisher's .sha file disagree.")
        print("       Refusing to pin a version whose checksum is not corroborated.")
        return 1

    new_sha = published or api_digest
    if not new_sha:
        print("ERROR: no checksum available from either source")
        return 1

    print("  downloading the asset to verify the checksum locally ...")
    blob = download(asset["browser_download_url"])
    local_sha = hashlib.sha256(blob).hexdigest()
    print(f"  our own hash of it   : {local_sha}  ({len(blob)} bytes)")
    if local_sha != new_sha:
        print("ERROR: the downloaded asset does not hash to the published value")
        return 1
    print("  checksum corroborated by API digest, .sha file and a local re-hash.")

    up_to_date = new_ver == cur_ver and new_sha == cur_sha

    if args.check:
        # Distinct exit codes so CI can branch on the result without parsing
        # stdout.
        if up_to_date:
            print(f"\nCHECK: already pinned to the newest release (micro {cur_ver})")
            return 0
        print(f"\nCHECK: micro {new_ver} is available (currently pinned: {cur_ver})")
        return 3

    if up_to_date:
        print(f"\nAlready pinned to the newest release (micro {cur_ver}). Nothing to do.")
        return 0

    today = datetime.date.today().isoformat().replace("-", ".")
    new_pver = next_plugin_version(today, cur_pver)

    print()
    print("  micro        :", cur_ver, "->", new_ver)
    print("  sha256       :", cur_sha[:16], "... ->", new_sha[:16], "...")
    print("  plugin ver   :", cur_pver, "->", new_pver)

    if not args.write:
        print("\n(dry run - pass --write to apply)")
        return 0

    text = set_entity(text, "microver", new_ver)
    text = set_entity(text, "microsha", new_sha)
    text = set_entity(text, "version", new_pver)
    text = prepend_changes(text, new_pver, new_ver)
    PLG.write_text(text, encoding="utf-8")
    print(f"\nwrote {PLG}")

    readme = README.read_text(encoding="utf-8")
    README.write_text(set_readme_version(readme, new_ver), encoding="utf-8")
    print(f"updated the bundled-version line in {README}")

    # The cached tarball from the previous pin must not be reused by the tests.
    cache = pathlib.Path("/tmp/micro-plugin-test-cache")
    if cache.exists():
        for old in cache.glob("micro-*.tar.gz"):
            if old.name != tarball:
                old.unlink()
                print(f"pruned stale test cache {old.name}")

    print("\nrunning the plugin test suite ...")
    rc = subprocess.run([sys.executable, str(HARNESS)]).returncode
    if rc != 0:
        print("ERROR: the test suite failed - reverting the changed files")
        subprocess.run(
            ["git", "-C", str(REPO), "checkout", "--", "micro.plg", "README.md"]
        )
        return 1

    if args.push:
        subprocess.run(
            ["git", "-C", str(REPO), "commit", "-am", f"micro {new_ver} ({new_pver})"],
            check=True,
        )
        subprocess.run(["git", "-C", str(REPO), "push"], check=True)
        print(f"\npushed micro {new_ver} as plugin {new_pver}")
    else:
        print("\ntests passed. Review, then commit - or re-run with --push.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
