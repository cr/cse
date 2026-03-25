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
#include "repl.h"
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

/* ═══════════════════════════════════════════════════════════════
 * Shared hex parsing helpers
 * ═══════════════════════════════════════════════════════════════ */

uint8_t __fastcall__ hex_val(uint8_t ch) {
    if (ch >= '0' && ch <= '9') return ch - '0';
    if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
    if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
    return 0xFF;
}

uint8_t __fastcall__ is_hex(uint8_t ch) { return hex_val(ch) != 0xFF; }

uint8_t __fastcall__ hex_val_to_char(uint8_t v) {
    return v < 10 ? '0' + v : 'a' + v - 10;
}

uint16_t parse_hex4(uint8_t **pp) {
    uint8_t *q = *pp;
    uint16_t v;
    if (!is_hex(q[0]) || !is_hex(q[1]) || !is_hex(q[2]) || !is_hex(q[3]))
        return 0;
    v  = (uint16_t)hex_val(q[0]) << 12;
    v |= (uint16_t)hex_val(q[1]) <<  8;
    v |= (uint16_t)hex_val(q[2]) <<  4;
    v |= (uint16_t)hex_val(q[3]);
    *pp = q + 4;
    return v;
}

uint8_t parse_hex2(uint8_t **pp) {
    uint8_t *q = *pp;
    uint8_t v;
    if (!is_hex(q[0]) || !is_hex(q[1])) return 0;
    v = (hex_val(q[0]) << 4) | hex_val(q[1]);
    *pp = q + 2;
    return v;
}

void skip_sp(uint8_t **pp) {
    while (**pp == ' ') ++(*pp);
}

/* ═══════════════════════════════════════════════════════════════
 * Init: fill free memory with $FF
 *
 * Helps developers catch uninitialized memory reads.
 * Free ZP: $44–$FF.  Free work: cse_end()–$C7FF.
 * ═══════════════════════════════════════════════════════════════ */

static void fill_free_memory(void) {
    uint16_t wlo = cse_end();
    /* Free ZP: $44–$7F (KERNAL owns $80+, CSE owns $02–$43) */
    memset((void *)0x44, 0xFF, 0x80 - 0x44);
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
#define BUILD_YEAR "2025"
#endif

void main(void)
{
    uint8_t ch;

    /* Key repeat: default (cursor, DEL, space only) */
    MEM_CONFIG &= ~0x20;                 /* unmap BASIC ROM */

    state = ST_REPL;
    io_init();                            /* disable KERNAL cursor — required */
    reset_screen();
    *(uint8_t *)0xD018 |= 0x02;          /* lowercase/uppercase charset */

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
        io_puts("cse v" VERSION);
        io_cx = 0; io_cy = row++; io_sync();
        io_puts("(c) 2025-" BUILD_YEAR " cr@23bit.net");
        row++;
        io_cx = 0; io_cy = row++; io_sync();
        io_puts("free:  0039-007f  zp");
        io_cx = 0; io_cy = row++; io_sync();
        io_puts("       ");
        io_puthex4(wlo); io_putc('-'); io_puthex4(whi);
        io_puts("  work");

        io_cx = 0; io_cy = SCREEN_HEIGHT - 1; io_sync();
        show_prompt();
    }

    /* ── Main loop ───────────────────────────────────────── */
    while (state != ST_STOP) {

        /* Check NMI flag (RUN/STOP + RESTORE) */
        if (nmi_pending) {
            nmi_pending = 0;
            if (state == ST_EDIT) leave_editor();
            state = ST_REPL;
            restore_colors();
            *(uint8_t *)0xD018 |= 0x02;  /* ensure lowercase charset */
            newline();
            io_puts("; run/stop+restore");
            clear_eol();
            newline();
            show_prompt();
            continue;
        }

        cursor_show();
        ch = io_getc();
        cursor_hide();

        /* RUN/STOP toggles REPL ↔ editor */
        if (ch == CH_STOP) {
            if (state == ST_REPL)
                enter_editor();
            else if (state == ST_EDIT)
                leave_editor();
            *(uint8_t *)0xC6 = 0;  /* flush keyboard buffer — no repeat */
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
            break;

        case CH_DEL: {
            uint8_t *row = SCREEN + io_cy * SCREEN_WIDTH;
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
            uint8_t *row = SCREEN + io_cy * SCREEN_WIDTH;
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
            reset_screen();
            show_prompt();
            break;

        case CH_ESC:
            reset_screen();
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
     * CSE code survives in RAM — SYS 2061 restarts.
     * ═══════════════════════════════════════════════════════ */
    asm("jmp $FCE2");
}
