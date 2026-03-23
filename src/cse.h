/* cse.h — shared definitions and utilities */

#ifndef CSE_H
#define CSE_H

#include <stdint.h>

/* ── Screen geometry ────────────────────────────────────── */
#define SCREEN_WIDTH  40
#define SCREEN_HEIGHT 25

/* ── Run state ──────────────────────────────────────────── */
#define ST_STOP 0
#define ST_REPL 1
#define ST_EDIT 2
extern uint8_t state;

/* ── Globals ────────────────────────────────────────────── */
extern uint8_t *const SCREEN;
extern uint8_t *src_top, *src_bot;

/* ── Memory info (meminfo.s) ────────────────────────────── */
extern uint16_t cse_start(void);
extern uint16_t cse_end(void);

/* ── Shared screen utilities (main.c) ───────────────────── */
void clear_eol(void);
void newline(void);
void scroll_up(uint8_t n);
void print_string(const uint8_t *str);
void reset_screen(void);

/* ── Shared hex parsing (main.c) ────────────────────────── */
uint8_t hex_val(uint8_t ch);
uint8_t is_hex(uint8_t ch);
uint16_t parse_hex4(uint8_t **pp);
uint8_t parse_hex2(uint8_t **pp);
void skip_sp(uint8_t **pp);

/* ── Current filename (set by l/w, shown in editor status) ── */
#define FILENAME_MAX_LEN 16
extern char cur_filename[FILENAME_MAX_LEN + 1];

/* ── Floppy (main.c) ────────────────────────────────────── */
void floppy_status(void);
void list_directory(uint8_t device);

/* ── Opcode length table ────────────────────────────────── */
extern const uint8_t t_opcode_len[256];

/* ── Assembler bridge ───────────────────────────────────── */
extern uint8_t asm_line(uint16_t addr, char *text);
extern void jsr_addr(uint16_t addr);
extern uint8_t reg_a, reg_x, reg_y, reg_sp, reg_p;

#endif
