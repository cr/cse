/* disk.c — CBM file I/O (floppy status, directory, load/save)
 *
 * Callback-based SEQ I/O keeps disk.c independent of editor.c.
 * After every operation, the drive error channel is read automatically. */

#include <cbm.h>
#include <string.h>
#include <stdint.h>
#include "cse.h"
#include "cse_io.h"
#include "screen.h"
#include "disk.h"

uint16_t disk_seq_bytes;
uint16_t disk_seq_lines;

/* ── Internal: open string builder ────────────────────────── */

#define OPEN_BUF_LEN 28
static char open_buf[OPEN_BUF_LEN];

/* Build CBM open string: prepend @: for writes, append ,s,r or ,s,w */
static const char *cbm_open_str(const char *name, char mode) {
    uint8_t len = 0;
    uint8_t nlen = strlen(name);
    if (nlen > 16) nlen = 16;
    if (mode == 'w') {
        open_buf[len++] = '@';
        open_buf[len++] = ':';
    }
    memcpy(open_buf + len, name, nlen);
    len += nlen;
    /* ensure ,s,r or ,s,w suffix */
    if (len < 2 || open_buf[len-2] != ','
        || (open_buf[len-1] != 'r' && open_buf[len-1] != 'w'))
    {
        open_buf[len++] = ',';
        open_buf[len++] = 's';
        open_buf[len++] = ',';
        open_buf[len++] = mode;
    }
    open_buf[len] = 0;
    return open_buf;
}

/* ── Drive status ─────────────────────────────────────────── */

static uint8_t fl_buf[32];

void floppy_status(void) {
    uint8_t n;
    if (cbm_open(14, 8, 15, "") != 0) return;
    n = cbm_read(14, fl_buf, sizeof(fl_buf) - 1);
    cbm_close(14);
    if (n > 0) {
        fl_buf[n - 1] = 0;
        print_string(fl_buf);
        newline();
    } else {
        print_string("floppy error");
        newline();
    }
}

/* ── Directory listing ────────────────────────────────────── */

void list_directory(uint8_t device) {
    struct cbm_dirent de;

    if (cbm_opendir(15, device)) { floppy_status(); return; }

    while (1) {
        if (io_kbhit()) {
            if (io_getc() == CH_STOP) {
                io_puts("break");
                newline();
                cbm_closedir(15);
                return;
            }
        }
        switch (cbm_readdir(15, &de)) {
        case 0:
            io_putdec(de.size); io_putc(' ');
            if (de.type == CBM_T_HEADER) {
                uint8_t start_col = io_cx;
                io_putc('"'); io_puts(de.name); io_putc('"');
                io_cx = 24;
                io_puthex2(de.access);
                { uint8_t *scr = SCREEN + io_cy * SCREEN_WIDTH;
                  uint8_t i;
                  for (i = start_col; i < io_cx; i++) scr[i] |= 0x80;
                }
                newline();
            } else {
                io_cx = 5;
                io_putc('"'); io_puts(de.name); io_putc('"');
                io_cx = 24;
                switch (de.type) {
                case CBM_T_DEL: io_puts("del"); break;
                case CBM_T_SEQ: io_puts("seq"); break;
                case CBM_T_PRG: io_puts("prg"); break;
                case CBM_T_USR: io_puts("usr"); break;
                case CBM_T_REL: io_puts("rel"); break;
                case CBM_T_DIR: io_puts("dir"); break;
                default:        io_putdec(de.type);
                }
                if (!de.access) io_putc('*');
                newline();
            }
            break;
        case 2:
            cbm_closedir(15);
            io_putdec(de.size); io_puts(" blocks free.");
            newline();
            floppy_status();
            return;
        default:
            cbm_closedir(15);
            floppy_status();
            return;
        }
    }
}

/* ── SEQ file I/O (callback-based) ────────────────────────── */

uint8_t disk_load_seq(const char *name, void (*insert_fn)(uint8_t)) {
    int n;
    uint8_t ch, err;

    disk_seq_bytes = 0;
    disk_seq_lines = 1;

    if (cbm_open(2, 8, 2, cbm_open_str(name, 'r')) != 0)
        return 1;

    /* check drive error channel */
    if (cbm_open(15, 8, 15, "") == 0) {
        n = cbm_read(15, fl_buf, sizeof(fl_buf) - 1);
        cbm_close(15);
        if (n > 1) {
            err = (fl_buf[0] - '0') * 10 + (fl_buf[1] - '0');
            if (err >= 20) {
                cbm_close(2);
                return err;
            }
        }
    }

    while (1) {
        n = cbm_read(2, &ch, 1);
        if (n <= 0) break;
        insert_fn(ch);
        ++disk_seq_bytes;
        if (ch == 0x0D) ++disk_seq_lines;
        if (*(volatile uint8_t *)0x90 & 0x40) break;  /* EOF */
    }
    cbm_close(2);
    return 0;
}

uint8_t disk_save_seq(const char *name, int (*read_fn)(void)) {
    int ch;

    disk_seq_bytes = 0;
    disk_seq_lines = 0;

    if (cbm_open(2, 8, 2, cbm_open_str(name, 'w')) != 0)
        return 1;

    while ((ch = read_fn()) >= 0) {
        uint8_t b = (uint8_t)ch;
        if (cbm_write(2, &b, 1) != 1) {
            cbm_close(2);
            return 2;
        }
        ++disk_seq_bytes;
        if (b == 0x0D) ++disk_seq_lines;
    }
    cbm_close(2);
    return 0;
}

/* ── PRG file I/O ─────────────────────────────────────────── */

uint8_t disk_load_prg(const char *name, uint16_t addr) {
    unsigned int r;
    if (addr)
        r = cbm_load(name, 8, (void *)addr);
    else
        r = cbm_load(name, 8, (void *)0);  /* use PRG header address */
    return (r == 0) ? 1 : 0;  /* cbm_load returns 0 on error */
}

uint8_t disk_save_prg(const char *name, uint16_t addr, uint16_t size) {
    return cbm_save(name, 8, (const void *)addr, size);
}
