/* ═══════════════════════════════════════════════════════════════
 * Editor — gap buffer + screen rendering
 *
 * Screen layout:
 *   Row  0-21  Source text (22 lines)
 *   Row 22     Status bar
 *   Row 23-24  Last 2 lines preserved from REPL
 * ═══════════════════════════════════════════════════════════════ */

#include <c64.h>
#include <cbm.h>
#include <string.h>
#include <stdint.h>
#include "cse.h"
#include "cse_io.h"
#include "editor.h"

#define ED_LINES     22                   /* visible source lines */
#define ED_STATUS    22                   /* status bar row */

/* ── REPL screen save buffer ────────────────────────────── */
static uint8_t repl_screen[1000];
static uint8_t repl_cur_x, repl_cur_y;   /* saved REPL cursor position */

/* ── Gap buffer ─────────────────────────────────────────── *
 *
 * Standard gap buffer in a downward-allocated region.
 * The buffer occupies buf_base..buf_end (ascending addresses).
 * buf_end is fixed at $C7FF.  buf_base moves down as we need
 * more space (the "growing downward" part).
 *
 *   buf_base ──→ [pre-gap text] [GAP] [post-gap text] ←── buf_end
 *                               ^     ^
 *                            gap_lo  gap_hi
 *
 * Text is in forward order.  gap_lo/gap_hi mark the gap.
 * Insert at cursor = write at gap_lo++.  O(1).
 */
static uint8_t *buf_base;                 /* lowest address of buffer */
static uint8_t *buf_end;                  /* one past last byte (exclusive, $C800) */
static uint8_t *gap_lo;                   /* first byte of gap */
static uint8_t *gap_hi;                   /* first byte after gap */

/* ── Editor state ───────────────────────────────────────── */
static uint16_t ed_cur_line;              /* cursor line (0-based) */
static uint8_t  ed_cur_col;              /* cursor column (0-based) */
static uint16_t ed_top_line;              /* line number at screen row 0 */
static uint8_t *ed_top_ptr;              /* cached buffer pos for ed_top_line */
static uint16_t ed_total_lines;           /* total line count */
static uint8_t  ed_dirty;                /* buffer modified flag */
uint16_t ed_save_bytes;                   /* bytes transferred (last l/w) */
uint16_t ed_save_lines;                   /* lines transferred (last l/w) */

/* Minimum address the buffer can grow to (end of CSE BSS) */
#define BUF_FLOOR  ((uint8_t *)0x4800)    /* safe margin above CSE */

/* ── Gap buffer operations ──────────────────────────────── */

static void ed_init(void)
{
    buf_end  = (uint8_t *)0xC800;          /* exclusive: one past last byte */
    buf_base = buf_end;
    gap_lo   = buf_end;
    gap_hi   = buf_end;
    ed_cur_line = 0;
    ed_cur_col  = 0;
    ed_top_line = 0;
    ed_top_ptr  = buf_end;
    ed_total_lines = 1;
    ed_dirty = 0;

    src_top = buf_end;
    src_bot = buf_end;
}

static uint8_t gb_ensure_room(void)
{
    uint16_t gap_size;
    gap_size = (uint16_t)(gap_hi - gap_lo);
    if (gap_size > 0) return 1;

    if (buf_base - 256 < BUF_FLOOR) return 0;
    {
        uint16_t pre_size = (uint16_t)(gap_lo - buf_base);
        uint8_t *new_base = buf_base - 256;
        if (pre_size > 0)
            memmove(new_base, buf_base, pre_size);
        {   uint16_t shift = (uint16_t)(buf_base - new_base);
            /* adjust ed_top_ptr if it's in the pre-gap region (inclusive
             * of buf_base).  Post-gap pointers (> gap_lo) don't move. */
            if (ed_top_ptr >= buf_base && ed_top_ptr <= gap_lo)
                ed_top_ptr -= shift;
            gap_lo = new_base + pre_size;
            gap_hi = gap_lo + 256;
            buf_base = new_base;
        }
    }
    src_bot = buf_base;
    return 1;
}

static void gb_insert(uint8_t ch)
{
    if (!gb_ensure_room()) return;
    *gap_lo++ = ch;
    if (ch == 0x0D) ++ed_total_lines;
    ed_dirty = 1;
}

static void gb_backspace(void)
{
    if (gap_lo == buf_base) return;
    --gap_lo;
    if (*gap_lo == 0x0D) --ed_total_lines;
    ed_dirty = 1;
}

static void gb_cursor_right(void)
{
    if (gap_hi >= buf_end) return;
    *gap_lo++ = *gap_hi++;
}

