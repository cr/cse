/* asm_src.h — Two-pass source assembler
 *
 * Reads source from the editor's gap buffer, resolves labels via symtab,
 * evaluates expressions via expr, emits machine code via asm_line.
 *
 * Forward declaration rule: constants (name = expr) must be defined
 * before use.  Labels (code addresses) may be forward-referenced.
 *
 * Directives: .org .db .dw .str .scr .res .align .cpu .bin */
#ifndef ASM_SRC_H
#define ASM_SRC_H

#include <stdint.h>

/* Assemble the current source buffer contents.
 * Pass 1: scan source, record labels, compute sizes.
 * Pass 2: resolve forward references, emit bytes.
 * Returns error count (0 = success). */
uint16_t asm_assemble(void);

/* Origin address set by .org directive (default $0800) */
extern uint16_t asm_org;

/* Number of bytes emitted in last assembly */
extern uint16_t asm_size;

/* Number of errors in last assembly */
extern uint16_t asm_errors;

#endif
