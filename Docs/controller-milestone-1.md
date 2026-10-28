# Windows controller support: milestone 1

Target: Windows 10/11, Xbox One/Series controllers over USB and Bluetooth.
No Steam Input, external mapper, rumble, aim assist, glyphs, or menu redesign.

## Source ownership and reproducibility

The top-level project normally obtains independent repositories through `./all`
and `misc/tools/all/{config,git,xonotic}.subr`. It has no submodules or revision
lock, and `initrepo()` expects an origin ending in `xonotic.git`; this fork's
name does not satisfy that assumption. Do not run `./all update` to prepare this
milestone: it can update or replace repositories outside the reviewed revision.

Instead, from the main checkout:

```sh
python3 misc/tools/prepare-controller-deps.py
python3 misc/tools/prepare-controller-deps.py --check
```

`controller-dependencies.json` locks exact upstream commits and SHA-256 hashes
of the two patches in `patches/`. The helper creates writable ordinary Git
checkouts on `feature/windows-controller-m1` when missing. It applies patches
to the index and working tree for review, preserves existing work, and refuses
different HEADs, unrecognized changes, or untracked files. It never resets,
pulls, pushes, or changes existing origins. `--check` is offline and read-only.
Existing checkouts are reused; no worktree is needed. No GitHub/GitLab fork or
write access to upstream is required. The main repository owns the patches, so
changes in its ignored dependency directories survive a fresh clone.

| Dependency | Locked base |
| --- | --- |
| DarkPlaces | `d93f9c4292039354a2b8d40d11bc386891e55fe5` + engine patch |
| xonotic-data.pk3dir | `09a3a7253a7290222da648193814355566bdbb46` + defaults patch |
| gmqcc | `b2a319efb41069b9a250e76991dbe505ff8d030d` |

These are source revision locks, not a byte-identical SDK or asset lock. Native
compiler/SDL package versions and optional map packs must be recorded separately.
Game compilation uses the locked revision as its watermark and does not need
release tags. Crypto libraries are optional for this build; missing
`crypto_keygen` does not affect controller input.

When editing a dependency, regenerate its patch with
`git -C <dependency> diff --binary --full-index HEAD` (include new source files
with `git add -N` first), then update its manifest SHA-256. Commit the patches,
manifest, tests, and documentation in the main feature branch for review.
Do not change a locked base to accommodate unknown local changes.

## Backend decision

**SDL2 GameController is the sole authority in the SDL client on Windows.**
SDL handles the Windows transport (XInput/HIDAPI as appropriate), controller
database, USB/Bluetooth differences, and device discovery. The engine does not
also enumerate native XInput devices or merge native XInput state into SDL
state. Windows XInput code remains in `vid_shared.c` for compatibility, but the
SDL backend no longer calls `VID_Shared_SetJoystick()` or
`VID_Shared_BuildJoyState_Begin()`. `joy_xinputavailable` is consequently not an
SDL availability diagnostic; use `joy_detected` and `joy_active`.

This prevents the same Xbox device being counted/read through both APIs.
Only the selected SDL device is sampled; hotplug events are not also translated
into button actions. External mappers can create additional virtual devices:
close Steam and other mappers for native validation.

Implementation locations (inside the engine patch):

- `joy_sdl.{c,h}`: `JoySDL_Select`, `JoySDL_Close`, `JoySDL_Poll` own one SDL
  device. Selection compares instance IDs, not just enumeration indices, and
  handles detached devices. A mapped controller owns its joystick handle; it is
  closed exactly once. Failed opens are retried on subsequent frames.
- `vid_sdl.c`: `VID_Init` initializes `SDL_INIT_GAMECONTROLLER` (which includes
  joystick support); `Sys_SDL_HandleEvents` refreshes selection each frame;
  `VID_EnableJoystick` honors both its enable argument and `joy_enable`;
  `VID_BuildJoyState` samples only SDL. Counts contain no native XInput duplicates.
- `vid_shared.c`: `VID_ReleaseJoyState` releases keys using the previous device's
  mapping before a replacement device is sampled. Existing
  `VID_ApplyJoyState` supplies movement, aiming, deadzones, and key events.
  A removal arriving between selection and polling also retains the old layout
  on the neutral state, so held controller actions release under the correct keys.
