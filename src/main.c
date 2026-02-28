#include <c64.h>
#include <cbm.h>
#include <conio.h>
#include <string.h>
#include <stdint.h>

#define SCREEN_WIDTH 40     // C64 screen width
#define SCREEN_HEIGHT 25    // C64 screen height

#define MEM_CONFIG (*(uint8_t *)0x01) // Bank management etc.
#define CURSOR_ROW (*(uint8_t *)0xD6) // Shorthand for cursor row
#define CURSOR_COL (*(uint8_t *)0xD3) // Shorthand for cursor column

#define CMD_BUFFER_LENGTH 2
#define MAX_INPUT_LENGTH (77) // Maximum input length

// Global RunState
typedef enum {
    RUN_STATE_STOP,     // 0: Program is stopped
    RUN_STATE_CMD,      // 1: Command mode
    RUN_STATE_EDITOR    // 2: Editor mode
} run_state;
static uint8_t state = 0;

// Declare the base address of the C64 screen memory
uint8_t *const SCREEN = (uint8_t *)0x0400;

static uint8_t cmd_buffer[CMD_BUFFER_LENGTH][MAX_INPUT_LENGTH+1];
static uint8_t cmd_length[CMD_BUFFER_LENGTH]; // lenght of current command line
static uint8_t cmd_current = 0;
static uint8_t cmd_buffered = 0;
static uint8_t cmd_cursor = 0; // cursor position in current command line

// Custom user IRQ handler to stop cursor blinking
void custom_user_irq(void) {
    __asm__("sei");
    if (*((uint8_t *)0xCC) == 0) {
        // Pretend we just blinked the cursor on.
        *((uint8_t *)0xCF) = 1; // Blink state reversed
        *((uint8_t *)0x0287) = *((uint8_t *)(*(unsigned int *)0xF3 + *(uint8_t *)0xD3)); // Store original color
        *((uint8_t *)(*(unsigned int *)0xD1 + *(uint8_t *)0xD3)) |= 0x80; // Reverse under cursor
        *((uint8_t *)0xCD) = 20; // Original IRQ shall never blink, but...
        // ...in this state it will take care of proper un-reversing on cursor movements. 
    }
    __asm__("jmp $EA31"); // Jump to the original KERNAL IRQ handler (standard entry point)
}

// Register the custom user IRQ handler
void register_user_irq(void) {
    // Set the new user IRQ vector
    *(void (**)(void))0x0314 = custom_user_irq;
}

// Restore the original user IRQ handler
void unregister_user_irq(void) {
    // Restore the old user IRQ vector
    *(void (**)(void))0x0314 = (void *)0xEA31;
}

void click_sound() {
    volatile uint8_t i;
    SID.v1.freq = 0x8000;   // Set frequency
    SID.v1.ctrl = 0x11;     // Set waveform (triangle) and gate bit
    SID.amp = 10;           // Set volume
    for (i = 0; i < 200; i++); // Short delay
    SID.v1.ctrl = 0x00;     // Turn off sound (clear gate bit)
}

// Function to reset the screen and cursor position
static void reset_screen(void) {
    switch (state) {
    
    case RUN_STATE_CMD:
        bgcolor(11);     // Set background color to dark gray
        bordercolor(12); // Set border color to mid gray
        textcolor(5);    // Set text color to green
        clrscr();        // Clear the screen
        memset(COLOR_RAM, 5, 1000); // All green
        gotoxy(0, 0);    // Move to the top-left corner
        break;
    
    case RUN_STATE_EDITOR:
        bgcolor(11);     // Set background color to dark gray
        bordercolor(15); // Set border color to light gray
        textcolor(5);    // Set text color to green
        clrscr();        // Clear the screen
        memset(COLOR_RAM, 5, 1000); // All green
        gotoxy(0, 0);    // Move to the top-left corner
        break;

    }
}

static void scroll_up(uint8_t num_lines) {
    if (num_lines >= SCREEN_HEIGHT) {
        // Clear the screen if num_lines is larger than or equal to the screen height
        clrscr();
        gotoxy(0, 0);
    } else {
        // Scroll the specified number of lines
        memmove(SCREEN, SCREEN + (num_lines * SCREEN_WIDTH), SCREEN_WIDTH * (SCREEN_HEIGHT - num_lines));
        memset(SCREEN + SCREEN_WIDTH * (SCREEN_HEIGHT - num_lines), ' ', SCREEN_WIDTH * num_lines);

        if (CURSOR_ROW > num_lines) {
            gotoy(CURSOR_ROW - num_lines);
        } else {
            gotoy(0);
        }
    }
}

