#!/usr/bin/env python3
"""Linux/MinGW build of the complete portable Windows controller test ZIP.

Prerequisites and GitHub Actions entry point: Docs/controller-milestone-1.md.
Uses private build caches, no worktrees, resets, merges, or environment publication.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def run(*args, env=None):
    print("+", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=ROOT / "build/portable-work")
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    work = args.work.resolve()
    sources = (args.sources or work / "sources").resolve()
    work.mkdir(parents=True, exist_ok=True)
    sources.mkdir(parents=True, exist_ok=True)
    cmake = os.environ.get("CMAKE", "cmake")
    cc = shutil.which(os.environ.get("MINGW_CC", "x86_64-w64-mingw32-gcc-posix"))
    cxx = shutil.which(os.environ.get("MINGW_CXX", "x86_64-w64-mingw32-g++-posix"))
    windres = shutil.which("x86_64-w64-mingw32-windres")
    strip = shutil.which("x86_64-w64-mingw32-strip")
    if not all((cc, cxx, windres, strip)):
        parser.error("Install the x86_64 MinGW POSIX compiler/binutils prerequisites")
    lock = json.loads((ROOT / "portable-dependencies.json").read_text())
    for entry in lock["sources"]:
        destination = sources / entry["name"]
        if not destination.exists():
            run("git", "clone", "--depth", "1", "--filter=blob:none", "--no-checkout", "--branch", entry["ref"], entry["url"], destination)
            exists = subprocess.run(["git", "-C", str(destination), "cat-file", "-e", entry["revision"]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
            if not exists:
                run("git", "-C", destination, "fetch", "--depth", "1", "origin", entry["revision"])
            if entry["name"] == "maps":
                run("git", "-C", destination, "sparse-checkout", "set", "--cone", "maps", "textures", "scripts", "sound", "env", "models")
            run("git", "-C", destination, "checkout", "--detach", entry["revision"])
        actual = subprocess.check_output(["git", "-C", str(destination), "rev-parse", "HEAD"], text=True).strip()
        if actual != entry["revision"]:
            raise ValueError(f"Unexpected source revision in {destination}; preserve it and use a fresh build cache")
    vorbis = sources / "vorbis"
    patch = ROOT / "patches/vorbis-mingw-library-names.patch"
    applied = subprocess.run(["git", "-C", str(vorbis), "apply", "--reverse", "--check", str(patch)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not applied:
        run("git", "-C", vorbis, "apply", "--check", patch)
        run("git", "-C", vorbis, "apply", patch)
    sdk_archive = work / "SDL2-devel-2.32.10-mingw.tar.gz"
    if not sdk_archive.exists():
        urllib.request.urlretrieve(lock["sdl"]["url"], sdk_archive)
    if hashlib.sha256(sdk_archive.read_bytes()).hexdigest() != lock["sdl"]["sha256"]:
        raise ValueError("Official SDL SDK checksum mismatch")
    sdk_root = work / "sdl-windows"
    if not (sdk_root / "SDL2-2.32.10").exists():
        sdk_root.mkdir(exist_ok=True)
        with tarfile.open(sdk_archive) as tar:
            # Python 3.12's data filter rejects paths escaping the extraction root.
            tar.extractall(sdk_root, filter="data")
    sdk = sdk_root / "SDL2-2.32.10/x86_64-w64-mingw32"
    runtime = work / "runtime-win"
    rc = work / "windres-cross"
    rc.write_text(f'#!/bin/sh\nexec "{windres}" --preprocessor="{cc}" --preprocessor-arg=-E --preprocessor-arg=-xc --preprocessor-arg=-DRC_INVOKED "$@"\n')
    rc.chmod(0o755)
    toolchain = work / "cross-runtime.cmake"
    toolchain.write_text(f'''set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(CMAKE_C_COMPILER "{cc}")
set(CMAKE_CXX_COMPILER "{cxx}")
set(CMAKE_RC_COMPILER "{rc}" CACHE FILEPATH "Cross resource compiler" FORCE)
set(CMAKE_FIND_ROOT_PATH "{runtime}")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
''')
    options = {
        "zlib": ["-DZLIB_BUILD_EXAMPLES=OFF"],
        "png": ["-DPNG_TESTS=OFF", "-DPNG_TOOLS=OFF", "-DPNG_STATIC=OFF"],
        "jpeg": ["-DENABLE_STATIC=OFF", "-DWITH_TURBOJPEG=OFF", "-DWITH_SIMD=OFF"],
        "ogg": ["-DINSTALL_DOCS=OFF"], "vorbis": [],
        "freetype": ["-DFT_DISABLE_BZIP2=ON", "-DFT_DISABLE_PNG=ON", "-DFT_DISABLE_HARFBUZZ=ON", "-DFT_DISABLE_BROTLI=ON", "-DFT_ENABLE_LOGGING=OFF"],
    }
    cross_env = os.environ.copy()
    cross_env.pop("PKG_CONFIG_SYSROOT_DIR", None)
    cross_env["PKG_CONFIG_LIBDIR"] = str(runtime / "lib/pkgconfig")
    for name, extra in options.items():
        build = work / "runtime-build" / name
        run(cmake, "-S", sources / name, "-B", build, f"-DCMAKE_TOOLCHAIN_FILE={toolchain}",
            f"-DCMAKE_INSTALL_PREFIX={runtime}", f"-DCMAKE_PREFIX_PATH={runtime}",
            "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=ON", "-DBUILD_TESTING=OFF", *extra, env=cross_env)
        run(cmake, "--build", build, f"-j{args.jobs}", env=cross_env)
        run(cmake, "--install", build, env=cross_env)
    run("python3", ROOT / "misc/tools/prepare-controller-deps.py")
    run("make", "-C", ROOT / "gmqcc", f"-j{args.jobs}", "gmqcc")
    game = ROOT / "data/xonotic-data.pk3dir"
    game_env = os.environ.copy()
    game_env["QCCFLAGS_WATERMARK"] = subprocess.check_output(["git", "-C", str(game), "rev-parse", "--short", "HEAD"], text=True).strip()
    run("make", "-B", "-C", game, f"-j{args.jobs}", "XON_BUILDSYSTEM=1", f"QCC={ROOT / 'gmqcc/gmqcc'}", "qc", env=game_env)
    run("make", "-C", ROOT / "darkplaces", f"-j{args.jobs}", "DP_MAKE_TARGET=mingw", f"CC={cc}",
        f"WINDRES={rc}", f"STRIP={strip}", f"SDL_CONFIG={sdk / 'bin/sdl2-config'} --prefix={sdk}", "DP_LINK_JPEG=dlopen", "sdl-release")
    native = work / "netradiant-build"
    native_flags = shlex.split(os.environ.get("PORTABLE_NATIVE_CMAKE_FLAGS", ""))
    run(cmake, "-S", sources / "netradiant", "-B", native, "-DBUILD_RADIANT=OFF", "-DDOWNLOAD_GAMEPACKS=OFF", "-DBUNDLE_LIBRARIES=OFF", *native_flags)
    run(cmake, "--build", native, "--target", "q3map2", f"-j{args.jobs}")
    map_work = work / "map-work"
    map_work.mkdir(exist_ok=True)
    shutil.copy2(sources / "maps/maps/finalrage.map", map_work / "finalrage.map")
    q3map = native / "q3map2"
    common = ["-game", "xonotic", "-threads", str(args.jobs), "-fs_basepath", str(ROOT),
              "-fs_game", "data", "-fs_pakpath", str(game), "-fs_pakpath", str(sources / "maps")]
    run(q3map, *common, "-meta", map_work / "finalrage.map")
    run(q3map, *common, "-vis", map_work / "finalrage.map")
    run(q3map, *common, "-light", "-fast", "-samples", "2", "-bounce", "1", map_work / "finalrage.map")
    run("python3", ROOT / "misc/tools/package-controller-windows.py", "--engine", ROOT / "darkplaces/darkplaces-sdl.exe",
        "--dll-dir", runtime / "bin", "--dll-dir", sdk / "bin", "--maps", sources / "maps", "--bsp", map_work / "finalrage.bsp",
        "--runtime-sources", sources, "--sdl-license", sdk_root / "SDL2-2.32.10/LICENSE.txt")


if __name__ == "__main__":
    main()
