# -----------------------------------------------------------------------
# Makefile — CSE 6502 assembler
# Owner: doc/build_system.md
#
# Targets
#   all          Build release (default, same as 'release')
#   release      Build all three CPU targets, optimized + exomizer + D64
#   debug        Build all three CPU targets with -g (full symbols)
#   tables       Regenerate the generated tables in src/ (both generators:
#                dev/mnemonic_tables.py, dev/dasm_tables.py)
#   test         Build debug + release, check the ROMs, run all pytest tests
#   check-roms   Fail with copy instructions when rom/kernal_cbm.bin is missing
#   m65-rom      Copy the MEGA65 ROM from xmega65's data into rom/mega65.rom
#   disk         Create a D64 disk image (uses CPU= for PRG selection);
#                PLATFORM=m65: release's D81
#   run          Build release and launch in VICE (PLATFORM=m65: xmega65)
#   size         Exhaustive size breakdown of selected PRG
#   clean        Remove build/
#   clean-tables Remove generated table sources in src/
#   themes       List the colour themes
#   help         Show this message
#
# CPU= selects the target for run/disk/size (default: 6510).
# Both 'release' and 'debug' always build all three variants:
#   build/release/{6510,6502}/cse*.prg   (optimized + exomizer)
#   build/debug/{6510,6502}/cse*.prg     (with -g, full .lbl)
#
# The VS64 extension manages build/build.ninja for IDE builds; this
# Makefile is the command-line interface and covers the full pipeline.
# -----------------------------------------------------------------------

ROOT  := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
SRC   := $(ROOT)src
DEV   := $(ROOT)dev

CA65      ?= ca65
LD65      ?= ld65
PYTHON    ?= pipenv run python
PYTEST    ?= pipenv run pytest
VICE      ?= x64sc
C1541     ?= c1541
EXOMIZER  ?= exomizer
XMEGA65   ?= /Applications/xmega65.app/Contents/MacOS/xmega65

# ── Platform selection ───────────────────────────────────────────────────
# PLATFORM=c64 (default) builds the three C64 PRGs; PLATFORM=m65 builds
# the one m65 build, m65-45gs02, its D81 (release, disk), runs
# it in xmega65 (run) and reports it (size).  Any other platform is
# refused instead of silently building the C64 PRGs.  TARGET= on the command
# line is PLATFORM's synonym (make run TARGET=m65).  See
# doc/build_system.md § Builds and CPU sets.
ifeq ($(origin TARGET),command line)
  ifeq ($(origin PLATFORM),command line)
    ifneq ($(TARGET),$(PLATFORM))
      $(error TARGET=$(TARGET) and PLATFORM=$(PLATFORM) disagree: TARGET is a synonym of PLATFORM)
    endif
  endif
  override PLATFORM := $(TARGET)
endif
PLATFORM ?= c64
_NON_PRG_GOALS := help themes clean clean-tables tables m65-rom check-roms
ifeq ($(PLATFORM),m65)
  override CPU := 45gs02
else ifneq ($(PLATFORM),c64)
  ifneq ($(filter-out $(_NON_PRG_GOALS),$(or $(MAKECMDGOALS),all)),)
    $(error PLATFORM=$(PLATFORM): no PRG for this platform; PLATFORM=c64 and PLATFORM=m65 build PRGs)
  endif
endif

# ── CPU target selection ──────────────────────────────────────────────────
# CPU= selects target for run/disk/size.  release/debug build both.
# Each build serves a CPU set; DEFAULT_CPU is the asm_cpu it starts with
# (`.cpu` / `u` switch within the set).  See doc/build_system.md
# § Builds and CPU sets.
# make CPU=6502   → mn6 classifier; CPU set 6502; starts as 6502
# make CPU=6510   → mn7 classifier; CPU set 6502, 6510; starts as 6502
#                   (the default target)
# Any other CPU is refused.  No target has the 65C02: the assembler's CMOS
# mode (CPU_65C02, CMOS_SUPPORT) is built only as test bundles.
CPU ?= 6510

