/* asm_src.h — Source assembler (2-pass assembly of gap buffer)
 *
 * Reads source from the editor's gap buffer, resolves labels via symtab,
 * evaluates expressions via expr, emits machine code via asm_line. */
#ifndef ASM_SRC_H
#define ASM_SRC_H

#include <stdint.h>

/* Assemble the current source buffer contents.
 * Pass 1: scan source, record labels, compute sizes.
 * Pass 2: resolve forward references, emit bytes.
 * Returns 0 on success, error count otherwise. */
uint16_t asm_assemble(void);

/* Origin address set by *= directive (default $0800) */
extern uint16_t asm_org;

/* Number of bytes emitted in last assembly */
extern uint16_t asm_size;

/* Number of errors in last assembly */
extern uint16_t asm_errors;

#endif
