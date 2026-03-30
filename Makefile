# -----------------------------------------------------------------------
# Makefile — CSE 6502 assembler
#
# Targets
#   all          Build cse.prg  (default)
#   tables       Regenerate src/mn*_tables.s and src/mn_{modes,config}.s
#   test         Run all pytest tests
#   test-bins    Assemble the three py65 test binaries
#   clean        Remove build/
#   clean-tables Remove generated table sources in src/
#   help         Show this message
#
# The VS64 extension manages build/build.ninja for IDE builds; this
# Makefile is the command-line interface and covers the full pipeline.
# -----------------------------------------------------------------------

ROOT  := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
BUILD := $(ROOT)build
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
# make CPU=6502   → MN6 assembler, disassembler in 6502 mode
# make CPU=6510   → MN7 assembler, disassembler in 6510 mode (default)
# make CPU=65c02  → MN7 assembler + CMOS, disassembler in 65C02 mode
CPU ?= 6510

ifeq ($(CPU),6502)
  CPU_DEFS   = -DCPU_6502 -DUSE_MN6 -DDEFAULT_CPU=0 -DCPU_CEIL=0
  MN_SRCS    = mn6 mn6_tables
else ifeq ($(CPU),65c02)
  CPU_DEFS   = -DCPU_65C02 -DCMOS_SUPPORT -DDEFAULT_CPU=2 -DCPU_CEIL=2
  MN_SRCS    = mn7 mn7_tables
else
  # 6510 (default): start in clean 6502 mode, upgradeable to 6510
  CPU_DEFS   = -DCPU_6510 -DDEFAULT_CPU=0 -DCPU_CEIL=1
  MN_SRCS    = mn7 mn7_tables
endif

# ── Theme selection ──────────────────────────────────────────────────────
# make THEME=cb5  →  border=C bg=B fg=5 (RADIOACTIVITY, default)
# Auto-rebuilds screen.o when THEME changes (stamp file).
# Predefined names:
#   RADIOACTIVITY GREENLAND MRSPIGGY BRUCELEE LEEBRUCE MATRIX
#   MILKYWAY HERCULES ORANGE MUDDY CLOUDY C64 C128
#   or a 3-digit hex code: make THEME=cb5
THEME ?= RADIOACTIVITY

# Named theme → 3-digit hex code
_THEME_MAP = RADIOACTIVITY=cb5 GREENLAND=d5d MRSPIGGY=a21 BRUCELEE=770 \
             LEEBRUCE=007 MATRIX=005 MILKYWAY=001 HERCULES=009 \
             ORANGE=880 MUDDY=990 CLOUDY=cbc C64=e6e C128=dbd
_THEME_CODE := $(patsubst $(THEME)=%,%,$(filter $(THEME)=%,$(_THEME_MAP)))
# If no match in map, treat THEME as a raw 3-digit hex code
ifeq ($(_THEME_CODE),)
  _THEME_CODE := $(THEME)
endif

THEME_DEFS := $(shell printf '%s' "$(_THEME_CODE)" | sed 's/./& /g' | \
  awk '{split("0123456789abcdef",h,""); for(i=1;i<=16;i++)m[substr("0123456789abcdef",i,1)]=i-1; \
  printf "-DTHEME_BOR=%d -DTHEME_BG=%d -DTHEME_FG=%d", m[$$1], m[$$2], m[$$3]}')

# ── Version / build date ──────────────────────────────────────────────────
VERSION  ?= 0.1
BUILD_YEAR := $(shell date +%Y)

# ── CC65 main-binary flags ───────────────────────────────────────────────
# -O for size optimization; add -g -DDEBUG with: make DEBUG=1
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
# all — main C64 binary
# -----------------------------------------------------------------------
PRG    = $(BUILD)/cse.prg
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
           au_mode parse_hex mn_modes mn_asm_tables opcode_lookup \
           meminfo cse_io screen disk expr symtab dasm dasm_tables \
           debugger
ASM_OBJS = $(patsubst %,$(BUILD)/src/%.o,$(ASM_SRCS))

# ── CPU change detection ─────────────────────────────────────────────────
# Force rebuild when CPU= changes between invocations.
CPU_STAMP = $(BUILD)/.cpu_stamp

.PHONY: all
all: $(PRG)

$(BUILD)/src/:
	mkdir -p $@