# ── ROM set selection ────────────────────────────────────────────────────
# ROMSET= selects KERNAL/BASIC/CHARGEN for 'make run'.
#   cbm   — rom/kernal_cbm.bin, basic_cbm.bin, chargen_cbm.bin (stock Commodore)
#   mega  — rom/kernal_mega.bin, basic_mega.bin, chargen_mega.bin
#           (MEGA65 Open-ROMs, C64-compatible build)
ROMSET ?= cbm

# Non-stock KERNALs need True Drive Emulation — VICE's virtual
# drive traps only recognise the stock KERNAL's serial routines.
ifeq ($(ROMSET),cbm)
  VICE_ROMFLAGS :=
else
  VICE_ROMFLAGS := -drive8truedrive
endif

# ── Per-CPU configuration ────────────────────────────────────────────────
# _cpu_defs, _mn_srcs, _subdir, _prg_name for each variant.

# TAB_WIDTH is a build-time constant for the editor's tab stop interval.
# A power of two in 1..32 (`col mod TAB_WIDTH` is `and #TAB_MASK`);
# any other value is a build error.  See doc/modules/editor.md.
TAB_WIDTH ?= 8

# The platform define: exactly one per assembly (doc/platform_layer.md
# § Platforms and defines).
_c64_PDEFS    = -DPLATFORM_C64
_m65_PDEFS    = -DPLATFORM_M65
PLATFORM_DEFS = $(_$(PLATFORM)_PDEFS)

_6510_DEFS    = -DCPU_6510 -DDEFAULT_CPU=0 -DCPU_CEIL=1 -DTAB_WIDTH=$(TAB_WIDTH)
_6510_MN      = mn7 mn7_tables
_6510_SUBDIR  = 6510
_6510_PRG     = cse.prg

_6502_DEFS    = -DCPU_6502 -DUSE_MN6 -DDEFAULT_CPU=0 -DCPU_CEIL=0 -DTAB_WIDTH=$(TAB_WIDTH)
_6502_MN      = mn6 mn6_tables
_6502_SUBDIR  = 6502
_6502_PRG     = cse-6502.prg

ifeq ($(PLATFORM),c64)
  ifeq ($(filter 6510 6502,$(CPU)),)
    ifneq ($(filter-out $(_NON_PRG_GOALS),$(or $(MAKECMDGOALS),all)),)
      $(error CPU=$(CPU): no such c64 build; CPU=6510 and CPU=6502 are)
    endif
  endif
endif

# the m65 build (PLATFORM=m65 sets CPU): 6502, 4510, 45GS02 at run time
_45gs02_DEFS  = -DCPU_45GS02 -DMEGA_SUPPORT -DDEFAULT_CPU=4 -DCPU_CEIL=4 -DTAB_WIDTH=$(TAB_WIDTH)
_45gs02_MN    = mn7 mn7_tables

# Resolve selected CPU (and platform: the m65 build has its own
# directory and name, doc/build_system.md § The m65 builds)
CPU_DEFS  = $(_$(CPU)_DEFS)
MN_SRCS   = $(_$(CPU)_MN)
ifeq ($(PLATFORM),m65)
  SUBDIR   = m65
  PRG_NAME = cse-m65.prg
else
  SUBDIR   = $(_$(CPU)_SUBDIR)
  PRG_NAME = $(_$(CPU)_PRG)
endif

# ── Build profile ────────────────────────────────────────────────────────
# _PROFILE selects debug or release (set by recursive make).
# Both profiles share the same _one sub-target; only BUILD dir and
# AFLAGS differ.
_PROFILE ?= release

ifeq ($(_PROFILE),debug)
  BUILD  = $(ROOT)build/debug/$(SUBDIR)
  AFLAGS = -g -t c64 -DDEBUG $(PLATFORM_DEFS) $(CPU_DEFS) $(THEME_DEFS) $(INTROSPECT_DEFS) -I$(ROOT) -I$(BUILD)
else
  BUILD  = $(ROOT)build/release/$(SUBDIR)
  AFLAGS = -t c64 $(PLATFORM_DEFS) $(CPU_DEFS) $(THEME_DEFS) $(INTROSPECT_DEFS) -I$(ROOT) -I$(BUILD)
endif

