/* screen.c — Screen management (scroll, newline, cursor, color)
 *
 * All functions are thin wrappers suitable for direct asm replacement.
 * Requires $CC=1 (KERNAL cursor disabled) — enforced by io_init(). */

#include <string.h>
#include <stdint.h>
#include "cse.h"
#include "cse_io.h"
#include "screen.h"

/* ── Color theme defaults ─────────────────────────────────── */
uint8_t theme_border = 12;       /* medium grey */
uint8_t theme_bg     = 11;       /* dark grey */
uint8_t theme_fg     =  5;       /* green */

void restore_colors(void) {
    io_bordercolor(theme_border);
    io_bgcolor(theme_bg);
    io_color = theme_fg;
    memset(COLOR_RAM, io_color, 1000);
}

void reset_screen(void) {
    restore_colors();
    memset(SCREEN, 0x20, 1000);
    io_cx = 0; io_cy = 0; io_sync();
}

void scroll_up(uint8_t n) {
    if (n >= SCREEN_HEIGHT) {
        memset(SCREEN, 0x20, 1000);
        memset(COLOR_RAM, io_color, 1000);
        io_cx = 0; io_cy = 0; io_sync();
    } else {
        __asm__("sei");
        memmove(SCREEN, SCREEN + n * SCREEN_WIDTH,
                SCREEN_WIDTH * (SCREEN_HEIGHT - n));
        memset(SCREEN + SCREEN_WIDTH * (SCREEN_HEIGHT - n),
               0x20, SCREEN_WIDTH * n);
        __asm__("cli");
        memmove(COLOR_RAM, COLOR_RAM + n * SCREEN_WIDTH,
                SCREEN_WIDTH * (SCREEN_HEIGHT - n));
        memset(COLOR_RAM + SCREEN_WIDTH * (SCREEN_HEIGHT - n),
               io_color, SCREEN_WIDTH * n);
        io_cy = (io_cy > n) ? io_cy - n : 0;
        io_sync();
    }
}

void newline(void) {
    if (io_cy == SCREEN_HEIGHT - 1) {
        scroll_up(1);
        io_cy = SCREEN_HEIGHT - 1;
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

/* ── Cursor show/hide ─────────────────────────────────────── */
void cursor_show(void) {
    SCREEN[io_cy * SCREEN_WIDTH + io_cx] ^= 0x80;
}

void cursor_hide(void) {
    SCREEN[io_cy * SCREEN_WIDTH + io_cx] ^= 0x80;
}
