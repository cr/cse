#include <stdint.h>

/* opcode bits:
 * A2 A1 A0 = bits 7..5
 * B2 B1 B0 = bits 4..2
 * C1 C0    = bits 1..0
 */

uint8_t __fastcall__ c64_op_len_bool(uint8_t op)
{
    uint8_t A2 = (op >> 7) & 1;
    uint8_t A1 = (op >> 6) & 1;
    uint8_t A0 = (op >> 5) & 1;

    uint8_t B2 = (op >> 4) & 1;
    uint8_t B1 = (op >> 3) & 1;
    uint8_t B0 = (op >> 2) & 1;

    uint8_t C1 = (op >> 1) & 1;
    uint8_t C0 =  op       & 1;

    /* L1 */
    uint8_t L1 =
        B0 |
        C0 |
        (!B1 && (
            (A2 && !B2) ||
            (B2 && !C1) ||
            (A0 && !A1 && !C1)
        ));

    /* L0 */
    uint8_t L0 =
        (B1 && (B0 || B2 || !C0)) ||
        (!C0 && !B0 && ((B2 && C1) || (!A2 && !B2)));

    return (L1 << 1) | L0;
}