static void gb_cursor_left(void)
{
    if (gap_lo == buf_base) return;
    *--gap_hi = *--gap_lo;
}



/* ── Public: ensure gap buffer is initialized ────────────── */

void ed_ensure_init(void)
{
    if (buf_end == 0) ed_init();
}

/* ── Source I/O — SEQ files ─────────────────────────────── */

/* Build a CBM open string.  For write mode, prepends "@:" to
 * allow overwriting existing files.  Appends ",r" or ",w" if
 * not already present.  Writes to static buffer, returns pointer. */
static char open_buf[FILENAME_MAX_LEN + 8];

static const char *cbm_open_str(const char *name, char mode)
{
    uint8_t len = 0;
    uint8_t nlen = strlen(name);
    if (nlen > FILENAME_MAX_LEN) nlen = FILENAME_MAX_LEN;

    /* prepend @: for write to allow overwrite */
    if (mode == 'w') {
        open_buf[len++] = '@';
        open_buf[len++] = ':';
    }

    memcpy(open_buf + len, name, nlen);
    len += nlen;

    /* append mode if name doesn't already end with ,r or ,w */
    if (len < 2 || open_buf[len-2] != ',' ||
        (open_buf[len-1] != 'r' && open_buf[len-1] != 'w')) {
        open_buf[len++] = ',';
        open_buf[len++] = mode;
    }
    open_buf[len] = 0;
    return open_buf;
}

uint8_t ed_save_source(const char *name)
{
    int n;
    uint16_t total = 0;
    const char *ostr = cbm_open_str(name, 'w');

    ed_ensure_init();

    if (cbm_open(2, 8, 2, ostr) != 0)
        return 1;

    /* write pre-gap text */
    n = (int)(gap_lo - buf_base);
    if (n > 0) {
        if (cbm_write(2, buf_base, n) != n) {
            cbm_close(2);
            return 2;
        }
        total += n;
    }

    /* write post-gap text */
    n = (int)(buf_end - gap_hi);
    if (n > 0) {
        if (cbm_write(2, gap_hi, n) != n) {
            cbm_close(2);
            return 3;
        }
        total += n;
    }

    cbm_close(2);
    ed_dirty = 0;
    ed_save_bytes = total;
    ed_save_lines = ed_total_lines;
    return 0;
}

uint8_t ed_load_source(const char *name)
{
    int n;
    uint8_t ch;
    const char *ostr = cbm_open_str(name, 'r');

    /* reinitialize buffer */
    ed_init();

    if (cbm_open(2, 8, 2, ostr) != 0)
        return 1;

    /* read byte by byte into gap buffer.
     * Check KERNAL status ($90) after each byte — bit 6 = EOF.
     * Must stop immediately when EOF is signaled WITH the last
     * byte, not after a failed read, or the drive hangs. */
    while (1) {
        n = cbm_read(2, &ch, 1);
        if (n <= 0) break;
        gb_insert(ch);
        if (*(uint8_t *)0x90 & 0x40) break;  /* ST bit 6 = EOF */
    }

    cbm_close(2);

    /* if nothing was read, the file likely doesn't exist.
     * The drive error was cleared by close, so we just report
     * failure and let floppy_status show whatever remains. */
    {
        uint16_t bytes = (uint16_t)(gap_lo - buf_base)
                       + (uint16_t)(buf_end - gap_hi);
        if (bytes == 0) {
            ed_init();
            return 1;
        }
    }

    /* move cursor to start of buffer */
    while (gap_lo > buf_base) gb_cursor_left();
    ed_cur_line = 0;
    ed_cur_col  = 0;
    ed_top_line = 0;
    ed_top_ptr  = buf_base;
    ed_dirty = 0;

    /* report stats for caller */
    ed_save_bytes = (uint16_t)(gap_lo - buf_base) + (uint16_t)(buf_end - gap_hi);
    ed_save_lines = ed_total_lines;

    return 0;
}

/* ── Editor screen rendering ────────────────────────────── */

/* Render one source line at screen row.  *pos advances past the
 * $0D or to buf_end.  Returns 1 if more text, 0 at EOF. */
static uint8_t ed_render_line(uint8_t row, uint8_t **pos)
{
    uint8_t *scr = SCREEN + (uint16_t)row * SCREEN_WIDTH;
    uint8_t col = 0;
    uint8_t ch, sc;

    while (col < SCREEN_WIDTH) {
        if (*pos == gap_lo) *pos = gap_hi;
        if (*pos >= buf_end) break;
        ch = **pos;
        if (ch == 0x0D) { ++(*pos); break; }
        sc = ch;
        if (sc >= 0x41 && sc <= 0x5A) sc -= 0x40;       /* unshifted → $01-$1A */
        else if (sc >= 0xC1 && sc <= 0xDA) sc -= 0x80; /* shifted → $41-$5A */
        scr[col++] = sc;
        ++(*pos);
    }
    while (col < SCREEN_WIDTH) scr[col++] = 0x20;
    if (*pos == gap_lo) *pos = gap_hi;
    return (*pos < buf_end) ? 1 : 0;
}

