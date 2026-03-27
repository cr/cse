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

/* Clear editor: reset gap buffer, clear dirty flag, clear filename */
void ed_new(void);

/* ── Gap buffer sequential reader (for source assembler) ── */

/* Reset read pointer to start of source text */
void ed_read_rewind(void);

/* Read next byte from source (transparently skips gap).
 * Returns the byte, or -1 at end of buffer. */
int ed_read_byte(void);

/* Read one line into buf (up to maxlen-1 chars + NUL).
 * Returns line length, or -1 at end of buffer.
 * Advances read pointer past the line + CR. */
int ed_read_line(char *buf, uint8_t maxlen);

/* Insert a PETSCII string into the gap buffer at current position.
 * Use '\r' (0x0D) for line breaks.  For testing: fill source
 * programmatically then call asm_assemble(). */
void ed_insert_string(const char *text);

#endif
