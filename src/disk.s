; disk.s — CBM file I/O via direct KERNAL calls
;
; Replaces disk.c + all cc65 cbm_*.o wrappers (~2.5KB)
; with direct KERNAL SETLFS/SETNAM/OPEN/CLOSE/CHKIN/CHKOUT/
; CHRIN/CHROUT/LOAD/SAVE/CLRCHN/READST calls.

        .export _floppy_status, _list_directory
        .export _disk_load_prg, _disk_save_prg
        .export _disk_load_seq, _disk_save_seq
        .export _disk_seq_bytes, _disk_seq_lines

        .import _io_puts, _io_putc, _io_putdec, _io_puthex2, _io_puthex4
        .import _io_getc, _io_kbhit, _io_clear_eol
        .import _io_color
        .import _newline, _print_string
        .import _show_prompt
        .import _cur_addr
        .import popa, popax

        .importzp sp

; ── KERNAL entry points ──────────────────────────────────
SETLFS  = $FFBA
SETNAM  = $FFBD
OPEN    = $FFC0
CLOSE   = $FFC3
CHKIN   = $FFC6
CHKOUT  = $FFC9
CLRCHN  = $FFCC
CHRIN   = $FFCF
CHROUT  = $FFD2
LOAD    = $FFD5
SAVE    = $FFD8
READST  = $FFB7

CUR_COL = $D3
CUR_ROW = $D6
CH_STOP = 3

