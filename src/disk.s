; disk.s — CBM file I/O via direct KERNAL calls
;
; Direct KERNAL calls for CBM file I/O
; with direct KERNAL SETLFS/SETNAM/OPEN/CLOSE/CHKIN/CHKOUT/
; CHRIN/CHROUT/LOAD/SAVE/CLRCHN/READST calls.

        .macpack longbranch
        .include "macros.inc"

        .export floppy_status, floppy_read_status, fl_buf
        .export list_directory
        .export disk_load_prg, disk_save_prg
        .export disk_load_seq, disk_save_seq
        .export disk_seq_bytes, disk_seq_lines

        .import puts_imm
        .import io_puts, io_putc, io_putdec, io_puthex2, io_puthex4
        .import io_getc, io_kbhit, io_clear_eol
        .import io_color
        .import newline, io_puts, log_info
        .import cur_device
        .import scr_lo, scr_hi
        .importzp disk_ptr
        .import str_dname, str_dir_brk, str_blk_free, str_blk_pre, str_blk_suf

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

; ── ZP temporaries ──────────────────────────────────────
        .importzp _io_tmp       ; shared with cse_io (zp.s)
ptr     = $FD                   ; 2 bytes, local pointer

; ── BSS ──────────────────────────────────────────────────
        .segment "BSS"
disk_seq_bytes: .res 2
disk_seq_lines: .res 2
fl_buf:          .res 32
open_buf:        .res 28    ; filename build buffer
callback:        .res 2     ; function pointer for SEQ I/O
eof_flag:        .res 1     ; READST EOF flag for SEQ read loop

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
        ; Check what the name already ends with:
        ;   ,s → append ,<mode>
        ;   ,r or ,w → already complete, done
        ;   other → append ,s,<mode>
        cpx #2
        bcc @add_full           ; too short to have suffix

        dex                     ; X points to last char
        lda open_buf,x
        dex                     ; X points to second-to-last
        ldy open_buf,x
        inx
        inx                     ; restore X past last char

        ; Check for ,r or ,w (complete open string)
        cpy #','
        bne @check_comma_s
        cmp #'r'
        beq @done
        cmp #'w'
        beq @done

@check_comma_s:
        ; Check for ,s (has type, needs mode)
        cpy #','
        bne @add_full
        cmp #'s'
        bne @add_full
        ; Name ends with ,s → just append ,<mode>
        lda #','
        sta open_buf,x
        inx
        lda @mode
        sta open_buf,x
        inx
        jmp @done

@add_full:
        ; No suffix → append ,s,<mode>
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
; floppy_read_status — read drive error channel into fl_buf
; ═════════════════════════════════════════════════════════
.proc floppy_read_status
        ; OPEN 14,8,15,""
        lda #0
        jsr SETNAM              ; empty filename
        lda #14                 ; lfn
        ldx cur_device
        ldy #15                 ; secondary (command channel)
        jsr SETLFS
        jsr OPEN
        bcs @done

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
        ; Strip trailing CR ($0D) if present
        cpy #0
        beq @term
        dey
        lda fl_buf,y
        cmp #$0D
        beq @term
        iny                     ; undo the dey
@term:
        ; NUL-terminate
        lda #0
        sta fl_buf,y

        jsr CLRCHN
        lda #14
        jmp CLOSE
@done:  rts
.endproc

; floppy_status — read + print on new line via log_info
; ═════════════════════════════════════════════════════════
floppy_status:
        jsr floppy_read_status
        lda #<fl_buf
        ldx #>fl_buf
        jmp log_info