# ── Theme selection ──────────────────────────────────────────────────────
# make THEME=fc1  →  border=F bg=C fg=1 (CLOUDY, the default on every
# platform).  Predefined names: `make themes` (screen.md § Theme System
# owns the table), or a 3-digit hex code: make THEME=cb5
THEME ?= CLOUDY

# Named theme → 3-digit hex code
_THEME_MAP = CLOUDY=fc1 CONCRETE=fbf ASPHALT=fc0 JIFFY=e61 \
             GREENLAND=d51 MOSS=d5d RADIOACTIVITY=cb5 MATRIX=005 \
             HERCULES=009 MILKYWAY=001 BRUCELEE=770 LEEBRUCE=007 \
             MRSPIGGY=a21 ORANGE=880 MUDDY=990 C64=e6e C128=dbd MEGA=661
_THEME_CODE := $(patsubst $(THEME)=%,%,$(filter $(THEME)=%,$(_THEME_MAP)))
ifeq ($(_THEME_CODE),)
  _THEME_CODE := $(THEME)
endif

THEME_DEFS := $(shell printf '%s' "$(_THEME_CODE)" | sed 's/./& /g' | \
  awk '{split("0123456789abcdef",h,""); for(i=1;i<=16;i++)m[substr("0123456789abcdef",i,1)]=i-1; \
  printf "-DTHEME_BOR=%d -DTHEME_BG=%d -DTHEME_FG=%d", m[$$1], m[$$2], m[$$3]}')

# ── Version / build date ──────────────────────────────────────────────────
VERSION  ?= 0.1
BUILD_YEAR := $(shell date +%Y)

# ── Introspection flag ───────────────────────────────────────────────────
# INTROSPECT=1 drops the user-ZP redirect in `m` and `.` so those
# commands show CSE's live ZP as-is.  For CSE developers only — breaks
# the normal "m always means user ZP" contract (see repl.md § User-ZP
# view).  Works with both release and debug profiles.
#   make run INTROSPECT=1
#   make debug INTROSPECT=1
ifeq ($(INTROSPECT),1)
  INTROSPECT_DEFS := -DINTROSPECT
else
  INTROSPECT_DEFS :=
endif

# ── Linker config ────────────────────────────────────────────────────────
# c64: two passes (compute_layout.py); m65: src/m65_cse.cfg as it is.
TRIAL_CFG = $(SRC)/c64_trial.cfg
CFG_TMPL  = $(SRC)/c64_cse.cfg.in
ifeq ($(PLATFORM),m65)
  LCFG    = $(SRC)/m65_cse.cfg
else
  LCFG    = $(BUILD)/c64_cse.cfg
endif
LFLAGS    = -C $(LCFG)

# -----------------------------------------------------------------------
# all — default target (builds release)
# -----------------------------------------------------------------------
.PHONY: all
all: release

# -----------------------------------------------------------------------
# release — optimized builds + exomizer + distribution D64
# -----------------------------------------------------------------------
.PHONY: release
ifeq ($(PLATFORM),m65)
release:
	@$(MAKE) --no-print-directory _one PLATFORM=m65 _PROFILE=release _LABEL="m65   cse-m65.prg"
	@$(MAKE) --no-print-directory _d81
else
release:
	@$(MAKE) --no-print-directory _one CPU=6510  _PROFILE=release _LABEL="6510  cse.prg"
	@$(MAKE) --no-print-directory _one CPU=6502  _PROFILE=release _LABEL="6502  cse-6502.prg"
	@$(MAKE) --no-print-directory _dist
endif

# -----------------------------------------------------------------------
# debug — builds with -g debug info, full .lbl symbol files
# -----------------------------------------------------------------------
# The -g flag embeds debug symbols into .o files; ld65 -Ln then emits
# ALL labels (exported + internal + @local) in the .lbl file —
# typically ~2040 symbols vs ~410 without -g.
# No exomizer step for debug builds.
.PHONY: debug
ifeq ($(PLATFORM),m65)
debug:
	@$(MAKE) --no-print-directory _one PLATFORM=m65 _PROFILE=debug _LABEL="m65   cse-m65.prg"
else
debug:
	@$(MAKE) --no-print-directory _one CPU=6510  _PROFILE=debug _LABEL="6510  cse.prg"
	@$(MAKE) --no-print-directory _one CPU=6502  _PROFILE=debug _LABEL="6502  cse-6502.prg"
