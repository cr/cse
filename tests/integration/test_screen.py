"""test_screen.py — Tier-I contract tests for screen.s.

Contract source: [doc/modules/screen.md](../../doc/modules/screen.md).

Coverage of the documented contract
-----------------------------------
All 8 exported entry points + 3 BSS theme bytes:

    restore_colors      — TestRestoreColors (border/bg/chrcolor + color RAM)
    reset_screen        — TestResetScreen  (clear + colors + cursor reset)
    vic_reset           — TestVicReset     (6 VIC register writes)
    scroll_up           — TestScrollUp     (1-row, 5-row, full, io_cy clamp)
    newline             — TestNewline      (advance + scroll at bottom)
    cursor_show         — TestCursorToggle (XOR $80 at cursor)
    cursor_hide         — TestCursorToggle (alias; restores via second toggle)
    theme_border / theme_bg / theme_fg (BSS) — TestRestoreColors

Out-of-scope (vocal skips — see TestVicHardwareBehaviour)
---------------------------------------------------------
C64Emu treats VIC-II registers as flat RAM.  The WRITE values are
verified (TestVicReset); the VIC's actual response (display mode,
IRQ latch clearing, raster timing) needs VICE.  See the ⚠ MID-RISK
L2 GAP preamble on TestVicHardwareBehaviour.

Tier: screen.s is Tier I by design (per testing.md's per-module
table).  Even though py65's emulator doesn't model VIC internals,
C64Emu gives us real KERNAL vectors, real $01 banking, and a
production-representative initialization path — the natural home
for a module whose whole contract is "pokes VIC registers, scrolls
screen RAM, syncs cursor via PLOT."

Requires: build/cmos/cse-cmos.prg (auto-built by cse_prg fixture).
"""

import pytest
from c64emu import C64Emu, SCREEN, COLS, ROWS, COLOR_RAM


def make_emu(cse_prg):
    """Fresh C64Emu with CMOS PRG loaded + screen initialized."""
    prg, map_path = cse_prg
    emu = C64Emu()
    emu.load_prg(prg, map_path)
    emu.init_cse()
    return emu


def fill_row(emu, row, sc):
    base = SCREEN + row * COLS
    for c in range(COLS):
        emu.memory[base + c] = sc


def row_is(emu, row, sc):
    base = SCREEN + row * COLS
    return all(emu.memory[base + c] == sc for c in range(COLS))


# ── restore_colors ──────────────────────────────────────────────────────────

class TestRestoreColors:
    """restore_colors sets VIC border/bg and fills color RAM."""

    def test_fills_color_ram(self, cse_prg):
        emu = make_emu(cse_prg)
        fg = emu.memory[emu.sym("theme_fg")]
        assert emu.memory[COLOR_RAM] == fg
        assert emu.memory[COLOR_RAM + 999] == fg

    def test_sets_border(self, cse_prg):
        emu = make_emu(cse_prg)
        assert emu.memory[0xD020] == emu.memory[emu.sym("theme_border")]

    def test_sets_background(self, cse_prg):
        emu = make_emu(cse_prg)
        assert emu.memory[0xD021] == emu.memory[emu.sym("theme_bg")]

    def test_sets_chrcolor(self, cse_prg):
        emu = make_emu(cse_prg)
        assert emu.memory[0x0286] == emu.memory[emu.sym("theme_fg")]


# ── reset_screen ────────────────────────────────────────────────────────────

class TestResetScreen:
    """reset_screen clears screen, restores colors, resets cursor."""

    def test_clears_screen(self, cse_prg):
        emu = make_emu(cse_prg)
        for i in range(100):
            emu.memory[SCREEN + i] = 0x01
        emu.jsr(emu.sym("reset_screen"))
        assert row_is(emu, 0, 0x20)
        assert row_is(emu, 24, 0x20)

    def test_resets_cursor(self, cse_prg):
        emu = make_emu(cse_prg)
        emu.set_cursor(10, 20)
        emu.jsr(emu.sym("reset_screen"))
        assert emu.memory[0xD6] == 0
        assert emu.memory[0xD3] == 0


