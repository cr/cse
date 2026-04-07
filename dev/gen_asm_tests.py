#!/usr/bin/env python3
"""
gen_asm_tests.py — Generate assembler smoke-test and self-check SEQ files
for the CSE test D64 image.

Reads instruction_set.py as the authoritative source.  Writes PETSCII SEQ
files to build/ and optionally updates dev/test.d64 via c1541.

Usage:
    python3 dev/gen_asm_tests.py           # generate files only
    python3 dev/gen_asm_tests.py --disk    # also write to dev/test.d64
"""

import sys, os, pathlib, subprocess, shutil

# ── Add dev/ to path so we can import instruction_set ──
DEV = pathlib.Path(__file__).parent
ROOT = DEV.parent
sys.path.insert(0, str(DEV))

import instruction_set as iset

BUILD = ROOT / "build"
BUILD.mkdir(exist_ok=True)
D64 = DEV / "test.d64"

# PETSCII carriage return
CR = b'\x0d'

# ── Mode → example operand (PETSCII lowercase) ──
# Uses fixed addresses so branches stay in range.
# REL and ZPREL use forward .here: label.
MODE_OPERAND = {
    'IMP':   '',
    'ACC':   'a',
    'IMM':   '#$42',
    'ZP':    '$80',
    'ZPX':   '$80,x',
    'ZPY':   '$80,y',
    'ABS':   '$2000',
    'ABX':   '$2000,x',
    'ABY':   '$2000,y',
    'IND':   '($2000)',
    'INX':   '($80,x)',
    'INY':   '($80),y',
    'REL':   '.here',
    'ZPI':   '($80)',
    'AIX':   '($2000,x)',
    'ZPREL': '$80,.here',
}

# Canonical mode display order
MODE_ORDER = ['IMP', 'ACC', 'REL', 'IMM', 'ZP', 'ZPX', 'ZPY',
              'ABS', 'ABX', 'ABY', 'IND', 'INX', 'INY', 'ZPI', 'AIX', 'ZPREL']

# ── Helpers ──

def petscii(s):
    """Convert ASCII string to PETSCII bytes (C64 lowercase/unshifted mode).
    ASCII a-z ($61-$7A) → PETSCII $41-$5A (lowercase letters).
    ASCII A-Z ($41-$5A) → PETSCII $C1-$DA (uppercase/shifted letters).
    Other printable ASCII unchanged."""
    out = bytearray()
    for ch in s:
        c = ord(ch)
        if 0x61 <= c <= 0x7A:       # a-z → PETSCII lowercase
            out.append(c - 0x20)     # $41-$5A
        elif 0x41 <= c <= 0x5A:      # A-Z → PETSCII uppercase
            out.append(c + 0x80)     # $C1-$DA
        else:
            out.append(c)
    return bytes(out)


TAB = b'\xa0'  # PETSCII tab (shifted space) — expanded by CSE editor

def seq_lines(lines):
    """Join lines with PETSCII CR, add trailing CR.
    Leading '  ' (2 spaces) is replaced with a single TAB for indentation."""
    result = bytearray()
    for i, l in enumerate(lines):
        if i > 0:
            result.extend(CR)
        # Convert leading 2-space indent to tab
        if l.startswith('  ') and not l.startswith('   '):
            result.extend(TAB)
            result.extend(petscii(l[2:]))
        else:
            result.extend(petscii(l))
    result.extend(CR)
    return bytes(result)


def write_seq(name, lines):
    """Write a SEQ file to build/."""
    path = BUILD / name
    path.write_bytes(seq_lines(lines))
    print(f"  {path.name}: {len(lines)} lines")
    return path


def get_modes(mne, force_nmos=False):
    """Return the set of valid modes for a mnemonic.
    If force_nmos=True, use the NMOS profile even if cmos_bit is set."""
    profile, cmos_bit, _ = iset.MNEMONICS[mne]
    if force_nmos:
        cmos_bit = False
    return iset.mne_modes(profile, cmos_bit)


def sorted_mnes(category):
    """Return mnemonics for a category, sorted alphabetically."""
    return sorted(m for m, (_, _, cat) in iset.MNEMONICS.items()
                  if cat == category)


def is_bit_operand(mne):
    """True if mnemonic takes a leading digit (RMB/SMB/BBR/BBS)."""
    profile, _, _ = iset.MNEMONICS[mne]
    return profile in (3, 4)