endif

# -----------------------------------------------------------------------
# _one — shared sub-target for a single CPU build (used by both profiles)
# -----------------------------------------------------------------------
PRG      = $(BUILD)/$(PRG_NAME)
PRG_EXO  = $(BUILD)/$(basename $(PRG_NAME))-exo.prg
DBG      = $(BUILD)/cse.dbg
MAP      = $(BUILD)/cse.map
LBL      = $(BUILD)/cse.lbl

# ── Build-flags stamp ───────────────────────────────────────────────────
# Object files don't depend on $(AFLAGS) naturally.  If the user changes
# THEME, TAB_WIDTH, etc. without touching any .s file, make thinks the
# .o files are up to date and re-uses them with the wrong flags.
# Workaround: write a stamp file containing all build-affecting flag
# values; if its contents differ, touch it so its mtime updates.
BUILD_FLAGS := PLATFORM=$(PLATFORM) CPU=$(CPU) THEME=$(THEME) TAB_WIDTH=$(TAB_WIDTH) PROFILE=$(_PROFILE) VERSION=$(VERSION) INTROSPECT=$(INTROSPECT)
FLAGS_STAMP := $(BUILD)/.build_flags
_PREV_FLAGS := $(shell cat $(FLAGS_STAMP) 2>/dev/null)
ifneq ($(_PREV_FLAGS),$(BUILD_FLAGS))
  $(shell mkdir -p $(BUILD) && printf '%s' '$(BUILD_FLAGS)' > $(FLAGS_STAMP))
endif

# ── All assembler source files (pure asm, no C) ─────────────────────
ASM_SRCS = zp loader main strings \
           asm_line asm_err asm_src mn_classify \
           $(MN_SRCS) \
           addr_mode mn_modes mn_asm_tables opcode_lookup \
           mem cse_io screen disk expr symtab dasm dasm_tables \
           breakpoints debugger gap_buffer repl editor log oplen_tbl
ASM_OBJS = $(patsubst %,$(BUILD)/src/%.o,$(ASM_SRCS))

.PHONY: _one
ifneq ($(or $(filter debug,$(_PROFILE)),$(filter m65,$(PLATFORM))),)
_one: $(PRG)
	@printf "  %s  %s bytes  lbl %s syms\n" \
	  "$(_LABEL)" "$$(wc -c < $(PRG) | tr -d ' ')" \
	  "$$(wc -l < $(LBL) | tr -d ' ')"
else
_one: $(PRG) $(PRG_EXO)
	@printf "  %s  %s bytes  exo %s bytes\n" \
	  "$(_LABEL)" "$$(wc -c < $(PRG) | tr -d ' ')" \
	  "$$(wc -c < $(PRG_EXO) | tr -d ' ')"
endif

# No trailing slash: make 3.81 stops matching the %.o pattern rule on a
# `dir/` order-only prerequisite once the first object created it.
$(BUILD)/src:
	mkdir -p $@

# Pattern rule: assemble src/*.s → build/{profile}/{cpu}/src/*.o
# ca65 --create-dep writes build/…/src/%.d: the object's prerequisites,
# i.e. its source plus every file it .includes (macros.inc, log.inc,
# dasm_mne_idx.s, version.inc).  A changed include therefore rebuilds
# exactly its includers.  The .d is itself a prerequisite (empty rule
# below), so an object without one — built before dependency tracking —
# is rebuilt once and gets one.
$(BUILD)/src/%.o: $(SRC)/%.s $(BUILD)/src/%.d $(FLAGS_STAMP) $(BUILD)/version.inc | $(BUILD)/src
	$(CA65) $(AFLAGS) --create-dep $(@:.o=.d) -o $@ $<

$(BUILD)/src/%.d: ;
.PRECIOUS: $(BUILD)/src/%.d

-include $(ASM_OBJS:.o=.d)

# The stamp file itself
$(FLAGS_STAMP): | $(BUILD)/
	@printf '%s' '$(BUILD_FLAGS)' > $@

