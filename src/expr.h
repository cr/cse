/* expr.h — Expression parser/evaluator
 *
 * Parses: $hex, %binary, decimal, labels, +, -, *, /, <, >, ()
 * All intermediate and return values are 16-bit unsigned.
 *
 * Designed for easy 6502 asm replacement: recursive descent maps
 * naturally to JSR/RTS. */
#ifndef EXPR_H
#define EXPR_H

#include <stdint.h>

/* Evaluate expression string starting at *pp.
 * Advances *pp past the consumed input.
 * Returns 0 on success, nonzero on error.
 * Result stored in *result. */
uint8_t expr_eval(uint8_t **pp, uint16_t *result);

/* Human-readable error from the last failed expr_eval */
const char *expr_error_str(void);

#endif
