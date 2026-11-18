# ROM files

**Owner:** [doc/build_system.md](../doc/build_system.md)

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

## Open ROMs, C64 build — **committed under LGPL-3.0**

| File | Size | Upstream file | SHA-256 |
|------|------|---------------|---------|
| `kernal_mega.bin` | 8 KB | `bin/kernal_generic.rom` | `88e86ed3d0c710edab8f90ad146faa8de1ead11f43494b176c7b54724ca721c6` |
| `basic_mega.bin`  | 8 KB | `bin/basic_generic.rom` | `54a1464b4b27c9dc61bbd62a818fdd12ec99af9089111005a5add0ad0e6bd5ec` |
| `chargen_mega.bin` | 4 KB | `bin/chargen_pxlfont_2.3.rom` | `bc5ed24e8e694543f0229800d050acff86d9674aec6dbd95055a26e824d8a395` |

The *generic* (C64-compatible) build of the **Open ROMs** —
clean-room ROM replacements written from scratch to avoid the CBM
copyright, by the project the MEGA65 team hosts.  Upstream:
[github.com/MEGA65/open-roms](https://github.com/MEGA65/open-roms),
KERNAL and BASIC at commit `5192c683` (2021-08-23), the PXL font at
`b9661811` (2020-03-06) — each the last change to that file.  The
`_mega` suffix is the `ROMSET=mega` name, not the platform: these
are the C64 images, not the MEGA65 one below.  Licensed under **GNU
LGPL-3.0** (see the upstream repo for the canonical LICENSE).

They serve the optional `ROMSET=mega` mode of `make run`
([build_system.md § ROM sets](../doc/build_system.md#rom-sets)):
the C64 builds of CSE under VICE on an open KERNAL.  No test path
needs them; `tests/unit/test_open_roms.py` pins them to the
upstream files above.

If you reuse these binaries elsewhere, retain the LGPL-3.0
notice and the attribution.

## MEGA65 ROMs

| File | Size | Tracked | Source |
|------|------|---------|--------|
| `mega65.rom` | 128 KB | **gitignored** | the MEGA65 ROM xmega65 uses (BASIC 65, C65/MEGA65 KERNAL, C64 mode) |
| `mega65_open.rom` | 128 KB | committed, LGPL-3.0 | MEGA65 Open ROMs, MEGA65 build |

`mega65.rom` is © the MEGA65 project and Commodore and cannot be
redistributed.  `make m65-rom` (`dev/find_m65_rom.py`) finds it in
xmega65's data directory and copies it here; where it searches and
what it accepts is in
[build_system.md § MEGA65 ROM](../doc/build_system.md#mega65-rom).

`mega65_open.rom` is `bin/mega65.rom` of
[github.com/MEGA65/open-roms](https://github.com/MEGA65/open-roms)
at commit `f9a1bab1` (2021-08-24, the last change to that file;
version string `O21082420`), SHA-256
`430e64de736d590b26c3314a65627e5ea366a5bf596f2d935e7a041828784422`
— identical to upstream's current file (checked 2026-11-18).  It is
the Open ROMs' only MEGA65 image (`bin/mega65_orfont.rom` is the same
build with the Open ROMs font); upstream's source is still developed,
but its binaries were last built in 2021.

It is **not** a substitute for `mega65.rom` on the m65 target:

- It holds a C64-style KERNAL and BASIC at `$2E000` and **no C65 /
  MEGA65 KERNAL** — `$3E000–$3FFFF` is zeros — and no BASIC 65.
- It starts in its *legacy* (C64) mode: the Hypervisor enters it
  through `$FFF8` (upstream `STATUS.md`, *API extensions — MEGA65
  build*).
- Its own *native mode* (`GO 65`) is the Open ROMs' MEGA65-enhanced
  environment on that same C64-style KERNAL — 80 columns (partial),
  MEGA65 storage, extra BASIC commands — not MEGA65 mode in the
  BASIC 65 sense.  Of the C65 jump table it implements `PRIMM`
  (`$FF7D`) only; `VECTOR`, `SETBNK`, `SCRORG`, `JSRFAR`, `VERSIONQ`
  and the `SYS` map that the m65 build relies on are absent.
- Upstream rates its MEGA65 support "PARTIAL … code mostly complete,
  but not tested yet".

So the m65 PRG cannot run on it as the m65 build is designed.  It can
serve the C64 target under its legacy mode on a MEGA65, the role the
C64 build above has under `ROMSET=mega`.  Running CSE on the Open
ROMs on both platforms is a stretch goal
([TODO § M65 slice 2](../doc/TODO.md#m65-slice-2--the-mega65-platform-r7-platform-layer)).

## Local-only artefacts — **gitignored**

| File pattern | Purpose |
|--------------|---------|
| `*_patched.bin`, `*_upatched.bin` | Local instrumentation — patched/unpatched copies used during ROM-side debugging. |
| `.pytest_cache/` | pytest's per-directory cache. |

These are produced by local workflows and are excluded from
the repo via `.gitignore`.