# version.inc — ca65-includable file with VERSION_STRING macro,
# consumed by strings.s.  Regenerates when the flags stamp changes
# (VERSION is part of BUILD_FLAGS).
$(BUILD)/version.inc: $(FLAGS_STAMP) | $(BUILD)/
	@printf '.define VERSION_STRING %s\n' '"$(VERSION)"' > $@

# Two-pass link: trial measures sizes, compute_layout.py generates config
TRIAL_MAP = $(BUILD)/trial.map

ifneq ($(PLATFORM),m65)
$(TRIAL_MAP): $(ASM_OBJS) $(TRIAL_CFG) | $(BUILD)/
	$(LD65) -C $(TRIAL_CFG) -o $(BUILD)/trial.prg -m $@ $(ASM_OBJS)

$(LCFG): $(TRIAL_MAP) $(CFG_TMPL)
	$(PYTHON) $(DEV)/compute_layout.py $(TRIAL_MAP) $(CFG_TMPL) > $@
endif

$(PRG): $(ASM_OBJS) $(LCFG) | $(BUILD)/
	$(LD65) $(LFLAGS) -o $@ --dbgfile $(DBG) -m $(MAP) -Ln $(LBL) $(ASM_OBJS)

# Exomizer SFX: self-extracting compressed PRG (for disk distribution)
$(PRG_EXO): $(PRG)
	@command -v $(EXOMIZER) >/dev/null 2>&1 || { \
	  printf "\n  *** exomizer not found ***\n\n"; \
	  printf "  Install via Homebrew:  brew install exomizer\n"; \
	  printf "  Or from source:       https://bitbucket.org/magli143/exomizer\n\n"; \
	  exit 1; }
	$(EXOMIZER) sfx sys -n -q -o $@ $<

# -----------------------------------------------------------------------
# _dist — D64 distribution image with all three compressed variants
# -----------------------------------------------------------------------
_REL = $(ROOT)build/release
DIST_D64 = $(ROOT)build/cse.d64
DIST_D81 = $(ROOT)build/cse-m65.d81

# _d81 — the m65 distribution D81: the raw PRG as "cse-m65" (no exomizer)
.PHONY: _d81
_d81:
	@rm -f $(DIST_D81)
	$(C1541) -format "cse $(VERSION),01" d81 $(DIST_D81) \
	  -write $(_REL)/m65/cse-m65.prg cse-m65
	@echo "  disk  cse-m65.d81"

.PHONY: _dist
_dist:
	@rm -f $(DIST_D64)
	$(C1541) -format "cse $(VERSION),01" d64 $(DIST_D64) \
	  -write $(_REL)/6510/cse-exo.prg cse \
	  -write $(_REL)/6502/cse-6502-exo.prg cse-6502
	@echo "  disk  $$(c1541 -attach $(DIST_D64) -list 2>/dev/null | grep -c prg) files on cse.d64"

# -----------------------------------------------------------------------
# disk — single-CPU D64 (for quick iteration with make CPU=... disk);
#        m65: the release's D81
# -----------------------------------------------------------------------
# Uses the release profile.
D64 = $(ROOT)build/release/$(_$(CPU)_SUBDIR)/cse.d64

.PHONY: disk
ifeq ($(PLATFORM),m65)
disk: release
else
disk:
	@$(MAKE) --no-print-directory _one CPU=$(CPU) _PROFILE=release _LABEL="$(CPU) $(PRG_NAME)"
	@rm -f $(D64)
	$(C1541) -format "cse $(VERSION),01" d64 $(D64) \
	  -write $(ROOT)build/release/$(_$(CPU)_SUBDIR)/$(basename $(PRG_NAME))-exo.prg cse
endif

# -----------------------------------------------------------------------
# tables — regenerate generated .s table files from Python
# -----------------------------------------------------------------------
TABLE_GEN  = $(DEV)/mnemonic_tables.py $(DEV)/dasm_tables.py
TABLE_DEPS = $(DEV)/instruction_set.py $(DEV)/hashes.py
TABLE_OUTS = $(SRC)/mn_modes.s \
             $(SRC)/mn6_tables.s $(SRC)/mn7_tables.s \
             $(SRC)/mn_asm_tables.s $(SRC)/oplen_tbl.s $(SRC)/cpu_set.inc \
             $(SRC)/dasm_tables.s $(SRC)/dasm_mne_idx.s