def is_crash(mne):
    """True if mnemonic halts the CPU."""
    return mne in ('CIM', 'HLT', 'JAM', 'KIL')


# ── Smoke test generators ──

def gen_smoke_lines(mnes, cpu_directive=None, skip_crash=True,
                    force_nmos=False):
    """Generate smoke test source lines for a list of mnemonics."""
    lines = []
    if cpu_directive:
        lines.append(cpu_directive)
    lines.append('.org $2000')
    lines.append('')

    # Group by mode for readability
    for mode in MODE_ORDER:
        group = []
        for mne in mnes:
            modes = get_modes(mne, force_nmos=force_nmos)
            if mode not in modes:
                continue
            if skip_crash and is_crash(mne):
                continue
            mne_lower = mne.lower()
            operand = MODE_OPERAND[mode]

            if is_bit_operand(mne):
                # Emit for digit 0 only (representative)
                asm_mne = f"{mne_lower}0"
            else:
                asm_mne = mne_lower

            if mode == 'REL':
                # Need a label target within range
                group.append(f'.here:')
                group.append(f'  {asm_mne} {operand}')
            elif mode == 'ZPREL':
                group.append(f'.here:')
                group.append(f'  {asm_mne} {operand}')
            elif operand:
                group.append(f'  {asm_mne} {operand}')
            else:
                group.append(f'  {asm_mne}')

        if group:
            lines.append(f'; --- {mode} ---')
            lines.extend(group)
            lines.append('')

    return lines


def gen_legal():
    """Generate t-legal smoke test."""
    mnes = sorted_mnes('legal')
    header = [
        '; t-legal: 6502 legal mnemonics',
        '; load with: l "t-legal,s"',
        '; assemble:  a',
        '.cpu 6510',
    ]
    body = gen_smoke_lines(mnes, force_nmos=True)
    return header + body


def gen_cmos():
    """Generate t-cmos smoke test."""
    mnes = sorted_mnes('cmos')
    header = [
        '; t-cmos: 65c02 mnemonics',
        '; load with: l "t-cmos,s"',
        '; assemble:  a',
        '.cpu 65c02',
    ]
    body = gen_smoke_lines(mnes, cpu_directive=None)
    return header + body


def gen_illegal():
    """Generate t-illegal smoke test."""
    mnes = sorted_mnes('illegal')
    header = [
        '; t-illegal: undocumented nmos',
        '; load with: l "t-illegal,s"',
        '; assemble:  a',
        '.cpu 6510',
    ]
    body = gen_smoke_lines(mnes, skip_crash=True, force_nmos=True)
    return header + body


def gen_directives():
    """Generate t-dir directive test."""
    return [
        '; t-dir: directive smoke test',
        '; load with: l "t-dir,s"',
        '; assemble:  a',
        '.cpu 6502',
        '.org $2000',
        '',
        '; --- .const ---',
        '.const max $ff',
        '.const base $2000',
        '',
        '; --- .db ---',
        'data:',
        '  .db $01,$02,$03,$04',
        '  .db $ff,$00,$80,$7f',
        '',
        '; --- .dw ---',
        'words:',
        '  .dw $1234,$abcd',
        '  .dw data,words',
        '',
        '; --- .str ---',
        'greeting:',
        '  .str "hello world"',
        '',
        '; --- .scr ---',
        'screen:',
        '  .scr "hello world"',
        '',
        '; --- .res ---',
        'buffer:',
        '  .res 16',
        '  .res 8,$ff',
        '',
        '; --- .align ---',
        '  .align 16',
        'aligned:',
        '  nop',
        '',
        '; --- .cpu ---',
        '  .cpu 6510',
        '  nop',
        '  .cpu 6502',
        '  nop',
        '',
        '; --- labels + forward ref ---',
        'main:',
        '  jmp skip',
        '  .db $ff,$ff,$ff',
        'skip:',
        '  jsr sub',
        '  rts',
        'sub:',
        '  lda #0',
        '  rts',
        '',
        '; --- local labels ---',
        'loop1:',
        '  ldx #$10',
        '.lp:',
        '  dex',
        '  bne .lp',
        '',
        'loop2:',
        '  ldy #$08',
        '.lp:',
        '  dey',
        '  bne .lp',
        '  rts',
        '',
        '; --- const in expression ---',
        '  lda #max',
        '  sta base',
    ]


