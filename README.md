# CSE — C64 Screen Editor

An integrated assembler development environment for the Commodore 64.
MasterSeka's workflow meets radare2's power — sketch ideas fast,
assemble, run, debug, iterate.  All on the C64 itself.

## Quick Start

    make            # build cse.prg (requires ca65/ld65)
    make run        # build + launch in VICE
    make test       # run pytest test suite (requires py65)

## Documentation

All design docs, module specs, and project goals live in [`doc/`](doc/README.md).

Start there.

## Build Requirements

- [cc65](https://cc65.github.io/) — provides `ca65` (assembler) and `ld65` (linker).  CSE is pure 6502 assembly; the cc65 *C compiler* is not used.
- [VICE](https://vice-emu.sourceforge.io/) — C64 emulator (for `make run`)
- Python 3 + [py65](https://pypi.org/project/py65/) — test harness
- pipenv or virtualenv for the test environment
