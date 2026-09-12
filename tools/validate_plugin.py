#!/usr/bin/env python3
"""Validate micro.plg and exercise its embedded install/remove scripts.

This is the plugin's test suite.  It derives the pinned micro version and
SHA256 from micro.plg itself, so it always tests what is actually pinned.

Three things are checked, all of which are real failure modes for an Unraid
plugin:

1. XML well-formedness.  Unraid parses .plg files with a strict XML parser and
   the install scripts live as raw text inside <INLINE>, so a bare '&' or '<'
   anywhere in the script (including the very common '2>&1') breaks the whole
   plugin.  Checked mechanically, then confirmed by a real parser.

2. Entity expansion.  The paths Unraid will actually write must be the paths
   the scripts expect.

3. Script behaviour.  The install and remove scripts are extracted, their
   absolute paths redirected into a sandbox, and executed for real against the
   genuine upstream archive: cold cache, warm cache, corrupt cache, and
   unreachable download.

Run:  python3 tools/validate_plugin.py
Deps: none beyond the standard library.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import xml.parsers.expat

REPO = pathlib.Path(__file__).resolve().parent.parent
PLG = REPO / "micro.plg"
CACHE = pathlib.Path(tempfile.gettempdir()) / "micro-plugin-test-cache"

ENTITY_RE = re.compile(r"&(?!#\d+;|#x[0-9a-fA-F]+;|[A-Za-z_][\w.\-]*;)")

# Absolute paths the plugin is expected to write to. Sandboxing rewrites these
# in one pass; the escape check asserts none survive outside the sandbox root.
ABS_PATH_RE = re.compile(
    r"/boot/config/plugins|/usr/local/bin|/usr/local/share/man|/tmp/|/root/\.config"
)
LITERAL_RE = re.compile(
    r"(?<![\w$])/(?:usr|boot|root|tmp|etc|var|bin|sbin|opt|mnt|home|srv)/[\w./-]*"
)

# The README quotes the bundled micro version. If it drifts from the pin, a user
# reading the README is told the wrong thing, so it is checked rather than
# trusted.
BUNDLED_RE = re.compile(r"Currently bundles \*\*micro (\d+\.\d+\.\d+)\*\*")

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    results.append((ok, label))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    return ok


def load() -> str:
    with open(PLG, encoding="utf-8") as fh:
        return fh.read()


def entity(src: str, name: str) -> str:
    m = re.search(rf'<!ENTITY\s+{name}\s+"([^"]*)"', src)
    if not m:
        raise SystemExit(f"micro.plg has no <!ENTITY {name}> declaration")
    return m.group(1)


# --------------------------------------------------------------------------
# 1. well-formedness
# --------------------------------------------------------------------------
def validate_xml(src: str) -> None:
    print("\n== 1. XML well-formedness ==")

    inline_blocks = re.findall(r"<INLINE>(.*?)</INLINE>", src, re.S)
    check(len(inline_blocks) == 2, "two <INLINE> scripts found", f"{len(inline_blocks)}")

    bad = False
    for i, block in enumerate(inline_blocks):
        for m in ENTITY_RE.finditer(block):
            bad = True
            line = block[: m.start()].count("\n") + 1
            print(f"       inline #{i + 1} line {line}: bare '&' -> {block[m.start():m.start()+12]!r}")
    check(not bad, "no bare '&' inside <INLINE> (this is what 2>&1 would break)")

    lt = False
    for i, block in enumerate(inline_blocks):
        for m in re.finditer(r"<", block):
            lt = True
            line = block[: m.start()].count("\n") + 1
            print(f"       inline #{i + 1} line {line}: bare '<' -> {block[m.start():m.start()+12]!r}")
    check(not lt, "no bare '<' inside <INLINE>")

    # Real parser.  expat, like PHP's xml_parse, expands the internal DTD subset.
    try:
        parser = xml.parsers.expat.ParserCreate()
        parser.Parse(src.encode(), True)
        check(True, "expat parsed the whole document")
    except xml.parsers.expat.ExpatError as exc:
        check(False, "expat parsed the whole document", str(exc))


# --------------------------------------------------------------------------
# 2. entity expansion
# --------------------------------------------------------------------------
def expand(src: str) -> str:
    doctype = src.split("<!DOCTYPE PLUGIN [", 1)[1].split("]>", 1)[0]
    ents = dict(re.findall(r'<!ENTITY\s+(\w+)\s+"([^"]*)"\s*>', doctype))
    out = src
    for _ in range(6):
        prev = out
        for name, value in ents.items():
            out = out.replace(f"&{name};", value)
        if out == prev:
            break
    return out


def validate_expansion(expanded: str, tarball: str) -> dict:
    print("\n== 2. entity expansion ==")
    root = re.search(r"<PLUGIN\s(.*?)>", expanded, re.S).group(1)
    attrs = dict(re.findall(r'(\w+)="([^"]*)"', root))

    for need in ("name", "author", "version", "pluginURL", "support", "icon"):
        check(bool(attrs.get(need)), f"PLUGIN @{need}", attrs.get(need, "MISSING"))

    check(attrs.get("name") == "micro", "plugin name is micro", attrs.get("name", ""))

    # A placeholder in an identity field would break the install URL or the CA
    # listing outright, so those are hard failures.  A placeholder in <Support>
    # only affects CA review, and is a known pre-submission state worth
    # surfacing without failing the mechanical checks.
    id_fields = {k: v for k, v in attrs.items() if k in ("pluginURL", "icon", "project", "readme")}
    check(
        not any("YOUR_" in v for v in id_fields.values()),
        "identity fields (pluginURL/icon/project/readme) have no placeholders",
        str(sorted(k for k, v in id_fields.items() if "YOUR_" in v)) or "",
    )

    supp = attrs.get("support", "")
    if "YOUR_" in supp:
        print("       [WAIT] <Support> still holds a placeholder:")
        print(f"              {supp}")
        print("              Fill it in once the forum thread exists - Community")
        print("              Apps will not accept the plugin until it resolves.")
    else:
        check(bool(supp), "support link points at a real forum thread", supp)

    files = re.findall(r"<FILE\s+([^>]*)>", expanded)
    entries = [dict(re.findall(r'(\w+)="([^"]*)"', f)) for f in files]
    print(f"       {len(entries)} <FILE> elements")
    for e in entries:
        print(f"         - {e}")

    cached = [e for e in entries if e.get("Name")]
    check(
        len(cached) == 1 and cached[0]["Name"].endswith(tarball),
        "cached archive path expands to the expected filename",
        cached[0]["Name"] if cached else "none",
    )
    return attrs


def extract_scripts(expanded: str) -> dict[str, str]:
    scripts = {}
    for m in re.finditer(r'<FILE\s+([^>]*?)>\s*<INLINE>(.*?)</INLINE>', expanded, re.S):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        scripts[attrs.get("Method", "install")] = m.group(2).strip("\n")
    return scripts


# --------------------------------------------------------------------------
# 3. sandbox execution
# --------------------------------------------------------------------------
def sandbox(script: str, root: str, bad_url: bool = False, tarball: str = "") -> str:
    """Redirect every absolute path in the script into `root`.

    Single-pass on purpose: doing this as a sequence of str.replace calls
    re-matches text inserted by an earlier pass and destroys the paths.
    """
    out = ABS_PATH_RE.sub(lambda m: root + m.group(0), script)
    if bad_url:
        out = re.sub(
            r'^(URL=").*(")',
            rf"\1https://github.com/micro-editor/micro/releases/download/v0.0.0/{tarball}\2",
            out,
            flags=re.M,
        )
    return out


def run_script(script: str, root: str) -> subprocess.CompletedProcess:
    os.makedirs(f"{root}/tmp", exist_ok=True)
    path = os.path.join(root, "run.sh")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(script)
    return subprocess.run(
        ["/bin/bash", path], capture_output=True, text=True, timeout=900
    )


def assert_no_real_paths(script: str, root: str, label: str) -> None:
    """No absolute path outside the sandbox may survive in the script."""
    offenders: set[str] = set()
    for ln in script.splitlines():
        if ln.lstrip().startswith("#"):
            continue
        for m in LITERAL_RE.finditer(ln):
            p = m.group(0)
            if p.startswith(root) or p == "/dev/null":
                continue
            offenders.add(p)
    check(
        not offenders,
        f"{label}: no absolute path escapes the sandbox",
        str(sorted(offenders)[:6]),
    )


def test_install(
    scripts: dict[str, str], cases: list[tuple[str, bool, bool, bool]],
    tarball: str, version: str, expected_sha: str, release: str,
) -> None:
    """cases: (label, seed_cache, corrupt_cache, expect_ok)"""
    print("\n== 3. install script behaviour ==")
    inst = scripts["install"]

    for label, seed, corrupt, expect_ok in cases:
        root = tempfile.mkdtemp(prefix="microsb-")
        for p in (
            "boot/config/plugins/micro",
            "usr/local/bin",
            "usr/local/share/man/man1",
            "root/.config",
        ):
            os.makedirs(f"{root}/{p}", exist_ok=True)

        cache = f"{root}/boot/config/plugins/micro/{tarball}"
        if seed:
            shutil.copy(CACHE / tarball, cache)
        if seed and corrupt:
            with open(cache, "r+b") as fh:
                fh.seek(4096)
                fh.write(b"\x00\x00\x00\x00")

        script = sandbox(inst, root, tarball=tarball)
        if label == "unreachable download":
            if os.path.exists(cache):
                os.remove(cache)
            script = sandbox(inst, root, bad_url=True, tarball=tarball)

        assert_no_real_paths(script, root, label)
        cp = run_script(script, root)

        blob = cp.stdout + cp.stderr
        bin_path = f"{root}/usr/local/bin/micro"
        installed = os.path.isfile(bin_path)

        if expect_ok:
            check(
                cp.returncode == 0 and installed,
                f"{label}: installs",
                f"rc={cp.returncode} installed={installed}",
            )
            if installed:
                size = os.path.getsize(bin_path)
                check(size > 10_000_000, f"{label}: binary size sane", f"{size} bytes")
                ver = subprocess.run(
                    [bin_path, "--version"], capture_output=True, text=True, timeout=60
                )
                check(
                    version in ver.stdout,
                    f"{label}: sandboxed micro runs and reports {version}",
                    ver.stdout.splitlines()[0] if ver.stdout else ver.stderr[:80],
                )
                link = f"{root}/root/.config/micro"
                check(
                    os.path.islink(link) and os.path.isdir(link),
                    f"{label}: config dir symlinked to flash",
                    os.readlink(link) if os.path.islink(link) else "not a symlink",
                )
                check(
                    os.path.isfile(f"{root}/usr/local/share/man/man1/micro.1"),
                    f"{label}: man page installed",
                )
                if os.path.exists(cache):
                    cached_sum = hashlib.sha256(open(cache, "rb").read()).hexdigest()
                else:
                    cached_sum = "missing"
                check(
                    cached_sum == expected_sha,
                    f"{label}: cached archive matches the pinned SHA256",
                )
                if label == "cold cache":
                    check("downloading" in blob, f"{label}: took the download path")
                if label == "warm cache":
                    check("downloading" not in blob, f"{label}: skipped the download")
                if label == "corrupt cache":
                    check("downloading" in blob, f"{label}: self-healed a corrupt cache")
        else:
            check(
                cp.returncode != 0 and not installed,
                f"{label}: refuses to install and exits non-zero",
                f"rc={cp.returncode} installed={installed}",
            )
            check(
                "ERROR" in blob,
                f"{label}: says why",
                next((l for l in blob.splitlines() if "ERROR" in l), "")[:110],
            )

        if label == "warm cache":
            cp2 = run_script(script, root)
            check(
                cp2.returncode == 0 and os.path.isfile(bin_path),
                f"{label}: second run is idempotent",
                f"rc={cp2.returncode}",
            )

        shutil.rmtree(root, ignore_errors=True)


def test_remove(scripts: dict[str, str]) -> None:
    print("\n== 4. remove script behaviour ==")
    if "remove" not in scripts:
        check(False, "remove script present")
        return
    root = tempfile.mkdtemp(prefix="microsb-rm-")
    for p in (
        "usr/local/bin",
        "usr/local/share/man/man1",
        "boot/config/plugins/micro/config",
        "root/.config",
    ):
        os.makedirs(f"{root}/{p}", exist_ok=True)
    for p in ("usr/local/bin/micro", "usr/local/share/man/man1/micro.1",
              "boot/config/plugins/micro/config/settings.json"):
        with open(f"{root}/{p}", "w") as fh:
            fh.write("x")
    os.symlink(
        f"{root}/boot/config/plugins/micro/config", f"{root}/root/.config/micro"
    )

    script = sandbox(scripts["remove"], root)
    assert_no_real_paths(script, root, "remove")
    cp = run_script(script, root)

    check(cp.returncode == 0, "remove: exits 0", f"rc={cp.returncode}")
    check(not os.path.exists(f"{root}/usr/local/bin/micro"), "remove: binary deleted")
    check(
        not os.path.exists(f"{root}/usr/local/share/man/man1/micro.1"),
        "remove: man page deleted",
    )
    check(not os.path.lexists(f"{root}/root/.config/micro"), "remove: symlink deleted")
    check(
        os.path.isfile(f"{root}/boot/config/plugins/micro/config/settings.json"),
        "remove: user settings preserved on flash",
    )
    shutil.rmtree(root, ignore_errors=True)


def validate_docs(install_url: str, micro_version: str) -> None:
    """The README is the public face of the repo; check it against the manifest."""
    print("\n== 5. documentation consistency ==")
    readme_path = REPO / "README.md"
    if not check(readme_path.is_file(), "README.md exists"):
        return
    readme = readme_path.read_text(encoding="utf-8")

    bundled = BUNDLED_RE.search(readme)
    check(bool(bundled), "README states which micro release is bundled")
    if bundled:
        check(
            bundled.group(1) == micro_version,
            "README's bundled version matches the pinned version",
            f"README says {bundled.group(1)}, micro.plg pins {micro_version}",
        )

    check(
        install_url in readme,
        "README's manual install URL matches the .plg's pluginURL",
        install_url,
    )
    check(
        "CONTRIBUTING.md" in readme,
        "README points contributors at CONTRIBUTING.md",
    )
    check(
        "YOUR_SUPPORT_TOPIC_ID" not in readme,
        "no placeholder leaked into the public README",
    )

    # Catch a repo rename: the URL Unraid installs from must match where the repo
    # actually lives, not just agree with itself.
    try:
        remote = subprocess.run(
            ["git", "-C", str(REPO), "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        remote = ""
    if remote:
        slug = re.sub(r"^.*github\.com[:/]", "", remote).removesuffix(".git")
        expected = f"https://raw.githubusercontent.com/{slug}/main/micro.plg"
        check(
            install_url == expected,
            "pluginURL matches the repository's real origin",
            f"expected {expected}, .plg says {install_url}",
        )
    else:
        print("       (no git origin available - skipped the rename check)")


def main() -> int:
    src = load()
    version = entity(src, "microver")
    expected_sha = entity(src, "microsha")
    plugin_version = entity(src, "version")
    tarball = f"micro-{version}-linux64-static.tar.gz"
    release = (
        f"https://github.com/micro-editor/micro/releases/download/v{version}/{tarball}"
    )

    print(f"plugin version : {plugin_version}")
    print(f"pinned micro   : {version}")
    print(f"pinned sha256  : {expected_sha}")

    validate_xml(src)
    expanded = expand(src)
    attrs = validate_expansion(expanded, tarball)
    scripts = extract_scripts(expanded)
    check(
        set(scripts) == {"install", "remove"},
        "install + remove scripts extracted",
        str(sorted(scripts)),
    )
    validate_docs(attrs.get("pluginURL", ""), version)

    CACHE.mkdir(parents=True, exist_ok=True)
    if not (CACHE / tarball).exists():
        print(f"\nfetching {tarball} for the sandbox ...")
        urllib.request.urlretrieve(release, CACHE / tarball)

    test_install(
        scripts,
        [
            ("cold cache", False, False, True),
            ("warm cache", True, False, True),
            ("corrupt cache", True, True, True),
            ("unreachable download", True, False, False),
        ],
        tarball, version, expected_sha, release,
    )
    test_remove(scripts)

    failed = [label for ok, label in results if not ok]
    print("\n" + "=" * 68)
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED:")
        for label in failed:
            print(f"  - {label}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    import os

    sys.exit(main())
