/* ═══════════════════════════════════════════════════════════════
 * Editor — gap buffer + screen rendering
 *
 * Screen layout:
 *   Row  0-21  Source text (22 lines)
 *   Row 22     Status bar
 *   Row 23-24  Last 2 lines preserved from REPL
 * ═══════════════════════════════════════════════════════════════ */

#include <c64.h>
#include <string.h>
#include <stdint.h>
#include "cse.h"
#include "cse_io.h"
#include "screen.h"
#include "disk.h"
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
uint8_t  tab_width = 8;                  /* tab stop interval (columns) */

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

/* ── Public: clear editor (new file) ──────────────────────── */

void ed_new(void)
{
    ed_init();
    cur_filename[0] = 0;
}

/* ── Source I/O — via disk.s callbacks ─────────────────── */

/* Save callback: reads sequentially from the gap buffer.
 * Pre-gap first, then post-gap.  Returns -1 at end. */
static uint8_t *save_ptr;
static uint8_t  save_phase;   /* 0 = pre-gap, 1 = post-gap */

static int save_read_fn(void) {
    if (save_phase == 0) {
        if (save_ptr < gap_lo) return *save_ptr++;
        /* switch to post-gap */
        save_phase = 1;
        save_ptr = gap_hi;
    }
    if (save_ptr < buf_end) return *save_ptr++;
    return -1;  /* EOF */
}

uint8_t ed_save_source(const char *name)
{
    uint8_t err;

    ed_ensure_init();

    save_ptr   = buf_base;
    save_phase = 0;

    err = disk_save_seq(name, save_read_fn);
    if (err) return err;

    ed_dirty = 0;
    ed_save_bytes = disk_seq_bytes;
    ed_save_lines = disk_seq_lines;
    return 0;
}

/* Load callback wrapper: gb_insert is the insert_fn */
static void load_insert_fn(uint8_t ch) {
    gb_insert(ch);
}

