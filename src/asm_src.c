/* asm_src.c — Two-pass source assembler
 *
 * Reads source from the editor's gap buffer (via ed_read_line).
 * Pass 1: collect labels/constants, compute instruction sizes.
 * Pass 2: resolve references, emit bytes via asm_line().
 *
 * Forward declaration rule: constants (name = expr) must be defined
 * before use.  Labels (code addresses) may be forward-referenced.
 * Branches are always 2 bytes.  Unknown label operands assume ABS (3 bytes).
 *
 * Directives: .org .db .dw .str .scr .res .align .cpu .bin
 * Local labels: .name stored as "parent.name" in symtab.
 * Anonymous labels: +/- (up to 5 forward/backward).
 */

#include <stdint.h>
#include <string.h>
#include "cse.h"
#include "cse_io.h"
#include "asm_src.h"
#include "symtab.h"
#include "editor.h"
#include "screen.h"

/* ── ZP variables from asm_vars.s (C aliases) ──────────── */
extern uint16_t al_pc;
extern uint8_t *al_out;
extern uint16_t expr_val;
extern uint8_t  expr_wide;
extern uint8_t *expr_ptr;
extern uint8_t *sym_name;
extern uint16_t sym_val;
extern uint8_t  sym_wide;

#pragma zpsym("al_pc")
#pragma zpsym("al_out")
#pragma zpsym("expr_val")
#pragma zpsym("expr_wide")
#pragma zpsym("expr_ptr")
#pragma zpsym("sym_name")
#pragma zpsym("sym_val")
#pragma zpsym("sym_wide")

/* ── External functions ────────────────────────────────── */
extern uint8_t asm_line(uint16_t addr, char *text);
extern uint8_t expr_eval(void);

/* symtab: asm functions that read/write ZP variables directly.
 * Set sym_name/sym_val/sym_wide before calling. Args are ignored
 * by the asm (it reads ZP), but C needs a declaration to call. */
extern void    sym_clear(void);
extern void __fastcall__ sym_set_heap(uint16_t addr);

/* Helper: set ZP then call sym_define. Returns 0=ok, 1=full. */
static uint8_t do_sym_define(char *name, uint16_t value, uint8_t wide) {
    sym_name = (uint8_t *)name;
    sym_val = value;
    sym_wide = wide;
    /* sym_define reads ZP, ignores C args. Pass dummies. */
    return sym_define(name, value);
}

/* ── State ─────────────────────────────────────────────── */
uint16_t asm_org    = 0x0800;
uint16_t asm_size   = 0;
uint16_t asm_errors = 0;

static uint8_t  asm_pass;           /* 0 = pass 1, 1 = pass 2 */
static uint16_t line_num;           /* current line number */
static char     line_buf[80];       /* current source line */

/* Current scope for local labels */
static char     scope_name[24];     /* last global label name */
static char     full_label[48];     /* "scope.local" concatenation */

/* Anonymous label tracking */
#define ANON_MAX 255
static uint16_t anon_list[ANON_MAX];   /* anonymous label PCs */
static uint8_t  anon_count;            /* total (set in pass 1) */
static uint8_t  anon_idx;             /* current index (pass 2) */

/* ── Helpers ───────────────────────────────────────────── */

static void emit_error(const char *msg) {
    asm_errors++;
    if (asm_pass == 1) {
        /* Only report errors in pass 2 */
        io_puts("; err ");
        io_putdec(line_num);
        io_puts(": ");
        io_puts(msg);
        newline();
    }
}

static uint8_t is_alpha(uint8_t c) {
    return (c >= 'a' && c <= 'z');     /* PETSCII lowercase = $41-$5A */
}

static uint8_t is_digit(uint8_t c) {
    return (c >= '0' && c <= '9');
}

static uint8_t is_ident_char(uint8_t c) {
    return is_alpha(c) || is_digit(c) || c == '.';
}

/* Fold PETSCII uppercase ($C1-$DA) to lowercase ($41-$5A) */
static uint8_t fold_char(uint8_t c) {
    if (c >= 0xC1 && c <= 0xDA) return c - 0x80;
    return c;
}

/* Skip spaces in a string, return pointer to next non-space */
static char *skipws(char *q) {
    while (*q == ' ') ++q;
    return q;
}

/* Parse an identifier starting at p.  Returns length.
 * Folds to lowercase in-place. */
static uint8_t parse_ident(char *p) {
    uint8_t len = 0;
    while (is_ident_char(fold_char(p[len]))) {
        p[len] = fold_char(p[len]);
        ++len;
    }
    return len;
}