- `makefile.inc` and `darkplaces-sdl2-vs2019.vcxproj` include the new poller.
- Game source `binds-xonotic.cfg`: enables controllers by default and adds
  standardized Xbox bindings without changing keyboard/mouse or legacy JOY binds.

Mapped SDL devices use the existing `X360_*` logical keys and `joy_x360_*`
axis/deadzone/sensitivity settings on every platform. SDL Y axes are inverted
to match the old XInput coordinate convention. Six named standard axis slots
are read strictly below the SDL sentinel; raw reports are capped at the engine's
16-axis/36-button storage. Both signed stick endpoints normalize exactly.
LT and RT retain independent analog axes (slots 4 and 5, range 0..1); firing uses
independent digital thresholds controlled by `joy_sdl2_trigger_deadzone` (0.5).
Trigger-to-button indices no longer depend on `SDL_CONTROLLER_BUTTON_MAX`.

One local controller is active (`joy_index`, default 0). Existing user config
loads after defaults: a saved `joy_enable 0` or custom binding remains respected.
Use `joy_enable 1` to reenable it. Automatic detection does not override an
explicit opt-out. Raw joysticks retain JOY/AUX mappings. Guide/Share are not bound.

## Default gameplay layout

| Control | Action |
| --- | --- |
| Left stick | Move/strafe |
| Right stick | Aim |
| A / B | Jump / crouch |
| X / Y | Use / next weapon |
| LB / RB | Previous / next weapon |
| LT / RT | Secondary / primary fire |
| Left / right stick click | Crouch / zoom |
| Start / Back (View) | Open menu / scoreboard |
| D-pad Up/Down/Left/Right | Weapon groups 1/2/3/4 |

Menu traversal is not completed by this milestone. Keep keyboard/mouse available
in menus. Leave `joy_axiskeyevents 0` for normal gameplay/rebinding; the legacy
global keyboard-emulation mode changes the controller key mapping. Do not enable
it as a substitute for a future context-aware menu implementation.

## Native Windows build and launch

Use the **MSYS2 UCRT64** shell (64-bit), not the plain MSYS shell. Install MSYS2
from its official distribution and complete its documented `pacman -Syu` update
cycle, reopening the shell if requested. Then:

```sh
pacman -S --needed git make python zip \
  mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-SDL2 \
  mingw-w64-ucrt-x86_64-zlib mingw-w64-ucrt-x86_64-libjpeg-turbo

git -c core.autocrlf=false clone https://github.com/Yodaman97/xonotic-full-controller-support.git
cd xonotic-full-controller-support
# Check out the reviewed milestone feature branch/commit before continuing.
python3 misc/tools/prepare-controller-deps.py
python3 misc/tools/prepare-controller-deps.py --check

make -C gmqcc -j4 CXX=g++ gmqcc.exe
QCCFLAGS_WATERMARK=$(git -C data/xonotic-data.pk3dir rev-parse --short HEAD) \
  make -C data/xonotic-data.pk3dir -j4 XON_BUILDSYSTEM=1 \
  QCC="$PWD/gmqcc/gmqcc.exe" qc
make -C darkplaces -j4 DP_MAKE_TARGET=mingw CC=gcc WINDRES=windres \
  DP_LINK_JPEG=dlopen sdl-release
```

Use SDL2 >= 2.0.18 (current MSYS2 packages qualify). Tests use SDL's virtual
joystick API. The official SDL2 SDK version used for Linux-to-Windows
cross-compilation is recorded in the validation section below.

The resulting `darkplaces/darkplaces-sdl.exe` is the modified engine. Launch it
from UCRT64 so `/ucrt64/bin` supplies SDL2 and compiler runtime DLLs. A standalone
package must place the required DLLs beside the executable (inspect dependencies
with `objdump -p`); do not copy arbitrary DLLs from third-party download sites.

The code checkouts do not include the complete map/music repositories. For a
playable source installation, add upstream maps (large download):

```sh
git clone --depth 1 --branch master https://gitlab.com/xonotic/xonotic-maps.pk3dir.git data/xonotic-maps.pk3dir
# Optional music:
# git clone --depth 1 https://gitlab.com/xonotic/xonotic-music.pk3dir.git data/xonotic-music.pk3dir

./darkplaces/darkplaces-sdl.exe -xonotic -basedir "$PWD" \
  -userdir "$PWD/build/controller-profile" +joy_enable 1
```

