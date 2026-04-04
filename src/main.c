/* ═══════════════════════════════════════════════════════════════
 * CSE — C64 Screen Editor / Assembler / Monitor
 *
 * main.c — hardware init, NMI intercept, mode switch, main loop.
 * ═══════════════════════════════════════════════════════════════ */

#include <c64.h>
#include <string.h>
#include <stdint.h>
#include "cse.h"
#include "cse_io.h"
#include "screen.h"
#include "disk.h"
/* repl.s exports (was repl.h) */
extern void exec_line(void);
extern void read_line(void);
extern void show_prompt(void);
extern uint16_t cur_addr;
extern uint8_t  cur_device;
extern char cur_filename[];
#include "editor.h"

#define MEM_CONFIG    (*(uint8_t *)0x01)
#define NMI_VEC       (*(uint16_t *)0x0318) /* KERNAL NMI indirect vector */
#define BASIC_WARM    0xA659                /* BASIC warm start ($A659) */

/* ── Globals (defined here, declared extern in cse.h) ──── */
uint8_t state = 0;
uint8_t *const SCREEN = (uint8_t *)0x0400;
uint8_t *src_top = 0;
uint8_t *src_bot = 0;

/* NMI flag — set by nmi_handler (cse_io.s), checked in main loop */
volatile uint8_t nmi_pending = 0;

/* Hex parsing helpers removed — now in repl.s (asm).
 * parse_hex4, parse_hex2, skip_sp were only used by the old repl.c. */

/* ═══════════════════════════════════════════════════════════════
 * Init: fill free memory with $FF
 *
 * Helps developers catch uninitialized memory reads.
 * Free ZP: cse_zp_end()–$7F.  Free work: cse_end()–$C7FF.
 * ═══════════════════════════════════════════════════════════════ */

static void fill_free_memory(void) {
    uint16_t wlo = cse_end();
    uint8_t zplo = cse_zp_end();
    /* Free ZP: zplo–$7F (KERNAL owns $80+, CSE owns $02–zplo) */
    memset((void *)(uint16_t)zplo, 0xFF, 0x80 - zplo);
    /* Free work area */
    if (wlo < 0xC800)
        memset((void *)wlo, 0xFF, 0xC800 - wlo);
}

/* ═══════════════════════════════════════════════════════════════
 * Main program
 * ═══════════════════════════════════════════════════════════════ */

#ifndef VERSION
#define VERSION "0.1"
#endif
#ifndef BUILD_YEAR
#define BUILD_YEAR "2026"
#endif

