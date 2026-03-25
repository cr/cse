/* symtab.c — Symbol table (stub)
 *
 * Placeholder implementation.  Currently stores nothing.
 * Will be replaced with a hash table once the source assembler needs it. */

#include <stdint.h>
#include "symtab.h"

uint8_t sym_define(const char *name, uint16_t value) {
    (void)name; (void)value;
    return 1;  /* table full (stub) */
}

uint8_t sym_lookup(const char *name, uint16_t *result) {
    (void)name; (void)result;
    return 1;  /* not found (stub) */
}

void sym_clear(void) { }

uint16_t sym_count(void) { return 0; }