uint8_t ed_load_source(const char *name)
{
    uint8_t err;

    ed_init();

    err = disk_load_seq(name, load_insert_fn);
    if (err || disk_seq_bytes == 0) {
        ed_init();   /* reset buffer on failure */
        return err ? err : 1;
    }

    /* move cursor to start of buffer */
    while (gap_lo > buf_base) gb_cursor_left();
    ed_cur_line = 0;
    ed_cur_col  = 0;
    ed_top_line = 0;
    ed_top_ptr  = buf_base;
    ed_dirty = 0;

    ed_save_bytes = disk_seq_bytes;
    ed_save_lines = disk_seq_lines;

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
        if (ch == 0xA0) {
            /* Tab: expand to spaces up to next tab_width boundary */
            uint8_t w = (tab_width > 0) ? (tab_width - (col % tab_width)) : 1;
            while (w-- && col < SCREEN_WIDTH) scr[col++] = 0x20;
            ++(*pos);
            continue;
        }
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
/* ── Status bar: partial update helpers ──────────────────────
 *
 * Layout (40 cols, all reversed):
 *   *filename        free:LLLL-HHHH LLL,CC
 *   0  1-17         18 19-32      33 34-39
 *
 * ed_status_full()   — rebuild everything (mode enter, load, save)
 * ed_status_pos()    — update LLL,CC only (cursor movement)
 * ed_status_dirty()  — update dirty flag only (first edit)
 * ed_status_free()   — update HHHH only (buffer grew/shrank)
 */

static const uint8_t st_hx[] = {
    0x30,0x31,0x32,0x33,0x34,0x35,0x36,0x37,
    0x38,0x39,0x01,0x02,0x03,0x04,0x05,0x06 };

/* Update cursor position (cols 34-39). */
static void ed_status_pos(void)
{
    uint8_t *s = SCREEN + ED_STATUS * SCREEN_WIDTH;
    uint16_t v;

    v = ed_cur_col + 1;
    s[39] = (0x30 + v % 10) | 0x80; v /= 10;
    s[38] = (0x30 + v % 10) | 0x80;
    s[37] = 0x2C | 0x80;
    v = ed_cur_line + 1;
    s[36] = (0x30 + v % 10) | 0x80; v /= 10;
    s[35] = v ? ((0x30 + v % 10) | 0x80) : 0xA0; v /= 10;
    s[34] = v ? ((0x30 + v % 10) | 0x80) : 0xA0;
}

/* Update dirty flag (col 0). */
static void ed_status_dirty(void)
{
    uint8_t *s = SCREEN + ED_STATUS * SCREEN_WIDTH;
    s[0] = ed_dirty ? (0x2A | 0x80) : 0xA0;
}

/* Update upper free address (cols 29-32) — called when buf_base moves. */
static void ed_status_free(void)
{
    uint8_t *s = SCREEN + ED_STATUS * SCREEN_WIDTH;
    uint16_t hi = (uint16_t)buf_base - 1;
    s[29] = st_hx[(hi >> 12) & 0xF] | 0x80;
    s[30] = st_hx[(hi >>  8) & 0xF] | 0x80;
    s[31] = st_hx[(hi >>  4) & 0xF] | 0x80;
    s[32] = st_hx[ hi        & 0xF] | 0x80;
}

/* Full rebuild — called on mode enter, load, save, filename change. */
static void ed_render_status(void)
{
    uint8_t *s = SCREEN + ED_STATUS * SCREEN_WIDTH;
    uint8_t col, j;
    uint16_t lo;

    /* fill with reversed spaces */
    for (col = 0; col < SCREEN_WIDTH; ++col) s[col] = 0xA0;

    /* dirty flag + filename (cols 0-17) */
    col = 0;
    s[col++] = ed_dirty ? (0x2A | 0x80) : 0xA0;
    if (cur_filename[0]) {
        uint8_t nlen = strlen(cur_filename);
        if (nlen >= 2 && cur_filename[nlen-2] == ',')
            nlen -= 2;
        for (j = 0; j < nlen && col < 18; ++j) {
            uint8_t sc = cur_filename[j];
            if (sc >= 0x41 && sc <= 0x5A) sc -= 0x40;
            s[col++] = sc | 0x80;
        }
    }

    /* "free:" label (cols 19-23) — static, only written on full rebuild */
    col = 19;
    s[col++] = 0x06 | 0x80;  /* f */
    s[col++] = 0x12 | 0x80;  /* r */
    s[col++] = 0x05 | 0x80;  /* e */
    s[col++] = 0x05 | 0x80;  /* e */
    s[col++] = 0x3A | 0x80;  /* : */

    /* lower free address (cols 24-27) — static within a session */
    lo = cse_end();
    s[col++] = st_hx[(lo >> 12) & 0xF] | 0x80;
    s[col++] = st_hx[(lo >>  8) & 0xF] | 0x80;
    s[col++] = st_hx[(lo >>  4) & 0xF] | 0x80;
    s[col++] = st_hx[ lo        & 0xF] | 0x80;
    s[col++] = 0x2D | 0x80;  /* '-' */

    /* upper free address + cursor pos via partial updaters */
    ed_status_free();
    ed_status_pos();
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
    ed_status_pos();
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
    ed_status_pos();
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

/* ── Tab character helpers ──────────────────────────────── */

/* Compute the visual column width of a single byte. */
static uint8_t char_width(uint8_t ch, uint8_t vcol)
{
    if (ch == 0xA0 && tab_width > 0) {
        /* Tab: advance to next tab_width boundary (min 1) */
        return tab_width - (vcol % tab_width);
    }
    return 1;
}

/* Recompute visual column from start of current line to gap_lo. */
static uint8_t visual_col(void)
{
    uint8_t *p = gap_lo;
    uint8_t vcol = 0;
    while (p > buf_base && *(p - 1) != 0x0D) --p;
    while (p < gap_lo) {
        vcol += char_width(*p, vcol);
        ++p;
    }
    return vcol;
}

/* Copy leading whitespace bytes ($20/$A0) from current line into ws_buf.
 * Returns count of bytes copied.  Used by RETURN for auto-indent. */
static uint8_t copy_leading_ws(uint8_t *ws_buf, uint8_t max)
{
    uint8_t *p = gap_lo;
    uint8_t n = 0;
    while (p > buf_base && *(p - 1) != 0x0D) --p;
    while (p < gap_lo && n < max && (*p == ' ' || *p == 0xA0))
        { ws_buf[n++] = *p++; }
    if (p == gap_lo) {
        uint8_t *q = gap_hi;
        while (q < buf_end && n < max && (*q == ' ' || *q == 0xA0))
            { ws_buf[n++] = *q++; }
    }
    return n;
}

/* ── Editor cursor movement helpers ─────────────────────── */

static void gb_home(void)
{
    while (gap_lo > buf_base) {
        if (*(gap_lo - 1) == 0x0D) break;
        gb_cursor_left();
    }
}



/* Advance cursor right on new line until visual column >= target.
 * Stops at CR or buf_end. */
static void advance_to_vcol(uint8_t target)
{
    while (gap_hi < buf_end && *gap_hi != 0x0D) {
        uint8_t w = char_width(*gap_hi, ed_cur_col);
        if (ed_cur_col + w > target) break;  /* would overshoot */
        gb_cursor_right();
        ed_cur_col += w;
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

    advance_to_vcol(target_col);

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

    advance_to_vcol(target_col);

    /* caller handles scrolling */
}


/* ── Editor key handler ─────────────────────────────────── */

void ed_handle_key(uint8_t ch)
{
    uint8_t scr_row = (uint8_t)(ed_cur_line - ed_top_line);
    uint8_t old_top = (uint8_t)ed_top_line;

    switch (ch) {

    case CH_CURS_LEFT:
        if (ed_cur_col > 0 && gap_lo > buf_base) {
            gb_cursor_left();
            ed_cur_col = visual_col();
        }
        ed_status_pos();
        goto reposition;

    case CH_CURS_RIGHT:
        if (gap_hi < buf_end && *gap_hi != 0x0D) {
            gb_cursor_right();
            ed_cur_col = visual_col();
        }
        ed_status_pos();
        goto reposition;

    case CH_CURS_UP:
        ed_cursor_up();
        if (ed_cur_line < ed_top_line)
            ed_scroll_down();
        else
            ed_status_pos();
        goto reposition;

    case CH_CURS_DOWN:
        ed_cursor_down();
        if (ed_cur_line >= ed_top_line + ED_LINES)
            ed_scroll_up();
        else
            ed_status_pos();
        goto reposition;

    case CH_HOME:
        gb_home();
        ed_cur_col = 0;
        ed_status_pos();
        goto reposition;

    case CH_DEL:
        if (ed_cur_col > 0) {
            gb_backspace();
            ed_cur_col = visual_col();
            scr_row = (uint8_t)(ed_cur_line - ed_top_line);
            ed_render_rows(scr_row, ED_LINES);
        } else if (ed_cur_line > 0) {
            gb_backspace();
            --ed_cur_line;
            ed_cur_col = visual_col();
            if (ed_cur_line < ed_top_line) ed_top_line = ed_cur_line;
            scr_row = (uint8_t)(ed_cur_line - ed_top_line);
            ed_render_rows(scr_row, ED_LINES);
        }
        if (!ed_dirty) { ed_dirty = 1; ed_status_dirty(); }
        ed_status_free();
        ed_status_pos();
        goto reposition;

    case CH_ENTER:
    {
        uint8_t ws_buf[39];
        uint8_t ws_n = 0;
        if (tab_width > 0)
            ws_n = copy_leading_ws(ws_buf, sizeof ws_buf);
        gb_insert(0x0D);
        ++ed_cur_line;
        ed_cur_col = 0;
        /* auto-indent: copy leading whitespace from previous line */
        {   uint8_t i;
            for (i = 0; i < ws_n; ++i) gb_insert(ws_buf[i]);
            ed_cur_col = visual_col();
        }
        if (ed_cur_line >= ed_top_line + ED_LINES) {
            ed_scroll_up();
        } else {
            scr_row = (uint8_t)(ed_cur_line - ed_top_line);
            if (scr_row > 0)
                ed_render_rows(scr_row - 1, ED_LINES);
            else
                ed_render();
        }
        if (!ed_dirty) { ed_dirty = 1; ed_status_dirty(); }
        ed_status_free();
        ed_status_pos();
        goto reposition;
    }

    case CH_INS:
        goto reposition;

    default:
        /* C=+SPACE ($A0): insert tab byte */
        if (ch == 0xA0 && tab_width > 0) {
            uint8_t new_vcol = ed_cur_col + char_width(0xA0, ed_cur_col);
            if (new_vcol <= SCREEN_WIDTH - 1) {
                gb_insert(0xA0);
                ed_cur_col = new_vcol;
                scr_row = (uint8_t)(ed_cur_line - ed_top_line);
                ed_render_rows(scr_row, scr_row + 1);
                if (!ed_dirty) { ed_dirty = 1; ed_status_dirty(); }
                ed_status_free();
                ed_status_pos();
            }
            goto reposition;
        }
        /* standard printable character */
        if (((ch >= 0x20 && ch <= 0x7E) || (ch >= 0xC1 && ch <= 0xDA))
            && ed_cur_col < SCREEN_WIDTH - 1) {
            gb_insert(ch);
            ++ed_cur_col;
            scr_row = (uint8_t)(ed_cur_line - ed_top_line);
            ed_render_rows(scr_row, scr_row + 1);
            if (!ed_dirty) { ed_dirty = 1; ed_status_dirty(); }
            ed_status_free();
            ed_status_pos();
        }
        goto reposition;
    }

reposition:
    scr_row = (uint8_t)(ed_cur_line - ed_top_line);
    if (scr_row < ED_LINES) {
        io_cx = ed_cur_col; io_cy = scr_row; io_sync();
    }
}

/* ═══════════════════════════════════════════════════════════════
 * Reindent — adjust leading spaces when tab width changes
 *
 * Walk the buffer line by line.  For each line, count leading spaces,
 * decompose into (levels * old_tw + remainder), rewrite as
 * (levels * new_tw + remainder) spaces.  Single pass, O(n).
 * ═══════════════════════════════════════════════════════════════ */


/* ═══════════════════════════════════════════════════════════════
 * Gap buffer sequential reader — for source assembler
 *
 * Reads source text byte-by-byte, transparently skipping the gap.
 * The read pointer is independent of the cursor/gap position.
 * ═══════════════════════════════════════════════════════════════ */

static uint8_t *read_ptr;

void ed_read_rewind(void) {
    ed_ensure_init();
    read_ptr = buf_base;
}

int ed_read_byte(void) {
    /* Skip over gap */
    if (read_ptr == gap_lo)
        read_ptr = gap_hi;
    /* End of buffer? */
    if (read_ptr >= buf_end)
        return -1;
    return *read_ptr++;
}

int ed_read_line(char *buf, uint8_t maxlen) {
    uint8_t len = 0;
    int ch;

    for (;;) {
        ch = ed_read_byte();
        if (ch < 0) {
            /* EOF — return what we have, or -1 if nothing */
            if (len == 0) return -1;
            break;
        }
        if (ch == 0x0D) {
            /* End of line (CR) */
            break;
        }
        if (len < maxlen - 1) {
            buf[len++] = (char)ch;
        }
        /* else: silently truncate long lines */
    }
    buf[len] = 0;
    return len;
}

void ed_insert_string(const char *text) {
    ed_ensure_init();
    while (*text) {
        gb_insert(*text++);
    }
}
