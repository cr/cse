# ROM files

This directory holds the C64 ROM images used by CSE's test
harness and by the ROMSET-investigation Makefile target, and the
MEGA65 ROM images of the m65 port.  Proprietary ROMs are copied
in locally and gitignored; open ROMs are committed:

## CBM ROMs — **gitignored, not in the repo**

| File | Size | Source |
|------|------|--------|
| `kernal_cbm.bin` | 8 KB | Commodore C64 KERNAL ROM |
| `basic_cbm.bin`  | 8 KB | Commodore C64 BASIC ROM |
| `chargen_cbm.bin` | 4 KB | Commodore C64 character ROM |

These are © Commodore Business Machines and **cannot** be
redistributed.  The pytest harness and the C64Emu fixture both
require `kernal_cbm.bin`; CSE's test setup expects you to
copy it from a legitimate VICE installation:

    cp /path/to/vice/C64/kernal-901227-03 rom/kernal_cbm.bin

VICE itself ships with these ROMs under its bundled-tools
distribution.  The CSE test suite reads `kernal_cbm.bin` once
at fixture init and never modifies it.

## MEGA65 Open ROMs — **committed under LGPL-3.0**

| File | Size | Source |
|------|------|--------|
| `kernal_mega.bin` | 8 KB | MEGA65 Open KERNAL |
| `basic_mega.bin`  | 8 KB | MEGA65 Open BASIC |
| `chargen_mega.bin` | 4 KB | MEGA65 Open CHARGEN |

These ROMs are part of the **MEGA65 Open ROMs project** —
clean-room C64-compatible ROM replacements written from scratch
by the MEGA65 team to avoid the CBM copyright.  Upstream:
[github.com/MEGA65/open-roms](https://github.com/MEGA65/open-roms).
Licensed under **GNU LGPL-3.0** (see the upstream repo for the
canonical LICENSE).

CSE includes them as test artifacts for the ROMSET investigation
documented in the Phase-11 commit (`Phase 11: DDD cleanup,
ROMSET support, Open-KERNAL investigation`).  They are NOT
required by any active build target or test path — only by the
optional `ROMSET=mega` Makefile mode (see `Makefile` line 49).

If you reuse these binaries elsewhere, retain the LGPL-3.0
notice and the MEGA65 attribution.

## MEGA65 ROMs

| File | Size | Tracked | Source |
|------|------|---------|--------|
| `mega65.rom` | 128 KB | **gitignored** | the MEGA65 ROM xmega65 uses (BASIC 65, C65/MEGA65 KERNAL, C64 mode) |
| `mega65_open.rom` | 128 KB | committed, LGPL-3.0 | MEGA65 Open ROMs, MEGA65 build |

`mega65.rom` is © the MEGA65 project and Commodore and cannot be
redistributed.  `make m65-rom` (`dev/find_m65_rom.py`) finds it in
xmega65's data directory and copies it here:

| Searched | Where |
|----------|-------|
| `$XEMU_MEGA65_DIR` | if set, the only place searched |
| macOS | `~/Library/Application Support/xemu-lgb/mega65/` |
| Linux | `~/.local/share/xemu-lgb/mega65/` |

In each, `MEGA65.ROM` first, then `hdos/MEGA65.ROM`.  The script
accepts only a 128 KB image with a C65/MEGA65 KERNAL (a reset
vector at `$3FFFC`), prints its version (`V920421` …, at offset
`$16`), and replaces a stale copy.  `dev/capture_m65_state.py`
runs the same discovery and refuses to record a snapshot whose ROM
differs from `mega65.rom`, so the snapshot and this copy name the
same ROM.

`mega65_open.rom` is `bin/mega65.rom` of
[github.com/MEGA65/open-roms](https://github.com/MEGA65/open-roms)
at commit `f9a1bab1` (2021-08-24, the last change to that file;
version string `O21082420`), SHA-256
`430e64de736d590b26c3314a65627e5ea366a5bf596f2d935e7a041828784422`.
It is **not** a substitute for `mega65.rom` on the m65 target: it
holds only a C64-mode KERNAL and BASIC (at `$2E000`) — no C65/MEGA65
KERNAL at `$3E000` (that 8 KB is zeros), no BASIC 65 — and its reset
starts in C64 mode.  Upstream rates its MEGA65 support "PARTIAL …
not tested yet".  A native PRG at `$2001` cannot run on it; it can
serve the C64 target under C64 mode on a MEGA65, the role the C64
Open ROMs above have under `ROMSET=mega`.

## Local-only artefacts — **gitignored**

| File pattern | Purpose |
|--------------|---------|
| `*_patched.bin`, `*_upatched.bin` | Local instrumentation — patched/unpatched copies used during ROM-side debugging. |
| `.pytest_cache/` | pytest's per-directory cache. |

These are produced by local workflows and are excluded from
the repo via `.gitignore`.
