/* symtab.h — Symbol table (label ↔ address mapping)
 *
 * Hash table with linear probing. Strings in a separate pool.
 * Hash function: same 7-bit hash family as mn7_classify.
 *
 * Designed for easy 6502 asm replacement. */
#ifndef SYMTAB_H
#define SYMTAB_H

#include <stdint.h>

/* Define or update a symbol.  Returns 0 on success, 1 if table full. */
uint8_t sym_define(const char *name, uint16_t value);

/* Look up a symbol.  Returns 0 if found (value stored in *result),
 * 1 if not found. */
uint8_t sym_lookup(const char *name, uint16_t *result);

/* Delete all symbols. */
void sym_clear(void);

/* Number of defined symbols. */
uint16_t sym_count(void);

#endif
