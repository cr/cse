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

# ── CC65 main-binary flags (match VS64 / build.ninja) ───────────────────
CFLAGS = -g -t c64 -DDEBUG -D__cc65__ -I$(ROOT) -I$(BUILD)
AFLAGS = -g -t c64 -DDEBUG -D__cc65__ -I$(ROOT) -I$(BUILD)
LCFG   = $(SRC)/c64_cse.cfg
LFLAGS = -C $(LCFG)

# ── Test-binary flags (bare 6502, no C64 platform defs) ─────────────────
T65 = $(CA65) --cpu 6502

# -----------------------------------------------------------------------
# all — main C64 binary
# -----------------------------------------------------------------------
PRG    = $(BUILD)/cse.prg
DBG    = $(BUILD)/cse.dbg
MAIN_S = $(BUILD)/src/main.s
MAIN_O = $(BUILD)/src/main.o

# ── C source files (besides main.c) ──────────────────────────────
C_SRCS   = editor repl
C_OBJS   = $(patsubst %,$(BUILD)/src/%.o,$(C_SRCS))

# ── Assembler source files linked into cse.prg ──────────────────────
ASM_SRCS = asm_bridge asm_line asm_vars mn_vars mn_classify \
           mn7 mn7_tables mn6 mn6_tables mn_config \
           au_mode parse_hex mn_modes mn_asm_tables opcode_lookup \
           meminfo
ASM_OBJS = $(patsubst %,$(BUILD)/src/%.o,$(ASM_SRCS))

.PHONY: all
all: $(PRG)

$(BUILD)/src/:
	mkdir -p $@

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
	$(LD65) $(LFLAGS) -o $@ --dbgfile $(DBG) $(MAIN_O) $(C_OBJS) $(ASM_OBJS) c64.lib

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
.PHONY: help
help:
	@printf "%-15s %s\n" "all"          "Build cse.prg (default)"
	@printf "%-15s %s\n" "disk"         "Build cse.d64 disk image"
	@printf "%-15s %s\n" "run"          "Build disk image and launch in VICE"
	@printf "%-15s %s\n" "tables"       "Regenerate src/mn*_tables.s via mnemonic_tables.py"
	@printf "%-15s %s\n" "test"         "Run all pytest tests"
	@printf "%-15s %s\n" "test-bins"    "Assemble au_mode / mn6 / mn7 test binaries"
	@printf "%-15s %s\n" "clean"        "Remove the build/ directory"
	@printf "%-15s %s\n" "clean-tables" "Remove generated table sources in src/"
	@printf "%-15s %s\n" "help"         "Show this message"
