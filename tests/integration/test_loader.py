"""test_loader.py — loader.s relocates the PRG as the harness assumes.

Owner: doc/modules/loader.md

Contract source: [loader.md § Design](../../doc/modules/loader.md#design).

Every other Tier I test loads the PRG through `EmuBase.load_prg()`,
whose `_relocate_segments()` copies each segment in Python, "as the
loader does".  This test holds the two to each other: it puts the
unrelocated PRG in memory, runs the real `loader_entry` up to the
`jmp _main`, and compares every relocated segment with what
`_relocate_segments()` produces — and checks the BSS is zeroed.
"""

from c64emu import C64Emu


def _segments(emu):
    """(name, run, size) of every segment the loader copies."""
    s = emu.sym
    return [("CODE+RODATA", s("__CODE_RUN__"), s("__CODE_SIZE__") + s("__RODATA_SIZE__")),
            ("KDATA", s("__KDATA_RUN__"), s("__KDATA_SIZE__"))]


def test_loader_entry_matches_python_relocation(cse_prg_per_cpu):
    prg_path, map_path = cse_prg_per_cpu

    ref = C64Emu()
    ref.load_prg(prg_path, map_path)                 # Python relocation

    emu = C64Emu()
    load_addr, payload = emu._read_prg(prg_path)
    emu._ram[load_addr:load_addr + len(payload)] = payload
    emu._load_symbols(map_path)                      # symbols only, no copy
    bss, bss_size = emu.sym("__BSS_RUN__"), emu.sym("__BSS_SIZE__")
    emu._ram[bss:bss + bss_size] = [0xA5] * bss_size  # stale RAM
    emu.run_until(emu.sym("_main"), start_at=emu.sym("loader_entry"),
                  max_cycles=2_000_000)

    for name, run, size in _segments(emu):
        assert size > 0
        assert bytes(emu._ram[run:run + size]) == bytes(ref._ram[run:run + size]), \
            f"{name} at ${run:04X} differs from _relocate_segments()"
    assert not any(emu._ram[bss:bss + bss_size]), "BSS not zeroed"
    assert emu.sp == 0xFF
