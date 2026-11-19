"""test_release_smoke.py — the shipping PRG boots.

Owner: doc/build_system.md

Contract source: [build_system.md § Test build pipeline](../../doc/build_system.md#test-build-pipeline):
every other Tier I test runs the debug PRG; this one boots the release
6510 PRG (`cse_release_prg`) the way a user does — the unrelocated
payload at $0801, started at its `SYS 2061` target ($080D, the
loader), through the real loader and cold init up to `main_loop_top`
— and checks the splash is on screen.
"""

from c64emu import C64Emu

SYS_TARGET = 0x080D     # BASIC stub: SYS 2061 → loader_entry


def test_release_prg_boots_to_the_main_loop(cse_release_prg):
    prg_path, map_path = cse_release_prg
    emu = C64Emu()
    load, payload = emu._read_prg(prg_path)
    assert load == 0x0801
    emu._ram[load:load + len(payload)] = payload     # as LOAD leaves it
    emu._load_symbols(map_path)
    emu.run_until(emu.sym("main_loop_top"), start_at=SYS_TARGET,
                  max_cycles=5_000_000)
    screen = [emu.screen_text(r) for r in range(25)]
    assert any(row.startswith("; cse v") for row in screen), screen
