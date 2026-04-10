"""
test_step_rom.py — Debugger step-into JSR with ROM target fallback.

Verifies that cmd_step ('t1') correctly falls back to step-over when
the JSR target is in KERNAL ROM ($E000–$FFFF), and steps into RAM
targets normally.  Uses C64Emu with the production PRG — no test stubs.

Replaces the xfailed TestStepIntoJSR_ROMFallback in test_repl.py.
"""

import subprocess
import pathlib
import pytest

from c64emu import C64Emu

ROOT = pathlib.Path(__file__).parent.parent
PRG  = ROOT / "build" / "cmos" / "cse-cmos.prg"
MAP  = ROOT / "build" / "cmos" / "cse.map"

# Address where we place the test JSR instruction
USER_CODE = 0x3000
# Snapshot location for step_bp (captured by patched dbg_enter)
SNAP_ADDR = 0x3F00


def _ensure_built():
    if not PRG.exists() or not MAP.exists():
        subprocess.run(["make", "CPU=65c02"], cwd=ROOT, check=True,
                       capture_output=True)


@pytest.fixture(scope="session")
def prg_map():
    _ensure_built()
    return PRG, MAP


def _run_step(prg_map, target_lo, target_hi):
    """Set up a JSR instruction at USER_CODE, run 't1' via exec_line,
    return the step_bp address that cmd_step armed before dbg_enter."""
    prg, map_path = prg_map
    emu = C64Emu()
    emu.load_prg(prg, map_path)

    # Init
    emu.jsr(emu.sym("theme_init"))
    emu.jsr(emu.sym("restore_colors"))
    emu.jsr(emu.sym("kernal_init"))

    # Patch dbg_enter: snapshot step_bp[0..1] → SNAP_ADDR, then
    # clear dbg_reason + set dbg_bp_hit=$FF + RTS.
    # This lets cmd_step arm step_bp normally, then we capture it
    # before the (now-stubbed) user code execution.
    dbg_enter = emu.sym("dbg_enter")
    sb = emu.sym("step_bp")
    dr = emu.sym("dbg_reason")
    bh = emu.sym("dbg_bp_hit")
    patch = [
        0xAD, sb & 0xFF, sb >> 8,                       # LDA step_bp
        0x8D, SNAP_ADDR & 0xFF, SNAP_ADDR >> 8,         # STA SNAP_ADDR
        0xAD, (sb+1) & 0xFF, (sb+1) >> 8,               # LDA step_bp+1
        0x8D, (SNAP_ADDR+1) & 0xFF, (SNAP_ADDR+1) >> 8, # STA SNAP_ADDR+1
        0xA9, 0x00, 0x8D, dr & 0xFF, dr >> 8,           # LDA #0; STA dbg_reason
        0xA9, 0xFF, 0x8D, bh & 0xFF, bh >> 8,           # LDA #$FF; STA dbg_bp_hit
        0x60,                                             # RTS
    ]
    for i, b in enumerate(patch):
        emu.memory[dbg_enter + i] = b

    # User code at USER_CODE: JSR <target>
    emu.memory[USER_CODE]     = 0x20
    emu.memory[USER_CODE + 1] = target_lo
    emu.memory[USER_CODE + 2] = target_hi

    # Pre-set debugger state (as if we stopped at USER_CODE)
    emu.write_word(emu.sym("cur_addr"), USER_CODE)
    emu.write_word(emu.sym("brk_pc"), USER_CODE)
    emu.memory[emu.sym("dbg_reason")] = 1
    emu.memory[emu.sym("dbg_bp_hit")] = 0xFF
    emu.write_word(emu.sym("block_size"), 0x0001)

    # Clear step_bp and snapshot
    for i in range(8):
        emu.memory[sb + i] = 0
    emu.memory[SNAP_ADDR] = 0
    emu.memory[SNAP_ADDR + 1] = 0

    # Write "t1" to line_buf (PETSCII: t=$54, 1=$31)
    lb = emu.sym("line_buf")
    emu.memory[lb]     = 0x54
    emu.memory[lb + 1] = 0x31
    emu.memory[lb + 2] = 0x00

    emu.jsr(emu.sym("exec_line"), max_cycles=200_000)

    return emu.memory[SNAP_ADDR] | (emu.memory[SNAP_ADDR + 1] << 8)


# ── Tests ───────────────────────────────────────────────────────────────────

class TestStepIntoJSR_ROMFallback:
    """JSR step-into to KERNAL ROM falls back to step-over."""

    def test_jsr_into_ram_steps_into(self, prg_map):
        """JSR $3010 (RAM) → step into the target."""
        assert _run_step(prg_map, 0x10, 0x30) == 0x3010

    def test_jsr_into_kernal_steps_over(self, prg_map):
        """JSR $FFD2 (CHROUT, KERNAL ROM) → step OVER (cur_addr+3)."""
        assert _run_step(prg_map, 0xD2, 0xFF) == USER_CODE + 3

    def test_jsr_into_e000_boundary_steps_over(self, prg_map):
        """JSR $E000 (first KERNAL byte) → step OVER."""
        assert _run_step(prg_map, 0x00, 0xE0) == USER_CODE + 3

    def test_jsr_into_ffff_boundary_steps_over(self, prg_map):
        """JSR $FFFF (last byte) → step OVER."""
        assert _run_step(prg_map, 0xFF, 0xFF) == USER_CODE + 3

    def test_jsr_into_a000_steps_into(self, prg_map):
        """JSR $A000 (workspace, BASIC unmapped) → step INTO."""
        assert _run_step(prg_map, 0x00, 0xA0) == 0xA000

    def test_jsr_into_bfff_steps_into(self, prg_map):
        """JSR $BFFF (top of workspace) → step INTO."""
        assert _run_step(prg_map, 0xFF, 0xBF) == 0xBFFF

    def test_jsr_into_c000_steps_into(self, prg_map):
        """JSR $C000 (RAM above BASIC region) → step INTO."""
        assert _run_step(prg_map, 0x00, 0xC0) == 0xC000

    def test_jsr_into_dfff_steps_into(self, prg_map):
        """JSR $DFFF (I/O area, RAM writable underneath) → step INTO."""
        assert _run_step(prg_map, 0xFF, 0xDF) == 0xDFFF
