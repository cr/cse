/* expr.c — Expression parser/evaluator (stub)
 *
 * Currently only handles hex literals ($XXXX, XX, XXXX).
 * Will be extended with: %binary, decimal, labels, operators, parens. */

#include <stdint.h>
#include "cse.h"
#include "expr.h"

static const char *last_error = 0;

uint8_t expr_eval(uint8_t **pp, uint16_t *result) {
    uint8_t *q = *pp;
    uint16_t v = 0;
    uint8_t digits = 0;

    skip_sp(&q);

    /* skip optional '$' prefix */
    if (*q == '$') ++q;

    /* parse hex digits */
    while (is_hex(*q)) {
        v = (v << 4) | hex_val(*q);
        ++q;
        ++digits;
        if (digits > 4) { last_error = "overflow"; return 1; }
    }

    if (digits == 0) {
        last_error = "expected value";
        return 1;
    }

    *pp = q;
    *result = v;
    last_error = 0;
    return 0;
}

static const char empty_str[] = "";

const char *expr_error_str(void) {
    return last_error ? last_error : empty_str;
}
