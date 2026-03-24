# cse_io API Contract

## Character Encoding

PETSCII (what C code and keyboard use) and Screen Codes (what VIC-II
displays from $0400) are different encodings.  cse_io converts between
them.  The round-trip MUST be lossless for all characters CSE uses.

### PETSCII → Screen Code (io_putc)

| PETSCII range | Screen code | Conversion | Characters |
|--------------|-------------|------------|------------|
| $20-$3F | $20-$3F | identity | space, 0-9, :;,.!?"#$%&'()*+-/<=>@ |
| $40-$5F | $00-$1F | subtract $40 | @ A-Z [ \ ] ^ _ |
| $60-$7F | $40-$5F | subtract $20 | (lowercase a-z in shifted charset) |
| $C0-$DF | $40-$5F | subtract $80 | (shifted letters = lowercase) |

### Screen Code → PETSCII (read_line)

| Screen code | PETSCII | Conversion |
|-------------|---------|------------|
| $00-$1F | $40-$5F | add $40 |
| $20-$3F | $20-$3F | identity |

Note: screen codes $40-$5F (produced by lowercase input) convert to
$40-$5F which maps back to uppercase PETSCII range.  This means
lowercase letters round-trip as uppercase — acceptable since CSE's
parser is case-insensitive.

### Round-trip guarantee

For any PETSCII char `ch` in the CSE-used range:
```
io_putc(ch)  →  screen code at SCREEN[row*40+col]
read_line()  →  PETSCII in line_buf[]
```

The result `line_buf[col]` must satisfy:
- For $20-$3F (digits, punctuation): exact match
- For $40-$5F (uppercase letters): exact match
- For $60-$7F (lowercase letters): maps to $40-$5F (uppercase)
- For $C0-$DF (shifted letters): maps to $40-$5F (uppercase)

### Critical characters for REPL parsing

| Character | PETSCII | Screen code | Round-trip result |
|-----------|---------|-------------|-------------------|
| '0'-'9' | $30-$39 | $30-$39 | $30-$39 (exact) |
| 'a'-'f' | $41-$46 | $01-$06 | $41-$46 (exact) |
| ':' | $3A | $3A | $3A (exact) |
| '.' | $2E | $2E | $2E (exact) |
| ' ' | $20 | $20 | $20 (exact) |
| 'm' | $4D | $0D | $4D (exact) |
| 'r' | $52 | $12 | $52 (exact) |
| 'd' | $44 | $04 | $44 (exact) |
| '+' | $2B | $2B | $2B (exact) |
| '-' | $2D | $2D | $2D (exact) |
| '"' | $22 | $22 | $22 (exact) |

### io_puthex4 / io_puthex2 output

hex_tab[] screen codes: $30-$39 (digits), $01-$06 (a-f).
These round-trip correctly through read_line:
- $30-$39 → $30-$39 (identity, digits)
- $01-$06 → $41-$46 (add $40, lowercase a-f)

### io_putdec output

Uses hex_tab[0..9] = $30-$39.  Round-trips as digits.  Correct.