void main(void)
{
    uint8_t ch;

    *(uint8_t *)0x028a |= 0x80;          /* all keys repeat */
    MEM_CONFIG &= ~0x20;                 /* unmap BASIC ROM */

    state = ST_REPL;
    io_init();                            /* disable KERNAL cursor — required */
    reset_screen();
    *(uint8_t *)0xD018 |= 0x02;          /* lowercase/uppercase charset */

    /* Install NMI trampoline in RAM under KERNAL ($FF00).
     * Must be called before any KERNAL bank-out operation. */
    {   extern void kernal_init(void);
        kernal_init();
    }

    /* Initialize symbol table heap (right after BSS) */
    sym_set_heap(cse_end());
    sym_clear();

    /* Initialize debugger state (breakpoint table, flags) */
    dbg_init();

    /* Fill free memory with $FF (catch uninitialized reads) */
    fill_free_memory();

    /* Install NMI handler (RUN/STOP + RESTORE → REPL).
     * Handler is pure asm in cse_io.s — no C prologue. */
    {   extern void nmi_handler(void);
        NMI_VEC = (uint16_t)nmi_handler;
    }

    /* ── Splash screen ───────────────────────────────────── */
    {   uint16_t wlo = cse_end();
        uint16_t whi = 0xC7FF;
        uint8_t  row = SCREEN_HEIGHT - 8;

        cur_addr = (wlo + 0xFF) & 0xFF00;

        io_cx = 0; io_cy = row++; io_sync();
        io_puts("cse v" VERSION " by cr");
        row++;
        io_cx = 0; io_cy = row++; io_sync();
        io_puts("manual:  github.com/cr/cse");
        io_cx = 0; io_cy = row++; io_sync();
        io_puts("  free:  00");
        io_puthex2(cse_zp_end());
        io_puts("-007f  zp");
        io_cx = 0; io_cy = row++; io_sync();
        io_puts("         ");
        io_puthex4(wlo); io_putc('-'); io_puthex4(whi);
        io_puts("  work");

        io_cx = 0; io_cy = SCREEN_HEIGHT - 1; io_sync();
        clear_eol();
        show_prompt();
    }

    /* ── Main loop ───────────────────────────────────────── */
    while (state != ST_STOP) {

        cursor_show();
        ch = io_getc();
        cursor_hide();

        /* NMI (RUN/STOP + RESTORE) takes priority over everything.
         * Check AFTER io_getc returns — the NMI fired during the
         * blocking read, and $03 may be in ch.  Skip it. */
        if (nmi_pending) {
            nmi_pending = 0;
            if (state == ST_EDIT) leave_editor();
            state = ST_REPL;
            restore_colors();
            *(uint8_t *)0xD018 |= 0x02;
            newline();
            io_puts("; run/stop+restore");
            clear_eol();
            newline();
            clear_eol();
            show_prompt();
            continue;
        }

        /* RUN/STOP toggles REPL ↔ editor */
        if (ch == CH_STOP) {
            if (state == ST_REPL)
                enter_editor();
            else if (state == ST_EDIT)
                leave_editor();
            continue;
        }

        /* ── Editor mode ──────────────────────────────── */
        if (state == ST_EDIT) {
            ed_handle_key(ch);
            continue;
        }

        /* ── REPL mode ────────────────────────────────── */
        switch (ch) {

        case CH_ENTER:
            read_line();
            io_cx = 0;
            exec_line();
            show_prompt();
            break;

        case CH_DEL: {
            uint8_t *row = SCREEN + ROW_OFFSET(io_cy);
            uint8_t mincol = 0;
            uint8_t i;
            if (row[4] == 0x3A) mincol = 5;
            if (io_cx > mincol) {
                --io_cx;
                for (i = io_cx; i < SCREEN_WIDTH - 1; ++i)
                    row[i] = row[i + 1];
                row[SCREEN_WIDTH - 1] = 0x20;
            }
            break;
        }

        case CH_INS: {
            uint8_t *row = SCREEN + ROW_OFFSET(io_cy);
            uint8_t i;
            for (i = SCREEN_WIDTH - 2; i > io_cx; --i)
                row[i] = row[i - 1];
            if (io_cx < SCREEN_WIDTH - 1)
                row[io_cx] = 0x20;
            row[SCREEN_WIDTH - 1] = 0x20;
            break;
        }

        case CH_CURS_UP:
            if (io_cy > 0) { --io_cy; io_sync(); }
            break;

        case CH_CURS_DOWN:
            if (io_cy < SCREEN_HEIGHT - 1) { ++io_cy; io_sync(); }
            break;

        case CH_CURS_LEFT:
            if (io_cx > 0) --io_cx;
            break;

        case CH_CURS_RIGHT:
            if (io_cx < SCREEN_WIDTH - 1) ++io_cx;
            break;

        case CH_HOME:
            io_cx = 0;
            break;

        case 147:                             /* shift+HOME = CLR ($93) */
        case CH_ESC:
            reset_screen();
            clear_eol();
            show_prompt();
            break;

        default:
            if (io_cx < SCREEN_WIDTH - 1)
                io_putc(ch);
            break;
        }
    }

    /* ═══════════════════════════════════════════════════════
     * Exit: KERNAL cold start ($FCE2)
     *
     * Full system reset — reinitializes all hardware, BASIC,
     * KERNAL, and ZP.  No manual cleanup needed.
     * ═══════════════════════════════════════════════════════ */
    asm("jmp $FCE2");
}