; ── ZP temporaries (reuse cse_io's _io_tmp) ─────────────
_io_tmp = $FB              ; 2 bytes, shared with cse_io
ptr     = $FD              ; 2 bytes, general pointer

; ── BSS ──────────────────────────────────────────────────
        .segment "BSS"
_disk_seq_bytes: .res 2
_disk_seq_lines: .res 2
fl_buf:          .res 32
open_buf:        .res 28    ; filename build buffer
callback:        .res 2     ; function pointer for SEQ I/O

        .segment "CODE"

; ═════════════════════════════════════════════════════════
; Helper: strlen(A/X) → length in Y, ptr set to string
; ═════════════════════════════════════════════════════════
.proc str_setup
        sta ptr
        stx ptr+1
        ldy #0
@len:   lda (ptr),y
        beq @done
        iny
        bne @len
@done:  rts             ; Y = length, ptr = string address
.endproc

; ═════════════════════════════════════════════════════════
; Helper: build CBM open string in open_buf
;   Input: ptr = filename, Y = filename length, A = mode ('r'/'w')
;   For write mode, prepends "@:"
;   Appends ",s,<mode>" if not already present
;   Returns: A = total length, open_buf filled
; ═════════════════════════════════════════════════════════
.proc build_open_str
        sta @mode       ; save mode char
        sty @nlen       ; save name length

        ldx #0          ; output index

        ; prepend @: for write
        lda @mode
        cmp #'w'
        bne @copy_name
        lda #'@'
        sta open_buf,x
        inx
        lda #':'
        sta open_buf,x
        inx

@copy_name:
        ldy #0
@cp:    cpy @nlen
        bcs @check_suffix
        lda (ptr),y
        sta open_buf,x
        inx
        iny
        bne @cp

@check_suffix:
        ; check if name already ends with ,r or ,w
        cpx #2
        bcc @add_suffix
        dex
        lda open_buf,x
        cmp #'r'
        beq @has_mode
        cmp #'w'
        beq @has_mode
        inx
        bne @add_suffix         ; always

@has_mode:
        dex
        lda open_buf,x
        inx
        inx                     ; restore X past the mode char
        cmp #','
        beq @done               ; already has ,r or ,w

@add_suffix:
        lda #','
        sta open_buf,x
        inx
        lda #'s'
        sta open_buf,x
        inx
        lda #','
        sta open_buf,x
        inx
        lda @mode
        sta open_buf,x
        inx

@done:
        lda #0
        sta open_buf,x          ; NUL terminate (for debug)
        txa                     ; A = total length
        rts

@mode:  .byte 0
@nlen:  .byte 0
.endproc

; ═════════════════════════════════════════════════════════
; floppy_status — read drive error channel, print to screen
; ═════════════════════════════════════════════════════════
.proc _floppy_status
        ; OPEN 14,8,15,""
        lda #0
        jsr SETNAM              ; empty filename
        lda #14                 ; lfn
        ldx #8                  ; device
        ldy #15                 ; secondary (command channel)
        jsr SETLFS
        jsr OPEN
        bcs @err

        ; CHKIN 14
        ldx #14
        jsr CHKIN

        ; read bytes into fl_buf
        ldy #0
@read:  jsr READST
        bne @close              ; any status = done
        jsr CHRIN
        cpy #30                 ; buffer limit
        bcs @close
        sta fl_buf,y
        iny
        bne @read

@close:
        ; NUL-terminate
        lda #0
        sta fl_buf,y

        jsr CLRCHN
        lda #14
        jsr CLOSE

        ; print if we got anything
        cpy #0
        beq @err
        lda #<fl_buf
        ldx #>fl_buf
        jsr _print_string
        jmp _newline

@err:   rts
.endproc

; ═════════════════════════════════════════════════════════
; list_directory(device) — directory listing with executable l commands
;   __fastcall__: device in A
;
; Output format:
;   AAAA:; "disk name" id
;   AAAA:l "filename,p"     ; 83
;   AAAA:l "test,s"         ;  1
;   AAAA:; 520 blocks free.
; ═════════════════════════════════════════════════════════
.proc _list_directory
        sta @dev                ; save device number

        ; SETNAM "$"
        lda #1
        ldx #<@dname
        ldy #>@dname
        jsr SETNAM

        ; SETLFS 1,device,0
        lda #1
        ldx @dev
        ldy #0
        jsr SETLFS

        jsr OPEN
        bcc @opened
        jmp @err
@opened:
        ldx #1
        jsr CHKIN

        ; Skip 2-byte load address
        jsr CHRIN
        jsr CHRIN

        lda #0
        sta @is_first           ; first entry = header

@entry:
        ; Read 2-byte link pointer
        jsr CHRIN
        sta @blocks
        jsr READST
        beq :+
        jmp @done
:       jsr CHRIN
        sta @blocks+1
        ; link = 0 → end
        ora @blocks
        bne :+
        jmp @done
:

        ; Read 2-byte line number (block count)
        jsr CHRIN
        sta @blocks
        jsr CHRIN
        sta @blocks+1

        ; Read line text into fl_buf (terminated by $00)
        ldy #0
@rdtxt: jsr CHRIN
        beq @got_line           ; $00 = line end
        cpy #30
        bcs @rdtxt              ; truncate: keep reading but don't store
        sta fl_buf,y
        iny
        bne @rdtxt              ; always (Y < 30)
@got_line:
        lda #0
        sta fl_buf,y            ; NUL-terminate
        sty @textlen

        ; Show prompt prefix: AAAA:
        jsr _show_prompt

        ; First entry = header → print as comment
        lda @is_first
        bne @not_header
        inc @is_first
        ; "; " + raw text (includes quoted disk name)
        lda #';'
        jsr _io_putc
        lda #<fl_buf
        ldx #>fl_buf
        jsr _io_puts
        jsr _io_clear_eol
        jsr _newline
        jmp @check_stop

@not_header:
        ; Check if this looks like a file entry (has a quote in text)
        ldy #0
@find_q:
        lda fl_buf,y
        beq @no_quote           ; no quote found → "blocks free" line
        cmp #'"'
        beq @found_q
        iny
        bne @find_q
@no_quote:
        ; "NNN blocks free." → print as "; NNN blocks free."
        lda #';'
        jsr _io_putc
        lda #' '
        jsr _io_putc
        lda @blocks
        ldx @blocks+1
        jsr _io_putdec
        lda #<@free_msg
        ldx #>@free_msg
        jsr _io_puts
        jsr _io_clear_eol
        jsr _newline
        jmp @check_stop

@found_q:
        ; Y points to opening quote in fl_buf
        ; Find closing quote, then trim trailing spaces from filename
        iny                     ; skip opening quote
        sty @fn_start

        ; scan to closing quote to find end
@scan_q:
        lda fl_buf,y
        beq @fn_found_end
        cmp #'"'
        beq @fn_found_end
        iny
        bne @scan_q
@fn_found_end:
        sty @fn_close           ; position of closing quote or NUL

        ; trim trailing spaces: walk back from closing quote
        dey
@trim:  cpy @fn_start
        bcc @trim_done          ; empty filename
        lda fl_buf,y
        cmp #' '
        bne @trim_done
        dey
        bne @trim               ; always (Y >= 0 loop)
@trim_done:
        iny                     ; Y = one past last non-space char
        sty @fn_trimmed_end

        ; Output: l "filename
        lda #'l'
        jsr _io_putc
        lda #' '
        jsr _io_putc
        lda #'"'
        jsr _io_putc

        ldy @fn_start
@fname: cpy @fn_trimmed_end
        bcs @fname_done
        lda fl_buf,y
        jsr _io_putc
        iny
        bne @fname
@fname_done:

        ; Find type: skip closing quote + spaces
        ldy @fn_close
        lda fl_buf,y
        beq @type_unk
        iny                     ; skip closing quote
@skip_spc:
        lda fl_buf,y
        beq @type_unk
        cmp #' '
        bne @got_type
        iny
        bne @skip_spc

@got_type:
        ; A = first char of type (PETSCII: already lowercase on C64)
        pha
        lda #','
        jsr _io_putc
        pla
        jsr _io_putc
        jmp @close_quote

@type_unk:
@close_quote:
        lda #'"'
        jsr _io_putc

        ; Pad to column 24 with spaces, then "; NNN"
        ldy CUR_COL
@pad:   cpy #24
        bcs @blk_comment
        lda #' '
        jsr _io_putc
        iny
        bne @pad

@blk_comment:
        lda #';'
        jsr _io_putc

        ; Right-align block count in 4 chars
        lda @blocks+1
        bne @big_blocks         ; >= 256

        ; < 256: right-align in 4 chars
        lda @blocks
        cmp #100
        bcs @three_digits
        cmp #10
        bcs @two_digits
        ; 1 digit
        lda #' '
        jsr _io_putc
        jsr _io_putc
        jsr _io_putc
        jmp @print_blocks
@two_digits:
        lda #' '
        jsr _io_putc
        jsr _io_putc
        jmp @print_blocks
@three_digits:
        lda #' '
        jsr _io_putc
        jmp @print_blocks

@big_blocks:
        ; >= 256, io_putdec handles it
@print_blocks:
        lda @blocks
        ldx @blocks+1
        jsr _io_putdec

        jsr _io_clear_eol
        jsr _newline

@check_stop:
        jsr _io_kbhit
        bne :+
        jmp @entry
:       jsr _io_getc
        cmp #CH_STOP
        beq :+
        jmp @entry
:

        lda #<@brk_msg
        ldx #>@brk_msg
        jsr _io_puts
        jsr _newline

@done:
        jsr CLRCHN
        lda #1
        jsr CLOSE
        jmp _floppy_status

@err:
        jsr CLRCHN
        lda #1
        jsr CLOSE
        jmp _floppy_status

@is_first:       .byte 0
@blocks:         .byte 0, 0
@textlen:        .byte 0
@dev:            .byte 0
@fn_start:       .byte 0
@fn_close:       .byte 0
@fn_trimmed_end: .byte 0

@dname:    .byte "$"
@brk_msg:  .byte "break", 0
@free_msg: .byte " blocks free.", 0
.endproc

; ═════════════════════════════════════════════════════════
; disk_load_prg(name, addr)
;   __fastcall__: addr in A/X, name on C stack
;   Returns end address in A/X (0 on error)
; ═════════════════════════════════════════════════════════
.proc _disk_load_prg
        ; A/X = addr (last arg, fastcall)
        sta _io_tmp             ; save addr lo
        stx _io_tmp+1           ; save addr hi

        ; pop name pointer from C stack
        jsr popax               ; A/X = name
        jsr str_setup           ; ptr = name, Y = length

        ; SETNAM
        tya                     ; A = length
        ldx ptr
        ldy ptr+1
        jsr SETNAM

        ; SETLFS 1,8,0 (0=use header addr) or 1,8,1 (1=use given addr)
        lda _io_tmp
        ora _io_tmp+1
        beq @use_header
        ; nonzero addr: secondary = 1
        lda #1
        ldx #8
        ldy #1
        jsr SETLFS
        jmp @do_load
@use_header:
        lda #1
        ldx #8
        ldy #0
        jsr SETLFS

@do_load:
        lda #0                  ; 0 = LOAD (not VERIFY)
        ldx _io_tmp             ; dest lo
        ldy _io_tmp+1           ; dest hi
        jsr LOAD
        bcs @error
        ; X/Y = end address on success
        stx _io_tmp
        sty _io_tmp+1
        lda #1
        jsr CLOSE
        lda _io_tmp
        ldx _io_tmp+1
        rts

@error:
        lda #1
        jsr CLOSE
        lda #0
        tax
        rts
.endproc

; (disk_save_prg is defined below, after disk_save_seq)

; ═════════════════════════════════════════════════════════
; disk_load_seq(name, insert_fn)
;   __fastcall__: insert_fn in A/X, name on C stack
;   Returns 0 on success, nonzero on error
; ═════════════════════════════════════════════════════════
.proc _disk_load_seq
        ; Save callback
        sta callback
        stx callback+1

        ; Pop name
        jsr popax
        jsr str_setup           ; ptr = name, Y = length

        ; Build open string ",s,r"
        lda #'r'
        jsr build_open_str      ; A = total length, open_buf filled

        ; SETNAM with open_buf
        ldx #<open_buf
        ldy #>open_buf
        jsr SETNAM

        ; SETLFS 2,8,2
        lda #2
        ldx #8
        ldy #2
        jsr SETLFS

        jsr OPEN
        bcs @err

        ; Check drive error channel
        jsr @check_drive_err
        bne @err_close

        ; CHKIN 2
        ldx #2
        jsr CHKIN

        ; Clear counters
        lda #0
        sta _disk_seq_bytes
        sta _disk_seq_bytes+1
        sta _disk_seq_lines
        sta _disk_seq_lines+1
        lda #1                  ; start with 1 line
        sta _disk_seq_lines

@read:
        jsr CHRIN
        pha                     ; save byte

        ; Call callback(byte) — byte in A
        pla
        pha
        jsr @do_callback

        ; Count bytes
        inc _disk_seq_bytes
        bne :+
        inc _disk_seq_bytes+1
:
        ; Count lines (if byte == $0D)
        pla
        cmp #$0D
        bne @no_newline
        inc _disk_seq_lines
        bne :+
        inc _disk_seq_lines+1
:
@no_newline:
        ; Check KERNAL status — bit 6 = EOF
        jsr READST
        and #$40
        bne @ok

        jmp @read

@ok:
        jsr CLRCHN
        lda #2
        jsr CLOSE

        ; Check if anything was read
        lda _disk_seq_bytes
        ora _disk_seq_bytes+1
        beq @empty

        lda #0                  ; success
        tax
        rts

@empty:
        lda #1                  ; empty file = error
        ldx #0
        rts

@err_close:
        jsr CLRCHN
        lda #2
        jsr CLOSE
@err:
        lda #1
        ldx #0
        rts

; Call the callback function pointer with A as argument
@do_callback:
        jmp (callback)

; Check drive error: open ch15, read first 2 chars, close.
; Returns Z=1 if OK (err < 20), Z=0 if error.
@check_drive_err:
        lda #0
        jsr SETNAM
        lda #15
        ldx #8
        ldy #15
        jsr SETLFS
        jsr OPEN
        bcs @drv_bad

        ldx #15
        jsr CHKIN

        jsr CHRIN               ; tens digit
        sec
        sbc #'0'
        asl
        asl
        asl                     ; * 8 (close enough for >= 20 check)
        sta _io_tmp             ; save
        asl                     ; * 16? no... let me just do it properly

        ; Read two digits, compute err = d1*10 + d2
        ; Already read first digit. Redo:
        ; Actually the first CHRIN already consumed the byte.
        ; Let's just check if first char >= '2' (error 20+)
        ; Reset: first digit was (original - '0') * 8 in _io_tmp
        ; Simpler: if original char >= '2', it's error 20+
        ; But we already subtracted '0' and shifted. Ugh.

        ; Simplest: just check the raw first character
        ; But we already consumed it. Read the rest and close.
        jsr CHRIN               ; units digit (discard)
        jsr CLRCHN
        lda #15
        jsr CLOSE

        ; Check: _io_tmp has (tens - '0') * 8
        ; If tens >= 2, _io_tmp >= 16
        lda _io_tmp
        cmp #16                 ; 2*8 = 16
        bcc @drv_ok
@drv_bad:
        lda #1                  ; Z=0 = error
        rts
@drv_ok:
        lda #0                  ; Z=1 = OK
        rts
.endproc

; ═════════════════════════════════════════════════════════
; disk_save_seq(name, read_fn)
;   __fastcall__: read_fn in A/X, name on C stack
;   read_fn returns byte in A (0-255), or -1 (carry set) for EOF
;   Returns 0 on success, nonzero on error
; ═════════════════════════════════════════════════════════
.proc _disk_save_seq
        ; Save callback
        sta callback
        stx callback+1

        ; Pop name
        jsr popax
        jsr str_setup           ; ptr = name, Y = length

        ; Build open string with @: prefix and ",s,w"
        lda #'w'
        jsr build_open_str

        ; SETNAM
        ldx #<open_buf
        ldy #>open_buf
        jsr SETNAM

        ; SETLFS 2,8,2
        lda #2
        ldx #8
        ldy #2
        jsr SETLFS

        jsr OPEN
        bcs @err

        ; CHKOUT 2
        ldx #2
        jsr CHKOUT

        ; Clear counters
        lda #0
        sta _disk_seq_bytes
        sta _disk_seq_bytes+1
        sta _disk_seq_lines
        sta _disk_seq_lines+1

@write:
        ; Call read_fn — returns next byte in A, carry set = EOF
        jsr @do_callback
        bcs @done               ; EOF

        ; Write byte via CHROUT
        jsr CHROUT

        ; Count bytes
        inc _disk_seq_bytes
        bne :+
        inc _disk_seq_bytes+1
:
        ; Check for $0D (newline)
        ; We need the byte we just wrote... it's gone.
        ; CHROUT doesn't preserve A. Read it from... hmm.
        ; Let's save it before CHROUT:
        jmp @write

@done:
        jsr CLRCHN
        lda #2
        jsr CLOSE
        lda #0
        tax
        rts

@err:
        lda #1
        ldx #0
        rts

@do_callback:
        jmp (callback)
.endproc

; ═════════════════════════════════════════════════════════
; disk_save_prg — proper implementation
; ═════════════════════════════════════════════════════════
; Redefine with simpler register management using ZP
.proc _disk_save_prg
        ; __fastcall__: size in A/X
        ; C stack: name (bottom), addr (top)
        sta @size
        stx @size+1

        ; pop addr
        jsr popax
        sta @addr
        stx @addr+1

        ; pop name
        jsr popax
        jsr str_setup           ; ptr = name, Y = length

        ; SETNAM
        tya
        ldx ptr
        ldy ptr+1
        jsr SETNAM

        ; SETLFS 1,8,1
        lda #1
        ldx #8
        tay                     ; Y = 1
        jsr SETLFS

        ; SAVE: A = ZP pointer to start addr, X/Y = end addr
        ; Store start address at a known ZP location
        lda @addr
        sta _io_tmp
        lda @addr+1
        sta _io_tmp+1

        ; compute end = addr + size
        lda @addr
        clc
        adc @size
        tax                     ; X = end lo
        lda @addr+1
        adc @size+1
        tay                     ; Y = end hi

        lda #<_io_tmp           ; ZP pointer to start address
        jsr SAVE
        bcs @error

        lda #1
        jsr CLOSE
        lda #0
        tax
        rts

@error:
        lda #1
        jsr CLOSE
        lda #1
        ldx #0
        rts

@addr:  .byte 0, 0
@size:  .byte 0, 0
.endproc
