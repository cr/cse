/* cse.h — shared definitions and utilities */

#ifndef CSE_H
#define CSE_H

#include <stdint.h>

/* ── Screen geometry ────────────────────────────────────── */
#define SCREEN_WIDTH  40
#define SCREEN_HEIGHT 25

/* ── Key codes (from cbm.h, reproduced to avoid pulling
 *    all of cbm.h into every module) ──────────────────── */
#ifndef CH_ENTER
#define CH_ENTER        13
#endif
#ifndef CH_STOP
#define CH_STOP          3
#endif
#ifndef CH_DEL
#define CH_DEL          20
#endif
#ifndef CH_INS
#define CH_INS         148
#endif
#ifndef CH_CURS_UP
#define CH_CURS_UP     145
#endif
#ifndef CH_CURS_DOWN
#define CH_CURS_DOWN    17
#endif
#ifndef CH_CURS_LEFT
#define CH_CURS_LEFT   157
#endif
#ifndef CH_CURS_RIGHT
#define CH_CURS_RIGHT   29
#endif
#ifndef CH_HOME
#define CH_HOME         19
#endif
#ifndef CH_ESC
#define CH_ESC          0x1B
#endif
#ifndef CH_F1
#define CH_F1          133
#endif
#ifndef CH_F3
#define CH_F3          134
#endif
#ifndef CH_F5
#define CH_F5          135
#endif
#ifndef CH_F7
#define CH_F7          136
#endif

/* ── Run state ──────────────────────────────────────────── */
#define ST_STOP 0
#define ST_REPL 1
#define ST_EDIT 2
extern uint8_t state;

/* ── Globals ────────────────────────────────────────────── */
extern uint8_t *const SCREEN;
extern uint8_t *src_top, *src_bot;
#ifndef COLOR_RAM
#define COLOR_RAM ((uint8_t *)0xD800)
#endif

/* ── Memory info (meminfo.s) ────────────────────────────── */
extern uint16_t cse_start(void);
extern uint16_t cse_end(void);
extern uint8_t  cse_zp_end(void);  /* first free ZP byte */

/* ── Symbol table (symtab.s) ─────────────────────────────── */
void __fastcall__ sym_set_heap(uint16_t addr);
void sym_clear(void);

/* ── REPL current address / device ────────────────────── */
extern uint16_t cur_addr;
extern uint8_t  cur_device;           /* default 8 */

/* ── Alias for io_clear_eol (used widely) ─────────────── */
#define clear_eol io_clear_eol

/* ── Shared hex parsing (main.c) ────────────────────────── */
uint8_t __fastcall__ hex_val(uint8_t ch);
uint8_t __fastcall__ is_hex(uint8_t ch);
uint8_t __fastcall__ hex_val_to_char(uint8_t v);
uint16_t parse_hex4(uint8_t **pp);
uint8_t parse_hex2(uint8_t **pp);
void skip_sp(uint8_t **pp);

/* ── Current filename (set by l/w, shown in editor status) ── */
#define FILENAME_MAX_LEN 16
extern char cur_filename[FILENAME_MAX_LEN + 1];

/* ── CPU mode ─────────────────────────────────────────── */
extern uint8_t al_cpu;          /* ZP variable from asm_vars.s */
#pragma zpsym("al_cpu")
#ifndef CPU_CEIL
#define CPU_CEIL 1              /* fallback: 6510 */
#endif

/* ── Assembler bridge ───────────────────────────────────── */
extern uint8_t asm_line(uint16_t addr, char *text);
extern void jsr_addr(uint16_t addr);
extern uint8_t reg_a, reg_x, reg_y, reg_sp, reg_p;

/* ── Debugger (debugger.s) ─────────────────────────────── */
extern void dbg_init(void);
extern uint8_t __fastcall__ dbg_bp_set(uint16_t addr);   /* slot (0-7) or $FF */
extern uint8_t __fastcall__ dbg_bp_del(uint8_t slot);     /* 0=ok, $FF=bad */
extern void dbg_bp_clear(void);
extern uint8_t dbg_bp_count(void);
extern void dbg_bp_patch(void);
extern void dbg_bp_unpatch(void);
extern uint8_t __fastcall__ dbg_bp_find(uint16_t addr);   /* slot or $FF */
extern uint8_t bp_table[];                                 /* 8×4 bytes */
extern void dbg_enter(void);    /* enter user code; returns on BRK/NMI */
extern uint8_t dbg_running;     /* $80 = user code active */
extern uint8_t dbg_reason;      /* 0=none, 1=BRK, 2=NMI */
extern uint16_t brk_pc;         /* break address / resume target */
extern uint8_t dbg_bp_hit;      /* slot# of hit bp ($FF=none) */
extern uint8_t dbg_has_ctx;     /* $80 = user context valid in $E200 */

#endif