Use a fresh profile for default-binding tests. Existing profiles retain their
saved overrides; `exec binds-xonotic.cfg` reapplies defaults but also resets
other bindings, so do that only deliberately. Start a local match to test the
modified server/client gamecode. Remote servers can supply their own gamecode.
The root release `Makefile` is not the Git build entry point.

## Automated checks

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
bash tests/run-controller-tests.sh
```

The SDL test compiles the production `joy_sdl.c` and, on Linux, relevant portions
of `vid_shared.c`, then drives SDL virtual devices. Windows runs the standalone
poller tests: the PE/COFF linker retains unrelated renderer sections when linking
`vid_shared.c` alone. Shared movement/key-event integration is tested on Linux.
Together these checks cover startup/late attach,
every mapped button, both triggers independently and together, stick signs and
deadzones, additive movement/look state, one initial key event, disconnect key
release, reconnect at the same index, disable, and oversized raw reports.
SDL device emulation is not a USB/Bluetooth driver test. The key-event recorder
does not replace a full Windows window-system test.

On Linux, add ASan/UBSan through `CONTROLLER_TEST_CFLAGS` and
`CONTROLLER_TEST_LDFLAGS` (`-fsanitize=address,undefined` in both). `SDL_CONFIG`
can include `--prefix` for a local SDL SDK. The tests do not require a display,
Steam, or a controller. The Python suite checks real temporary Git repositories:
fresh setup, repeatability, checksum validation, and preservation of unknown work.
The existing gmqcc suite can also run on Linux with `make -C gmqcc test`; its
upstream Makefile excludes the test runner on Windows.

## Physical Windows acceptance checklist

Run every row with **both Xbox One and Xbox Series**, first USB, then Bluetooth,
on Windows 10 and 11 where available. Close Steam completely, disable external
mappers, record controller firmware, SDL version, OS version, connection type,
dependency lock/patch hashes, profile, and pass/fail evidence.

| Scenario | Procedure and expected result |
| --- | --- |
| Connected at startup | Plug in/pair before launch. `joy_detected` includes the device, `joy_active` is 1, and console reports one selected SDL GameController instance. No manual enable required in a fresh profile. |
| Late connection | Launch disconnected, then connect. Detection/activation and gameplay work without `vid_restart` or relaunch. |
| Disconnect held input | Hold RT and a movement direction; unplug or disconnect Bluetooth. Firing/movement stop, held keys release, keyboard/mouse still work. |
| Reconnect | Reconnect without relaunch. New instance opens, bindings persist, no stuck firing, no stale buttons. Repeat several times, including while firing. |
| Stick motion/aim | Check all directions, endpoints, slow partial deflection, and centered drift. Forward and aim-up have correct signs; pitch is not inverted by default. |
| Triggers | Press LT only, RT only, both, then release one while holding the other. Primary/secondary fire remain independent; gradual deflection crosses the configured threshold once. |
| Duplicate events | With `developer 1; developer_insane 1`, tap A and each trigger. Inspect `Key_Event` logs: one initial down and one up per tap, no JOY/AUX duplicate for the same control. Long holds can produce the existing key-repeat events; gameplay ignores repeated bind presses. |
| Keyboard/mouse coexistence | Alternate and combine WASD, mouse aim/fire, and controller input. Disconnect controller while keyboard/mouse input is held; keyboard/mouse remain usable and bindings unchanged. |
| Disabled controller | Save `joy_enable 0`, restart/connect, verify keyboard/mouse only; set `joy_enable 1`, verify activation without restart. |
| Enumeration change | Connect a second device, remove the selected device, and reconnect it. Verify selection follows documented `joy_index`, releases prior held actions, and samples only one device. |
| Steam absent | Reboot or exit Steam, confirm no Steam process remains, launch the modified executable directly, and repeat movement/fire/hotplug. |

Missing device access or a passing cross-build does not establish a hardware
pass. Mark unexecuted rows **NOT RUN** rather than passed.

## Validation record

- Linux: SDL client, dedicated engine, and client/server/menu gamecode build.
- Linux: rebuilt dedicated engine loaded gamecode, spawned the initialization
  map, and reported server status in a bounded headless smoke check.
- Linux: 97 upstream gmqcc tests passed.
- Linux: SDL virtual-controller checks passed with ASan/UBSan.
- Dependency preparation: eight automated tests passed; current lock verified,
  including a check that Git preserves the locked patch bytes on storage.
- The real engine/game-source patches were applied to clean local clones and
  checked again to verify replay and repeatability without changing the originals.
- Windows x64: engine cross-build passed with Debian MinGW GCC 14-posix and the
  official SDL2 2.32.10 MinGW SDK. The SDK archive SHA-256 is
  `83a5d74012311edc3c0d40ea6faecbe57ad692aa033fa5dc273cc937e3938ff2`.
  Cross-compilation does not run a Windows executable or certify its DLL bundle.
- Windows USB/Bluetooth, actual game window behavior, and Steam-absent physical
  checks: **NOT RUN in this Linux cloud environment**.
- Full menu support, rumble, aim assist, and glyphs remain outside this milestone.

## Portable Windows test ZIP

`Xonotic-Controller-Test-Windows-x64.zip` is built by
`.github/workflows/portable-windows.yml`. On the feature branch, open the
**Portable Windows controller test** workflow in GitHub Actions, run it, and
download the **Xonotic-Controller-Test-Windows-x64** artifact from the completed
run. The artifact contains the named test ZIP. The workflow also runs on pushes
that change packaging inputs. It uploads a test artifact for 30 days; it does
not merge, publish an environment, or create an official release.

Extract the complete test ZIP into a writable folder, connect an Xbox
controller, close Steam/external mappers, and double-click `Play-Xonotic.bat`.
The launcher anchors paths to its own directory and creates a fresh
`profiles/controller-test-*` profile on every launch. It starts **Final Rage
deathmatch with three bots**, without a public master-server advertisement.
Your regular Xonotic settings are not read or overwritten. Keyboard/mouse can
still be used, including menus. Logs/settings remain in that launch's profile.

Contents include the modified x64 SDL engine, freshly compiled `progs.dat`,
`csprogs.dat`, and `menu.dat`, upstream game assets, fonts, a compiled Final Rage
map and map assets, Windows SDL/zlib/PNG/JPEG/FreeType/Ogg/Vorbis DLLs, licensing,
source snapshots, dependency locks, and per-file SHA-256 hashes. Runtime DLLs
are built from locked upstream sources, except SDL2, which uses its official
checksum-verified MinGW SDK. Compatibility aliases preserve the DLL filenames
the engine and import tables expect. The Vorbis patch supplies missing LIBRARY
names in upstream `.def` files for GNU binutils; it changes no audio algorithms.

No development tools or administrator installation are required on the test PC.
Optional online download/crypto and module-music libraries are not included;
this package targets offline controller testing. Physical Windows controller
acceptance checks above remain mandatory even when packaging verification passes.

To reproduce on an ordinary Ubuntu 24.04 Linux build machine (allow at least
20 GB free disk space and the upstream downloads):

```sh
sudo apt-get install build-essential git cmake pkg-config python3 \
  gcc-mingw-w64-x86-64-posix g++-mingw-w64-x86-64-posix \
  libglib2.0-dev libxml2-dev libminizip-dev libpng-dev libjpeg-dev libwebp-dev libgl-dev zlib1g-dev
python3 misc/tools/build-portable-windows.py --jobs 4
python3 misc/tools/package-controller-windows.py \
  --verify build/Xonotic-Controller-Test-Windows-x64.zip
```

`portable-dependencies.json` pins map assets, NetRadiant/q3map2, runtime sources,
and the SDL2 SDK checksum. The builder uses the milestone's existing locked
engine/game/compiler, builds both engine and all three game programs, compiles
the official map source with BSP/visibility/lighting passes, packages the game,
and verifies archive CRCs, SHA-256 hashes, x64 PE headers, imported DLL closure,
dynamically loaded runtime filenames, launcher paths/profile isolation, game
programs, assets, and deathmatch spawn entities. The game/map PK3s are ordinary
ZIPs and retain upstream asset sources and attribution. Code/runtime source
snapshots are in `Source/corresponding-source.tar.gz`.

The Linux cloud build cannot execute a native Windows GUI session or certify
controller hardware. GitHub Actions artifact availability is established only
after a completed run; a pushed workflow alone is not a published ZIP.
