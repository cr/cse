/* cse_io.h — Ultra-lean screen I/O for CSE
 *
 * Replaces cc65 conio.h.  Do NOT include <conio.h> alongside this.
 * Cursor position is KERNAL's own $D3/$D6 — zero-cost gotox/wherex.
 * Call io_sync() after changing io_cy to update line pointers.
 */

#ifndef CSE_IO_H
#define CSE_IO_H

#include <stdint.h>

/* ── Cursor position (KERNAL ZP, read/write directly) ──── */
#define io_cx  (*(volatile uint8_t *)0xD3)   /* column 0-39 */
#define io_cy  (*(volatile uint8_t *)0xD6)   /* row 0-24 */

/* ── Text color for screen clears ──────────────────────── */
extern uint8_t io_color;

/* ── Assembly I/O functions (cse_io.s) ─────────────────── */
void __fastcall__ io_putc(uint8_t ch);
void __fastcall__ io_puts(const char *s);
void __fastcall__ io_puthex4(uint16_t v);
void __fastcall__ io_puthex2(uint8_t v);
void __fastcall__ io_putdec(uint16_t v);
void io_clear_eol(void);
uint8_t io_getc(void);
uint8_t io_kbhit(void);
void io_sync(void);       /* update $D1/$D2/$F3/$F4 from io_cy */

/* ── Inline macros (no function call, no library pull) ─── */
#define io_cursor_on()     (*(uint8_t *)0xCC = 0)
#define io_cursor_off()    (*(uint8_t *)0xCC = 1)
#define io_bordercolor(c)  (*(uint8_t *)0xD020 = (c))
#define io_bgcolor(c)      (*(uint8_t *)0xD021 = (c))

#endif