/* Build full label path for a local: "scope.name" → full_label */
static void build_local_path(const char *local, uint8_t local_len) {
    uint8_t slen = strlen(scope_name);
    uint8_t i;
    /* Copy scope */
    for (i = 0; i < slen && i < sizeof(full_label) - 2; ++i)
        full_label[i] = scope_name[i];
    full_label[i++] = '.';
    /* Copy local name */
    {   uint8_t j;
        for (j = 0; j < local_len && i < sizeof(full_label) - 1; ++j)
            full_label[i++] = local[j];
    }
    full_label[i] = 0;
}

/* ── Directive handlers ────────────────────────────────── */

/* Parse comma-separated expressions for .db/.dw */
static void emit_data_bytes(char *p, uint8_t word_size) {
    uint8_t rc;

    for (;;) {
        p = skipws(p);
        if (!*p || *p == ';') break;

        /* Handle quoted strings in .db */
        if (*p == '"' && word_size == 1) {
            ++p;    /* skip opening quote */
            while (*p && *p != '"') {
                if (asm_pass == 1) {
                    *(uint8_t *)al_pc = *p;
                }
                al_pc++;
                asm_size++;
                ++p;
            }
            if (*p == '"') ++p;     /* skip closing quote */
        } else {
            /* Expression */
            expr_ptr = (uint8_t *)p;
            rc = expr_eval();
            p = (char *)expr_ptr;
            if (rc >= 2) {
                emit_error("bad expr");
                return;
            }
            if (asm_pass == 1) {
                *(uint8_t *)al_pc = expr_val & 0xFF;
                if (word_size >= 2) {
                    *((uint8_t *)al_pc + 1) = (expr_val >> 8) & 0xFF;
                }
            }
            al_pc += word_size;
            asm_size += word_size;
        }

        /* Expect comma or end */
        p = skipws(p);
        if (*p == ',') ++p;
    }
}

/* .str "text" — emit PETSCII string */
static void emit_string(char *p, uint8_t convert_to_scr) {
    p = skipws(p);
    if (*p != '"') { emit_error("expected \""); return; }
    ++p;

    while (*p && *p != '"') {
        uint8_t ch = *p;
        if (convert_to_scr) {
            /* PETSCII → screen code conversion */
            if (ch >= 0x41 && ch <= 0x5A) ch -= 0x40;
            else if (ch >= 0xC1 && ch <= 0xDA) ch -= 0x80;
        }
        if (asm_pass == 1) {
            *(uint8_t *)al_pc = ch;
        }
        al_pc++;
        asm_size++;
        ++p;
    }
    if (*p == '"') ++p;

    /* Check for trailing ,0 or similar */
    p = skipws(p);
    if (*p == ',') {
        ++p;
        emit_data_bytes(p, 1);
    }
}

/* .res count [,fill] — reserve bytes */
static void emit_reserve(char *p) {
    uint8_t rc;
    uint16_t count;
    uint8_t fill = 0;

    expr_ptr = (uint8_t *)p;
    rc = expr_eval();
    if (rc >= 2) { emit_error("bad count"); return; }
    count = expr_val;

    p = (char *)expr_ptr;
    p = skipws(p);
    if (*p == ',') {
        ++p;
        expr_ptr = (uint8_t *)p;
        rc = expr_eval();
        if (rc >= 2) { emit_error("bad fill"); return; }
        fill = expr_val & 0xFF;
    }

    if (asm_pass == 1) {
        memset((void *)(uint16_t)al_pc, fill, count);
    }
    al_pc += count;
    asm_size += count;
}

/* .align boundary — advance PC to next multiple */
static void emit_align(char *p) {
    uint8_t rc;
    uint16_t boundary, pad;

    expr_ptr = (uint8_t *)p;
    rc = expr_eval();
    if (rc >= 2) { emit_error("bad boundary"); return; }
    boundary = expr_val;
    if (boundary == 0) { emit_error("align 0"); return; }

    pad = boundary - (al_pc % boundary);
    if (pad == boundary) pad = 0;   /* already aligned */

    if (asm_pass == 1 && pad > 0) {
        memset((void *)(uint16_t)al_pc, 0, pad);
    }
    al_pc += pad;
    asm_size += pad;
}

/* .bin "filename" — include binary file */
static void emit_binary(char *p) {
    /* TODO: read binary file from disk, emit bytes.
     * For now: error. */
    (void)p;
    emit_error(".bin not yet");
}