class TestKernalScreenReset:
    """kernal_screen_reset restores KERNAL screen-edit ZP to a
    pristine post-init state.  Defends against NMI-during-CHROUT
    corruption: when RESTORE fires inside a tight `$FFD2` loop,
    KERNAL leaves $D5 / $D9-$F1 / $D8 / $D4 / $CE / $C6 in
    transient mid-update values; PLOT (called by io_sync) does
    not touch any of those.  Without this sanitize step the
    editor swallows the first cursor key and the REPL's line-
    edit cursor drifts off-screen.

    Call-site discipline: kernal_screen_reset is called ONLY
    from `refresh_body` (the cse_refresh / kernel-mode NMI
    dispatch), NOT from the broader `reset_screen` proc.  An
    earlier rc2 candidate landed the call inside reset_screen
    and regressed userland CHROUT positioning — the cold-init
    and `x`-command callers of reset_screen do not own a
    transient mid-CHROUT state, and wiping LDTB1 / $D5 on those
    paths corrupted the line-link state KERNAL had built up
    from prior REPL output.  Tests below pin the helper itself,
    not its (single) call site.
    """

    def _poison(self, emu):
        """Set every sanitized byte to a non-pristine value."""
        emu.memory[0xC6] = 0x05         # NDX: 5 buffered keys
        emu.memory[0xD4] = 0x01         # QTSW: quote mode active
        emu.memory[0xD5] = 0x4F         # LNMX: 79 (logical line spans 2 rows)
        emu.memory[0xD8] = 0x02         # INSRT: 2 inserts pending
        emu.memory[0xCE] = 0x41         # GDBLN: stale char-under-cursor
        for r in range(25):
            # Half the rows marked as continuation (00), half as start ($80)
            emu.memory[0xD9 + r] = 0x00 if r & 1 else 0x80

    def test_drains_key_buffer(self, cse_prg):
        emu = make_emu(cse_prg)
        self._poison(emu)
        emu.jsr(emu.sym("kernal_screen_reset"))
        assert emu.memory[0xC6] == 0, "NDX must be drained"

    def test_clears_quote_mode(self, cse_prg):
        emu = make_emu(cse_prg)
        self._poison(emu)
        emu.jsr(emu.sym("kernal_screen_reset"))
        assert emu.memory[0xD4] == 0, "QTSW must be cleared"

    def test_resets_lnmx_to_39(self, cse_prg):
        emu = make_emu(cse_prg)
        self._poison(emu)
        emu.jsr(emu.sym("kernal_screen_reset"))
        assert emu.memory[0xD5] == 39, "LNMX must be 39 (single-row logical line)"

    def test_clears_insert_pending(self, cse_prg):
        emu = make_emu(cse_prg)
        self._poison(emu)
        emu.jsr(emu.sym("kernal_screen_reset"))
        assert emu.memory[0xD8] == 0, "INSRT must be cleared"

    def test_clears_char_under_cursor(self, cse_prg):
        emu = make_emu(cse_prg)
        self._poison(emu)
        emu.jsr(emu.sym("kernal_screen_reset"))
        assert emu.memory[0xCE] == 0, "GDBLN must be cleared"

    def test_reinit_line_link_table(self, cse_prg):
        emu = make_emu(cse_prg)
        self._poison(emu)
        emu.jsr(emu.sym("kernal_screen_reset"))
        # Each row marked as a logical-line start ($80) AND tagged
        # with its screen-address page in low bits (KERNAL stores
        # the page there for $D1/$D2 recomputation on row change).
        # Rows 0-6: page $04, rows 7-12: page $05, rows 13-19: page $06,
        # rows 20-24: page $07.
        for r in range(25):
            expected = 0x80 | ((0x0400 + r * 40) >> 8)
            actual = emu.memory[0xD9 + r]
            assert actual == expected, \
                f"LDTB1[{r}] (=${0xD9+r:02X}) must be ${expected:02X} " \
                f"($80 | scr_hi[{r}]), got ${actual:02X}"

    def test_reset_screen_does_NOT_touch_kernal_zp(self, cse_prg):
        """Regression net: reset_screen must NOT call kernal_screen_reset.
        Cold-init and the `x` command depend on KERNAL line-link state
        being preserved across screen clears so subsequent CHROUT
        positions correctly.  See class docstring."""
        emu = make_emu(cse_prg)
        self._poison(emu)
        emu.jsr(emu.sym("reset_screen"))
        # Poisoned bytes outside PLOT's scope MUST survive.
        # ($D5/$D8/$CE/$D9..$F1/$D4 are not set by PLOT.  $C6 is drained
        # by hygiene_after_userland on userland exit, but NOT by
        # reset_screen — it's not reset_screen's concern.)
        assert emu.memory[0xD4] == 0x01, "reset_screen must not touch QTSW"
        assert emu.memory[0xD5] == 0x4F, "reset_screen must not touch LNMX"
        assert emu.memory[0xD8] == 0x02, "reset_screen must not touch INSRT"
        assert emu.memory[0xCE] == 0x41, "reset_screen must not touch GDBLN"
        assert emu.memory[0xC6] == 0x05, "reset_screen must not touch NDX"
        # Line-link table must survive too (preserves logical-line context
        # for subsequent CHROUT after a cold-init or `x` clear).
        ld_state = bytes(emu.memory[0xD9 + r] for r in range(25))
        expected = bytes(0x00 if r & 1 else 0x80 for r in range(25))
        assert ld_state == expected, "reset_screen must not touch LDTB1"