# If the CPU stamp doesn't match, wipe and restart.
# Uses $(shell) so it runs before dependency evaluation.
_PREV_CPU := $(shell cat $(CPU_STAMP) 2>/dev/null)
ifneq ($(_PREV_CPU),$(CPU))
  $(shell mkdir -p $(BUILD) && rm -f $(BUILD)/src/*.o $(BUILD)/src/*.s $(PRG) $(D64))
  $(info CPU changed: $(_PREV_CPU) -> $(CPU))
endif
$(shell mkdir -p $(BUILD) && echo "$(CPU)" > $(CPU_STAMP))

# If THEME changes, rebuild screen.o (the only consumer).
THEME_STAMP = $(BUILD)/.theme_stamp
_PREV_THEME := $(shell cat $(THEME_STAMP) 2>/dev/null)
ifneq ($(_PREV_THEME),$(THEME))
  $(shell rm -f $(BUILD)/src/screen.o)
endif
$(shell mkdir -p $(BUILD) && echo "$(THEME)" > $(THEME_STAMP))

$(MAIN_S): $(SRC)/main.c | $(BUILD)/src/
	$(CC65) $(CFLAGS) -o $@ $<

$(MAIN_O): $(MAIN_S)
	$(CA65) $(AFLAGS) -o $@ $<

# Pattern rule: compile + assemble src/*.c → build/src/*.o
$(BUILD)/src/%.o: $(SRC)/%.c | $(BUILD)/src/
	$(CC65) $(CFLAGS) -o $(BUILD)/src/$*.s $<
	$(CA65) $(AFLAGS) -o $@ $(BUILD)/src/$*.s

# Pattern rule: assemble src/*.s → build/src/*.o
$(BUILD)/src/%.o: $(SRC)/%.s | $(BUILD)/src/
	$(CA65) $(AFLAGS) -o $@ $<

$(PRG): $(MAIN_O) $(C_OBJS) $(ASM_OBJS) | $(BUILD)/
	$(LD65) $(LFLAGS) -o $@ --dbgfile $(DBG) -m $(MAP) $(MAIN_O) $(C_OBJS) $(ASM_OBJS) c64.lib

# -----------------------------------------------------------------------
# disk — create a D64 disk image with cse.prg
# -----------------------------------------------------------------------
D64 = $(BUILD)/cse.d64

.PHONY: disk
disk: $(D64)

$(D64): $(PRG)
	@if [ -f $@ ]; then \
		$(C1541) -attach $@ -delete cse -write $< cse; \
	else \
		$(C1541) -format "cse,01" d64 $@ -write $< cse; \
	fi

# -----------------------------------------------------------------------
# tables — regenerate generated .s table files from Python
#
# A stamp file records the last successful run so that the individual
# table .s files can be used as Make prerequisites without re-triggering
# the script every build.
# -----------------------------------------------------------------------
TABLE_GEN  = $(DEV)/mnemonic_tables.py
TABLE_DEPS = $(DEV)/instruction_set.py $(DEV)/hashes.py
TABLE_OUTS = $(SRC)/mn_modes.s $(SRC)/mn_config.s \
             $(SRC)/mn6_tables.s $(SRC)/mn7_tables.s \
             $(SRC)/mn_asm_tables.s
TABLES_STAMP = $(BUILD)/.tables.stamp

.PHONY: tables
tables: $(TABLES_STAMP)

$(TABLES_STAMP): $(TABLE_GEN) $(TABLE_DEPS) | $(BUILD)/
	$(PYTHON) $(TABLE_GEN)
	@touch $@

# Individual table files depend on the stamp so other rules can use them
# as prerequisites.
$(TABLE_OUTS): $(TABLES_STAMP)

# -----------------------------------------------------------------------
# test-bins — assemble the three py65 unit-test binaries
#
# conftest.py also builds these on demand (mtime check), but having
# explicit Make rules gives proper dependency tracking and a way to
# verify assembly independently of running the test suite.
# -----------------------------------------------------------------------

# au_mode ----------------------------------------------------------------
AU_BIN = $(BUILD)/au_mode_test.bin
AU_MAP = $(BUILD)/au_mode_test.map
AU_LST = $(BUILD)/au_mode_test.lst
AU_O1  = $(BUILD)/au_mode.o
AU_O2  = $(BUILD)/au_mode_test_stub.o

$(AU_O1): $(SRC)/au_mode.s | $(BUILD)/
	$(T65) --listing $(AU_LST) $< -o $@

$(AU_O2): $(DEV)/au_mode_test_stub.s | $(BUILD)/
	$(T65) $< -o $@

$(AU_BIN): $(AU_O1) $(AU_O2) $(DEV)/test.cfg
	$(LD65) -C $(DEV)/test.cfg $(AU_O1) $(AU_O2) -o $@ -m $(AU_MAP)

# mn6 --------------------------------------------------------------------
MN6_BIN = $(BUILD)/mn6_test.bin
MN6_MAP = $(BUILD)/mn6_test.map
MN6_LST = $(BUILD)/mn6_classify.lst
MN6_O1  = $(BUILD)/mn_vars_mn6.o
MN6_O2  = $(BUILD)/mn6_mn6.o
MN6_O3  = $(BUILD)/mn6_tables_mn6.o

$(MN6_O1): $(SRC)/mn_vars.s | $(BUILD)/
	$(T65) $< -o $@

$(MN6_O2): $(SRC)/mn6.s | $(BUILD)/
	$(T65) --listing $(MN6_LST) $< -o $@

$(MN6_O3): $(SRC)/mn6_tables.s | $(BUILD)/
	$(T65) $< -o $@

$(MN6_BIN): $(MN6_O1) $(MN6_O2) $(MN6_O3) $(DEV)/test.cfg
	$(LD65) -C $(DEV)/test.cfg $(MN6_O1) $(MN6_O2) $(MN6_O3) -o $@ -m $(MN6_MAP)

# mn7 --------------------------------------------------------------------
MN7_BIN = $(BUILD)/mn7_test.bin
MN7_MAP = $(BUILD)/mn7_test.map
MN7_LST = $(BUILD)/mn7_classify.lst
MN7_O1  = $(BUILD)/mn_vars_mn7.o
MN7_O2  = $(BUILD)/mn7_mn7.o
MN7_O3  = $(BUILD)/mn7_tables_mn7.o

$(MN7_O1): $(SRC)/mn_vars.s | $(BUILD)/
	$(T65) $< -o $@

$(MN7_O2): $(SRC)/mn7.s | $(BUILD)/
	$(T65) --listing $(MN7_LST) $< -o $@

$(MN7_O3): $(SRC)/mn7_tables.s | $(BUILD)/
	$(T65) $< -o $@

$(MN7_BIN): $(MN7_O1) $(MN7_O2) $(MN7_O3) $(DEV)/test.cfg
	$(LD65) -C $(DEV)/test.cfg $(MN7_O1) $(MN7_O2) $(MN7_O3) -o $@ -m $(MN7_MAP)

.PHONY: test-bins
test-bins: $(AU_BIN) $(MN6_BIN) $(MN7_BIN)

# -----------------------------------------------------------------------
# run — build disk image and launch in VICE with D64 attached as drive 8
# -----------------------------------------------------------------------
.PHONY: run
run: $(D64)
	$(VICE) -autostart $(PRG) -8 $(D64)

# -----------------------------------------------------------------------
# test — run pytest (conftest.py rebuilds test binaries if needed)
# -----------------------------------------------------------------------
.PHONY: test
test:
	$(PYTEST) tests/ -v

# -----------------------------------------------------------------------
# size — exhaustive size breakdown of cse.prg
# -----------------------------------------------------------------------
.PHONY: size
size: $(PRG)
	@$(PYTHON) $(DEV)/size_report.py

# -----------------------------------------------------------------------
# clean
# -----------------------------------------------------------------------
.PHONY: clean
clean:
	rm -rf $(BUILD)

.PHONY: clean-tables
clean-tables:
	rm -f $(TABLE_OUTS) $(TABLES_STAMP)

# -----------------------------------------------------------------------
# Directory order-only prerequisite
# -----------------------------------------------------------------------
$(BUILD)/:
	mkdir -p $@

# -----------------------------------------------------------------------
# help
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
	@printf "%-15s %s\n" "all"          "Build cse.prg (default)"
	@printf "%-15s %s\n" "disk"         "Build cse.d64 disk image"
	@printf "%-15s %s\n" "run"          "Build disk image and launch in VICE"
	@printf "%-15s %s\n" "tables"       "Regenerate src/mn*_tables.s via mnemonic_tables.py"
	@printf "%-15s %s\n" "test"         "Run all pytest tests"
	@printf "%-15s %s\n" "test-bins"    "Assemble au_mode / mn6 / mn7 test binaries"
	@printf "%-15s %s\n" "size"         "Exhaustive size breakdown of cse.prg"
	@printf "%-15s %s\n" "clean"        "Remove the build/ directory"
	@printf "%-15s %s\n" "clean-tables" "Remove generated table sources in src/"
	@printf "%-15s %s\n" "themes"       "List available color themes"
	@printf "%-15s %s\n" "help"         "Show this message"
