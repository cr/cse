/* asm_src.c — Source assembler (stub)
 *
 * Placeholder.  Will implement 2-pass assembly once the editor,
 * expression parser, and symbol table are complete. */

#include <stdint.h>
#include "asm_src.h"

uint16_t asm_org    = 0x0800;
uint16_t asm_size   = 0;
uint16_t asm_errors = 0;

uint16_t asm_assemble(void) {
    asm_errors = 0;
    asm_size   = 0;
    /* stub: nothing to assemble yet */
    return 0;
}