/* Advance a buffer pointer past one line (to start of next). */
static uint8_t *skip_one_line(uint8_t *pos)
{
    while (pos < buf_end) {
        if (pos == gap_lo) pos = gap_hi;
        if (pos >= buf_end) break;
        if (*pos++ == 0x0D) break;
    }
    return pos;
}

/* Retreat to start of the previous line (pos should point to
 * the start of the current line).  Returns start of prev line. */
static uint8_t *prev_line_start(uint8_t *pos)
{
    if (pos == gap_hi) pos = gap_lo;
    if (pos <= buf_base) return buf_base;
    --pos;                                /* step back over $0D */
    if (pos == gap_hi) pos = gap_lo;      /* might cross gap */
    /* scan backwards to previous $0D or buf_base */
    while (pos > buf_base) {
        uint8_t *prev = pos - 1;
        if (prev == gap_hi) prev = gap_lo;
        if (prev < buf_base) break;
        if (*prev == 0x0D) break;
        pos = prev;
    }
    return pos;
}

/* Render status bar (row 22).  Fixed layout, 40 cols:
 * cols 0-17:  " *filename,s       " (dirty + name, 18 chars)
 * cols 18-39: "  free:LLLL-HHHH LLL,CC" (22 chars, right-aligned)
 */
static void ed_render_status(void)
{
    static const uint8_t hx[] = {
        0x30,0x31,0x32,0x33,0x34,0x35,0x36,0x37,
        0x38,0x39,0x01,0x02,0x03,0x04,0x05,0x06 };
    uint8_t *s = SCREEN + ED_STATUS * SCREEN_WIDTH;
    uint8_t col, j;
    uint16_t lo, hi, v;

    /* fill with reversed spaces */
    for (col = 0; col < SCREEN_WIDTH; ++col) s[col] = 0xA0;

    /* ── left: cols 0-17: dirty flag + filename ── */
    col = 0;
    s[col++] = 0xA0;                          /* leading space */
    s[col++] = ed_dirty ? (0x2A | 0x80) : 0xA0;  /* '*' or space */
    if (cur_filename[0]) {
        uint8_t nlen = strlen(cur_filename);
        /* strip ",s" or ",p" type suffix for display */
        if (nlen >= 2 && cur_filename[nlen-2] == ',')
            nlen -= 2;
        for (j = 0; j < nlen && col < 18; ++j) {
            uint8_t sc = cur_filename[j];
            if (sc >= 0x41 && sc <= 0x5A) sc -= 0x40;
            s[col++] = sc | 0x80;
        }
    }

    /* ── right: fixed positions at cols 18-39 ──
     * Layout: "  free:LLLL-HHHH LLL,CC"
     *          18             33 34  38  */

    /* free:LLLL-HHHH at cols 20-33 */
    lo = cse_end();
    hi = (uint16_t)buf_base - 1;
    col = 20;
    s[col++] = 0x06 | 0x80;  /* f */
    s[col++] = 0x12 | 0x80;  /* r */
    s[col++] = 0x05 | 0x80;  /* e */
    s[col++] = 0x05 | 0x80;  /* e */
    s[col++] = 0x3A | 0x80;  /* : */
    s[col++] = hx[(lo >> 12) & 0xF] | 0x80;
    s[col++] = hx[(lo >>  8) & 0xF] | 0x80;
    s[col++] = hx[(lo >>  4) & 0xF] | 0x80;
    s[col++] = hx[ lo        & 0xF] | 0x80;
    s[col++] = 0x2D | 0x80;  /* '-' */
    s[col++] = hx[(hi >> 12) & 0xF] | 0x80;
    s[col++] = hx[(hi >>  8) & 0xF] | 0x80;
    s[col++] = hx[(hi >>  4) & 0xF] | 0x80;
    s[col++] = hx[ hi        & 0xF] | 0x80;
    /* col is now 34 */

    /* LLL,CC right-aligned at cols 34-39 (3 digits line, 2 digits col) */
    /* col 39-38: column (2 digits, zero-padded) */
    v = ed_cur_col + 1;
    s[39] = (0x30 + v % 10) | 0x80; v /= 10;
    s[38] = (0x30 + v % 10) | 0x80;

    /* col 37: comma */
    s[37] = 0x2C | 0x80;

    /* cols 34-36: line (3 digits, space-padded) */
    v = ed_cur_line + 1;
    s[36] = (0x30 + v % 10) | 0x80; v /= 10;
    s[35] = v ? ((0x30 + v % 10) | 0x80) : 0xA0; v /= 10;
    s[34] = v ? ((0x30 + v % 10) | 0x80) : 0xA0;
}