/* .cpu 6502/6510/65c02 */
static void set_cpu(char *p) {
    p = skipws(p);
    if (p[0] == '6' && p[1] == '5') {
        if (p[2] == '0' && p[3] == '2') { al_cpu = 0; return; }
        if (p[4] == '0' && p[5] == '2') { al_cpu = 2; return; }  /* 65c02 */
    }
    if (p[0] == '6' && p[1] == '5' && p[2] == '1' && p[3] == '0') {
        al_cpu = 1; return;
    }
    emit_error("bad .cpu");
}

/* ── Process one directive ─────────────────────────────── */
static void process_directive(char *p) {
    /* p points past the '.' */
    if (p[0] == 'o' && p[1] == 'r' && p[2] == 'g') {
        /* .org expr */
        expr_ptr = (uint8_t *)(p + 3);
        if (expr_eval() >= 2) { emit_error("bad .org"); return; }
        al_pc = expr_val;
        if (asm_pass == 0) asm_org = expr_val;
    }
    else if (p[0] == 'd' && p[1] == 'b') {
        emit_data_bytes(p + 2, 1);
    }
    else if (p[0] == 'd' && p[1] == 'w') {
        emit_data_bytes(p + 2, 2);
    }
    else if (p[0] == 's' && p[1] == 't' && p[2] == 'r') {
        emit_string(p + 3, 0);
    }
    else if (p[0] == 's' && p[1] == 'c' && p[2] == 'r') {
        emit_string(p + 3, 1);
    }
    else if (p[0] == 'r' && p[1] == 'e' && p[2] == 's') {
        emit_reserve(p + 3);
    }
    else if (p[0] == 'a' && p[1] == 'l' && p[2] == 'i'
          && p[3] == 'g' && p[4] == 'n') {
        emit_align(p + 5);
    }
    else if (p[0] == 'c' && p[1] == 'p' && p[2] == 'u') {
        set_cpu(p + 3);
    }
    else if (p[0] == 'b' && p[1] == 'i' && p[2] == 'n') {
        emit_binary(p + 3);
    }
    else {
        emit_error("bad directive");
    }
}