// static void scroll_down(uint8_t num_lines) {
//     if (num_lines >= SCREEN_HEIGHT) {
//         // Clear the screen if num_lines is larger than or equal to the screen height
//         clrscr();
//         gotoxy(0, SCREEN_HEIGHT-1);
//     } else {
//         // Scroll the specified number of lines
//         memmove(SCREEN + (num_lines * SCREEN_WIDTH), SCREEN, SCREEN_WIDTH * (SCREEN_HEIGHT - num_lines));
//         memset(SCREEN, ' ', SCREEN_WIDTH * num_lines);

//         gotox(CURSOR_COL + num_lines);
//         if (CURSOR_ROW >= SCREEN_HEIGHT) {
//             gotoxy(0, SCREEN_HEIGHT-1);  // Clamp to screen bottom
//         }
//     }
// }

static void newline() {
    if (CURSOR_ROW == SCREEN_HEIGHT - 1) {
        scroll_up(1);
    }
    gotoxy(0, CURSOR_ROW+1);
}

// Function to print a character and handle wrapping and scrolling
static void print_char(uint8_t ch) {
    if (CURSOR_COL == SCREEN_WIDTH-1 && CURSOR_ROW == SCREEN_HEIGHT-1) scroll_up(1);
    cputc(ch);
}

// Function to print a string and update cursor position
static void print_string(const uint8_t *str) {
    uint8_t l, lines_required, lines_free;

    // Do we need scrolling?
    l = strlen(str);
    lines_required = (l + CURSOR_COL + 1) / SCREEN_WIDTH;  // +1 for cursor
    lines_free = SCREEN_HEIGHT - CURSOR_ROW - 1;
    if (lines_required > 0 && lines_free < lines_required) {
        scroll_up(lines_required - lines_free);
    }

    cputs(str);
}

static void print_prompt() {
    cputs("> ");
    cmd_buffer[cmd_current][0] = 0;
    cmd_length[cmd_current] = 0;
}

static void insert_char(uint8_t ch) {
    uint8_t *p, l;
    l = cmd_length[cmd_current];
    if (l < MAX_INPUT_LENGTH) {
        print_char(ch);
        p = cmd_buffer[cmd_current] + l;
        *(p++) = ch;
        *p = 0;
        cmd_length[cmd_current] = l+1;
    }
}

static void delete_char() {
    uint8_t col, row;
    if (cmd_length[cmd_current] == 0) return;
    if (CURSOR_COL == 0) {
        if (CURSOR_ROW == 0) {
            print_string("ERROR"); // FIXME
        } else {
            gotoxy(SCREEN_WIDTH-1, CURSOR_ROW-1);
        }
    } else {
        gotox(CURSOR_COL-1);
    }
    col = CURSOR_COL;
    row = CURSOR_ROW;
    cputc(' '); // Clear the character visually
    gotoxy(col, row);
    cmd_buffer[cmd_current][--cmd_length[cmd_current]] = 0;
}

static void print_inverse(const uint8_t *str) {
    uint8_t x, y;
    while (*str) {
        x = CURSOR_COL;
        y = CURSOR_ROW;
        print_char(*str++);
        SCREEN[y*SCREEN_WIDTH+x] |= 0x80; // Set bit 7 for inverse video
    }
}

uint8_t l, status[32];

void floppy_status() {
    if (cbm_open(14, 8, 15, NULL) == 0) {
        cbm_write(14, "i", 1);
        l = cbm_read(14, status, sizeof(status)-1);
        cbm_close(14);
        if (l>0) {
            status[l-1] = 0; // remove trailing newlines
            print_string(status);
            newline();
        } else {
            print_string("ERROR: unable to read drive status");
            newline();
        }
    }
}