/* Render lines from_row to to_row using the cached view pointer. */
static void ed_render_range(uint8_t from_row, uint8_t to_row)
{
    uint8_t *pos;
    uint8_t row;

    /* find start position: advance from cached ed_top_ptr */
    pos = ed_top_ptr;
    for (row = 0; row < from_row; ++row)
        pos = skip_one_line(pos);

    for (row = from_row; row < to_row && row < ED_LINES; ++row) {
        if (pos == gap_lo) pos = gap_hi;
        if (pos >= buf_end) {
            memset(SCREEN + (uint16_t)row * SCREEN_WIDTH, 0x20,
                   SCREEN_WIDTH);
        } else {
            ed_render_line(row, &pos);
        }
    }
}

/* Full re-render of all 22 editor lines + status bar. */
static void ed_render(void)
{
    ed_render_range(0, ED_LINES);
    ed_render_status();
}

/* Render a range of screen rows + status. */
static void ed_render_rows(uint8_t from_row, uint8_t to_row)
{
    ed_render_range(from_row, to_row);
    ed_render_status();
}

/* Scroll screen up by one line, render new bottom line. */
static void ed_scroll_up(void)
{
    /* advance cached view pointer by one line */
    ed_top_ptr = skip_one_line(ed_top_ptr);
    ++ed_top_line;

    /* shift screen rows 1..21 → 0..20 */
    memmove(SCREEN, SCREEN + SCREEN_WIDTH,
            (ED_LINES - 1) * SCREEN_WIDTH);

    /* render only the new bottom line */
    {
        uint8_t *pos = ed_top_ptr;
        uint8_t row;
        for (row = 0; row < ED_LINES - 1; ++row)
            pos = skip_one_line(pos);
        if (pos == gap_lo) pos = gap_hi;
        if (pos >= buf_end)
            memset(SCREEN + (ED_LINES - 1) * SCREEN_WIDTH, 0x20,
                   SCREEN_WIDTH);
        else
            ed_render_line(ED_LINES - 1, &pos);
    }
    ed_render_status();
}

/* Scroll screen down by one line, render new top line. */
static void ed_scroll_down(void)
{
    /* retreat cached view pointer by one line */
    ed_top_ptr = prev_line_start(ed_top_ptr);
    --ed_top_line;

    /* shift screen rows 0..20 → 1..21 */
    memmove(SCREEN + SCREEN_WIDTH, SCREEN,
            (ED_LINES - 1) * SCREEN_WIDTH);

    /* render only the new top line */
    {
        uint8_t *pos = ed_top_ptr;
        if (pos == gap_lo) pos = gap_hi;
        if (pos >= buf_end)
            memset(SCREEN, 0x20, SCREEN_WIDTH);
        else
            ed_render_line(0, &pos);
    }
    ed_render_status();
}

/* ── Mode switching ─────────────────────────────────────── */

void enter_editor(void)
{
    /* save REPL state */
    repl_cur_x = io_cx;
    repl_cur_y = io_cy;
    memcpy(repl_screen, SCREEN, 1000);

    if (buf_end == 0) ed_init();

    /* clear editor area (rows 0–21), keep rows 23–24 from REPL */
    memset(SCREEN, 0x20, ED_LINES * SCREEN_WIDTH);

    /* copy last 2 REPL lines above the prompt to rows 23–24 */
    {
        uint8_t prompt_row = repl_cur_y;
        uint8_t src_row;
        if (prompt_row >= 2) src_row = prompt_row - 2;
        else src_row = 0;
        memcpy(SCREEN + 23 * SCREEN_WIDTH,
               repl_screen + src_row * SCREEN_WIDTH,
               2 * SCREEN_WIDTH);
    }

    ed_render();

    io_cx = ed_cur_col; io_cy = ed_cur_line - ed_top_line; io_sync();
    state = ST_EDIT;
}

void leave_editor(void)
{
    memcpy(SCREEN, repl_screen, 1000);
    io_cx = repl_cur_x; io_cy = repl_cur_y; io_sync();
    state = ST_REPL;
}

/* ── Editor cursor movement helpers ─────────────────────── */

static void gb_home(void)
{
    while (gap_lo > buf_base) {
        if (*(gap_lo - 1) == 0x0D) break;
        gb_cursor_left();
    }
}



