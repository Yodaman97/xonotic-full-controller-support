#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT
# SDL_CONFIG may include --prefix for a workspace-local SDK.
read -r -a sdl_config <<< "${SDL_CONFIG:-sdl2-config}"
read -r -a sdl_cflags <<< "$("${sdl_config[@]}" --cflags)"
read -r -a sdl_libs <<< "$("${sdl_config[@]}" --libs)"
read -r -a extra_cflags <<< "${CONTROLLER_TEST_CFLAGS:-}"
read -r -a extra_ldflags <<< "${CONTROLLER_TEST_LDFLAGS:-}"
shared_sources=(darkplaces/vid_shared.c)
if [[ ${OS:-} == Windows_NT ]]; then
  # PE/COFF retains renderer unwind/reference sections from vid_shared.c.
  # Run the standalone production poller here; Linux also tests shared
  # movement/key handling without linking the rest of the game engine.
  extra_cflags+=(-DCONTROLLER_SDL_ONLY)
  shared_sources=()
fi
"${CC:-cc}" -std=gnu99 -g -Wall -Wextra -Wno-missing-field-initializers \
  -ffunction-sections -fdata-sections "${extra_cflags[@]}" \
  "${sdl_cflags[@]}" -Idarkplaces tests/controller_sdl.c \
  darkplaces/joy_sdl.c "${shared_sources[@]}" \
  -Wl,--gc-sections "${extra_ldflags[@]}" "${sdl_libs[@]}" -lm \
  -o "$test_dir/controller-tests"
"$test_dir/controller-tests"