class TestPlotAgainstCorruptLdtb1:
    """Mechanism witness for the rc1 NMI-during-userland-CHROUT jank.

    KERNAL PLOT (`$FFF0`) walks the line-link table to find the
    logical-line start row, then computes `$D1/$D2/$F3/$F4` and the
    in-line column from THAT start row's screen address — not from
    the requested row directly.  Two ways LDTB1 can be wrong:

    1. **Logical-line corruption**: row R marked as a continuation
       of row R-1, LNMX=79 (left over from a 2-row wrap).  PLOT(R,
       any) lands on row R-1, column reinterpreted within the wrap.

    2. **Page corruption**: LDTB1[r] low 7 bits are wrong (KERNAL
       stores the row's screen-address page there; rc3 v1 of this
       fix wrote a flat $80 instead of $80 | scr_hi[r], leaving
       PLOT to compute every row's $D2 as $04 — the "user CHROUT
       output stuck in upper third of screen" symptom).

    These tests pin both mechanisms so the rc1/rc3 root-causes stay
    documented in the test suite, and confirm `kernal_screen_reset`
    sanitizes LDTB1 before PLOT can read it.
    """

    @staticmethod
    def _canonical_ldtb1_for_row(r):
        """KERNAL CINT's per-row LDTB1 value: $80 | scr_hi[r]."""
        scr_addr = 0x0400 + r * 40
        return 0x80 | (scr_addr >> 8)

    def _plot(self, emu, row, col):
        """KERNAL PLOT (CLC = set position)."""
        emu._cpu.x = row
        emu._cpu.y = col
        emu.carry = False
        emu.jsr(0xFFF0)

    def test_plot_with_clean_ldtb1_computes_correct_screen_ptr(self, cse_prg):
        """Reference: canonical LDTB1 ($80 | scr_hi[r]) → PLOT(10,5)
        lands at row 10's actual screen address $0590, col 5."""
        emu = make_emu(cse_prg)
        for r in range(25):
            emu.memory[0xD9 + r] = self._canonical_ldtb1_for_row(r)
        emu.memory[0xD5] = 39
        self._plot(emu, row=10, col=5)
        # Row 10's screen address: $0400 + 10*40 = $0590.
        assert (emu.memory[0xD1], emu.memory[0xD2]) == (0x90, 0x05), \
            f"PNT should point at row 10's start ($0590), " \
            f"got ${emu.memory[0xD2]:02X}{emu.memory[0xD1]:02X}"
        assert emu.memory[0xD3] == 5, "column should be 5 as requested"

    def test_plot_with_logical_line_corruption(self, cse_prg):
        """Mechanism witness 1: logical-line corruption.  LDTB1[10]=0
        ('row 10 is continuation of row 9') with LNMX=79 →
        PLOT(10, 5) silently lands on row 9 col 45 instead of
        row 10 col 5.  This is the original rc1 cursor-drift jank."""
        emu = make_emu(cse_prg)
        for r in range(25):
            emu.memory[0xD9 + r] = self._canonical_ldtb1_for_row(r)
        emu.memory[0xD9 + 10] = 0x00       # row 10 = continuation
        emu.memory[0xD5] = 79              # 2-row LNMX
        self._plot(emu, row=10, col=5)
        # Row 9's screen address: $0400 + 9*40 = $0568.
        assert (emu.memory[0xD1], emu.memory[0xD2]) == (0x68, 0x05), \
            f"with logical-line corruption, PNT lands on row 9 " \
            f"(start of logical line); got " \
            f"${emu.memory[0xD2]:02X}{emu.memory[0xD1]:02X}"
        assert emu.memory[0xD3] == 45, \
            "column reinterpreted as col-within-2-row-logical-line (5 + 40)"

    def test_plot_with_page_corruption(self, cse_prg):
        """Mechanism witness 2: page corruption.  LDTB1[r]=$80 (low
        bits zero, no page info) → PLOT(10, 5) lands at $0490
        (page $04, wrong row) instead of $0590.  This was the rc3
        v1 bug — userland CHROUT output stuck in upper third."""
        emu = make_emu(cse_prg)
        for r in range(25):
            emu.memory[0xD9 + r] = 0x80     # logical-line start, page $00
        emu.memory[0xD5] = 39
        self._plot(emu, row=10, col=5)
        # WRONG: $D2 reflects KERNAL's "use base $04" fallback when
        # LDTB1's low bits are 0.  Real row 10 should be at $0590.
        assert emu.memory[0xD2] == 0x04, \
            "page-corrupted LDTB1 → PLOT computes wrong page"
        # But $D1 IS row 10's low byte ($90) because PLOT does honour
        # the row argument for the in-page offset.
        assert emu.memory[0xD1] == 0x90, "low byte still row-10's"

    def test_kernal_screen_reset_then_plot_recovers(self, cse_prg):
        """Defence: kernal_screen_reset before PLOT recovers the
        clean reference behaviour from BOTH corruption mechanisms.
        This is the contract hygiene_after_userland relies on — it
        calls kernal_screen_reset before its tail-call to io_sync."""
        emu = make_emu(cse_prg)
        # Poison LDTB1 maximally: alternating start/continuation rows
        # AND zero out the page bits.  Plus LNMX=79.
        for r in range(25):
            emu.memory[0xD9 + r] = 0x80 if (r & 1) else 0x00
        emu.memory[0xD5] = 79
        # Apply the defence:
        emu.jsr(emu.sym("kernal_screen_reset"))
        # PLOT(10, 5) should land at row 10's actual address $0590 col 5.
        self._plot(emu, row=10, col=5)
        assert (emu.memory[0xD1], emu.memory[0xD2]) == (0x90, 0x05), \
            f"after sanitize, PNT must land at row 10's ACTUAL " \
            f"address $0590; got " \
            f"${emu.memory[0xD2]:02X}{emu.memory[0xD1]:02X}"
        assert emu.memory[0xD3] == 5, \
            "after sanitize, column = 5 as requested"

    def test_kernal_screen_reset_writes_per_row_pages(self, cse_prg):
        """The page-encoding contract: LDTB1[r] = $80 | scr_hi[r]
        for each row, matching what KERNAL CINT writes.  Pin every
        row so a regression is immediate."""
        emu = make_emu(cse_prg)
        # Poison every row to a wrong value.
        for r in range(25):
            emu.memory[0xD9 + r] = 0xFF
        emu.jsr(emu.sym("kernal_screen_reset"))
        for r in range(25):
            expected = self._canonical_ldtb1_for_row(r)
            actual = emu.memory[0xD9 + r]
            assert actual == expected, \
                f"LDTB1[{r}] (=${0xD9+r:02X}): expected ${expected:02X}, " \
                f"got ${actual:02X}"