static void ed_cursor_up(void)
{
    uint8_t target_col = ed_cur_col;

    if (ed_cur_line == 0) return;

    gb_home();
    ed_cur_col = 0;

    if (gap_lo > buf_base) {
        gb_cursor_left();
        --ed_cur_line;
    }

    gb_home();
    ed_cur_col = 0;

    while (ed_cur_col < target_col && gap_hi < buf_end && *gap_hi != 0x0D) {
        gb_cursor_right();
        ++ed_cur_col;
    }

    /* caller handles scrolling */
}

static void ed_cursor_down(void)
{
    uint8_t target_col = ed_cur_col;

    if (ed_cur_line + 1 >= ed_total_lines) return;

    while (gap_hi < buf_end && *gap_hi != 0x0D)
        gb_cursor_right();

    if (gap_hi < buf_end) {
        gb_cursor_right();
        ++ed_cur_line;
        ed_cur_col = 0;
    }

    while (ed_cur_col < target_col && gap_hi < buf_end && *gap_hi != 0x0D) {
        gb_cursor_right();
        ++ed_cur_col;
    }

    /* caller handles scrolling */
}

/* ── Editor key handler ─────────────────────────────────── */

void ed_handle_key(uint8_t ch)
{
    uint8_t scr_row = (uint8_t)(ed_cur_line - ed_top_line);
    uint8_t old_top = (uint8_t)ed_top_line;

    switch (ch) {

    case CH_CURS_LEFT:
        if (ed_cur_col > 0) {
            gb_cursor_left();
            --ed_cur_col;
        }
        /* cursor-only: just update status + reposition */
        ed_render_status();
        goto reposition;

    case CH_CURS_RIGHT:
        if (gap_hi < buf_end && *gap_hi != 0x0D) {
            gb_cursor_right();
            ++ed_cur_col;
        }
        ed_render_status();
        goto reposition;

    case CH_CURS_UP:
        ed_cursor_up();
        if (ed_cur_line < ed_top_line)
            ed_scroll_down();             /* one-line scroll, render 1 row */
        else
            ed_render_status();
        goto reposition;

    case CH_CURS_DOWN:
        ed_cursor_down();
        if (ed_cur_line >= ed_top_line + ED_LINES)
            ed_scroll_up();               /* one-line scroll, render 1 row */
        else
            ed_render_status();
        goto reposition;

    case CH_HOME:
        gb_home();
        ed_cur_col = 0;
        ed_render_status();
        goto reposition;

    case CH_DEL:
        if (ed_cur_col > 0) {
            gb_backspace();
            --ed_cur_col;
            /* redraw current line to end of screen (text shifted) */
            scr_row = (uint8_t)(ed_cur_line - ed_top_line);
            ed_render_rows(scr_row, ED_LINES);
        } else if (ed_cur_line > 0) {
            gb_backspace();
            --ed_cur_line;
            ed_cur_col = 0;
            {
                uint8_t *p = gap_lo;
                while (p > buf_base && *(p-1) != 0x0D) { --p; ++ed_cur_col; }
            }
            if (ed_cur_line < ed_top_line) ed_top_line = ed_cur_line;
            /* line join — redraw from joined line down */
            scr_row = (uint8_t)(ed_cur_line - ed_top_line);
            ed_render_rows(scr_row, ED_LINES);
        }
        goto reposition;

    case CH_ENTER:
        gb_insert(0x0D);
        ++ed_cur_line;
        ed_cur_col = 0;
        if (ed_cur_line >= ed_top_line + ED_LINES) {
            ed_scroll_up();
        } else {
            scr_row = (uint8_t)(ed_cur_line - ed_top_line);
            if (scr_row > 0)
                ed_render_rows(scr_row - 1, ED_LINES);
            else
                ed_render();
        }
        goto reposition;

    default:
        /* accept unshifted ($20-$7E) and shifted letters ($C1-$DA) */
        if (((ch >= 0x20 && ch <= 0x7E) || (ch >= 0xC1 && ch <= 0xDA))
            && ed_cur_col < SCREEN_WIDTH - 1) {
            gb_insert(ch);
            ++ed_cur_col;
            /* redraw only the current line + status */
            scr_row = (uint8_t)(ed_cur_line - ed_top_line);
            ed_render_rows(scr_row, scr_row + 1);
        }
        goto reposition;
    }

reposition:
    scr_row = (uint8_t)(ed_cur_line - ed_top_line);
    if (scr_row < ED_LINES) {
        io_cx = ed_cur_col; io_cy = scr_row; io_sync();
    }
}