/* ── Process one source line ───────────────────────────── */
static void process_line(char *p) {
    uint8_t ident_len;
    uint8_t nbytes;

    p = skipws(p);

    /* Empty line or comment */
    if (*p == 0 || *p == ';') return;

    /* ── Anonymous label marker: bare '+' at start ────── */
    if (*p == '+' && (*(p+1) == 0 || *(p+1) == ' ' || *(p+1) == ';')) {
        if (asm_pass == 0 && anon_count < ANON_MAX) {
            anon_list[anon_count++] = al_pc;
        }
        if (asm_pass == 1) anon_idx++;
        ++p;
        p = skipws(p);
        if (*p == 0 || *p == ';') return;
    }

    /* ── Directive: starts with '.' ───────────────────── */
    if (*p == '.') {
        process_directive(p + 1);
        return;
    }

    /* ── Origin shorthand: *= expr ────────────────────── */
    if (*p == '*' && *(p+1) == '=') {
        expr_ptr = (uint8_t *)(p + 2);
        if (expr_eval() >= 2) { emit_error("bad org"); return; }
        al_pc = expr_val;
        if (asm_pass == 0) asm_org = expr_val;
        return;
    }

    /* ── Label or constant definition ─────────────────── */
    if (is_alpha(fold_char(*p))) {
        char *start = p;
        ident_len = parse_ident(p);

        if (ident_len > 0) {
            char *after = p + ident_len;
            char *rest = skipws(after);

            /* Constant: name = expr */
            if (*rest == '=') {
                rest++;
                expr_ptr = (uint8_t *)rest;
                if (expr_eval() >= 2) {
                    emit_error("bad const expr");
                    return;
                }
                if (asm_pass == 0) {
                    if (do_sym_define(start, expr_val, expr_wide)) {
                        emit_error("sym full");
                    }
                }
                return;
            }

            /* Label: name followed by ':' or instruction */
            if (*rest == ':') rest++;    /* optional colon */

            if (asm_pass == 0) {
                /* Check if it's a local (.name) stored as scope.name */
                char *label_name;
                uint8_t si;
                uint8_t wide;
                if (start[0] == '.') {
                    build_local_path(start + 1, ident_len - 1);
                    label_name = full_label;
                } else {
                    label_name = start;
                    /* Update scope for future locals */
                    for (si = 0; si < ident_len && si < sizeof(scope_name) - 1; ++si)
                        scope_name[si] = start[si];
                    scope_name[si] = 0;
                }
                wide = (al_pc > 0xFF) ? 1 : 0;
                if (do_sym_define(label_name, al_pc, wide)) {
                    emit_error("sym full");
                }
            }

            if (asm_pass == 1) {
                /* Update scope and anon tracking for pass 2 */
                if (start[0] != '.' && start[0] != '+') {
                    uint8_t si2;
                    for (si2 = 0; si2 < ident_len && si2 < sizeof(scope_name) - 1; ++si2)
                        scope_name[si2] = start[si2];
                    scope_name[si2] = 0;
                }
            }

            p = skipws(rest);
            if (*p == 0 || *p == ';') return;
            /* Fall through to instruction */
        }
    }

    /* ── Instruction: preprocess operand, then pass to asm_line ── */
    /* asm_line expects canonical hex operands: #$XX, $XX, $XXXX, ($XX),y etc.
     * We parse the mnemonic, evaluate the operand expression, and rebuild
     * the line with hex values so asm_line's parser handles it. */
    {
        static char insn_buf[32];   /* rebuilt instruction for asm_line */
        char *dst = insn_buf;
        char *src = p;
        uint8_t mne_len;
        uint8_t rc;

        /* Copy mnemonic (up to first space or end) */
        mne_len = 0;
        while (*src && *src != ' ' && mne_len < 8) {
            *dst++ = *src++;
            mne_len++;
        }

        /* Skip spaces between mnemonic and operand */
        while (*src == ' ') src++;

        if (*src && *src != ';') {
            /* There's an operand.  Detect addressing mode syntax and
             * evaluate the expression within it. */
            uint8_t prefix = 0;     /* chars before the expression value */
            uint8_t has_hash = 0;
            uint8_t has_lparen = 0;

            /* Scan prefix characters: #, ( */
            if (*src == '#') { has_hash = 1; src++; while (*src == ' ') src++; }
            if (*src == '(') { has_lparen = 1; src++; while (*src == ' ') src++; }

            /* Evaluate the expression */
            expr_ptr = (uint8_t *)src;
            rc = expr_eval();
            src = (char *)expr_ptr;
            if (rc >= 2) {
                emit_error("bad operand");
                return;
            }

            /* Rebuild: mnemonic + space + prefix + hex value + suffix */
            *dst++ = ' ';

            if (has_hash) *dst++ = '#';
            if (has_lparen) *dst++ = '(';

            /* Write hex value: $XX or $XXXX based on width */
            *dst++ = '$';
            if (expr_wide || expr_val > 0xFF) {
                *dst++ = "0123456789abcdef"[(expr_val >> 12) & 0xF];
                *dst++ = "0123456789abcdef"[(expr_val >>  8) & 0xF];
            }
            *dst++ = "0123456789abcdef"[(expr_val >>  4) & 0xF];
            *dst++ = "0123456789abcdef"[ expr_val        & 0xF];

            /* Copy suffix: ),y  ),x  ,x  ,y  ) etc */
            while (*src == ' ') src++;
            while (*src && *src != ';' && (dst - insn_buf) < sizeof(insn_buf) - 1) {
                *dst++ = *src++;
            }
        }

        *dst = 0;

        nbytes = asm_line((uint16_t)al_pc, insn_buf);
        if (nbytes == 0) {
            emit_error(insn_buf);
            return;
        }
        al_pc += nbytes;
        asm_size += nbytes;
    }
}

/* ── Main assembly loop ───────────────────────────────── */

static void do_pass(void) {
    int len;
    ed_read_rewind();
    line_num = 0;
    al_pc = asm_org;

    while ((len = ed_read_line(line_buf, sizeof(line_buf))) >= 0) {
        line_num++;
        process_line(line_buf);
    }
}

uint16_t asm_assemble(void) {
    uint16_t heap_addr;

    asm_errors = 0;
    asm_size   = 0;
    anon_count = 0;
    anon_idx   = 0;
    scope_name[0] = 0;

    /* Set up symbol table heap in free memory above BSS */
    heap_addr = cse_end();
    sym_set_heap(heap_addr);
    sym_clear();

    /* Pass 1: collect labels, compute sizes */
    asm_pass = 0;
    asm_org  = 0x0800;     /* default origin, may be overridden by .org */
    do_pass();

    /* Pass 2: resolve, emit */
    asm_pass = 1;
    asm_size = 0;           /* recount for pass 2 */
    anon_idx = 0;
    scope_name[0] = 0;
    do_pass();

    return asm_errors;
}