# ── newline ─────────────────────────────────────────────────────────────────

class TestNewline:
    """newline advances cursor to next row col 0, scrolls at bottom."""

    def test_advance_row(self, cse_prg):
        emu = make_emu(cse_prg)
        emu.set_cursor(5, 10)
        emu.jsr(emu.sym("newline"))
        assert emu.memory[0xD6] == 6
        assert emu.memory[0xD3] == 0

    def test_scroll_at_bottom(self, cse_prg):
        emu = make_emu(cse_prg)
        fill_row(emu, 1, 0x01)
        emu.set_cursor(24, 0)
        emu.jsr(emu.sym("newline"))
        assert emu.memory[0xD6] == 24
        assert emu.memory[0xD3] == 0
        assert row_is(emu, 0, 0x01)  # row 1 scrolled to row 0

    def test_no_scroll_mid_screen(self, cse_prg):
        emu = make_emu(cse_prg)
        fill_row(emu, 0, 0x02)
        emu.set_cursor(10, 0)
        emu.jsr(emu.sym("newline"))
        assert row_is(emu, 0, 0x02)  # row 0 untouched


# ── scroll_up ───────────────────────────────────────────────────────────────

class TestScrollUp:
    """scroll_up(n) scrolls screen RAM up by n rows."""

    def test_scroll_1(self, cse_prg):
        emu = make_emu(cse_prg)
        for r in range(ROWS):
            fill_row(emu, r, r + 1)
        emu.set_cursor(0, 0)
        emu.jsr(emu.sym("scroll_up"), a=1)
        assert emu.memory[SCREEN] == 2        # was row 1
        assert emu.memory[SCREEN + 23*COLS] == 25  # was row 24
        assert row_is(emu, 24, 0x20)           # cleared

    def test_scroll_5(self, cse_prg):
        emu = make_emu(cse_prg)
        for r in range(ROWS):
            fill_row(emu, r, r + 1)
        emu.set_cursor(12, 0)
        emu.jsr(emu.sym("scroll_up"), a=5)
        assert emu.memory[SCREEN] == 6  # was row 5
        for r in range(20, 25):
            assert row_is(emu, r, 0x20), f"row {r} should be cleared"

    def test_scroll_full(self, cse_prg):
        emu = make_emu(cse_prg)
        for r in range(ROWS):
            fill_row(emu, r, 0x42)
        emu.jsr(emu.sym("scroll_up"), a=25)
        for r in range(ROWS):
            assert row_is(emu, r, 0x20)

    def test_scroll_clamps_io_cy_to_zero(self, cse_prg):
        """scroll_up must adjust io_cy, clamping at 0 (screen.md § scroll_up
        'io_cy adjusted (clamped to 0)')."""
        emu = make_emu(cse_prg)
        emu.set_cursor(3, 0)     # row 3
        emu.jsr(emu.sym("scroll_up"), a=5)   # scroll more than cursor is from top
        # Per contract: io_cy clamped to 0 (can't go negative).
        assert emu.memory[0xD6] == 0, \
            f"scroll_up didn't clamp io_cy: {emu.memory[0xD6]}"

    def test_scroll_adjusts_io_cy_partial(self, cse_prg):
        """scroll_up(n) with cursor at row r where r >= n → io_cy = r - n."""
        emu = make_emu(cse_prg)
        emu.set_cursor(10, 5)
        emu.jsr(emu.sym("scroll_up"), a=3)
        assert emu.memory[0xD6] == 7, \
            f"io_cy should be 10-3=7, got {emu.memory[0xD6]}"