// Function to list the directory of the given drive
static void list_directory(uint8_t device) {
    register struct cbm_dirent dirent;

    if (cbm_opendir(15, device)) {
        floppy_status();
        return;
    }

    while (1) {
        if (kbhit()) {
            if (cgetc() == CH_STOP) {
                cputs("break");
                newline();
                cbm_closedir(15);
                // floppy_status();
                return;
            }
        }
        switch (cbm_readdir(15, &dirent)) {
            case 0:
                cprintf("%d ", dirent.size);
                if (dirent.type == CBM_T_HEADER) {
                    revers(1);
                    cprintf("\"%-16s\"    %02x", dirent.name, dirent.access);
                    revers(0);
                    newline();
                    break;
                } else {
                    gotox(5);
                    cputc('"');
                    cputs(dirent.name);
                    cputc('"');
                }
                gotox(24);
                switch (dirent.type) {
                    case CBM_T_DEL:
                        cputs("del");
                        break;
                    case CBM_T_HEADER:
                        break;
                    case CBM_T_SEQ:
                        cputs("seq");
                        break;
                    case CBM_T_PRG:
                        cputs("prg");
                        break;
                    case CBM_T_USR:
                        cputs("usr");
                        break;
                    case CBM_T_REL:
                        cputs("rel");
                        break;
                    case CBM_T_DIR:
                        cputs("dir");
                        break;
                    case CBM_T_CBM:
                        cputs("cbm");
                        break;
                    case CBM_T_LNK:
                        cputs("lnk");
                        break;
                    case CBM_T_OTHER:
                        cputs("???");
                        break;
                    default:
                        cprintf("%03d", dirent.type);
                }
                if (!dirent.access) cputc('*');
                newline();
                break;
            case 2:  // Last line
                cbm_closedir(15);
                cprintf("%d blocks free.", dirent.size);
                newline();
                floppy_status();
                return;
            default:
                cbm_closedir(15);
                floppy_status();
                return;
        }
    }
    // Unreachable
    cbm_closedir(15);
    floppy_status();
}

uint8_t *p, *e;

// Function to parse the command
void parse_command(uint8_t *start, uint8_t length) {
    uint8_t *cmd;
    uint8_t *args;

    p = start;
    // skip leading and trailing whitespace
    while (length > 0 && p[length-1] == ' ') length--;
    e = start + length;
    while (p < e && *p == ' ') p++;
    *e = 0;

    cmd = p;

    // skip over command
    while (p < e && *p != ' ') p++;
    *(p++) = 0;  // p may point one after e if no args

    // Extract args, if any
    if (p >= e) {
        args = e;
    } else {
        // Skip leading whitespace
        while (p < e && *p == ' ') p++;
        args = p;
    }

    if (strlen(cmd) == 0) {
        return;
    }

    // Print parsed command and arguments
    // print_string("DEBUG: cmd: \"");
    // print_string(cmd);
    // print_string("\" args: \"");
    // print_string(args);
    // print_string("\"");
    // newline();

    if (strcmp(cmd, "q") == 0) {
        print_string("Really quit? (y/n) ");
        // erase_cursor();
        while (kbhit());
        if (cgetc() == 'y') {
            newline();
            print_string("Good bye!");
            newline();
            state = RUN_STATE_STOP;
        } else {
            newline();
        };
    } else if (strcmp(cmd, "$") == 0) {
        list_directory(8);
    } else if (strcmp(cmd, "clr") == 0 || strcmp(cmd, "cls") == 0 ) {
        reset_screen();
    } else {
        // print_string("ERROR: unknown command: \"");
        // print_string(cmd);
        // print_string("\"");
        print_string("unknown command");
        newline();
    }
}

void debug_cursor() {
    uint8_t x, y;
    x = CURSOR_COL;
    y = CURSOR_ROW;
    gotoxy(40-5, 0);
    cprintf("%02d/%02d", x, y);
    gotoxy(x, y);
}

// Main program loop
void maino(void) {
    uint8_t ch;

    register_user_irq();
    *(uint8_t *)0x028a |= 0b11000000; // All keys shall repeat


    // Let's make use of all of $0800 - $d000
    MEM_CONFIG &= ~0x20; // Clear bit 5, unmap BASIC

    // Starting out in CMD mode
    state = RUN_STATE_CMD;

    // Reset the screen at the start
    reset_screen();

    // Show greeter and initial prompt
    cursor(1);
    cputsxy(0, SCREEN_HEIGHT-4, "cse v0.1");
    cputsxy(0, SCREEN_HEIGHT-3, "(c) 2025 cr");
    gotoxy(0, SCREEN_HEIGHT-1);
    print_prompt();

    // Main loop
    while (state != RUN_STATE_STOP) {
        debug_cursor();
        switch (state) {
            case RUN_STATE_CMD:
                ch = cgetc();
                switch (ch) {
                    case CH_ENTER:
                        newline();
                        parse_command(cmd_buffer[cmd_current], cmd_length[cmd_current]);
                        print_prompt();
                        break;
                    case CH_ESC:
                        state = RUN_STATE_EDITOR;
                        reset_screen();
                        break;
                    case CH_DEL:
                        if (cmd_length[cmd_current] > 0) {
                            delete_char();
                        } else {
                            click_sound();
                        }
                        break;
                    case CH_INS:
                        print_string("INS");
                        newline();
                        print_prompt();
                        break;
                    case CH_STOP:
                        print_string("STOP");
                        newline();
                        print_prompt();
                        break;
                    case CH_HOME:
                        print_string("HOME");
                        newline();
                        print_prompt();
                        break;
                    case CH_CURS_UP:
                        if (CURSOR_ROW > 0) gotoy(CURSOR_ROW-1);
                        break;
                    case CH_CURS_DOWN:
                        if (CURSOR_ROW < SCREEN_HEIGHT-1) gotoy(CURSOR_ROW+1);
                        break;
                    case CH_CURS_LEFT:
                        if (CURSOR_COL > 0) gotox(CURSOR_COL-1);
                        break;
                    case CH_CURS_RIGHT:
                        if (CURSOR_COL < SCREEN_WIDTH-1) gotox(CURSOR_COL+1);
                        break;
                    default:
                        insert_char(ch);
                }
                break;
            case RUN_STATE_EDITOR:
                ch = cgetc();
                if (ch == CH_ESC) {
                    state = RUN_STATE_CMD;
                    reset_screen();
                    print_prompt();
                }
                // TODO: full editor input handling
                break;
            default:
                reset_screen();
                cputs("INVALID STATE");
                cgetc();
                state = RUN_STATE_STOP;
        }

    }

    *(unsigned long *)0x0800 = 0;  // Clear BASIC memory on exit (non-reentrant)
    MEM_CONFIG |= 0x20; // Set bit 5, remap BASIC
    unregister_user_irq(); // Let cursor blink again
    *(uint8_t *)0x028a &= 0b00111111; // Only csr/spc/del shall repeat
    asm("jsr $A659"); // Jump to BASIC warm start
}