; ═════════════════════════════════════════════════════════
; list_directory(device) — LOAD-based directory listing
;   A = device
;
; Uses KERNAL LOAD to read the directory into workspace at
; $0801, then walks the in-memory buffer to display entries.
; This works on both stock CBM KERNAL and MEGA65 Open-KERNAL
; (Open-KERNAL has multiple IEC channel-I/O bugs that break
; the traditional OPEN+CHKIN+CHRIN approach; see
; MEGA65/open-roms#116, #117).
;
; Clobbers workspace at $0801+ (up to ~5 KB for a full disk).
;
; Output format:
;   AAAA:; "disk name" id
;   AAAA:l "filename,p"     ; 83
;   AAAA:l "test,s"         ;  1
;   AAAA:; 520 blocks free.
; ═════════════════════════════════════════════════════════
.proc list_directory
        sta @dev                ; save device number

        ; SETNAM "$"
        lda #1
        ldx #<str_dname
        ldy #>str_dname
        jsr SETNAM

        ; SETLFS 0,device,0  (SA=0 → load to given address)
        lda #0
        ldx @dev
        ldy #0
        jsr SETLFS

        ; LOAD directory to workspace at $0801 (same as BASIC)
        lda #0                  ; 0 = LOAD (not VERIFY)
        ldx #<$0801
        ldy #>$0801
        jsr LOAD
        jcs @err                ; carry set = error

        ; X/Y = end address after LOAD; save as limit
        stx @end_lo
        sty @end_hi

        ; disk_ptr = walk pointer into loaded data ($0801)
        ; (Using disk_ptr because ptr/$FD is clobbered by screen scroll)
        lda #<$0801
        sta disk_ptr
        lda #>$0801
        sta disk_ptr+1

        ; First 2 bytes are the link pointer of the first line
        ldy #0
        lda (disk_ptr),y        ; link lo
        iny
        ora (disk_ptr),y        ; link hi — if both 0, empty dir
        jeq @done

        ; Advance past link to block count
        lda #2
        jsr @advance_dp

        lda #0
        sta @is_first           ; first entry = header

@entry:
        ; Read 2-byte block count (line number)
        ldy #0
        lda (disk_ptr),y
        sta @blocks
        iny
        lda (disk_ptr),y
        sta @blocks+1
        lda #2
        jsr @advance_dp

        ; Read line text into fl_buf (terminated by $00)
        ldy #0
@rdtxt: lda (disk_ptr),y
        beq @got_line           ; $00 = line end
        cpy #30
        bcs @skip_char          ; truncate: skip but keep scanning
        sta fl_buf,y
@skip_char:
        iny
        bne @rdtxt              ; always
@got_line:
        lda #0
        sta fl_buf,y            ; NUL-terminate
        sty @textlen

        ; Advance disk_ptr past text + NUL byte
        iny                     ; include the $00 terminator
        tya
        jsr @advance_dp

        ; ── Header (first entry) ──────────────────────────────
        lda @is_first
        bne @not_header
        inc @is_first

        ; Print "; " normally, then everything from first " onward inverted.
        ; Filter $12/$92 control chars, convert $A0→$20 (shifted space).
        lda #';'
        jsr io_putc
        lda #' '
        jsr io_putc

        ; Scan to first " in fl_buf
        ldx #0
@hdr_skip_pre:
        lda fl_buf,x
        beq @hdr_done
        cmp #'"'
        beq @hdr_inv
        inx
        bne @hdr_skip_pre

        ; Print from first " to end of text, all inverted
@hdr_inv:
        lda fl_buf,x
        beq @hdr_done
        cmp #$12                ; RVS ON — skip
        beq @hdr_next
        cmp #$92                ; RVS OFF — skip
        beq @hdr_next
        cmp #$A0                ; shifted space → regular space
        bne :+
        lda #' '
:       stx @fn_tmp
        jsr @putc_inv
        ldx @fn_tmp
@hdr_next:
        inx
        bne @hdr_inv

@hdr_done:

        jsr io_clear_eol
        jsr newline
        jmp @check_stop

        ; ── File entry or blocks-free ─────────────────────────
@not_header:
        ; Scan for opening quote to distinguish file from "blocks free"
        ldy #0
@find_q:
        lda fl_buf,y
        beq @no_quote
        cmp #'"'
        beq @found_q
        iny
        bne @find_q

@no_quote:
        ; "blocks free" line — always last entry
        lda #';'
        jsr io_putc
        lda #' '
        jsr io_putc
        lda @blocks
        ldx @blocks+1
        jsr io_putdec
        puts str_blk_free
        jsr io_clear_eol
        jsr newline
        jmp @done

        ; ── File entry: l "name,t"  ; NNN ─────────────────────
@found_q:
        ; Y = opening quote position. Find closing quote, trim spaces.
        iny                     ; skip opening quote
        sty @fn_start
@scan_q:
        lda fl_buf,y
        beq @fn_found_end
        cmp #'"'
        beq @fn_found_end
        iny
        bne @scan_q
@fn_found_end:
        sty @fn_close

        ; Trim trailing spaces from filename
        dey
@trim:  cpy @fn_start
        bcc @trim_done
        lda fl_buf,y
        cmp #' '
        bne @trim_done
        dey
        bne @trim
@trim_done:
        iny
        sty @fn_trimmed_end

        ; Output: l "filename
        lda #'l'
        jsr io_putc
        lda #' '
        jsr io_putc
        lda #'"'
        jsr io_putc

        ldx @fn_start
@fname: cpx @fn_trimmed_end
        bcs @fname_done
        lda fl_buf,x
        stx @fn_tmp
        jsr io_putc
        ldx @fn_tmp
        inx
        bne @fname
@fname_done:

        ; Find type after closing quote
        ldy @fn_close
        lda fl_buf,y
        beq @close_q
        iny
@skip_spc:
        lda fl_buf,y
        beq @close_q
        cmp #' '
        bne @got_type
        iny
        bne @skip_spc

@got_type:
        ; A = first char of type (PETSCII)
        pha
        lda #','
        jsr io_putc
        pla
        jsr io_putc

@close_q:
        lda #'"'
        jsr io_putc

        ; "; N blocks"
        puts str_blk_pre
        lda @blocks
        ldx @blocks+1
        jsr io_putdec
        puts str_blk_suf

        jsr io_clear_eol
        jsr newline

@check_stop:
        jsr io_kbhit
        bne @user_key
        jsr @check_next
        jne @entry
        jmp @done
@user_key:
        jsr io_getc
        cmp #CH_STOP
        beq @user_stop
        jsr @check_next
        jne @entry
        jmp @done
@user_stop:

        puts str_dir_brk
        jsr newline

@done:
@err:
        rts

; Helper: check if next directory entry exists.
; Returns Z=1 if end (no more entries), Z=0 if entry follows.
; If entry follows, disk_ptr is advanced past the link pointer.
@check_next:
        ; Bounds check: disk_ptr >= end → done
        lda disk_ptr+1
        cmp @end_hi
        bcc @cn_ok              ; hi < end_hi → safe
        bne @cn_end             ; hi > end_hi → past end
        lda disk_ptr
        cmp @end_lo
        bcs @cn_end             ; lo >= end_lo → at/past end
@cn_ok:
        ; Read link pointer
        ldy #0
        lda (disk_ptr),y        ; link lo
        iny
        ora (disk_ptr),y        ; link hi
        beq @cn_end             ; link = 0 → end of directory
        ; Valid entry follows — advance past link
        lda #2
        jsr @advance_dp
        lda #1                  ; Z=0 (not done)
        rts
@cn_end:
        lda #0                  ; Z=1 (done)
        rts

; Helper: advance disk_ptr by A bytes
@advance_dp:
        clc
        adc disk_ptr
        sta disk_ptr
        bcc :+
        inc disk_ptr+1
:       rts

; Helper: print char in A inverted (io_putc then OR $80 on screen)
@putc_inv:
        jsr io_putc
        ; flip bit 7 on the char we just wrote (at CUR_COL - 1)
        ldx CUR_ROW
        lda scr_lo,x
        sta _io_tmp
        lda scr_hi,x
        sta _io_tmp+1
        ldy CUR_COL
        dey
        lda (_io_tmp),y
        ora #$80
        sta (_io_tmp),y
        rts

@is_first:       .byte 0
@blocks:         .byte 0, 0
@textlen:        .byte 0
@end_lo:         .byte 0
@end_hi:         .byte 0
@dev:            .byte 0
@fn_start:       .byte 0
@fn_close:       .byte 0
@fn_trimmed_end: .byte 0
@fn_tmp:         .byte 0

.endproc

; ═════════════════════════════════════════════════════════
; disk_load_prg
;   A/X = addr, disk_ptr = name (ZP, set by caller)
;   Returns end address in A/X (0 on error)
; ═════════════════════════════════════════════════════════
.proc disk_load_prg
        sta _io_tmp             ; save addr lo
        stx _io_tmp+1           ; save addr hi

        ; name pointer from disk_ptr (set by caller)
        lda disk_ptr
        ldx disk_ptr+1
        jsr str_setup           ; ptr = name, Y = length

        ; SETNAM
        tya                     ; A = length
        ldx ptr
        ldy ptr+1
        jsr SETNAM

        ; SETLFS 1,dev,SA — SA=0: load to X/Y addr; SA=1: use PRG header
        lda _io_tmp
        ora _io_tmp+1
        beq @use_header
        ; nonzero addr: SA=0 → KERNAL loads to X/Y
        lda #1
        ldx cur_device
        ldy #0
        jsr SETLFS
        jmp @do_load
@use_header:
        ; no addr: SA=1 → KERNAL loads to PRG header address
        lda #1
        ldx cur_device
        ldy #1
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
;   A/X = insert_fn, name on parameter stack
;   Returns 0 on success, nonzero on error
; ═════════════════════════════════════════════════════════
.proc disk_load_seq
        ; Save callback
        sta callback
        stx callback+1

        ; Name from disk_ptr (set by caller)
        lda disk_ptr
        ldx disk_ptr+1
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
        ldx cur_device
        ldy #2
        jsr SETLFS

        jsr OPEN
        bcs @err

        ; CHKIN 2 — no drive error check here; opening channel 15
        ; between OPEN and CHKIN disrupts the serial bus channel.
        ; Errors are caught by READST during the read loop.
        ldx #2
        jsr CHKIN

        ; Clear counters (must explicitly load 0 — A is undefined after CHKIN)
        lda #0
        sta disk_seq_bytes
        sta disk_seq_bytes+1
        sta disk_seq_lines+1
        lda #1                  ; lines starts at 1 (N newlines = N+1 lines)
        sta disk_seq_lines

@read:
        jsr CHRIN
        pha                     ; save byte

        ; Check KERNAL status IMMEDIATELY after CHRIN,
        ; before the callback (which may clobber $90).
        jsr READST
        sta eof_flag            ; save full READST

        ; Call callback(byte)
        pla                     ; byte → A
        pha                     ; keep byte on stack for $0D check
        jsr @do_callback

        ; Count bytes
        inc disk_seq_bytes
        bne :+
        inc disk_seq_bytes+1
:
        ; Count lines (if byte == $0D)
        pla                     ; byte → A
        cmp #$0D
        bne @no_newline
        inc disk_seq_lines
        bne :+
        inc disk_seq_lines+1
:
@no_newline:
        ; EOF check (bit 6)
        lda eof_flag
        and #$40
        beq @read

@ok:
        jsr CLRCHN
        lda #2
        jsr CLOSE

        ; Check for read errors (timeout/device not present).
        ; For non-existent files the drive returns a garbage byte
        ; with READST error bits set — catch that here.
        lda eof_flag
        and #$83                ; bits 0,1,7 = error indicators
        bne @err_status

        ; Check if anything was read
        lda disk_seq_bytes
        ora disk_seq_bytes+1
        beq @empty

        lda #0                  ; success
        tax
        rts

@err_status:
@empty:
        lda #1                  ; error or empty file
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

.endproc

; ═════════════════════════════════════════════════════════
; disk_save_seq(name, read_fn)
;   A/X = read_fn, name on parameter stack
;   read_fn returns byte in A (0-255), or -1 (carry set) for EOF
;   Returns 0 on success, nonzero on error
; ═════════════════════════════════════════════════════════
.proc disk_save_seq
        ; Save callback
        sta callback
        stx callback+1

        ; Name from disk_ptr (set by caller)
        lda disk_ptr
        ldx disk_ptr+1
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
        ldx cur_device
        ldy #2
        jsr SETLFS

        jsr OPEN
        bcs @err

        ; CHKOUT 2
        ldx #2
        jsr CHKOUT

        ; Clear counters (lines starts at 1: N newlines = N+1 lines)
        lda #0
        sta disk_seq_bytes
        sta disk_seq_bytes+1
        sta disk_seq_lines+1
        lda #1
        sta disk_seq_lines

@write:
        ; Call read_fn — returns int: 0-255 = byte (A=lo, X=0),
        ; -1 = EOF (A=$FF, X=$FF).  Check X for hi byte.
        jsr @do_callback
        cpx #$FF
        beq @done               ; EOF: return value was -1

        ; Save byte for line counting
        pha

        ; Write byte via CHROUT
        jsr CHROUT

        ; Count bytes
        inc disk_seq_bytes
        bne :+
        inc disk_seq_bytes+1
:
        ; Count lines (if byte == $0D)
        pla
        cmp #$0D
        bne @write
        inc disk_seq_lines
        bne @write
        inc disk_seq_lines+1
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
; disk_save_prg
;   A/X = size
;   disk_ptr = filename ptr (ZP, set by caller)
;   _io_tmp  = start address (ZP, set by caller)
;   Returns A=0 on success, A=1 on error
; ═════════════════════════════════════════════════════════
.proc disk_save_prg
        ; Save size on 6502 stack
        pha                     ; size lo
        txa
        pha                     ; size hi

        ; addr already in _io_tmp (set by caller)

        ; Name from disk_ptr (set by caller)
        lda disk_ptr
        ldx disk_ptr+1
        jsr str_setup           ; ptr = name, Y = length

        ; SETNAM
        tya
        ldx ptr
        ldy ptr+1
        jsr SETNAM

        ; SETLFS 1,device,1
        lda #1
        ldx cur_device
        tay                     ; Y = 1
        jsr SETLFS

        ; compute end = addr + size
        ; addr is in _io_tmp, size is on 6502 stack
        pla                     ; size hi
        tay                     ; save in Y
        pla                     ; size lo
        clc
        adc _io_tmp
        tax                     ; X = end lo
        tya
        adc _io_tmp+1
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
.endproc
