# strings — Centralised string constants

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/strings.s`](../../src/strings.s) | implementation |

## Interface

No callable routines.  All exports are RODATA labels — NUL-terminated
byte strings consumed by `io_puts` / the `puts` macro, or by direct
byte-indexing (e.g. `str_flag_ch`).

### Exported labels

**repl group:** `str_flag_ch`, `str_bp_pfx`, `str_3sp`, `str_2sp`,
`str_brk`, `str_at`, `str_nmi`, `str_ok_at`, `str_bp_clr`, `str_deleted`,
`str_syntax`, `str_bad_val`, `str_full`, `str_cmd`, `str_no_name`,
`str_range`, `str_fail`, `str_too_big`, `str_expr`, `str_no_ctx`,
`str_r_pc`, `str_a`, `str_x`, `str_y`, `str_s`,
`str_lines`, `str_bytes`, `str_bytes_sp`, `str_long`,
`str_del_src`, `str_unsaved`, `str_ok`, `str_blk_eq`,
`str_color`, `str_cpu`, `str_6510`\*, `str_65c02`\*,
`str_asm_ing`, `str_load_pfx`, `str_save_pfx`, `str_dots`,
`str_errors`, `str_quit`, `str_dashes`, `str_colon_sp`, `str_pct`,
`str_ioport`, `str_stack`, `str_kernal`, `str_screen`,
`str_cse_rt`, `str_bytes_free`, `str_io`,
`str_free`, `str_l`, `str_main`,
`str_tag_cpu`, `str_tag_zp`, `str_tag_stk`, `str_tag_sys`,
`str_tag_scr`, `str_tag_cse`, `str_tag_work`, `str_free_suf`,
`str_tag_src`, `str_tag_lo02`, `str_tag_io`,
`str_tag_rom`, `str_banked`

\* conditional: `str_6510` requires `CPU_6510`, `str_65c02` requires `CMOS_SUPPORT`

**disk group:** `str_dname`, `str_dir_brk`, `str_blk_free`,
`str_blk_pre`, `str_blk_suf`

**mem group:** `s_workstart`, `s_workend`

**main group:** `VERSION_STR`, `s_manual`, `s_zp_tag`, `s_lo02_tag`,
`s_work_tag`, `s_free`

**asm_src group:** `s_err_sep`, `s_bad_val`, `s_exp_name`, `s_sym_full`,
`s_exp_quot`, `s_bad_insn`, `s_seg_pfx`, `s_save_s`, `s_save_q_sp`,
`s_save_default`, `s_trunc`

**expr group:** `err_none`, `err_expected`, `err_overflow`, `err_paren`,
`err_undefined`, `err_divzero`, `err_str_lo`, `err_str_hi`

### Aliases

Labels that share storage with another string — either exact duplicates
or suffix/prefix substrings:

| Alias | Points to | Mechanism |
|-------|-----------|-----------|
| `str_tag_scr` | `str_screen` | duplicate `"scr"` |
| `str_cse_rt` | `str_tag_cse` | duplicate `"cse"` |
| `str_tag_io` | `str_io` | duplicate `"io"` |
| `str_free_suf` | `str_bytes_free` | duplicate `"b free"` |
| `s_free` | `str_bytes_free` | duplicate `"b free"` |
| `s_bad_val` | `str_bad_val` | duplicate `"bad val"` |
| `s_err_sep` | `str_colon_sp` | duplicate `": "` |
| `str_dots` | `str_asm_ing + 3` | suffix — `"..."` within `"asm..."` |
| `str_full` | `s_sym_full + 4` | suffix — `"full"` within `"sym full"` |
| `str_dname` | `str_dashes` | prefix — `"$"` within `"$----"` |

### Shared tables

`dec_pow_lo` / `dec_pow_hi` — powers of 10 (10000,1000,100,10,1).
Used by `io_putdec` (cse_io.s), `utoa_sub` (repl.s), and
`_emit_decimal` (asm_src.s).

**Depends on:** nothing (pure RODATA leaf)

## Design

### Rationale

Strings were originally scattered across 6 modules (`repl.s`, `main.s`,
`mem.s`, `disk.s`, `asm_src.s`, `expr.s`), causing silent duplication
and making the corpus hard to audit or optimise.  Centralisation
provides a single source of truth.  Duplicate strings are stored once
via aliases; short strings that are suffixes of longer ones share
storage via offset aliases (`label = host + N`).

### What is NOT here

- **Info tables** (`info_tbl_h1..tail`, `INFO_TBL_*_ROWS`) remain in
  `repl.s` because the row-count constants are computed from segment
  arithmetic (`(* - label) / 8`) and cannot be exported/imported in ca65.
- **Non-string RODATA** (decimal power tables, CPU-pair lookup, etc.)
  remains in its owning module.

### Naming convention

All string labels use the `str_` prefix (except legacy `s_` / `err_`
labels from asm_src and expr, kept for compatibility with existing
call sites).  Label names should match string content — e.g.
`str_no_ctx` for `"no ctx"`, not a stale name from a prior wording.

### String style convention

All user-visible strings follow these prefixing rules (enforced by the
log output helpers `out_log_open`, `out_err`, etc.):

| Pattern | Meaning |
|---------|---------|
| `"; ..."` | normal status / info |
| `";!..."` | warning |
| `";?tag"` | terse error tag (BASIC-style) |
| `";?word ..."` | long error explanation |
| `"; ...? y/n "` | yes/no confirmation prompt |

Always lowercase.  New strings must use the prefix that matches their
semantic role.

## Caveats

- `str_flag_ch` has no NUL terminator — it is indexed by bit position,
  not passed to `io_puts`.
- `s_save_s` and `s_save_q_sp` contain embedded `$22` (PETSCII quote)
  bytes that are not visible in the label name.
- `s_exp_quot` also contains an embedded `$22` (the error shows the
  expected quote character).
- `str_6510` and `str_65c02` are conditionally assembled; code that
  references them must be inside matching `.ifdef` guards.
- Suffix aliases (`str_dots`, `str_full`, `str_dname`) depend on the
  host string's layout — changing the host string content will silently
  break the alias.
