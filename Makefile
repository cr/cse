# -----------------------------------------------------------------------
# Makefile — CSE 6502 assembler
#
# Targets
#   all          Build all three CPU targets (default)
#   tables       Regenerate src/mn*_tables.s and src/mn_{modes,config}.s
#   test         Run all pytest tests
#   test-bins    Assemble the three py65 test binaries
#   disk         Create D64 disk image (uses CPU= for PRG selection)
#   run          Build disk image and launch in VICE
#   size         Exhaustive size breakdown of selected PRG
#   clean        Remove build/
#   clean-tables Remove generated table sources in src/
#   help         Show this message
#
# CPU= selects the target for run/disk/size (default: 6510).
# The 'all' target always builds all three variants:
#   build/6510/cse.prg       (CPU 6510, default)
#   build/6502/cse-6502.prg  (CPU 6502)
#   build/cmos/cse-cmos.prg  (CPU 65C02)
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

# ── CPU target selection ──────────────────────────────────────────────────
# CPU= selects target for run/disk/size.  'all' builds all three.
# make CPU=6502   → MN6 assembler, disassembler in 6502 mode
# make CPU=6510   → MN7 assembler, disassembler in 6510 mode (default)
# make CPU=65c02  → MN7 assembler + CMOS, disassembler in 65C02 mode
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
# _cpu_defs, _mn_srcs, _build_dir, _prg_name for each variant.

# TAB_WIDTH is a build-time constant for the editor's tab stop interval.
# Power-of-two values get a fast `and #TAB_MASK` modulo; other values
# assemble but pay a runtime loop.  See doc/modules/editor.md.
TAB_WIDTH ?= 8

_6510_DEFS    = -DCPU_6510 -DDEFAULT_CPU=0 -DCPU_CEIL=1 -DTAB_WIDTH=$(TAB_WIDTH)
_6510_MN      = mn7 mn7_tables
_6510_DIR     = $(ROOT)build/6510
_6510_PRG     = cse.prg

_6502_DEFS    = -DCPU_6502 -DUSE_MN6 -DDEFAULT_CPU=0 -DCPU_CEIL=0 -DTAB_WIDTH=$(TAB_WIDTH)
_6502_MN      = mn6 mn6_tables
_6502_DIR     = $(ROOT)build/6502
_6502_PRG     = cse-6502.prg

_65c02_DEFS   = -DCPU_65C02 -DCMOS_SUPPORT -DDEFAULT_CPU=2 -DCPU_CEIL=2 -DTAB_WIDTH=$(TAB_WIDTH)
_65c02_MN     = mn7 mn7_tables
_65c02_DIR    = $(ROOT)build/cmos
_65c02_PRG    = cse-cmos.prg

# Resolve selected CPU for single-target commands (run, disk, size)
CPU_DEFS  = $(_$(CPU)_DEFS)
MN_SRCS   = $(_$(CPU)_MN)
BUILD     = $(_$(CPU)_DIR)
PRG_NAME  = $(_$(CPU)_PRG)

# ── Theme selection ──────────────────────────────────────────────────────
# make THEME=d5d  →  border=D bg=5 fg=D (GREENLAND, default)
# Predefined names:
#   RADIOACTIVITY GREENLAND MRSPIGGY BRUCELEE LEEBRUCE MATRIX
#   MILKYWAY HERCULES ORANGE MUDDY CLOUDY C64 C128
#   or a 3-digit hex code: make THEME=cb5
THEME ?= GREENLAND

# Named theme → 3-digit hex code
_THEME_MAP = RADIOACTIVITY=cb5 GREENLAND=d5d MRSPIGGY=a21 BRUCELEE=770 \
             LEEBRUCE=007 MATRIX=005 MILKYWAY=001 HERCULES=009 \
             ORANGE=880 MUDDY=990 CLOUDY=cbc C64=e6e C128=dbd
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

# ── Assembler flags ──────────────────────────────────────────────────────
ifdef DEBUG
  AFLAGS = -g -t c64 -DDEBUG $(CPU_DEFS) $(THEME_DEFS) -I$(ROOT) -I$(BUILD)
else
  AFLAGS = -t c64 $(CPU_DEFS) $(THEME_DEFS) -I$(ROOT) -I$(BUILD)
endif
TRIAL_CFG = $(SRC)/c64_trial.cfg
CFG_TMPL  = $(SRC)/c64_cse.cfg.in
LCFG      = $(BUILD)/c64_cse.cfg
LFLAGS    = -C $(LCFG)

# ── Test-binary flags (bare 6502, no C64 platform defs) ─────────────────
T65 = $(CA65) --cpu 6502

# -----------------------------------------------------------------------
# all — build all three CPU targets
# -----------------------------------------------------------------------
.PHONY: all
all:
	@$(MAKE) --no-print-directory CPU=6510  _one TARGET="6510  cse.prg"
	@$(MAKE) --no-print-directory CPU=6502  _one TARGET="6502  cse-6502.prg"
	@$(MAKE) --no-print-directory CPU=65c02 _one TARGET="65c02 cse-cmos.prg"
	@$(MAKE) --no-print-directory _dist

