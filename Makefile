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

CA65   ?= ca65
LD65   ?= ld65
CC65   ?= cc65
PYTHON ?= pipenv run python
PYTEST ?= pipenv run pytest
VICE   ?= x64sc
C1541  ?= c1541

# ── CPU target selection ──────────────────────────────────────────────────
# CPU= selects target for run/disk/size.  'all' builds all three.
# make CPU=6502   → MN6 assembler, disassembler in 6502 mode
# make CPU=6510   → MN7 assembler, disassembler in 6510 mode (default)
# make CPU=65c02  → MN7 assembler + CMOS, disassembler in 65C02 mode
CPU ?= 6510

# ── Per-CPU configuration ────────────────────────────────────────────────
# _cpu_defs, _mn_srcs, _build_dir, _prg_name for each variant.

_6510_DEFS    = -DCPU_6510 -DDEFAULT_CPU=0 -DCPU_CEIL=1
_6510_MN      = mn7 mn7_tables
_6510_DIR     = $(ROOT)build/6510
_6510_PRG     = cse.prg

_6502_DEFS    = -DCPU_6502 -DUSE_MN6 -DDEFAULT_CPU=0 -DCPU_CEIL=0
_6502_MN      = mn6 mn6_tables
_6502_DIR     = $(ROOT)build/6502
_6502_PRG     = cse-6502.prg

_65c02_DEFS   = -DCPU_65C02 -DCMOS_SUPPORT -DDEFAULT_CPU=2 -DCPU_CEIL=2
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

# ── CC65 flags ───────────────────────────────────────────────────────────
VER_DEFS = -DVERSION=\"$(VERSION)\" -DBUILD_YEAR=\"$(BUILD_YEAR)\"
ifdef DEBUG
  CFLAGS = -g -O -t c64 -DDEBUG -D__cc65__ $(CPU_DEFS) $(VER_DEFS) -I$(ROOT) -I$(BUILD)
  AFLAGS = -g -t c64 -DDEBUG -D__cc65__ $(CPU_DEFS) $(THEME_DEFS) -I$(ROOT) -I$(BUILD)
else
  CFLAGS = -O -t c64 -D__cc65__ $(CPU_DEFS) $(VER_DEFS) -I$(ROOT) -I$(BUILD)
  AFLAGS = -t c64 -D__cc65__ $(CPU_DEFS) $(THEME_DEFS) -I$(ROOT) -I$(BUILD)
endif
LCFG   = $(SRC)/c64_cse.cfg
LFLAGS = -C $(LCFG)

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

# -----------------------------------------------------------------------
# _one — build a single CPU target (called by 'all' or directly)
# -----------------------------------------------------------------------
PRG    = $(BUILD)/$(PRG_NAME)
DBG    = $(BUILD)/cse.dbg
MAP    = $(BUILD)/cse.map
MAIN_S = $(BUILD)/src/main.s
MAIN_O = $(BUILD)/src/main.o

# ── C source files (besides main.c) ──────────────────────────────
C_SRCS   = editor repl
C_OBJS   = $(patsubst %,$(BUILD)/src/%.o,$(C_SRCS))

# ── Assembler source files linked into cse.prg ──────────────────────
ASM_SRCS = asm_bridge asm_line asm_vars asm_src mn_vars mn_classify \
           $(MN_SRCS) mn_config \
           au_mode mn_modes mn_asm_tables opcode_lookup \
           meminfo cse_io screen disk expr symtab dasm dasm_tables \
           debugger
ASM_OBJS = $(patsubst %,$(BUILD)/src/%.o,$(ASM_SRCS))

.PHONY: _one
_one: $(PRG)
	@echo "  $(TARGET)  $(shell wc -c < $(PRG)) bytes"

$(BUILD)/src/:
	mkdir -p $@

$(MAIN_S): $(SRC)/main.c | $(BUILD)/src/
	$(CC65) $(CFLAGS) -o $@ $<

$(MAIN_O): $(MAIN_S)
	$(CA65) $(AFLAGS) -o $@ $<

