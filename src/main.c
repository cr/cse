/* ═══════════════════════════════════════════════════════════════
 * CSE — C64 Screen Editor / Assembler / Monitor
 *
 * main.c — hardware init, shared utilities, main loop.
 * REPL commands are in repl.c, editor in editor.c.
 * ═══════════════════════════════════════════════════════════════ */

#include <c64.h>
#include <cbm.h>
#include <string.h>
#include <stdint.h>
#include "cse.h"
#include "cse_io.h"
#include "repl.h"
#include "editor.h"

#define MEM_CONFIG (*(uint8_t *)0x01)

/* CH_ENTER, CH_DEL, etc. come from <c64.h>.
 * CH_ESC is not in cc65's headers. */
#ifndef CH_ESC
#define CH_ESC  0x1B
#endif

/* ── Globals (defined here, declared extern in cse.h) ──── */
uint8_t state = 0;
uint8_t *const SCREEN = (uint8_t *)0x0400;
uint8_t *src_top = 0;
uint8_t *src_bot = 0;

/* ═══════════════════════════════════════════════════════════════
 * Hardware helpers
 * ═══════════════════════════════════════════════════════════════ */

/* ── Steady cursor ──────────────────────────────────────── *
 * KERNAL cursor blink disabled ($CC=1).  We reverse the char
 * at the cursor position before io_getc and un-reverse after.
 * No custom IRQ handler — zero race conditions. */
static void cursor_show(void) {
    SCREEN[io_cy * SCREEN_WIDTH + io_cx] |= 0x80;
}
static void cursor_hide(void) {
    SCREEN[io_cy * SCREEN_WIDTH + io_cx] &= 0x7F;
}

/* ═══════════════════════════════════════════════════════════════
 * Shared screen utilities
 * ═══════════════════════════════════════════════════════════════ */

void reset_screen(void) {
    io_bgcolor(11);
    io_bordercolor(12);
    io_color = 5;
    memset(SCREEN, 0x20, 1000);
    memset(COLOR_RAM, io_color, 1000);
    io_cx = 0; io_cy = 0; io_sync();
}

void scroll_up(uint8_t n) {
    if (n >= SCREEN_HEIGHT) {
        memset(SCREEN, 0x20, 1000);
        memset(COLOR_RAM, io_color, 1000);
        io_cx = 0; io_cy = 0; io_sync();
    } else {
        /* Disable IRQs: the custom IRQ handler writes to the screen
         * via ($D1),Y and would corrupt data mid-memmove. */
        __asm__("sei");
        memmove(SCREEN, SCREEN + n * SCREEN_WIDTH,
                SCREEN_WIDTH * (SCREEN_HEIGHT - n));
        memmove(COLOR_RAM, COLOR_RAM + n * SCREEN_WIDTH,
                SCREEN_WIDTH * (SCREEN_HEIGHT - n));
        memset(SCREEN + SCREEN_WIDTH * (SCREEN_HEIGHT - n),
               0x20, SCREEN_WIDTH * n);
        memset(COLOR_RAM + SCREEN_WIDTH * (SCREEN_HEIGHT - n),
               io_color, SCREEN_WIDTH * n);
        __asm__("cli");
        io_cy = (io_cy > n) ? io_cy - n : 0;
    }
}

void newline(void) {
    if (io_cy == SCREEN_HEIGHT - 1) {
        scroll_up(1);              /* decrements io_cy to 23 */
        io_cy = SCREEN_HEIGHT - 1; /* put it back to 24 (new empty row) */
    } else {
        ++io_cy;
    }
    io_cx = 0;
    io_sync();
}

void print_string(const uint8_t *str) {
    uint8_t l = strlen(str);
    uint8_t need = (l + io_cx + 1) / SCREEN_WIDTH;
    uint8_t have = SCREEN_HEIGHT - io_cy - 1;
    if (need > 0 && have < need)
        scroll_up(need - have);
    io_puts((const char *)str);
}

/* ═══════════════════════════════════════════════════════════════
 * Floppy / directory listing
 * ═══════════════════════════════════════════════════════════════ */

static uint8_t fl_len;
static uint8_t fl_buf[32];

void floppy_status(void) {
    if (cbm_open(14, 8, 15, "") == 0) {
        fl_len = cbm_read(14, fl_buf, sizeof(fl_buf) - 1);
        cbm_close(14);
        if (fl_len > 0) {
            fl_buf[fl_len - 1] = 0;
            print_string(fl_buf);
            newline();
        } else {
            print_string("floppy error");
            newline();
        }
    }
}