# -----------------------------------------------------------------------
# _one — build a single CPU target (called by 'all' or directly)
# -----------------------------------------------------------------------
PRG      = $(BUILD)/$(PRG_NAME)
PRG_EXO  = $(BUILD)/$(basename $(PRG_NAME))-exo.prg
DBG      = $(BUILD)/cse.dbg
MAP      = $(BUILD)/cse.map
LBL      = $(BUILD)/cse.lbl

# ── Build-flags stamp ───────────────────────────────────────────────────
# Object files don't depend on $(AFLAGS) naturally.  If the user changes
# THEME, TAB_WIDTH, DEBUG, etc. without touching any .s file, make
# thinks the .o files are up to date and re-uses them with the wrong
# flags.  Workaround: write a stamp file containing all build-affecting
# flag values; if its contents differ, touch it so its mtime updates;
# every object rule depends on the stamp.
BUILD_FLAGS := CPU=$(CPU) THEME=$(THEME) TAB_WIDTH=$(TAB_WIDTH) DEBUG=$(DEBUG) VERSION=$(VERSION)
FLAGS_STAMP := $(BUILD)/.build_flags
_PREV_FLAGS := $(shell cat $(FLAGS_STAMP) 2>/dev/null)
ifneq ($(_PREV_FLAGS),$(BUILD_FLAGS))
  $(shell mkdir -p $(BUILD) && printf '%s' '$(BUILD_FLAGS)' > $(FLAGS_STAMP))
endif

# ── All assembler source files (pure asm, no C) ─────────────────────
ASM_SRCS = loader main \
           asm_line asm_vars asm_src mn_vars mn_classify \
           $(MN_SRCS) mn_config \
           au_mode mn_modes mn_asm_tables opcode_lookup \
           mem cse_io screen disk expr symtab dasm dasm_tables \
           debugger repl editor oplen_tbl
ASM_OBJS = $(patsubst %,$(BUILD)/src/%.o,$(ASM_SRCS))

.PHONY: _one
_one: $(PRG) $(PRG_EXO)
	@printf "  %s  %s bytes  exo %s bytes\n" \
	  "$(TARGET)" "$$(wc -c < $(PRG) | tr -d ' ')" \
	  "$$(wc -c < $(PRG_EXO) | tr -d ' ')"

$(BUILD)/src/:
	mkdir -p $@

# Pattern rule: assemble src/*.s → build/CPU/src/*.o
# Every object also depends on $(FLAGS_STAMP) so that a change to
# THEME / TAB_WIDTH / CPU / DEBUG triggers rebuilds even when the
# .s source itself is unchanged.
$(BUILD)/src/%.o: $(SRC)/%.s $(FLAGS_STAMP) | $(BUILD)/src/
	$(CA65) $(AFLAGS) -o $@ $<

# The stamp file itself: a rule so make knows it exists, but the
# actual content writing happens at parse time above.  The rule is
# a no-op target that just makes the file present for the dep check.
$(FLAGS_STAMP): | $(BUILD)/
	@printf '%s' '$(BUILD_FLAGS)' > $@

# Two-pass link: trial measures sizes, compute_layout.py generates config
TRIAL_MAP = $(BUILD)/trial.map

$(TRIAL_MAP): $(ASM_OBJS) $(TRIAL_CFG) | $(BUILD)/
	$(LD65) -C $(TRIAL_CFG) -o $(BUILD)/trial.prg -m $@ $(ASM_OBJS)

$(LCFG): $(TRIAL_MAP) $(CFG_TMPL)
	$(PYTHON) $(DEV)/compute_layout.py $(TRIAL_MAP) $(CFG_TMPL) > $@

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
DIST_D64 = $(ROOT)build/cse.d64

.PHONY: _dist
_dist:
	@rm -f $(DIST_D64)
	$(C1541) -format "cse,01" d64 $(DIST_D64) \
	  -write $(_6510_DIR)/cse-exo.prg cse \
	  -write $(_6502_DIR)/cse-6502-exo.prg cse-6502 \
	  -write $(_65c02_DIR)/cse-cmos-exo.prg cse-cmos
	@echo "  disk  $$(c1541 -attach $(DIST_D64) -list 2>/dev/null | grep -c prg) files on cse.d64"

# -----------------------------------------------------------------------
# disk — single-CPU D64 (for quick iteration with make CPU=... disk)
# -----------------------------------------------------------------------
D64 = $(BUILD)/cse.d64

.PHONY: disk
disk: $(PRG_EXO)
	@rm -f $(D64)
	$(C1541) -format "cse,01" d64 $(D64) -write $(PRG_EXO) cse

# -----------------------------------------------------------------------
# tables — regenerate generated .s table files from Python
# -----------------------------------------------------------------------
TABLE_GEN  = $(DEV)/mnemonic_tables.py
TABLE_DEPS = $(DEV)/instruction_set.py $(DEV)/hashes.py
TABLE_OUTS = $(SRC)/mn_modes.s $(SRC)/mn_config.s \
             $(SRC)/mn6_tables.s $(SRC)/mn7_tables.s \
             $(SRC)/mn_asm_tables.s $(SRC)/oplen_tbl.s
