#!/usr/bin/env python3
"""Create/verify a self-contained Windows controller test distribution."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
FOLDER = "Xonotic-Controller-Test-Windows-x64"
SYSTEM_DLLS = set("kernel32 msvcrt user32 shell32 winmm ws2_32 advapi32 gdi32 ole32 oleaut32 imm32 setupapi version wintrust crypt32 uxtheme dinput8 hid comdlg32 shlwapi rpcrt4 secur32 bcrypt ntdll cfgmgr32 powrprof dwmapi avrt normaliz".split())
CONFIG = '''// Offline controller acceptance match; no master-server advertisement.
sv_public 0
joy_enable 1
joy_axiskeyevents 0
cl_firststart 1
name "Controller Tester"
g_gametype dm
g_warmup 0
g_maplist finalrage
bot_number 3
maxplayers 8
timelimit 20
fraglimit 30
map finalrage
'''
LAUNCHER = r'''@echo off
setlocal
pushd "%~dp0" || exit /b 1
if not exist "darkplaces-sdl.exe" goto missing
if not exist "data\xonotic-data.pk3" goto missing
if not exist "data\xonotic-maps.pk3" goto missing
set "PROFILE=%CD%\profiles\controller-test-%RANDOM%-%RANDOM%"
mkdir "%PROFILE%" || goto failed
echo Starting an offline match with a new isolated profile:
echo %PROFILE%
"%CD%\darkplaces-sdl.exe" -xonotic -basedir "%CD%" -userdir "%PROFILE%" +exec controller-test.cfg
if errorlevel 1 goto failed
popd
exit /b 0
:missing
echo Required game files are missing. Extract the complete ZIP before playing.
:failed
echo Launch failed. Extract to a writable folder and see README-TEST.txt.
pause
popd
exit /b 1
'''.replace("\n", "\r\n")


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args])


def tracked(path):
    return [p.decode() for p in git(path, "ls-files", "-z").split(b"\0") if p]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pe_imports(data):
    """Read x64 PE import names without relying on a host Windows loader."""
    if data[:2] != b"MZ":
        raise ValueError("Not a PE file")
    pe = struct.unpack_from("<I", data, 60)[0]
    if data[pe:pe + 4] != b"PE\0\0" or struct.unpack_from("<H", data, pe + 4)[0] != 0x8664:
        raise ValueError("Not a Windows x64 executable/library")
    count, = struct.unpack_from("<H", data, pe + 6)
    opt_size, = struct.unpack_from("<H", data, pe + 20)
    opt = pe + 24
    if struct.unpack_from("<H", data, opt)[0] != 0x20b:
        raise ValueError("PE32+ required")
    sections = []
    for i in range(count):
        header = opt + opt_size + i * 40
        virtual_size, va, raw_size, raw = struct.unpack_from("<IIII", data, header + 8)
        sections.append((va, max(virtual_size, raw_size), raw))

    def offset(rva):
        for va, size, raw in sections:
            if va <= rva < va + size:
                return raw + rva - va
        raise ValueError(f"Invalid PE RVA {rva}")

    imports_rva, = struct.unpack_from("<I", data, opt + 112 + 8)
    if not imports_rva:
        return []
    pos = offset(imports_rva)
    result = []
    while any(data[pos:pos + 20]):
        name_rva, = struct.unpack_from("<I", data, pos + 12)
        name = offset(name_rva)
        result.append(data[name:data.index(b"\0", name)].decode("ascii").lower())
        pos += 20
    return result


def is_system(name):
    return name.startswith(("api-ms-win-", "ext-ms-win-")) or name.removesuffix(".dll") in SYSTEM_DLLS


def pk3(output, source, names, extra=None):
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as z:
        for name in sorted(set(names)):
            if (source / name).is_file():
                z.write(source / name, name)
        for name, path in (extra or {}).items():
            z.write(path, name)


def source_archive(output, repositories):
    with tarfile.open(output, "w:gz", compresslevel=3) as tar:
        for label, repo in repositories:
            # Assets and map sources already ship inside PK3s. Include code and
            # licensing here without duplicating gigabytes of texture data.
            for name in tracked(repo):
                if label == "game" and not name.startswith("qcsrc/"):
                    continue
                file = repo / name
                if file.is_file():
                    tar.add(file, arcname=f"{label}/{name}", recursive=False)
                else:
                    data = git(repo, "show", f"HEAD:{name}")
                    info = tarfile.TarInfo(f"{label}/{name}")
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))


def verify(archive):
    with zipfile.ZipFile(archive) as outer:
        if outer.testzip():
            raise ValueError("Outer ZIP CRC failure")
        files = {n.removeprefix(FOLDER + "/"): n for n in outer.namelist()}
        if any(".." in Path(n).parts or not n.startswith(FOLDER + "/") for n in outer.namelist()):
            raise ValueError("Unsafe archive path")
        hashes = json.loads(outer.read(files["SHA256SUMS.json"]))
        if set(hashes) != set(files) - {"SHA256SUMS.json"}:
            raise ValueError("Archive has missing or unmanifested files")
        for name, expected in hashes.items():
            if digest(outer.read(files[name])) != expected:
                raise ValueError(f"SHA-256 mismatch: {name}")
        imports = {}
        dlls = {n.lower() for n in files if "/" not in n and n.lower().endswith(".dll")}
        for name in files:
            if name.lower().endswith((".exe", ".dll")):
                imports[name] = pe_imports(outer.read(files[name]))
                for needed in imports[name]:
                    if not is_system(needed) and needed not in dlls:
                        raise ValueError(f"Missing imported DLL: {name} -> {needed}")
        for name in ("sdl2.dll", "zlib1.dll", "libpng16.dll", "libjpeg.dll", "libvorbis.dll", "libvorbisfile.dll", "libfreetype-6.dll"):
            if name not in dlls:
                raise ValueError(f"Missing dynamically loaded runtime: {name}")
        launcher = outer.read(files["Play-Xonotic.bat"])
        if b'pushd "%~dp0"' not in launcher or b'-userdir "%PROFILE%"' not in launcher or b'+exec controller-test.cfg' not in launcher:
            raise ValueError("Launcher does not anchor paths/isolate its profile")
        assert outer.read(files["data/controller-test.cfg"]).decode() == CONFIG
        with zipfile.ZipFile(io.BytesIO(outer.read(files["data/xonotic-data.pk3"]))) as game:
            if game.testzip():
                raise ValueError("Game PK3 CRC failure")
            for name in ("progs.dat", "csprogs.dat", "menu.dat"):
                if game.getinfo(name).file_size < 100000:
                    raise ValueError(f"Missing/empty game program {name}")
            binds = game.read("binds-xonotic.cfg")
            if b'bind X360_RIGHT_TRIGGER "+fire"' not in binds:
                raise ValueError("Controller defaults missing")
            for prefix in ("models/", "textures/", "sound/", "gfx/"):
                if not any(n.startswith(prefix) for n in game.namelist()):
                    raise ValueError(f"Missing game assets: {prefix}")
        with zipfile.ZipFile(io.BytesIO(outer.read(files["data/xonotic-maps.pk3"]))) as maps:
            if maps.testzip():
                raise ValueError("Map PK3 CRC failure")
            bsp = maps.read("maps/finalrage.bsp")
            if bsp[:4] not in (b"IBSP", b"RBSP") or len(bsp) < 100000:
                raise ValueError("Playable compiled Final Rage BSP missing")
            entity_offset, entity_size = struct.unpack_from("<II", bsp, 8)
            if b"info_player_deathmatch" not in bsp[entity_offset:entity_offset + entity_size]:
                raise ValueError("Map has no deathmatch player spawns")
            maps.getinfo("maps/finalrage.mapinfo")
        print(f"PASS archive CRCs, SHA-256 manifest, x64 PE/DLL closure, launcher, programs, assets and playable map: {archive}")
        return imports


def package(args):
    subprocess.run(["python3", str(ROOT / "misc/tools/prepare-controller-deps.py"), "--check"], check=True)
    game = ROOT / "data/xonotic-data.pk3dir"
    with tempfile.TemporaryDirectory(prefix="controller-package-") as temporary:
        stage = Path(temporary) / FOLDER
        (stage / "data").mkdir(parents=True)
        (stage / "Source").mkdir()
        shutil.copy2(args.engine, stage / "darkplaces-sdl.exe")
        for directory in args.dll_dir:
            for dll in directory.glob("*.dll"):
                shutil.copy2(dll, stage / dll.name)
        for original, alias in (("libzlib1.dll", "zlib1.dll"), ("libjpeg-62.dll", "libjpeg.dll"), ("libfreetype.dll", "libfreetype-6.dll"), ("libogg.dll", "ogg.dll")):
            if (stage / original).exists():
                shutil.copy2(stage / original, stage / alias)
        pk3(stage / "data/xonotic-data.pk3", game, tracked(game),
            {n: game / n for n in ("progs.dat", "csprogs.dat", "menu.dat", "progs.lno", "csprogs.lno", "menu.lno")})
        map_names = [n for n in tracked(args.maps) if not n.startswith(".") and (
            not n.startswith("maps/") or n.startswith(("maps/finalrage.", "maps/_init/")) or ".license" in n.lower())]
        pk3(stage / "data/xonotic-maps.pk3", args.maps, map_names, {"maps/finalrage.bsp": args.bsp})
        for font in sorted((ROOT / "data").glob("font-*.pk3dir")):
            pk3(stage / "data" / font.name.replace(".pk3dir", ".pk3"), font,
                [str(p.relative_to(font)) for p in font.rglob("*") if p.is_file()])
        (stage / "Play-Xonotic.bat").write_bytes(LAUNCHER.encode("ascii"))
        (stage / "data/controller-test.cfg").write_text(CONFIG)
        (stage / "README-TEST.txt").write_text(
            "Extract the ENTIRE ZIP to a writable folder on Windows 10/11 x64.\n"
            "Connect/pair an Xbox controller, close Steam and external mappers, then double-click Play-Xonotic.bat.\n"
            "A new profiles/controller-test-* folder is created on EVERY launch; your normal Xonotic profile is untouched.\n"
            "The launcher starts Final Rage deathmatch with 3 bots. A jumps, sticks move/aim, RT fires, LT secondary fires.\n"
            "Keyboard/mouse remain available; full controller menu traversal is outside milestone 1.\n"
            "No development tools or administrator installation are required. The directory must be writable.\n"
            "This is a test build, not an official Xonotic release. USB/Bluetooth hardware validation is still required.\n"
            "Optional online-download/crypto/music-module libraries are not included; this build targets offline play.\n"
            "Corresponding source and dependency locks are in Source/. Original asset/map sources ship inside the PK3s (ZIP files).\n"
            "See controller-milestone-1.md for the full acceptance checklist and source build instructions.\n")
        for name in ("COPYING", "GPL-2", "GPL-3", "key_0.d0pk", "key_1.d0pk"):
            shutil.copy2(ROOT / name, stage / name)
        shutil.copy2(ROOT / "Docs/controller-milestone-1.md", stage / "controller-milestone-1.md")
        repos = [("project", ROOT), ("engine", ROOT / "darkplaces"), ("game", game), ("gmqcc", ROOT / "gmqcc")]
        if args.runtime_sources:
            for repo in sorted(args.runtime_sources.iterdir()):
                if repo.name not in ("maps", "netradiant") and (repo / ".git").exists():
                    repos.append((repo.name, repo))
        if args.sdl_license:
            shutil.copy2(args.sdl_license, stage / "LICENSE-SDL.txt")
        source_archive(stage / "Source/corresponding-source.tar.gz", repos)
        for name in ("controller-dependencies.json", "portable-dependencies.json"):
            shutil.copy2(ROOT / name, stage / "Source" / name)
        (stage / "THIRD-PARTY-NOTICES.txt").write_text(
            "Xonotic and DarkPlaces: GPL; see COPYING, GPL-2, GPL-3 and original per-file notices.\n"
            "Game and map assets: official Xonotic GitLab repositories; original source/attribution retained in the PK3 ZIPs.\n"
            "SDL2: official libsdl-org SDK, zlib license; see LICENSE-SDL.txt.\n"
            "zlib, libpng, libjpeg-turbo, libogg, libvorbis: upstream licenses and full corresponding source in Source/corresponding-source.tar.gz.\n"
            "Portions of this software are copyright The FreeType Project (www.freetype.org). All rights reserved.\n"
            "FreeType license texts are retained in its source snapshot.\n"
            "Exact upstream URLs, revisions and SDL SDK SHA-256: Source/portable-dependencies.json.\n")
        shutil.copytree(ROOT / "patches", stage / "Source/patches")
        shutil.copytree(ROOT / "misc/tools", stage / "Source/tools", ignore=shutil.ignore_patterns("__pycache__"))
        metadata = {"main_commit": git(ROOT, "rev-parse", "HEAD").decode().strip(),
                    "maps_commit": git(args.maps, "rev-parse", "HEAD").decode().strip(),
                    "map": "Final Rage, compiled from official Xonotic map source",
                    "windows_hardware_validation": "NOT RUN", "fresh_profile_each_launch": True,
                    "project_working_tree_changed": bool(git(ROOT, "status", "--porcelain"))}
        (stage / "build-info.json").write_text(json.dumps(metadata, indent=2) + "\n")
        hashes = {str(p.relative_to(stage)): digest(p.read_bytes()) for p in stage.rglob("*") if p.is_file()}
        (stage / "SHA256SUMS.json").write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(args.output, "w", zipfile.ZIP_STORED) as z:
            for file in sorted(stage.rglob("*")):
                if file.is_file():
                    z.write(file, str(file.relative_to(stage.parent)))
    verify(args.output)
    print("SHA256", digest(args.output.read_bytes()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--dll-dir", type=Path, action="append", default=[])
    parser.add_argument("--maps", type=Path)
    parser.add_argument("--bsp", type=Path)
    parser.add_argument("--runtime-sources", type=Path)
    parser.add_argument("--sdl-license", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "build/Xonotic-Controller-Test-Windows-x64.zip")
    args = parser.parse_args()
    if args.verify:
        verify(args.verify)
    else:
        if not all((args.engine, args.dll_dir, args.maps, args.bsp)):
            parser.error("--engine, --dll-dir, --maps and --bsp are required")
        package(args)


if __name__ == "__main__":
    main()