# ── cursor_show / cursor_hide ──────────────────────────────────────────────

class TestCursorToggle:
    """cursor_show XORs $80 at cursor position; cursor_hide is identical."""

    def test_show_inverts(self, cse_prg):
        emu = make_emu(cse_prg)
        emu.set_cursor(0, 0)
        emu.memory[SCREEN] = 0x01
        emu.jsr(emu.sym("cursor_show"))
        assert emu.memory[SCREEN] == 0x81

    def test_hide_restores(self, cse_prg):
        emu = make_emu(cse_prg)
        emu.set_cursor(0, 0)
        emu.memory[SCREEN] = 0x01
        emu.jsr(emu.sym("cursor_show"))
        emu.jsr(emu.sym("cursor_hide"))
        assert emu.memory[SCREEN] == 0x01

    def test_cursor_at_position(self, cse_prg):
        emu = make_emu(cse_prg)
        emu.set_cursor(5, 10)
        addr = SCREEN + 5 * COLS + 10
        emu.memory[addr] = 0x04
        emu.jsr(emu.sym("cursor_show"))
        assert emu.memory[addr] == 0x84
        assert emu.memory[addr - 1] == 0x20
        assert emu.memory[addr + 1] == 0x20


# ── vic_reset — VIC register writes ────────────────────────────────────────
#
# vic_reset writes six VIC-II registers to force known text-mode state.
# The register WRITES are observable in C64Emu (memory-mapped I/O), but
# the VIC-II chip's interpretation of those bytes (display on/off,
# character ROM source, sprite muting) is NOT emulated — C64Emu treats
# $D011–$D01A as flat RAM.  What we CAN test: the bytes land at the
# correct register addresses with the correct values.  What we CAN'T
# test: that the VIC actually reacts to them (that's a VICE check).