TABLES_STAMP = $(ROOT)build/.tables.stamp

.PHONY: tables
tables: $(TABLES_STAMP)

$(TABLES_STAMP): $(TABLE_GEN) $(TABLE_DEPS) | $(ROOT)build/
	$(PYTHON) $(TABLE_GEN)
	@touch $@

$(TABLE_OUTS): $(TABLES_STAMP)

# -----------------------------------------------------------------------
# test-bins — assemble the three py65 unit-test binaries
# -----------------------------------------------------------------------

# (au_mode test binary removed — now part of asm_core bundle built by conftest.py)

# mn6 --------------------------------------------------------------------
MN6_BIN = $(ROOT)build/mn6_test.bin
MN6_MAP = $(ROOT)build/mn6_test.map
MN6_LST = $(ROOT)build/mn6_classify.lst
MN6_O1  = $(ROOT)build/mn_vars_mn6.o
MN6_O2  = $(ROOT)build/mn6_mn6.o
MN6_O3  = $(ROOT)build/mn6_tables_mn6.o

$(MN6_O1): $(SRC)/mn_vars.s | $(ROOT)build/
	$(T65) $< -o $@

$(MN6_O2): $(SRC)/mn6.s | $(ROOT)build/
	$(T65) --listing $(MN6_LST) $< -o $@

$(MN6_O3): $(SRC)/mn6_tables.s | $(ROOT)build/
	$(T65) $< -o $@

$(MN6_BIN): $(MN6_O1) $(MN6_O2) $(MN6_O3) $(DEV)/test.cfg
	$(LD65) -C $(DEV)/test.cfg $(MN6_O1) $(MN6_O2) $(MN6_O3) -o $@ -m $(MN6_MAP)

# mn7 --------------------------------------------------------------------
MN7_BIN = $(ROOT)build/mn7_test.bin
MN7_MAP = $(ROOT)build/mn7_test.map
MN7_LST = $(ROOT)build/mn7_classify.lst
MN7_O1  = $(ROOT)build/mn_vars_mn7.o
MN7_O2  = $(ROOT)build/mn7_mn7.o
MN7_O3  = $(ROOT)build/mn7_tables_mn7.o

$(MN7_O1): $(SRC)/mn_vars.s | $(ROOT)build/
	$(T65) $< -o $@

$(MN7_O2): $(SRC)/mn7.s | $(ROOT)build/
	$(T65) --listing $(MN7_LST) $< -o $@

$(MN7_O3): $(SRC)/mn7_tables.s | $(ROOT)build/
	$(T65) $< -o $@

$(MN7_BIN): $(MN7_O1) $(MN7_O2) $(MN7_O3) $(DEV)/test.cfg
	$(LD65) -C $(DEV)/test.cfg $(MN7_O1) $(MN7_O2) $(MN7_O3) -o $@ -m $(MN7_MAP)

.PHONY: test-bins
test-bins: $(MN6_BIN) $(MN7_BIN)

# -----------------------------------------------------------------------
# run — build disk image and launch in VICE
# -----------------------------------------------------------------------
.PHONY: run
run: all
	$(VICE) -kernal $(KERNAL_IMG) -basic $(BASIC_IMG) -chargen $(CHARGEN_IMG) \
	  $(VICE_ROMFLAGS) -autostart $(PRG) -8 $(DIST_D64)

# -----------------------------------------------------------------------
# test — run pytest (conftest.py rebuilds test binaries if needed)
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

test: check-roms
	$(PYTEST) tests/ -v

# -----------------------------------------------------------------------
# size — exhaustive size breakdown of selected PRG
# -----------------------------------------------------------------------
.PHONY: size
size: $(PRG)
	@BUILD=$(BUILD) $(PYTHON) $(DEV)/size_report.py

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
	@printf "%-15s %s\n" "all"          "Build all three CPU targets (default)"
	@printf "%-15s %s\n" ""             "  build/6510/cse.prg  build/6502/cse-6502.prg  build/cmos/cse-cmos.prg"
	@printf "%-15s %s\n" "disk"         "Create D64 with compressed PRG (CPU=6510|6502|65c02)"
	@printf "%-15s %s\n" "run"          "Build + launch in VICE (CPU=, ROMSET=cbm|mega)"
	@printf "%-15s %s\n" "tables"       "Regenerate src/mn*_tables.s via mnemonic_tables.py"
	@printf "%-15s %s\n" "test"         "Run all pytest tests"
	@printf "%-15s %s\n" "test-bins"    "Assemble au_mode / mn6 / mn7 test binaries"
	@printf "%-15s %s\n" "size"         "Size breakdown of selected PRG (CPU=)"
	@printf "%-15s %s\n" "clean"        "Remove the build/ directory"
	@printf "%-15s %s\n" "clean-tables" "Remove generated table sources in src/"
	@printf "%-15s %s\n" "themes"       "List available color themes"
	@printf "%-15s %s\n" "help"         "Show this message"