def gen_expressions():
    """Generate t-expr expression test."""
    return [
        '; t-expr: expression smoke test',
        '; load with: l "t-expr,s"',
        '; assemble:  a',
        '.cpu 6502',
        '.org $2000',
        '',
        '; --- hex, decimal, binary ---',
        '  lda #$42',
        '  lda #66',
        '  lda #%01000010',
        '',
        '; --- arithmetic ---',
        '  lda #$10+$20',
        '  lda #$80-$40',
        '  lda #$04*$10',
        '  lda #$80/$04',
        '',
        '; --- shifts ---',
        '  lda #$01<<4',
        '  lda #$80>>3',
        '',
        '; --- bitwise ---',
        '  lda #$ff&$0f',
        '  lda #$f0^$ff',
        '',
        '; --- unary ---',
        '  lda #-1',
        '  lda #!$ff',
        '  lda #<$1234',
        '  lda #>$1234',
        '',
        '; --- parenthesized ---',
        '  lda #($10+$20)*2',
        '',
        '; --- * (current pc) ---',
        'here:',
        '  .dw *',
        '  lda #<here',
        '  ldx #>here',
        '',
        '; --- mixed width ---',
        '.const zp $42',
        '.const abs $1234',
        '  lda zp',
        '  lda abs',
        '  lda #<abs',
        '  lda #>abs',
        '  rts',
    ]


def gen_selfcheck():
    """Generate t-chk self-checking test.

    Assembles a block of instructions at $2100, then compares
    emitted bytes against an expected table at $2200.
    """
    # Select a representative subset: one opcode per mode per base mne
    # (avoids aliases, picks first alphabetically)
    test_insns = []  # list of (asm_text, expected_bytes)

    # Legal non-branch, non-implied, non-crash instructions
    done_mnes = set()
    for mne in sorted_mnes('legal'):
        if mne in done_mnes:
            continue
        if is_crash(mne) or is_bit_operand(mne):
            continue
        modes = get_modes(mne, force_nmos=True)
        mne_lower = mne.lower()
        opcodes = iset.OPCODES.get(mne, {})

        for mode in MODE_ORDER:
            if mode not in modes:
                continue
            if mode in ('REL', 'ZPREL'):
                continue  # skip branches (offset depends on position)
            if mode == 'ACC':
                continue  # asm_src expr parser treats 'a' as label
            opc = opcodes.get(mode)
            if opc is None:
                continue

            operand = MODE_OPERAND[mode]
            asm_text = f'{mne_lower} {operand}'.strip()

            # Build expected bytes
            ebytes = [opc]
            op_bytes = iset.MODE_OPERAND_BYTES[mode]
            if mode == 'IMM':
                ebytes.append(0x42)
            elif mode in ('ZP', 'ZPX', 'ZPY', 'INX', 'INY', 'ZPI'):
                ebytes.append(0x80)
            elif mode in ('ABS', 'ABX', 'ABY', 'IND', 'AIX'):
                ebytes.extend([0x00, 0x20])  # $2000 little-endian
            # ACC, IMP: no operand bytes

            test_insns.append((asm_text, ebytes))
        done_mnes.add(mne)

    # Limit to keep program reasonable size
    if len(test_insns) > 128:
        test_insns = test_insns[:128]

    # Build the expected byte table
    all_expected = []
    for _, ebytes in test_insns:
        all_expected.extend(ebytes)
    total = len(all_expected)

    # Split into pages of 256 bytes — each page uses Y-indexed compare
    page_size = 256 if total > 256 else total

    lines = [
        '; t-chk: opcode byte self-check',
        '; load with: l "t-chk,s"',
        '; assemble:  a',
        '; run:       j main',
        '.cpu 6510',
        '.org $2000',
        '',
        f'; {total} bytes to verify',
        'main:',
    ]

    # Simple: compare in chunks up to 256 using Y
    offset = 0
    chunk_id = 0
    remaining = total
    while remaining > 0:
        chunk = min(remaining, 256)
        lines.append(f'  ldy #0')
        lines.append(f'.lp{chunk_id}:')
        lines.append(f'  lda expect+{offset},y')
        lines.append(f'  cmp code+{offset},y')
        lines.append(f'  bne .fail')
        lines.append(f'  iny')
        if chunk < 256:
            lines.append(f'  cpy #{chunk}')
            lines.append(f'  bne .lp{chunk_id}')
        else:
            lines.append(f'  bne .lp{chunk_id}')  # Y wraps at 256
        offset += chunk
        remaining -= chunk
        chunk_id += 1

    lines.extend([
        '  lda #79  ; "o" in petscii',
        '  jsr $ffd2',
        '  lda #75  ; "k"',
        '  jsr $ffd2',
        '  rts',
        '.fail:',
        '  lda #63  ; "?"',
        '  jsr $ffd2',
        '  rts',
        '',
        '; --- assembled code under test ---',
        'code:',
    ])

    for asm_text, _ in test_insns:
        lines.append(f'  {asm_text}')

    lines.append('')
    lines.append('; --- expected bytes ---')
    lines.append('expect:')

    # Emit expected bytes in rows of 8
    for i in range(0, total, 8):
        chunk = all_expected[i:i+8]
        hex_strs = ','.join(f'${b:02x}' for b in chunk)
        lines.append(f'  .db {hex_strs}')

    return lines


