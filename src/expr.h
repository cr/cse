/* expr.h — Expression parser (ZP-based interface)
 *
 * Numeric formats:
 *   $ff      hex (requires $ prefix)
 *   %101     binary (requires % prefix)
 *   42       decimal (bare digits)
 *   label    symbol lookup (starts with letter)
 *   *        current PC (al_pc)
 *   <expr    lo byte
 *   >expr    hi byte
 *   (expr)   grouping
 *
 * ZP variables (asm_vars.s):
 *   expr_ptr (2B): input pointer (in/out, advanced past consumed)
 *   expr_val (2B): 16-bit result (out, valid on success)
 *   al_pc    (2B): current PC for '*' operator (in)
 */
#ifndef EXPR_H
#define EXPR_H

#include <stdint.h>

/* ZP variables — defined in asm_vars.s */
extern uint8_t expr_ptr[];
extern uint16_t expr_val;
#pragma zpsym("expr_ptr")
#pragma zpsym("expr_val")

/* Error codes (returned in A by _expr_eval) */
#define EXPR_OK        0
#define EXPR_EXPECTED  1
#define EXPR_OVERFLOW  2
#define EXPR_PAREN     3
#define EXPR_UNDEFINED 4

/* Evaluate expression at expr_ptr.
 * Returns 0 on success (C=0), error code on failure (C=1).
 * On success: expr_val = result, expr_ptr advanced. */
uint8_t __fastcall__ expr_eval(void);

/* Error string for last failure */
const char *expr_error_str(void);

#endif