TABLES_STAMP = $(ROOT)build/.tables.stamp

.PHONY: tables
tables: $(TABLES_STAMP)

# dasm_tables.py imports mnemonic_tables.py's CPU-set registry, so any
# generator change regenerates both.
$(TABLES_STAMP): $(TABLE_GEN) $(TABLE_DEPS) | $(ROOT)build/
	$(PYTHON) $(DEV)/mnemonic_tables.py
	$(PYTHON) $(DEV)/dasm_tables.py
	@touch $@

$(TABLE_OUTS): $(TABLES_STAMP)

# -----------------------------------------------------------------------
# run — build release, then launch in VICE (c64) or xmega65 (m65)
# -----------------------------------------------------------------------
# m65: xmega65 with the user's own configuration (SD image, ROM, keymap);
# -prg loads the PRG and RUNs it once BASIC 65 is up, -8 mounts the
# release's D81 on unit 8.  Never from
# automation: Tier X starts xmega65 -headless (tests/xmega65.py).
.PHONY: run
ifeq ($(PLATFORM),m65)
run: release
	$(XMEGA65) -prg $(ROOT)build/release/m65/cse-m65.prg -prgmode 65 -8 $(DIST_D81)
else
run: release
	$(VICE) -kernal $(KERNAL_IMG) -basic $(BASIC_IMG) -chargen $(CHARGEN_IMG) \
	  $(VICE_ROMFLAGS) \
	  -autostart $(ROOT)build/release/$(_$(CPU)_SUBDIR)/$(PRG_NAME) \
	  -8 $(DIST_D64)
endif

# -----------------------------------------------------------------------
# test — run pytest (requires both debug + release builds)
# -----------------------------------------------------------------------
.PHONY: test check-roms
ROM_DIR := $(ROOT)rom

KERNAL_IMG  := $(ROM_DIR)/kernal_$(ROMSET).bin
BASIC_IMG   := $(ROM_DIR)/basic_$(ROMSET).bin
CHARGEN_IMG := $(ROM_DIR)/chargen_$(ROMSET).bin

KERNAL_ROM := $(ROM_DIR)/kernal_cbm.bin

check-roms:
	@if [ ! -f "$(KERNAL_ROM)" ]; then \
	  printf "\n  *** C64 KERNAL ROM not found at rom/kernal_cbm.bin ***\n\n"; \
	  printf "  Copy the C64 ROMs from your VICE installation into rom/:\n\n"; \
	  printf "    cp <VICE>/C64/kernal-901227-03.bin rom/kernal_cbm.bin\n"; \
	  printf "    cp <VICE>/C64/basic-901226-01.bin  rom/basic_cbm.bin\n"; \
	  printf "    cp <VICE>/C64/chargen-901225-01.bin rom/chargen_cbm.bin\n\n"; \
	  printf "  Common <VICE> locations:\n"; \
	  printf "    macOS (Homebrew): /opt/homebrew/share/vice\n"; \
	  printf "    Linux:            /usr/share/vice\n\n"; \
	  exit 1; \
	fi

# m65-rom — copy the MEGA65 ROM from xmega65's data directory into rom/
.PHONY: m65-rom
m65-rom:
	$(PYTHON) $(DEV)/find_m65_rom.py

test: debug release check-roms
	$(PYTEST) -v

# -----------------------------------------------------------------------
# size — exhaustive size breakdown of selected PRG (release profile)
# -----------------------------------------------------------------------
.PHONY: size
ifeq ($(PLATFORM),m65)
size:
	@$(MAKE) --no-print-directory _one PLATFORM=m65 _PROFILE=release _LABEL="m65   cse-m65.prg"
	@BUILD=$(ROOT)build/release/m65 PRG=$(ROOT)build/release/m65/cse-m65.prg $(PYTHON) $(DEV)/size_report.py --platform m65
else
size:
	@$(MAKE) --no-print-directory _one CPU=$(CPU) _PROFILE=release _LABEL="$(CPU) $(PRG_NAME)"
	@BUILD=$(ROOT)build/release/$(_$(CPU)_SUBDIR) $(PYTHON) $(DEV)/size_report.py
