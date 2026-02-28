#ifndef OPLEN_BOOL_H
#define OPLEN_BOOL_H

#include <stdint.h>

/* Boolean implementation in C */
uint8_t __fastcall__ c64_op_len_bool(uint8_t opcode);

/* Size-optimized constant-time ASM version */
uint8_t __fastcall__ c64_op_len_bool_asm(uint8_t opcode);

#endif