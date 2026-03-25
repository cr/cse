/* editor.h — source editor (gap buffer + screen rendering) */

#ifndef EDITOR_H
#define EDITOR_H

#include <stdint.h>

/* Called from main loop when in ST_EDIT mode */
void __fastcall__ ed_handle_key(uint8_t ch);

/* Mode switching */
void enter_editor(void);
void leave_editor(void);

/* Source I/O — save/load gap buffer as SEQ file.
 * After success, ed_save_bytes/ed_save_lines report stats. */
uint8_t ed_save_source(const char *name);   /* 0=ok, else error */
uint8_t ed_load_source(const char *name);   /* 0=ok, else error */
extern uint16_t ed_save_bytes;
extern uint16_t ed_save_lines;

/* Ensure gap buffer is initialized */
void ed_ensure_init(void);

#endif
