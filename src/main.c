/* ═══════════════════════════════════════════════════════════════
 * CSE — C64 Screen Editor / Assembler / Monitor
 *
 * CLI: the screen IS the command buffer.  Every line is executable.
 *
 *   AAAA:cmd [args]    — addressed commands (. d m j)
 *   cmd [args]          — bare commands (r q $ bs clr)
 *
 * Line formats (40 columns):
 *   AAAA:. BB BB BB DISASSEMBLY           (asm / disasm)
 *   AAAA:m BB BB BB BB BB BB BB BB cccccccc (hex dump / edit)
 *   r A:XX X:XX Y:XX S:XX NV-BDIZC        (CPU registers)
 *
 * Press RETURN on any line to execute it.  ';' ends parsing.
 * ═══════════════════════════════════════════════════════════════ */

#include <c64.h>
#include <cbm.h>
#include <conio.h>
#include <string.h>
#include <stdint.h>
#include <stdlib.h>

/* ── Screen geometry ────────────────────────────────────── */
#define SCREEN_WIDTH  40
#define SCREEN_HEIGHT 25
#define MEM_CONFIG    (*(uint8_t *)0x01)
#define CURSOR_ROW    (*(uint8_t *)0xD6)
#define CURSOR_COL    (*(uint8_t *)0xD3)

/* ── Run state ──────────────────────────────────────────── */
static uint8_t state = 0;
#define ST_STOP 0
#define ST_RUN  1

/* ── Globals ────────────────────────────────────────────── */
uint8_t *const SCREEN = (uint8_t *)0x0400;
static uint16_t cur_addr = 0x1000;

/* Last command for repeat-on-empty-RETURN */
static uint8_t last_cmd = 0;          /* command letter, or 0 = none */
static uint8_t last_args[16];         /* saved args (e.g. "08" for m/d) */

/* Block size for block commands (m, d, f, c, t).  Default 16 bytes. */
static uint16_t block_size = 0x10;

/* ── Forward declarations ───────────────────────────────── */
static void exec_line(void);
static const uint8_t t_opcode_len[256];

/* ═══════════════════════════════════════════════════════════════
 * Hardware helpers
 * ═══════════════════════════════════════════════════════════════ */

/* Custom user IRQ handler — steady cursor (no blink) */
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
 * Screen utilities
 * ═══════════════════════════════════════════════════════════════ */

static void reset_screen(void) {
    bgcolor(11);             /* dark gray */
    bordercolor(12);         /* mid gray */
    textcolor(5);            /* green */
    clrscr();
    memset(COLOR_RAM, 5, 1000);
    gotoxy(0, 0);
}

