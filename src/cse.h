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

/* ── Color theme ──────────────────────────────────────────── */
extern uint8_t theme_border;     /* $D020 color */
extern uint8_t theme_bg;         /* $D021 color */
extern uint8_t theme_fg;         /* text/color RAM color */
void restore_colors(void);       /* apply theme + fill color RAM */

/* ── Shared screen utilities (main.c + cse_io.s) ────────── */
#define clear_eol io_clear_eol
void newline(void);
void scroll_up(uint8_t n);
void print_string(const uint8_t *str);
void reset_screen(void);
#ifndef COLOR_RAM
#define COLOR_RAM ((uint8_t *)0xD800)
#endif


/* ── Shared hex parsing (main.c) ────────────────────────── */
uint8_t hex_val(uint8_t ch);
uint8_t is_hex(uint8_t ch);
uint8_t hex_val_to_char(uint8_t v);
uint16_t parse_hex4(uint8_t **pp);
uint8_t parse_hex2(uint8_t **pp);
void skip_sp(uint8_t **pp);

/* ── Current filename (set by l/w, shown in editor status) ── */
#define FILENAME_MAX_LEN 16
extern char cur_filename[FILENAME_MAX_LEN + 1];

/* ── Floppy (main.c) ────────────────────────────────────── */
void floppy_status(void);
void list_directory(uint8_t device);


/* ── CPU mode ─────────────────────────────────────────── */
/* al_cpu: 0=6502 (legal only), 1=6510 (+illegal), 2=65C02 (+CMOS)   */
/* CPU_CEIL: build-time maximum (passed as -DCPU_CEIL=N)              */
extern uint8_t al_cpu;          /* ZP variable from asm_vars.s */
#pragma zpsym("al_cpu")
#ifndef CPU_CEIL
#define CPU_CEIL 1              /* fallback: 6510 */
#endif

/* ── Assembler bridge ───────────────────────────────────── */
extern uint8_t asm_line(uint16_t addr, char *text);
extern void jsr_addr(uint16_t addr);
extern uint8_t reg_a, reg_x, reg_y, reg_sp, reg_p;

#endif