endif

# -----------------------------------------------------------------------
# clean
# -----------------------------------------------------------------------
.PHONY: clean
clean:
	rm -rf $(ROOT)build

.PHONY: clean-tables
clean-tables:
	rm -f $(TABLE_OUTS) $(TABLES_STAMP)

# -----------------------------------------------------------------------
# Directory order-only prerequisites
# -----------------------------------------------------------------------
$(BUILD)/:
	mkdir -p $@

$(ROOT)build/:
	mkdir -p $@

# -----------------------------------------------------------------------
# help / themes
# -----------------------------------------------------------------------
.PHONY: themes
themes:
	@echo "Available themes (make THEME=NAME):"
	@echo ""
	@c="black white red cyan purple green blue yellow orange brown lt_red dk_grey grey lt_green lt_blue lt_grey"; \
	for t in $(_THEME_MAP); do \
	  name=$${t%%=*}; code=$${t##*=}; \
	  b=$$(echo $$c | awk -v i=$$((16#$${code:0:1}+1)) '{print $$i}'); \
	  g=$$(echo $$c | awk -v i=$$((16#$${code:1:1}+1)) '{print $$i}'); \
	  f=$$(echo $$c | awk -v i=$$((16#$${code:2:1}+1)) '{print $$i}'); \
	  printf "  %-15s %s  %s / %s / %s\n" "$$name" "$$code" "$$b" "$$g" "$$f"; \
	done
	@echo ""
	@echo "Or use any 3-digit hex code: make THEME=f0f"

.PHONY: help
help:
	@printf "%-15s %s\n" "all"          "Build release (default)"
	@printf "%-15s %s\n" "release"      "Build all three CPU targets, optimized + exomizer + D64"
	@printf "%-15s %s\n" ""             "  build/release/{6510,6502}/cse*.prg"
	@printf "%-15s %s\n" "debug"        "Build all three CPU targets with -g (full symbols)"
	@printf "%-15s %s\n" ""             "  build/debug/{6510,6502}/cse*.prg"
	@printf "%-15s %s\n" "disk"         "Create D64 with compressed PRG (CPU=6510|6502); PLATFORM=m65: the D81"
	@printf "%-15s %s\n" "run"          "Build release + launch in VICE (CPU=, ROMSET=cbm|mega); PLATFORM=m65: xmega65"
	@printf "%-15s %s\n" "tables"       "Regenerate the generated tables in src/ (both generators)"
	@printf "%-15s %s\n" "test"         "Run all pytest tests (builds both debug + release)"
	@printf "%-15s %s\n" "check-roms"   "Fail with copy instructions if rom/kernal_cbm.bin is missing"
	@printf "%-15s %s\n" "size"         "Size breakdown of selected PRG (CPU=)"
	@printf "%-15s %s\n" "m65-rom"      "Copy the MEGA65 ROM from xmega65's data into rom/mega65.rom"
	@printf "%-15s %s\n" "clean"        "Remove the build/ directory"
	@printf "%-15s %s\n" "clean-tables" "Remove generated table sources in src/"
	@printf "%-15s %s\n" "themes"       "List available color themes"
	@printf "%-15s %s\n" "help"         "Show this message"
	@printf "\nOptions (prefix any target):\n"
	@printf "  %-20s %s\n" "PLATFORM=c64|m65"    "platform (default: c64; m65: one PRG, its D81)"
	@printf "  %-20s %s\n" "CPU=6510|6502" "target CPU (default: 6510)"
	@printf "  %-20s %s\n" "THEME=NAME|BGF"      "colour theme (default: CLOUDY)"
	@printf "  %-20s %s\n" "TAB_WIDTH=N"         "editor tab width, 1|2|4|8|16|32 (default: 8)"
	@printf "  %-20s %s\n" "VERSION=STRING"      "version string (default: 0.1)"
	@printf "  %-20s %s\n" "ROMSET=cbm|mega"     "KERNAL set for 'run' (default: cbm)"
	@printf "  %-20s %s\n" "INTROSPECT=1"        "disable user-ZP redirect in m/. (CSE devs only)"
