#!/usr/bin/env python3
"""Materialize pinned, writable source trees and apply reviewed local patches.

Existing work is never reset, removed, or pulled. No fork/push credentials needed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[2]


def git(path, *args, capture=False):
    result = subprocess.run(
        ["git", "-c", "core.autocrlf=false", "-C", str(path), *args],
        check=True, stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout if capture else b""


def prepare(root, dependency, check_only):
    relative = Path(dependency["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Unsafe dependency path")
    path = root / relative
    patch_path = PROJECT / dependency["patch"] if dependency.get("patch") else None
    patch = patch_path.read_bytes() if patch_path else b""
    if patch and hashlib.sha256(patch).hexdigest() != dependency["patch_sha256"]:
        raise ValueError(f"Patch checksum mismatch: {patch_path}")
    revision = dependency["revision"]
    if not (path / ".git").exists():
        if check_only:
            raise ValueError(f"Missing checkout: {path}")
        if path.exists():
            raise ValueError(f"Refusing to overwrite existing directory: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "-c", "core.autocrlf=false", "clone", "--no-checkout",
                        "--depth", "1", dependency["url"], str(path)], check=True)
        if subprocess.run(["git", "-C", str(path), "cat-file", "-e", revision],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            git(path, "fetch", "--depth", "1", "origin", revision)
        git(path, "switch", "-c", "feature/windows-controller-m1", revision)
    actual = git(path, "rev-parse", "HEAD", capture=True).decode().strip()
    if actual != revision:
        raise ValueError(f"{path}: HEAD {actual} differs from locked {revision}; preserve your work and use a fresh checkout")
    changes = git(path, "diff", "--binary", "--full-index", "HEAD", capture=True)
    untracked = git(path, "ls-files", "--others", "--exclude-standard", capture=True)
    if untracked:
        raise ValueError(f"{path}: preserve untracked files before preparing dependencies")
    if changes == patch:
        print(f"OK {relative}: {revision} + verified patch" if patch else f"OK {relative}: {revision}")
        return
    if changes:
        raise ValueError(f"{path}: existing changes differ from the reviewed patch; refusing to overwrite")
    if check_only:
        raise ValueError(f"{path}: locked patch has not been applied")
    git(path, "apply", "--check", "--index", str(patch_path))
    git(path, "apply", "--index", str(patch_path))
    if git(path, "diff", "--binary", "--full-index", "HEAD", capture=True) != patch:
        raise ValueError(f"{path}: resulting changes differ from the locked patch")
    print(f"Prepared {relative}: {revision} + verified patch (staged for review)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT, help="checkout destination root")
    parser.add_argument("--check", action="store_true", help="verify without fetching or modifying anything")
    args = parser.parse_args()
    lock = json.loads((PROJECT / "controller-dependencies.json").read_text())
    if lock["version"] != 1:
        raise ValueError("Unsupported dependency lock version")
    for dependency in lock["dependencies"]:
        prepare(args.root.resolve(), dependency, args.check)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, subprocess.CalledProcessError, OSError) as error:
        sys.exit(str(error))