/* cc65 / C64 (6502/6510) opcode length helper
 *
 * Returns the instruction length in bytes for *all 256 opcodes*.
 * Undocumented opcodes are included with their real addressing-mode lengths.
 * “JAM/KIL” opcodes are treated as 1-byte instructions (they’re single-byte
 * opcodes that lock the CPU).
 */

static const uint8_t t_opcode_len[256] = {
    /* 0x00 */
    1,2,1,2,2,2,2,2, 1,2,1,2,3,3,3,3,
    /* 0x10 */
    2,2,1,2,2,2,2,2, 1,3,1,3,3,3,3,3,
    /* 0x20 */
    3,2,1,2,2,2,2,2, 1,2,1,2,3,3,3,3,
    /* 0x30 */
    2,2,1,2,2,2,2,2, 1,3,1,3,3,3,3,3,
    /* 0x40 */
    1,2,1,2,2,2,2,2, 1,2,1,2,3,3,3,3,
    /* 0x50 */
    2,2,1,2,2,2,2,2, 1,3,1,3,3,3,3,3,
    /* 0x60 */
    1,2,1,2,2,2,2,2, 1,2,1,2,3,3,3,3,
    /* 0x70 */
    2,2,1,2,2,2,2,2, 1,3,1,3,3,3,3,3,
    /* 0x80 */
    2,2,2,2,2,2,2,2, 1,2,1,2,3,3,3,3,
    /* 0x90 */
    2,2,1,2,2,2,2,2, 1,3,1,3,3,3,3,3,
    /* 0xA0 */
    2,2,2,2,2,2,2,2, 1,2,1,2,3,3,3,3,
    /* 0xB0 */
    2,2,1,2,2,2,2,2, 1,3,1,3,3,3,3,3,
    /* 0xC0 */
    2,2,2,2,2,2,2,2, 1,2,1,2,3,3,3,3,
    /* 0xD0 */
    2,2,1,2,2,2,2,2, 1,3,1,3,3,3,3,3,
    /* 0xE0 */
    2,2,2,2,2,2,2,2, 1,2,1,2,3,3,3,3,
    /* 0xF0 */
    2,2,1,2,2,2,2,2, 1,3,1,3,3,3,3,3
};

/* If you already have the opcode byte */
uint8_t __fastcall__ c64_op_len(uint8_t opcode)
{
    return t_opcode_len[opcode];
}

/* If you have a pointer to the instruction in memory */
uint8_t __fastcall__ c64_insn_len(const void* addr)
{
    return t_opcode_len[*(const uint8_t*)addr];
}

/* opcode bits:
 * A2 A1 A0 = bits 7..5
 * B2 B1 B0 = bits 4..2
 * C1 C0    = bits 1..0
 */

