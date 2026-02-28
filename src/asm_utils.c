#include <stdint.h>

/* Packed legality for opcodes 0x00..0x7F only.
   Byte i covers (i*8 .. i*8+7). Bit k (LSB=bit0) covers opcode (i*8+k). */
static const uint8_t t_6510_legal_packed_128[16] = {
    0x63, 0x67, 0x63, 0x63, 0x63, 0x63, 0x63, 0x63,
    0x65, 0x67, 0xF7, 0xF7, 0x67, 0xE7, 0x67, 0xE7
};

/* C accessor (cc65) */
uint8_t __fastcall__ is_legal_opcode(uint8_t op)
{
    op &= 0x7F;                    /* fold 0x80..0xFF onto 0x00..0x7F */
    return (t_6510_legal_packed_128[op >> 3] >> (op & 7)) & 1;
}