static void scroll_up(uint8_t n) {
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

static void newline(void) {
    if (CURSOR_ROW == SCREEN_HEIGHT - 1)
        scroll_up(1);
    gotoxy(0, CURSOR_ROW + 1);
}

/* Print string with scroll-awareness */
static void print_string(const uint8_t *str) {
    uint8_t l = strlen(str);
    uint8_t need = (l + CURSOR_COL + 1) / SCREEN_WIDTH;
    uint8_t have = SCREEN_HEIGHT - CURSOR_ROW - 1;
    if (need > 0 && have < need)
        scroll_up(need - have);
    cputs(str);
}

/* Clear from cursor to end of current row (direct screen write). */
static void clear_eol(void) {
    uint8_t col = CURSOR_COL;
    uint8_t *row = SCREEN + CURSOR_ROW * SCREEN_WIDTH;
    while (col < SCREEN_WIDTH) row[col++] = ' ';
}

/* ═══════════════════════════════════════════════════════════════
 * Floppy / directory listing
 * ═══════════════════════════════════════════════════════════════ */

static uint8_t fl_len;
static uint8_t fl_buf[32];

static void floppy_status(void) {
    if (cbm_open(14, 8, 15, NULL) == 0) {
        cbm_write(14, "i", 1);
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

static void list_directory(uint8_t device) {
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
 * Assembler bridge (asm_bridge.s)
 * ═══════════════════════════════════════════════════════════════ */

/* uint8_t asm_line(uint16_t addr, char *text);
 * Assembles one instruction from PETSCII text, writes to addr.
 * Returns byte count (1–3), or 0 on error.  __fastcall__ default. */
extern uint8_t asm_line(uint16_t addr, char *text);

/* void jsr_addr(uint16_t addr);
 * JSR to addr, capture registers on return. */
extern void jsr_addr(uint16_t addr);

/* Captured CPU registers (written by jsr_addr). */
extern uint8_t reg_a, reg_x, reg_y, reg_sp, reg_p;

/* ═══════════════════════════════════════════════════════════════
 * Hex parsing helpers (work on PETSCII strings)
 * ═══════════════════════════════════════════════════════════════ */

static uint8_t hex_val(uint8_t ch) {
    if (ch >= '0' && ch <= '9') return ch - '0';
    if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
    if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
    return 0xFF;
}

static uint8_t is_hex(uint8_t ch) { return hex_val(ch) != 0xFF; }

/* Parse exactly 4 hex digits.  Advances *pp.  Returns 0 on bad input. */
static uint16_t parse_hex4(uint8_t **pp) {
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

/* Parse exactly 2 hex digits.  Advances *pp.  Returns 0 on bad input. */
static uint8_t parse_hex2(uint8_t **pp) {
    uint8_t *q = *pp;
    uint8_t v;
    if (!is_hex(q[0]) || !is_hex(q[1])) return 0;
    v = (hex_val(q[0]) << 4) | hex_val(q[1]);
    *pp = q + 2;
    return v;
}

static void skip_sp(uint8_t **pp) {
    while (**pp == ' ') ++(*pp);
}

/* ═══════════════════════════════════════════════════════════════
 * Screen line I/O — the screen IS the command buffer
 * ═══════════════════════════════════════════════════════════════ */

static uint8_t line_buf[42];   /* 40 chars + NUL + safety */

/* Read current screen row into line_buf as PETSCII.
 * Strips reverse-video bit, converts screen codes → PETSCII,
 * trims trailing spaces, cuts at ';', NUL-terminates. */
static void read_line(void) {
    uint8_t *src = SCREEN + CURSOR_ROW * SCREEN_WIDTH;
    uint8_t  i, sc;

    for (i = 0; i < SCREEN_WIDTH; ++i) {
        sc = src[i] & 0x7F;                        /* strip reverse */
        line_buf[i] = (sc < 0x20) ? (sc + 0x40) : sc;
    }
    /* trim trailing spaces */
    i = SCREEN_WIDTH;
    while (i > 0 && line_buf[i - 1] == ' ') --i;
    line_buf[i] = 0;
    /* cut at ';' */
    for (i = 0; line_buf[i]; ++i) {
        if (line_buf[i] == ';') { line_buf[i] = 0; break; }
    }
}

/* Show "AAAA:" prompt using cur_addr.  Clears rest of line.
 * Cursor ends at col 5, ready for command input. */
static void show_prompt(void) {
    gotox(0);
    cprintf("%04x:", cur_addr);
    clear_eol();
}

/* ═══════════════════════════════════════════════════════════════
 * Stub disassembler
 * TODO: replace with real 6502 disassembler
 * ═══════════════════════════════════════════════════════════════ */

static const char *disasm(uint16_t addr) {
    (void)addr;
    return "---";
}

/* ═══════════════════════════════════════════════════════════════
 * Line emitters — write a fixed-format line at the current row
 *
 * Each emitter does gotox(0), writes the full line content, and
 * calls clear_eol().  Cursor column after return is unspecified.
 * ═══════════════════════════════════════════════════════════════ */

/* AAAA:. BB BB BB DISASM                   (7 + 9 + 24 = 40) */
static void emit_dot(uint16_t addr) {
    uint8_t olen, i;
    gotox(0);
    olen = t_opcode_len[*(uint8_t *)addr];
    cprintf("%04x:.", addr);
    for (i = 0; i < 3; ++i) {
        if (i < olen)
            cprintf(" %02x", ((uint8_t *)addr)[i]);
        else
            cputs("   ");
    }
    cputc(' ');
    cputs(disasm(addr));
    clear_eol();
}

/* AAAA:m BB BB BB BB BB BB BB BB cccccccc  (7 + 23 + 1 + 8 = 39) */
/* cols = number of bytes to show (1–8). */
static void emit_mem(uint16_t addr, uint8_t cols) {
    uint8_t *base = (uint8_t *)addr;
    uint8_t  i, b;
    if (cols == 0) cols = 8;
    if (cols > 8)  cols = 8;
    gotox(0);
    cprintf("%04x:m", addr);
    for (i = 0; i < 8; ++i) {
        if (i < cols)
            cprintf(" %02x", base[i]);
        else
            cputs("   ");
    }
    cputc(' ');
    for (i = 0; i < cols; ++i) {
        b = base[i];
        cputc((b >= 0x20 && b <= 0x7E) ? b : '.');
    }
    clear_eol();
}

/* r A:XX X:XX Y:XX S:XX NV-BDIZC          (30 chars) */
static void emit_reg(void) {
    static const char flag_ch[] = "nv-bdizc";
    uint8_t i, p;
    gotox(0);
    cprintf("r a:%02x x:%02x y:%02x s:%02x ",
            reg_a, reg_x, reg_y, reg_sp);
    p = reg_p;
    for (i = 0; i < 8; ++i) {
        cputc((p & 0x80) ? flag_ch[i] : '.');
        p <<= 1;
    }
    clear_eol();
}

/* ═══════════════════════════════════════════════════════════════
 * Command handlers
 * ═══════════════════════════════════════════════════════════════ */

/* ── AAAA:. [BB BB BB] [MNEMONIC OPERAND] ──────────────────
 *
 * Smart detection:
 *   1. Parse hex bytes (up to 3).
 *   2. If hex differs from memory → patch bytes (user edited hex).
 *   3. If hex matches → look at mnemonic text after the bytes:
 *      - starts with a letter → try assembling it.
 *      - otherwise (empty, "---", etc.) → just refresh.
 *   4. Overwrite current line + auto-advance.
 * ──────────────────────────────────────────────────────────── */
static void cmd_dot(uint16_t addr, uint8_t *args)
{
    uint8_t  bytes[3], nbytes, olen, i, changed;
    uint8_t *q = args, *mne;

    /* ── parse hex bytes ──────────────────────────────────── */
    nbytes = 0;
    while (nbytes < 3 && is_hex(*q) && is_hex(*(q + 1))) {
        bytes[nbytes++] = parse_hex2(&q);
        skip_sp(&q);
    }

    /* ── compare with memory ──────────────────────────────── */
    changed = 0;
    for (i = 0; i < nbytes; ++i) {
        if (bytes[i] != ((uint8_t *)addr)[i]) {
            changed = 1;
            break;
        }
    }

    if (changed) {
        /* hex was edited — patch memory */
        for (i = 0; i < nbytes; ++i)
            ((uint8_t *)addr)[i] = bytes[i];
    } else {
        /* hex matches — check for mnemonic */
        skip_sp(&q);
        mne = q;
        /* only try assembly if text starts with a letter (a–z = $41–$5A) */
        if (*mne >= 'a' && *mne <= 'z') {
            nbytes = asm_line(addr, (char *)mne);
            if (nbytes == 0) {
                /* assembly error — show and don't advance */
                gotox(0);
                cputs("?asm");
                clear_eol();
                return;
            }
        }
    }

    /* ── update this line to reflect current memory ────────── */
    emit_dot(addr);

    /* ── fresh prompt at next instruction ─────────────────── */
    olen = t_opcode_len[*(uint8_t *)addr];
    cur_addr = addr + olen;
    newline();
    show_prompt();
}

/* ── AAAA:d — disassemble block_size bytes ───────────────────
 * Emits . lines covering at least block_size bytes from addr,
 * finishing the last instruction.  RETURN repeats. */
static void cmd_disasm(uint16_t addr, uint8_t *args)
{
    uint16_t end;
    (void)args;

    end = addr + block_size;
    if (end < addr) end = 0xFFFF;         /* 16-bit wrap */

    while (addr < end) {
        emit_dot(addr);
        addr += t_opcode_len[*(uint8_t *)addr];
        newline();
        if (addr == 0) break;
    }

    cur_addr = addr;
    show_prompt();
}

/* ── AAAA:m [BB BB BB BB BB BB BB BB cccccccc] ───────────────
 * Dual-purpose:
 *   bare (no args)  → dump block_size bytes as m-lines.
 *   with hex bytes  → write them to addr, refresh line.
 * RETURN on empty prompt repeats the last command. */
static void cmd_mem(uint16_t addr, uint8_t *args)
{
    uint8_t  *q = args;
    uint8_t  nbytes, cols;
    uint16_t remaining;

    skip_sp(&q);

    /* ── edit mode: hex bytes present → write to memory ───── */
    if (is_hex(q[0]) && is_hex(q[1]) && is_hex(q[2])) {
        /* 3+ hex chars means at least "XX " — a byte pair.
         * Distinguishes from empty/whitespace-only args. */
        nbytes = 0;
        while (nbytes < 8 && is_hex(*q) && is_hex(*(q + 1))) {
            uint8_t b = parse_hex2(&q);
            if (b != ((uint8_t *)addr)[nbytes])
                ((uint8_t *)addr)[nbytes] = b;
            ++nbytes;
            skip_sp(&q);
        }
        /* refresh this line to reflect memory state */
        emit_mem(addr, nbytes);
        cur_addr = addr + nbytes;
        if (cur_addr < addr) cur_addr = 0;
        newline();
        show_prompt();
        return;
    }

    /* ── dump mode: no args → dump block_size bytes ───────── */
    remaining = block_size;

    while (remaining > 0) {
        cols = (remaining >= 8) ? 8 : (uint8_t)remaining;
        emit_mem(addr, cols);
        addr += cols;
        remaining -= cols;
        newline();
        if (addr < cols) break;               /* 16-bit wrap */
    }

    cur_addr = addr;
    show_prompt();
}

/* ── AAAA:j — JSR to address, show registers ─────────────── */
static void cmd_jmp(uint16_t addr)
{
    cur_addr = addr;
    jsr_addr(addr);
    newline();
    emit_reg();
    newline();
    show_prompt();
}

/* ── r [A:XX X:XX Y:XX S:XX FLAGS] ──────────────────────── */

static uint8_t parse_regval(uint8_t **pp)
{
    uint8_t *q = *pp;
    uint8_t v;
    q += 2;                               /* skip "X:" prefix */
    v = (hex_val(q[0]) << 4) | hex_val(q[1]);
    q += 2;
    *pp = q;
    return v;
}

static void cmd_reg(uint8_t *args)
{
    static const char flag_ch[] = "nv-bdizc";
    uint8_t *q = args, i, p;

    skip_sp(&q);

    if (*q) {
        /* parse "a:XX x:XX y:XX s:XX NV-BDIZC" */
        reg_a  = parse_regval(&q); skip_sp(&q);
        reg_x  = parse_regval(&q); skip_sp(&q);
        reg_y  = parse_regval(&q); skip_sp(&q);
        reg_sp = parse_regval(&q); skip_sp(&q);

        p = 0;
        for (i = 0; i < 8; ++i) {
            p <<= 1;
            if (*q == (uint8_t)flag_ch[i]) p |= 1;
            if (*q) ++q;
        }
        reg_p = p;
    }

    /* always display (confirms edits, or shows current state) */
    emit_reg();
    newline();
    show_prompt();
}

/* ═══════════════════════════════════════════════════════════════
 * Command dispatcher — parse line_buf and execute
 *
 * Addressed: AAAA:cmd [args]   where cmd ∈ { . e d m j }
 * Bare:      cmd [args]        where cmd ∈ { r q $ clr }
 * ═══════════════════════════════════════════════════════════════ */

static void exec_line(void)
{
    uint8_t *q = line_buf;
    uint16_t addr;
    uint8_t  cmd;

    skip_sp(&q);

    /* ── Try AAAA:cmd format ─────────────────────────────── */
    if (is_hex(q[0]) && is_hex(q[1]) && is_hex(q[2]) && is_hex(q[3])
        && q[4] == ':')
    {
        addr = parse_hex4(&q);
        ++q;                              /* skip ':' */
        cmd = *q;

        /* empty after colon → repeat last command at this address */
        if (cmd == 0 || cmd == ' ') {
            if (last_cmd == 0) {
                newline();
                show_prompt();
                return;
            }
            cur_addr = addr;
            cmd = last_cmd;
            q = last_args;
            /* echo the repeated command into the prompt line */
            gotox(5);
            cputc(cmd);
            if (*q) { cputc(' '); cputs(q); }
            clear_eol();
        } else {
            ++q;                          /* skip command letter */
            if (*q == ' ') ++q;           /* optional space */
        }

        /* seek: args override prefix address */
        if (cmd == 's') {
            skip_sp(&q);
            if (is_hex(q[0]) && is_hex(q[1]) && is_hex(q[2]) && is_hex(q[3]))
                cur_addr = parse_hex4(&q);
            else
                cur_addr = addr;
            newline();
            show_prompt();
            return;
        }

        cur_addr = addr;

        /* save for repeat (compact: just the args portion) */
        last_cmd = cmd;
        strncpy(last_args, q, sizeof(last_args) - 1);
        last_args[sizeof(last_args) - 1] = 0;

        switch (cmd) {
        case '.': cmd_dot(addr, q);    break;
        case 'd': cmd_disasm(addr, q); break;
        case 'm': cmd_mem(addr, q);    break;
        case 'j': cmd_jmp(addr);       break;
        case 'b':                             /* b — set/show block size */
            if (is_hex(q[0]) && is_hex(q[1])) {
                if (is_hex(q[2]) && is_hex(q[3]))
                    block_size = parse_hex4(&q);
                else
                    block_size = parse_hex2(&q);
                if (block_size == 0) block_size = 8;
            }
            cprintf("b=%04x", block_size);
            clear_eol();
            newline();
            show_prompt();
            break;
        default:
            cputs("?cmd");
            clear_eol();
            newline();
            show_prompt();
        }
        return;
    }

    /* empty line with no AAAA: prefix */
    if (*q == 0) {
        newline();
        show_prompt();
        return;
    }

    /* ── Bare commands (no address prefix) ───────────────── */

    /* multi-char: clr/cls */
    if (q[0] == 'c' && q[1] == 'l' && (q[2] == 'r' || q[2] == 's')) {
        reset_screen();
        show_prompt();
        return;
    }

    cmd = *q++;
    if (*q == ' ') ++q;
    skip_sp(&q);

    switch (cmd) {
    case 's':                                 /* seek (bare: s AAAA) */
        if (is_hex(q[0]) && is_hex(q[1]) && is_hex(q[2]) && is_hex(q[3]))
            cur_addr = parse_hex4(&q);
        newline();
        show_prompt();
        break;

    case 'r':
        cmd_reg(q);
        break;

    case 'q':
        cputs("quit? y/n ");
        while (kbhit());
        if (cgetc() == 'y') {
            state = ST_STOP;
        }
        newline();
        if (state != ST_STOP) show_prompt();
        break;

    case '$':
        newline();
        list_directory(8);
        show_prompt();
        break;

    default:
        cputs("?");
        clear_eol();
        newline();
        show_prompt();
    }
}

/* ═══════════════════════════════════════════════════════════════
 * Main program loop
 *
 * The screen is the REPL.  Free cursor movement; RETURN on any
 * line reads that row and executes it.  No separate cmd_buffer.
 * ═══════════════════════════════════════════════════════════════ */

void main(void)
{
    uint8_t ch;

    register_user_irq();
    *(uint8_t *)0x028a |= 0b11000000;    /* all keys repeat */
    MEM_CONFIG &= ~0x20;                 /* unmap BASIC ROM */

    state = ST_RUN;
    reset_screen();
    cursor(1);

    /* greeter */
    cputsxy(0, SCREEN_HEIGHT - 4, "cse v0.1");
    cputsxy(0, SCREEN_HEIGHT - 3, "(c) 2025 cr");
    gotoxy(0, SCREEN_HEIGHT - 1);
    show_prompt();

    /* ── main loop ──────────────────────────────────────── */
    while (state != ST_STOP) {

        ch = cgetc();

        switch (ch) {

        case CH_ENTER:
            read_line();
            gotox(0);
            exec_line();
            break;

        case CH_DEL: {
            /* stop at col 5 if there's a colon prompt at col 4 */
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

        case CH_STOP:
            break;                        /* ignored for now */

        default:
            /* printable char — write to screen at cursor */
            if (CURSOR_COL < SCREEN_WIDTH - 1)
                cputc(ch);
            break;
        }
    }

    /* ── exit cleanup ───────────────────────────────────── */
    *(unsigned long *)0x0800 = 0;         /* clear BASIC start */
    MEM_CONFIG |= 0x20;                  /* remap BASIC ROM */
    unregister_user_irq();
    *(uint8_t *)0x028a &= 0b00111111;    /* normal key repeat */
    asm("jsr $A659");                     /* BASIC warm start */
}

/* ═══════════════════════════════════════════════════════════════
 * Opcode length table — all 256 opcodes (including undocumented)
 *
 * JAM/KIL opcodes = 1 (single-byte, locks CPU).
 * ═══════════════════════════════════════════════════════════════ */

static const uint8_t t_opcode_len[256] = {
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

uint8_t __fastcall__ c64_op_len(uint8_t opcode)
{
    return t_opcode_len[opcode];
}

uint8_t __fastcall__ c64_insn_len(const void *addr)
{
    return t_opcode_len[*(const uint8_t *)addr];
}