uint8_t __fastcall__ c64_op_len_bool(uint8_t op)
{
    uint8_t A2 = (op >> 7) & 1;
    uint8_t A1 = (op >> 6) & 1;
    uint8_t A0 = (op >> 5) & 1;

    uint8_t B2 = (op >> 4) & 1;
    uint8_t B1 = (op >> 3) & 1;
    uint8_t B0 = (op >> 2) & 1;

    uint8_t C1 = (op >> 1) & 1;
    uint8_t C0 =  op       & 1;

    /* L1 */
    uint8_t L1 =
        B0 |
        C0 |
        (!B1 && (
            (A2 && !B2) ||
            (B2 && !C1) ||
            (A0 && !A1 && !C1)
        ));

    /* L0 */
    uint8_t L0 =
        (B1 && (B0 || B2 || !C0)) ||
        (!C0 && !B0 && ((B2 && C1) || (!A2 && !B2)));

    return (L1 << 1) | L0;
}

#include <stdint.h>
#include <cbm.h>

/* -------------------------------------------------- */
/* KERNAL output helpers                              */
/* -------------------------------------------------- */

static void chrout(char c)
{
    cbm_k_bsout((unsigned char)c);   /* CHROUT / $FFD2 */
}

static void print_hex_nibble(uint8_t v)
{
    if (v < 10)
        chrout('0' + v);
    else
        chrout('A' + (v - 10));
}

static void print_hex_byte(uint8_t v)
{
    print_hex_nibble(v >> 4);
    print_hex_nibble(v & 0x0F);
}

static void newlinek(void)
{
    chrout(13);   /* CR */
    chrout(10);   /* LF */
}

/* -------------------------------------------------- */
/* Final minimal opcode-length logic                  */
/* -------------------------------------------------- */
/*
 * Opcode bits: aaa bbb cc
 *
 * L0 = C0
 *
 * L1 = (B0 | C0)
 *    | (!B1 & (A2 | A0 | B2))
 *
 * length = (L1 << 1) | L0   -> 1, 2, or 3
 */

static uint8_t opcode_len(uint8_t op)
{
    uint8_t A2 = (op >> 7) & 1;
    uint8_t A1 = (op >> 6) & 1;
    uint8_t A0 = (op >> 5) & 1;

    uint8_t B2 = (op >> 4) & 1;
    uint8_t B1 = (op >> 3) & 1;
    uint8_t B0 = (op >> 2) & 1;

    uint8_t C1 = (op >> 1) & 1;
    uint8_t C0 =  op       & 1;

    /* L1 */
    uint8_t L1 =
        (uint8_t)(B0 | C0) |
        (uint8_t)((!B1) && (
            (A2 && !B2) ||
            (B2 && !C1) ||
            (A0 && !A1 && !C1)
        ));

    /* L0 (factored form) */
    uint8_t L0 =
        (uint8_t)((B1 && (B0 || B2 || !C0)) ||
                  (!C0 && !B0 && ((B2 && C1) || (!A2 && !B2))));

    return (uint8_t)((L1 << 1) | L0);
}

static uint8_t opcode_len_opt(uint8_t op)
{
    /* split into aaa bbb cc */
    uint8_t a = (uint8_t)(op >> 5);          /* 0..7 */
    uint8_t b = (uint8_t)((op >> 2) & 7);    /* 0..7 */
    uint8_t c = (uint8_t)(op & 3);           /* 0..3 */

    /* normalize to 0/1 */
    uint8_t A2 = (a & 4) != 0;
    uint8_t A1 = (a & 2) != 0;
    uint8_t A0 = (a & 1) != 0;

    uint8_t B2 = (b & 4) != 0;
    uint8_t B1 = (b & 2) != 0;
    uint8_t B0 = (b & 1) != 0;

    uint8_t C1 = (c & 2) != 0;
    uint8_t C0 = (c & 1) != 0;

    /* Correct (previously verified) logic */
    uint8_t L1 =
        (uint8_t)(B0 | C0) |
        (uint8_t)((!B1) && (
            (A2 && !B2) ||
            (B2 && !C1) ||
            (A0 && !A1 && !C1)
        ));

    uint8_t L0 =
        (uint8_t)((B1 && (B0 || B2 || !C0)) ||
                  (!C0 && !B0 && ((B2 && C1) || (!A2 && !B2))));

    return (uint8_t)((L1 << 1) | L0);   /* 1..3 */
}

/* -------------------------------------------------- */
/* main                                               */
/* -------------------------------------------------- */

void main(void)
{
    uint8_t op = 0;
    uint8_t i;

    do {
        /* Line prefix: hex opcode */
        print_hex_byte(op);
        chrout(':');
        chrout(' ');

        for (i = 0; i < 16; ++i) {
            uint8_t len = opcode_len(op);

            chrout('0' + len);

            if (i != 15)
                chrout(' ');

            ++op;
        }

        chrout(13); chrout(10);

    } while (op != 0);

    /* Stay resident */
    for (;;) ;
}