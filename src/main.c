/* ═══════════════════════════════════════════════════════════════
 * CSE — C64 Screen Editor / Assembler / Monitor
 *
 * main.c — hardware init, shared utilities, main loop.
 * REPL commands are in repl.c, editor in editor.c.
 * ═══════════════════════════════════════════════════════════════ */

#include <c64.h>
#include <cbm.h>
#include <conio.h>
#include <string.h>
#include <stdint.h>
#include <stdlib.h>
#include "cse.h"
#include "repl.h"
#include "editor.h"

#define MEM_CONFIG    (*(uint8_t *)0x01)
#define CURSOR_ROW    (*(uint8_t *)0xD6)
#define CURSOR_COL    (*(uint8_t *)0xD3)

/* ── Globals (defined here, declared extern in cse.h) ──── */
uint8_t state = 0;
uint8_t *const SCREEN = (uint8_t *)0x0400;
uint8_t *src_top = 0;
uint8_t *src_bot = 0;

/* ═══════════════════════════════════════════════════════════════
 * Hardware helpers
 * ═══════════════════════════════════════════════════════════════ */

void custom_user_irq(void) {
    __asm__("sei");
    if (*((uint8_t *)0xCC) == 0) {
        *((uint8_t *)0xCF) = 1;
        *((uint8_t *)0x0287) = *((uint8_t *)(*(unsigned int *)0xF3
                                + *(uint8_t *)0xD3));
        *((uint8_t *)(*(unsigned int *)0xD1
                      + *(uint8_t *)0xD3)) |= 0x80;
        *((uint8_t *)0xCD) = 20;
    }
    __asm__("jmp $EA31");
}

void register_user_irq(void) {
    *(void (**)(void))0x0314 = custom_user_irq;
}

void unregister_user_irq(void) {
    *(void (**)(void))0x0314 = (void *)0xEA31;
}

void click_sound(void) {
    volatile uint8_t i;
    SID.v1.freq = 0x8000;
    SID.v1.ctrl = 0x11;
    SID.amp     = 10;
    for (i = 0; i < 200; i++);
    SID.v1.ctrl = 0x00;
}

/* ═══════════════════════════════════════════════════════════════
 * Shared screen utilities
 * ═══════════════════════════════════════════════════════════════ */

void reset_screen(void) {
    bgcolor(11);
    bordercolor(12);
    textcolor(5);
    clrscr();
    memset(COLOR_RAM, 5, 1000);
    gotoxy(0, 0);
}

void scroll_up(uint8_t n) {
    if (n >= SCREEN_HEIGHT) {
        clrscr();
        gotoxy(0, 0);
    } else {
        memmove(SCREEN, SCREEN + n * SCREEN_WIDTH,
                SCREEN_WIDTH * (SCREEN_HEIGHT - n));
        memmove(COLOR_RAM, COLOR_RAM + n * SCREEN_WIDTH,
                SCREEN_WIDTH * (SCREEN_HEIGHT - n));
        memset(SCREEN + SCREEN_WIDTH * (SCREEN_HEIGHT - n),
               ' ', SCREEN_WIDTH * n);
        memset(COLOR_RAM + SCREEN_WIDTH * (SCREEN_HEIGHT - n),
               5, SCREEN_WIDTH * n);
        gotoy(CURSOR_ROW > n ? CURSOR_ROW - n : 0);
    }
}

void newline(void) {
    if (CURSOR_ROW == SCREEN_HEIGHT - 1)
        scroll_up(1);
    gotoxy(0, CURSOR_ROW + 1);
}

void print_string(const uint8_t *str) {
    uint8_t l = strlen(str);
    uint8_t need = (l + CURSOR_COL + 1) / SCREEN_WIDTH;
    uint8_t have = SCREEN_HEIGHT - CURSOR_ROW - 1;
    if (need > 0 && have < need)
        scroll_up(need - have);
    cputs(str);
}

void clear_eol(void) {
    uint8_t col = CURSOR_COL;
    uint8_t *row = SCREEN + CURSOR_ROW * SCREEN_WIDTH;
    while (col < SCREEN_WIDTH) row[col++] = ' ';
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
    register struct cbm_dirent de;

    if (cbm_opendir(15, device)) { floppy_status(); return; }

    while (1) {
        if (kbhit()) {
            if (cgetc() == CH_STOP) {
                cputs("break");
                newline();
                cbm_closedir(15);
                return;
            }
        }
        switch (cbm_readdir(15, &de)) {
        case 0:
            cprintf("%d ", de.size);
            if (de.type == CBM_T_HEADER) {
                revers(1);
                cprintf("\"%-16s\"    %02x", de.name, de.access);
                revers(0);
                newline();
            } else {
                gotox(5);
                cputc('"'); cputs(de.name); cputc('"');
                gotox(24);
                switch (de.type) {
                case CBM_T_DEL: cputs("del"); break;
                case CBM_T_SEQ: cputs("seq"); break;
                case CBM_T_PRG: cputs("prg"); break;
                case CBM_T_USR: cputs("usr"); break;
                case CBM_T_REL: cputs("rel"); break;
                case CBM_T_DIR: cputs("dir"); break;
                default:        cprintf("%03d", de.type);
                }
                if (!de.access) cputc('*');
                newline();
            }
            break;
        case 2:
            cbm_closedir(15);
            cprintf("%d blocks free.", de.size);
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

    register_user_irq();
    *(uint8_t *)0x028a |= 0b11000000;    /* all keys repeat */
    MEM_CONFIG &= ~0x20;                 /* unmap BASIC ROM */

    state = ST_REPL;
    reset_screen();
    *(uint8_t *)0xD018 |= 0x02;          /* lowercase/uppercase charset */
    cursor(1);

    /* greeter */
    cputsxy(0, SCREEN_HEIGHT - 4, "cse v0.1");
    cputsxy(0, SCREEN_HEIGHT - 3, "(c) 2025 cr");
    gotoxy(0, SCREEN_HEIGHT - 1);
    show_prompt();

    /* ── main loop ──────────────────────────────────────── */
    while (state != ST_STOP) {

        ch = cgetc();

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
            gotox(0);
            exec_line();
            break;

        case CH_DEL: {
            uint8_t mincol = 0;
            if (SCREEN[CURSOR_ROW * SCREEN_WIDTH + 4] == 0x3A)
                mincol = 5;
            if (CURSOR_COL > mincol) {
                gotox(CURSOR_COL - 1);
                cputc(' ');
                gotox(CURSOR_COL - 1);
            }
            break;
        }

        case CH_CURS_UP:
            if (CURSOR_ROW > 0) gotoy(CURSOR_ROW - 1);
            break;

        case CH_CURS_DOWN:
            if (CURSOR_ROW < SCREEN_HEIGHT - 1) gotoy(CURSOR_ROW + 1);
            break;

        case CH_CURS_LEFT:
            if (CURSOR_COL > 0) gotox(CURSOR_COL - 1);
            break;

        case CH_CURS_RIGHT:
            if (CURSOR_COL < SCREEN_WIDTH - 1) gotox(CURSOR_COL + 1);
            break;

        case CH_HOME:
            gotox(0);
            break;

        case CH_ESC:
            reset_screen();
            show_prompt();
            break;

        default:
            if (CURSOR_COL < SCREEN_WIDTH - 1)
                cputc(ch);
            break;
        }
    }

    /* ── exit cleanup ───────────────────────────────────── */
    *(unsigned long *)0x0800 = 0;
    MEM_CONFIG |= 0x20;
    unregister_user_irq();
    *(uint8_t *)0x028a &= 0b00111111;
    asm("jsr $A659");
}
