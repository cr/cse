/* screen.h — Screen management (scroll, newline, cursor, color) */
#ifndef SCREEN_H
#define SCREEN_H

#include <stdint.h>

/* Color theme */
extern uint8_t theme_border;
extern uint8_t theme_bg;
extern uint8_t theme_fg;

void restore_colors(void);          /* apply theme + fill color RAM */
void reset_screen(void);            /* clear screen + restore colors */

/* Screen output */
void scroll_up(uint8_t n);          /* scroll screen + color RAM up by n rows */
void newline(void);                 /* advance to next row, scroll if needed */
void print_string(const uint8_t *str); /* scroll-aware string output */

/* Cursor show/hide (XOR $80 at cursor position) */
void cursor_show(void);
void cursor_hide(void);

#endif