class TestVicReset:
    """vic_reset forces known text-mode VIC state (screen.md § vic_reset)."""

    def test_sets_d011_text_mode(self, cse_prg):
        """$D011=$1B: display on, 25 rows, text mode, no ECM/BMM, Y-scroll=3."""
        emu = make_emu(cse_prg)
        emu.memory[0xD011] = 0x00   # pretend user-code had blanked display
        emu.jsr(emu.sym("vic_reset"))
        assert emu.memory[0xD011] == 0x1B

    def test_sets_d016_text_mode(self, cse_prg):
        """$D016=$C8: 40 cols, no MCM, no X-scroll (bits 6:7 set by C64 default)."""
        emu = make_emu(cse_prg)
        emu.memory[0xD016] = 0x00
        emu.jsr(emu.sym("vic_reset"))
        assert emu.memory[0xD016] == 0xC8

    def test_sets_d018_screen_and_charset(self, cse_prg):
        """$D018=$16: screen at $0400 (bits 7:4 = 1), charset at $1800
        (bits 3:1 = 3) — the lowercase/uppercase font in ROM."""
        emu = make_emu(cse_prg)
        emu.memory[0xD018] = 0x00
        emu.jsr(emu.sym("vic_reset"))
        assert emu.memory[0xD018] == 0x16

    def test_sets_d015_sprites_off(self, cse_prg):
        """$D015=0: all sprites disabled."""
        emu = make_emu(cse_prg)
        emu.memory[0xD015] = 0xFF
        emu.jsr(emu.sym("vic_reset"))
        assert emu.memory[0xD015] == 0x00

    def test_sets_d01a_irq_enable_off(self, cse_prg):
        """$D01A=0: all VIC IRQ sources disabled."""
        emu = make_emu(cse_prg)
        emu.memory[0xD01A] = 0xFF
        emu.jsr(emu.sym("vic_reset"))
        assert emu.memory[0xD01A] == 0x00

    def test_acks_d019_latches(self, cse_prg):
        """$D019=$0F: ack any pending IRQ latches (write-1-to-clear on real
        hardware; flat-RAM write on C64Emu)."""
        emu = make_emu(cse_prg)
        emu.jsr(emu.sym("vic_reset"))
        assert emu.memory[0xD019] == 0x0F


# ═══════════════════════════════════════════════════════════════════
# Contract clauses intentionally not automated (vocal skips)
# ═══════════════════════════════════════════════════════════════════
#
# Skip policy per doc/testing.md § Principle 9.


# ⚠  MID-RISK L2 GAP (per coverage audit 2026-04-20):
#    C64Emu treats VIC-II registers as flat RAM.  The register-write
#    tests above confirm the correct BYTES reach the correct registers,
#    but don't observe the VIC's actual response (display visibility,
#    charset source, sprite rendering).  A refactor that corrupts
#    vic_reset's register values would be caught; a refactor that
#    changes the register set being reset (adding / removing writes)
#    could silently break recovery-after-userland-VIC-twiddle on real
#    hardware.  VICE manual checklist is the only backstop.


class TestVicHardwareBehaviour:

    @pytest.mark.skip(reason=(
        "Real VIC-II display state (screen.md § vic_reset): C64Emu does "
        "not model the VIC-II chip — $D011/$D016/$D018/$D015/$D01A/$D019 "
        "are flat RAM.  Register-write values ARE verified (TestVicReset). "
        "End-to-end 'VIC renders correctly after user code flipped it to "
        "bitmap mode / sprites on / charset swapped' is verified ONLY in "
        "the VICE manual checklist.  See the MID-RISK comment above."
    ))
    def test_vic_renders_text_mode_after_reset(self, cse_prg):
        pass

    @pytest.mark.skip(reason=(
        "VIC IRQ latch acknowledgment (screen.md § vic_reset): the "
        "$D019=$0F write is write-1-to-clear on real hardware (acks "
        "pending latches); on C64Emu it's a flat-RAM byte write.  The "
        "fact that the write happens is verified (test_acks_d019_latches); "
        "that it actually clears a pending IRQ latch requires real VIC "
        "silicon behaviour — VICE only."
    ))
    def test_d019_ack_clears_pending_irq(self, cse_prg):
        pass

    @pytest.mark.skip(reason=(
        "scroll_up VIC tear prevention (screen.md § Design): SEI/CLI "
        "guards around the screen-RAM memmove prevent the VIC from "
        "reading a partially-scrolled frame.  This is COSMETIC — at "
        "most a 1-frame visual tear on real hardware; it has no "
        "functional consequence.  Not observable on C64Emu (no VIC "
        "raster)."
    ))
    def test_scroll_up_prevents_vic_tear(self, cse_prg):
        pass