void list_directory(uint8_t device) {
    struct cbm_dirent de;

    if (cbm_opendir(15, device)) { floppy_status(); return; }

    while (1) {
        if (io_kbhit()) {
            if (io_getc() == CH_STOP) {
                io_puts("break");
                newline();
                cbm_closedir(15);
                return;
            }
        }
        switch (cbm_readdir(15, &de)) {
        case 0:
            io_putdec(de.size); io_putc(' ');
            if (de.type == CBM_T_HEADER) {
                uint8_t start_col = io_cx;
                io_putc('"'); io_puts(de.name); io_putc('"');
                io_cx = 24;
                io_puthex2(de.access);
                /* invert the header line */
                { uint8_t *scr = SCREEN + io_cy * SCREEN_WIDTH;
                  uint8_t i;
                  for (i = start_col; i < io_cx; i++) scr[i] |= 0x80;
                }
                newline();
            } else {
                io_cx = 5;
                io_putc('"'); io_puts(de.name); io_putc('"');
                io_cx = 24;
                switch (de.type) {
                case CBM_T_DEL: io_puts("del"); break;
                case CBM_T_SEQ: io_puts("seq"); break;
                case CBM_T_PRG: io_puts("prg"); break;
                case CBM_T_USR: io_puts("usr"); break;
                case CBM_T_REL: io_puts("rel"); break;
                case CBM_T_DIR: io_puts("dir"); break;
                default:        io_putdec(de.type);
                }
                if (!de.access) io_putc('*');
                newline();
            }
            break;
        case 2:
            cbm_closedir(15);
            io_putdec(de.size); io_puts(" blocks free.");
            newline();
            floppy_status();
            return;
        default:
            cbm_closedir(15);
            floppy_status();
            return;
        }
    }
}

/* ═══════════════════════════════════════════════════════════════
 * Shared hex parsing helpers
 * ═══════════════════════════════════════════════════════════════ */

uint8_t hex_val(uint8_t ch) {
    if (ch >= '0' && ch <= '9') return ch - '0';
    if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
    if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
    return 0xFF;
}

uint8_t is_hex(uint8_t ch) { return hex_val(ch) != 0xFF; }

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
 * Opcode length table — all 256 opcodes (including undocumented)
 * ═══════════════════════════════════════════════════════════════ */

const uint8_t t_opcode_len[256] = {
    /* $00 */ 1,2,1,2,2,2,2,2, 1,2,1,2,3,3,3,3,
    /* $10 */ 2,2,1,2,2,2,2,2, 1,3,1,3,3,3,3,3,
    /* $20 */ 3,2,1,2,2,2,2,2, 1,2,1,2,3,3,3,3,
    /* $30 */ 2,2,1,2,2,2,2,2, 1,3,1,3,3,3,3,3,
    /* $40 */ 1,2,1,2,2,2,2,2, 1,2,1,2,3,3,3,3,
    /* $50 */ 2,2,1,2,2,2,2,2, 1,3,1,3,3,3,3,3,
    /* $60 */ 1,2,1,2,2,2,2,2, 1,2,1,2,3,3,3,3,
    /* $70 */ 2,2,1,2,2,2,2,2, 1,3,1,3,3,3,3,3,
    /* $80 */ 2,2,2,2,2,2,2,2, 1,2,1,2,3,3,3,3,
    /* $90 */ 2,2,1,2,2,2,2,2, 1,3,1,3,3,3,3,3,
    /* $A0 */ 2,2,2,2,2,2,2,2, 1,2,1,2,3,3,3,3,
    /* $B0 */ 2,2,1,2,2,2,2,2, 1,3,1,3,3,3,3,3,
    /* $C0 */ 2,2,2,2,2,2,2,2, 1,2,1,2,3,3,3,3,
    /* $D0 */ 2,2,1,2,2,2,2,2, 1,3,1,3,3,3,3,3,
    /* $E0 */ 2,2,2,2,2,2,2,2, 1,2,1,2,3,3,3,3,
    /* $F0 */ 2,2,1,2,2,2,2,2, 1,3,1,3,3,3,3,3
};

uint8_t __fastcall__ c64_op_len(uint8_t opcode) {
    return t_opcode_len[opcode];
}

uint8_t __fastcall__ c64_insn_len(const void *addr) {
    return t_opcode_len[*(const uint8_t *)addr];
}

/* ═══════════════════════════════════════════════════════════════
 * Main program loop
 * ═══════════════════════════════════════════════════════════════ */

void main(void)
{
    uint8_t ch;

    *(uint8_t *)0x028a |= 0b11000000;    /* all keys repeat */
    MEM_CONFIG &= ~0x20;                 /* unmap BASIC ROM */

    state = ST_REPL;
    reset_screen();
    *(uint8_t *)0xD018 |= 0x02;          /* lowercase/uppercase charset */
    io_cursor_off();                      /* disable KERNAL cursor blink */

    /* greeter */
    io_cx = 0; io_cy = SCREEN_HEIGHT - 4; io_sync();
    io_puts("cse v0.1");
    io_cx = 0; io_cy = SCREEN_HEIGHT - 3; io_sync();
    io_puts("(c) 2025 cr");
    io_cx = 0; io_cy = SCREEN_HEIGHT - 1; io_sync();
    show_prompt();

    /* ── main loop ──────────────────────────────────────── */
    while (state != ST_STOP) {

        cursor_show();
        ch = io_getc();
        cursor_hide();

        /* RUN/STOP toggles mode regardless */
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
            break;

        case CH_DEL: {
            uint8_t mincol = 0;
            if (SCREEN[io_cy * SCREEN_WIDTH + 4] == 0x3A)
                mincol = 5;
            if (io_cx > mincol) {
                --io_cx;
                io_putc(' ');
                --io_cx;
            }
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

    /* ── exit cleanup ───────────────────────────────────── */
    *(unsigned long *)0x0800 = 0;
    MEM_CONFIG |= 0x20;
    io_cursor_on();                       /* re-enable KERNAL cursor for BASIC */
    *(uint8_t *)0x028a &= 0b00111111;
    asm("jsr $A659");
}
