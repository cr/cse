/* expr.h — Expression parser (ZP-based interface)
 *
 * Numeric formats:
 *   $ff      hex (requires $ prefix)
 *   %101     binary (requires % prefix)
 *   42       decimal (bare digits)
 *   label    symbol lookup (starts with letter or dot)
 *   *        current PC (al_pc)
 *
 * Operators:
 *   + - * / << >>    arithmetic (standard precedence)
 *   & £ ^            AND, OR (pound key), XOR (↑ key)
 *   ! < >            NOT, lo byte, hi byte (unary prefix)
 *   ( )              grouping
 *
 * ZP variables (asm_vars.s):
 *   expr_ptr (2B): input pointer (in/out, advanced past consumed)
 *   expr_val (2B): 16-bit result (out, valid on success)
 *   al_pc    (2B): current PC for '*' operator (in)
 *
 * Return code in A:
 *   0 = ZP-eligible, 1 = ABS, 2+ = error
 */
#ifndef EXPR_H
#define EXPR_H

#include <stdint.h>

/* ZP variables — defined in asm_vars.s */
extern uint8_t expr_ptr[];
extern uint16_t expr_val;
#pragma zpsym("expr_ptr")
#pragma zpsym("expr_val")

/* Return / error codes (must match expr.s) */
#define EXPR_RC_ZP       0
#define EXPR_RC_ABS      1
#define EXPR_EXPECTED    2
#define EXPR_OVERFLOW    3
#define EXPR_PAREN       4
#define EXPR_UNDEFINED   5
#define EXPR_DIVZERO     6

/* Evaluate expression at expr_ptr.
 * Returns 0 (ZP) or 1 (ABS) on success, 2+ on error.
 * On success: expr_val = result, expr_ptr advanced. */
uint8_t __fastcall__ expr_eval(void);

/* Error string for last failure */
const char *expr_error_str(void);

#endif