# Pattern rule: compile + assemble src/*.c → build/CPU/src/*.o
$(BUILD)/src/%.o: $(SRC)/%.c | $(BUILD)/src/
	$(CC65) $(CFLAGS) -o $(BUILD)/src/$*.s $<
	$(CA65) $(AFLAGS) -o $@ $(BUILD)/src/$*.s

# Pattern rule: assemble src/*.s → build/CPU/src/*.o
$(BUILD)/src/%.o: $(SRC)/%.s | $(BUILD)/src/
	$(CA65) $(AFLAGS) -o $@ $<

$(PRG): $(MAIN_O) $(C_OBJS) $(ASM_OBJS) | $(BUILD)/
	$(LD65) $(LFLAGS) -o $@ --dbgfile $(DBG) -m $(MAP) $(MAIN_O) $(C_OBJS) $(ASM_OBJS) c64.lib

# -----------------------------------------------------------------------
# disk — create a D64 disk image with the selected CPU's PRG
# -----------------------------------------------------------------------
D64 = $(BUILD)/cse.d64

.PHONY: disk
disk: $(PRG)
	@if [ -f $(D64) ]; then \
		$(C1541) -attach $(D64) -delete cse -write $(PRG) cse; \
	else \
		$(C1541) -format "cse,01" d64 $(D64) -write $(PRG) cse; \
	fi

# -----------------------------------------------------------------------
# tables — regenerate generated .s table files from Python
# -----------------------------------------------------------------------
TABLE_GEN  = $(DEV)/mnemonic_tables.py
TABLE_DEPS = $(DEV)/instruction_set.py $(DEV)/hashes.py
TABLE_OUTS = $(SRC)/mn_modes.s $(SRC)/mn_config.s \
             $(SRC)/mn6_tables.s $(SRC)/mn7_tables.s \
             $(SRC)/mn_asm_tables.s
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

# au_mode ----------------------------------------------------------------
AU_BIN = $(ROOT)build/au_mode_test.bin
AU_MAP = $(ROOT)build/au_mode_test.map
AU_LST = $(ROOT)build/au_mode_test.lst
AU_O1  = $(ROOT)build/au_mode.o
AU_O2  = $(ROOT)build/au_mode_test_stub.o

$(AU_O1): $(SRC)/au_mode.s | $(ROOT)build/
	$(T65) --listing $(AU_LST) $< -o $@

$(AU_O2): $(DEV)/au_mode_test_stub.s | $(ROOT)build/
	$(T65) $< -o $@

$(AU_BIN): $(AU_O1) $(AU_O2) $(DEV)/test.cfg
	$(LD65) -C $(DEV)/test.cfg $(AU_O1) $(AU_O2) -o $@ -m $(AU_MAP)

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
test-bins: $(AU_BIN) $(MN6_BIN) $(MN7_BIN)

# -----------------------------------------------------------------------
# run — build disk image and launch in VICE
# -----------------------------------------------------------------------
.PHONY: run
run: disk
	$(VICE) -autostart $(PRG) -8 $(D64)

# -----------------------------------------------------------------------
# test — run pytest (conftest.py rebuilds test binaries if needed)
# -----------------------------------------------------------------------
.PHONY: test
test:
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
	@printf "%-15s %s\n" "disk"         "Create D64 disk image (CPU=6510|6502|65c02)"
	@printf "%-15s %s\n" "run"          "Build + launch in VICE (CPU=6510|6502|65c02)"
	@printf "%-15s %s\n" "tables"       "Regenerate src/mn*_tables.s via mnemonic_tables.py"
	@printf "%-15s %s\n" "test"         "Run all pytest tests"
	@printf "%-15s %s\n" "test-bins"    "Assemble au_mode / mn6 / mn7 test binaries"
	@printf "%-15s %s\n" "size"         "Size breakdown of selected PRG (CPU=)"
	@printf "%-15s %s\n" "clean"        "Remove the build/ directory"
	@printf "%-15s %s\n" "clean-tables" "Remove generated table sources in src/"
	@printf "%-15s %s\n" "themes"       "List available color themes"
	@printf "%-15s %s\n" "help"         "Show this message"
