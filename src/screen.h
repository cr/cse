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
void __fastcall__ scroll_up(uint8_t n);
void newline(void);
void __fastcall__ print_string(const uint8_t *str);

/* Cursor show/hide (XOR $80 at cursor position) */
void cursor_show(void);
void cursor_hide(void);

#endif