def gen_hello():
    """Generate t-hello: classic 'hello world' via KERNAL CHROUT.

    Prints 'hello world' followed by CR, then RTS.  Used as a
    minimal user-code test for the debugger's `g` and `j` commands:
    after running, the screen should show 'hello world' on a fresh
    row below the typed command, with the next prompt below that.
    No prompt corruption, no register dump (clean RTS).
    """
    lines = [
        '; ============================================================',
        ";  t-hello  -  the classic 'hello world'",
        ';',
        ';  prints "hello world" via kernal chrout, then returns',
        ';  cleanly to cse. used as the canonical smoke test for',
        ";  the debugger's g / j commands and for the repl's prompt",
        ';  row handling around user code output.',
        ';',
        ';  load:      l "t-hello,s"',
        ';  assemble:  a',
        ';  run:       g              (or: j main)',
        ';',
        ';  expected display after g:',
        ';      6000:g',
        ';      hello world',
        ';      6000:',
        '; ============================================================',
        '',
        '.cpu 6510',
        '.const chrout $ffd2        ; kernal chrout',
        '.org $6000',
        '',
        '; ---- entry point -------------------------------------------',
        'main:',
        '  ldx #0                   ; x = read index into msg',
        '.lp:',
        '  lda msg,x                ; next char',
        '  beq .done                ; nul terminator?  -> done',
        '  jsr chrout               ; print the char',
        '  inx                      ; advance',
        '  bne .lp                  ; loop (msg short, x never wraps)',
        '.done:',
        '  rts                      ; back to cse',
        '',
        '; ---- message table -----------------------------------------',
        'msg:',
        '  .str "hello world"       ; 11 bytes',
        '  .db $0d                  ; carriage return',
        '  .db $00                  ; nul terminator (end of msg)',
    ]
    return lines


# ── Main ──

def main():
    do_disk = '--disk' in sys.argv

    print("Generating assembler test programs...")

    files = {}
    files['t-legal.seq']   = write_seq('t-legal.seq',   gen_legal())
    files['t-cmos.seq']    = write_seq('t-cmos.seq',    gen_cmos())
    files['t-illegal.seq'] = write_seq('t-illegal.seq', gen_illegal())
    files['t-dir.seq']     = write_seq('t-dir.seq',     gen_directives())
    files['t-expr.seq']    = write_seq('t-expr.seq',    gen_expressions())
    files['t-chk.seq']     = write_seq('t-chk.seq',     gen_selfcheck())
    files['t-hello.seq']   = write_seq('t-hello.seq',   gen_hello())

    if do_disk:
        c1541 = shutil.which('c1541')
        if not c1541:
            # Try common locations
            for p in ['/opt/homebrew/bin/c1541', '/usr/local/bin/c1541']:
                if os.path.exists(p):
                    c1541 = p
                    break
        if not c1541:
            print("ERROR: c1541 not found. Install VICE.")
            sys.exit(1)

        if not D64.exists():
            print(f"ERROR: {D64} not found.")
            sys.exit(1)

        print(f"\nWriting to {D64.name}...")
        for seq_name, seq_path in files.items():
            # CBM filename: strip .seq, use ,s suffix for SEQ type
            cbm_name = seq_name.replace('.seq', ',s')
            # Delete old, write new
            subprocess.run(
                [c1541, '-attach', str(D64), '-delete', cbm_name.replace(',s', '')],
                capture_output=True)
            subprocess.run(
                [c1541, '-attach', str(D64), '-write', str(seq_path), cbm_name],
                check=True, capture_output=True)
            print(f"  {cbm_name}")

        print("Done.")
    else:
        print(f"\nFiles in {BUILD}/. Use --disk to write to {D64.name}.")


if __name__ == '__main__':
    main()
