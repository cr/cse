"""xmega65.py — drive xmega65 (Xemu's MEGA65 emulator) for Tier X.

Owner: doc/build_system.md

Contract source: [doc/testing.md § Tier X](../doc/testing.md#tier-x--xmega65-m65-automated).

Starts xmega65 headless at full speed on a fresh copy-on-write clone
of the user's configured SD image and talks to its `-uartmon` monitor
socket: `r` registers, `m` / `s` read and write linear (28-bit)
memory (`777xxxx` addresses the CPU's mapped view), `g` set PC, `t1`
trace mode, an empty line one step.

Use it as a context manager, so xmega65 never outlives the caller:

    with XMega65(work_dir) as xm:
        xm.cmd("t1")

`rom=` boots a given MEGA65 ROM: it goes onto the clone's FAT
partition as MEGA65.ROM (mcopy, at the partition's offset from the
clone's MBR) and xmega65 starts with -romfromsd; `booted_rom()` reads
back what it booted.  `prg=` makes xmega65 load and RUN a PRG in
MEGA65 mode (-prg, -prgmode 65); `d81=` mounts a copy of a D81 (in the
run directory, so the original is never written) on unit 8 and
autoloads its first program (-8, -autoload).  `addkeys()` types keys:
a driver `ADDKEY`s them into the KERNAL's buffer (the monitor cannot
type) and returns to where the CPU stopped.

Never start xmega65 without `-headless` from automation (not even
`-h`): it opens the GUI and blocks on an error dialog.

`recording()` is the session the golden-file recorders share: start,
wait for BASIC 65, enter trace mode, and remove the run directory at
the end; `write_recording()` writes their one-entry-per-line JSON.
"""
import contextlib
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import time

# $XMEGA65 overrides the binary, as the Makefile's XMEGA65 option does.
XMEGA65 = os.environ.get(
    "XMEGA65", "/Applications/xmega65.app/Contents/MacOS/xmega65")


def xemu_dir(env=os.environ, home=None, system=sys.platform):
    """Where xmega65 keeps its data (SD image, MEGA65.ROM):
    $XEMU_MEGA65_DIR when set, else the platform's directory."""
    if env.get("XEMU_MEGA65_DIR"):
        return pathlib.Path(env["XEMU_MEGA65_DIR"])
    home = pathlib.Path.home() if home is None else pathlib.Path(home)
    if system == "darwin":
        return home / "Library/Application Support/xemu-lgb/mega65"
    data = pathlib.Path(env["XDG_DATA_HOME"]) if env.get("XDG_DATA_HOME") \
        else home / ".local/share"
    return data / "xemu-lgb/mega65"


SDIMG = xemu_dir() / "mega65.img"

POST_BOOT_MAP = (0xE300, 0xB300)   # MAPL, MAPH once BASIC 65 is up
FAT_TYPES = (0x06, 0x0B, 0x0C, 0x0E)


def fat_partition_offset(mbr):
    """The byte offset of the first FAT partition the MBR lists."""
    if mbr[510:512] != b"\x55\xAA":
        raise ValueError("no MBR (no $55 $AA signature)")
    for i in range(4):
        entry = mbr[0x1BE + 16 * i:0x1BE + 16 * (i + 1)]
        if entry[4] in FAT_TYPES:
            return int.from_bytes(entry[8:12], "little") * 512
    raise ValueError("the MBR lists no FAT partition")


def start_args(rom=False, prg=None, d81=None):
    """xmega65's arguments: headless at full speed on sd.img with the
    monitor on um.sock; the ROM from the SD card, a PRG to RUN, a D81
    on unit 8 to autoload."""
    args = ["-skipconfigfile", "-headless", "-sleepless", "-besure",
            "-sdimg", "sd.img", "-uartmon", "um.sock"]
    if prg is not None:
        args += ["-prg", str(prg), "-prgmode", "65"]
    if d81 is not None:
        args += ["-8", str(d81), "-autoload"]
    if rom:
        args += ["-romfromsd"]
    return args

_REGS = re.compile(
    r"^([0-9A-F]{4}) ([0-9A-F]{2}) ([0-9A-F]{2}) ([0-9A-F]{2}) "
    r"([0-9A-F]{2}) ([0-9A-F]{2}) ([0-9A-F]{4}) ([0-9A-F]{4}) "
    r"([0-9A-F]{4}) [0-9A-F]{2} +([0-9A-F]{2}) ", re.M)
_REG_NAMES = ("pc", "a", "x", "y", "z", "b", "sp", "maph", "mapl", "p")
_DUMP = re.compile(r":[0-9A-F]{8}:([0-9A-F]{32})")
_PROMPT = b"\r\n.\r\n"


ADDKEY = 0xFF4A                 # the KERNAL's: a key into its buffer
DRIVER = 0x1E00                 # 0.1E00, a test's driver code: free for
                                # programs, the same in BASIC 65's map and CSE's
CHIP_ROM = slice(0x20000, 0x40000)  # the ROM in chip RAM: banks 2-3


def missing(*tools):
    """Why Tier X cannot run here (None: it can): xmega65, the
    configured SD image, mcopy (the ROM onto the SD clone), `tools`."""
    if not pathlib.Path(XMEGA65).exists():
        return f"no xmega65 at {XMEGA65} (set $XMEGA65)"
    if not SDIMG.exists():
        return f"no configured MEGA65 SD image at {SDIMG}"
    for tool in ("mcopy", *tools):
        if shutil.which(tool) is None:
            return f"no {tool}"
    return None


def addkey_driver(keys, back):
    """The code `addkeys()` runs: php pha phx phy phz tba pha, B = 0,
    lda #key · jsr ADDKEY per key, then pla tab plz ply plx pla plp
    and jmp back."""
    code = [0x08, 0x48, 0xDA, 0x5A, 0xDB, 0x7B, 0x48, 0xA9, 0x00, 0x5B]
    for k in keys:
        code += [0xA9, k, 0x20, ADDKEY & 0xFF, ADDKEY >> 8]
    return code + [0x68, 0x5B, 0xFB, 0x7A, 0xFA, 0x68, 0x28,
                   0x4C, back & 0xFF, back >> 8]


class Interrupted(RuntimeError):
    """A stepped sequence did not run straight through (an interrupt
    got in); the caller may retry it."""


class XMega65:
    def __init__(self, work, rom=None, prg=None, d81=None):
        self.work = pathlib.Path(work)
        self.rom = None if rom is None else pathlib.Path(rom)
        self.prg = None if prg is None else pathlib.Path(prg)
        self.d81 = None if d81 is None else pathlib.Path(d81)
        self.work.mkdir(parents=True, exist_ok=True)
        self.proc = self.sock = None
        self.log = open(self.work / "xmega65.log", "w")
        try:
            self._start()
        except BaseException:
            self.close()
            raise

    def _start(self):
        # copy-on-write clone (APFS): the user's image is never written
        sd = self.work / "sd.img"
        subprocess.run(["cp", "-c", str(SDIMG), str(sd)], check=True)
        if self.rom is not None:
            with open(sd, "rb") as f:
                offset = fat_partition_offset(f.read(512))
            subprocess.run(["mcopy", "-o", "-i", f"{sd}@@{offset}",
                            str(self.rom), "::MEGA65.ROM"], check=True,
                           env=dict(os.environ, MTOOLS_SKIP_CHECK="1"))
        prg = d81 = None
        if self.prg is not None:
            prg = "run.prg"
            shutil.copy(self.prg, self.work / prg)
        if self.d81 is not None:
            d81 = "disk.d81"
            shutil.copy(self.d81, self.work / d81)
        sock = self.work / "um.sock"
        sock.unlink(missing_ok=True)
        self.proc = subprocess.Popen(
            [XMEGA65] + start_args(rom=self.rom is not None, prg=prg, d81=d81),
            cwd=self.work, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.time() + 10
        while not sock.exists():
            if self.proc.poll() is not None or time.time() > deadline:
                raise RuntimeError(f"xmega65 opened no monitor socket; "
                                   f"see {self.work / 'xmega65.log'}")
            time.sleep(0.05)
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(10)
        # A Unix-domain socket path is limited to 104 characters, so
        # connect by the relative name from inside the run directory.
        cwd = os.getcwd()
        os.chdir(self.work)
        try:
            self.sock.connect("um.sock")
        finally:
            os.chdir(cwd)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.sock is not None:
            self.sock.close()
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait()
        self.log.close()

    def cmd(self, line):
        """Send one monitor line; return its output up to the prompt."""
        self.sock.sendall((line + "\n").encode())
        buf = b""
        while not buf.endswith(_PROMPT):
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("xmega65 closed the monitor")
            buf += chunk
        return buf.decode(errors="replace")

    def regs(self, text=None):
        """The registers `r` prints (or those in a step's output)."""
        text = self.cmd("r") if text is None else text
        m = _REGS.search(text)
        if not m:
            raise RuntimeError(f"cannot parse registers: {text!r}")
        return dict(zip(_REG_NAMES, (int(g, 16) for g in m.groups())))

    def step(self):
        """Run one opcode in trace mode; return the registers after it."""
        return self.regs(self.cmd(""))

    def wait_for_basic(self, timeout=60):
        """Block until BASIC 65 is up (its MAP is in place)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = self.regs()
            if (r["mapl"], r["maph"]) == POST_BOOT_MAP and r["pc"] >= 0x8000:
                return
            time.sleep(0.5)
        raise RuntimeError("xmega65 did not reach BASIC 65")

    def run(self, addr, instructions):
        """Write `instructions` (a list of byte lists) at `addr` and
        step through them in trace mode; return the registers after
        the last.  Raise Interrupted at the first step that does not
        land on the next instruction (an interrupt got in)."""
        self.write(addr, [b for ins in instructions for b in ins])
        self.cmd(f"g {addr:x}")
        r = self.regs()
        for ins in instructions:
            addr += len(ins)
            r = self.step()
            if r["pc"] != addr:
                raise Interrupted(r)
        return r

    def run_to(self, addr, timeout=60, at_hit=False):
        """Run at full speed (from trace mode) until PC reaches `addr`,
        then pause; return the registers.  The monitor reports the hit
        by itself — a register dump without a prompt — and the CPU runs
        one more instruction before it stops, so park the code at
        `addr` (e.g. JMP to itself), or take `at_hit`: the registers of
        the hit report, as they were at `addr`."""
        self.cmd(f"b {addr:x}")
        self.sock.sendall(b"t0\n")
        want = f"\r\n{addr:04X} ".encode()
        buf, deadline = b"", time.time() + timeout
        while want not in buf:
            if time.time() > deadline:
                raise TimeoutError(f"breakpoint ${addr:04X} not reached")
            try:
                buf += self.sock.recv(65536)
            except socket.timeout:
                pass
        self.cmd("t1")
        if at_hit:
            return self.regs(buf.decode(errors="replace"))
        return self.regs()

    def run_to_page(self, addr, b, tries=50):
        """`run_to(addr, at_hit=True)` until the hit has B = `b`: the
        same address runs in other base pages too (BASIC 65's code
        under the CSE map, before the loader); return the hit."""
        for _ in range(tries):
            hit = self.run_to(addr, at_hit=True)
            if hit["b"] == b:
                return hit
        raise Interrupted(hit)

    def set_map(self, addr, mapl, maph, mb_lo=0, mb_hi=0):
        """Run, at `addr`, the code that sets the megabyte selectors
        and then both MAP halves, with interrupts off; EOM ends each."""
        def map_code(a, x, y, z):
            return [[0xA9, a], [0xA2, x], [0xA0, y], [0xA3, z],
                    [0x5C], [0xEA], [0xA9, 0x00]]
        seq = ([[0x78]] + map_code(mb_lo, 0x0F, mb_hi, 0x0F)
               + map_code(mapl & 0xFF, mapl >> 8, maph & 0xFF, maph >> 8))
        r = retrying(lambda: self.run(addr, seq))
        if (r["mapl"], r["maph"]) != (mapl, maph):
            raise RuntimeError(f"MAP not set: {r}")
        return r

    def write(self, addr, data):
        for k in range(0, len(data), 64):
            chunk = data[k:k + 64]
            self.cmd(f"s {addr + k:x} " + " ".join(f"{b:02x}" for b in chunk))

    def read(self, addr, length):
        """`length` bytes of linear memory from `addr`."""
        out = bytearray()
        for a in range(addr & ~15, addr + length, 16):
            text = self.cmd(f"m {a:x}")
            m = _DUMP.search(text)
            if not m:
                raise RuntimeError(f"cannot parse memory dump: {text!r}")
            out += bytes.fromhex(m.group(1))
        return bytes(out[addr & 15:(addr & 15) + length])

    def addkeys(self, keys, at=DRIVER):
        """Type `keys` (PETSCII): a driver at `at` (bank 0, below
        `$2000`: the same in BASIC 65's map and in CSE's) `ADDKEY`s
        each into the KERNAL's buffer with B = 0, every register and P
        kept, and jumps back to where the CPU stopped."""
        back = self.regs()["pc"]
        self.write(at, addkey_driver(keys, back))
        self.cmd(f"g {at:x}")

    def mounted_d81(self):
        """The D81 copy xmega65 has on unit 8 (its writes land there)."""
        return self.work / "disk.d81"

    def read_cpu(self, addr, length):
        """`length` bytes as the CPU sees them at the 16-bit `addr`."""
        assert addr + length <= 0x10000
        return self.read(0x7770000 | addr, length)

    def booted_rom(self):
        """The ROM image xmega65 runs (flat $20000-$3FFFF)."""
        return self.read(0x20000, 0x20000)

    def version(self):
        """The VERSION line this instance logged at start-up."""
        self.log.flush()
        text = (self.work / "xmega65.log").read_text(errors="replace")
        m = re.search(r"VERSION: (.*)", text)
        return m.group(1).strip() if m else "unknown"


def retrying(action, tries=3):
    """Run `action()`, again when an interrupt got into its stepping."""
    for _ in range(tries):
        try:
            return action()
        except Interrupted:
            continue
    raise RuntimeError("stepping kept being interrupted")


@contextlib.contextmanager
def recording(work, rom=None):
    """An xmega65 in trace mode at the BASIC 65 prompt (on `rom`, if
    given), for a golden-file recorder; the run directory is removed
    afterwards."""
    try:
        with XMega65(work, rom=rom) as xm:
            xm.wait_for_basic()
            xm.cmd("t1")
            yield xm
    finally:
        shutil.rmtree(work, ignore_errors=True)


def write_recording(path, header, key, entries):
    """Write a golden file: `header`'s items, then `key`: `entries`,
    one entry per line, so a re-record's diff reads entry by entry."""
    lines = [f' "{k}": {json.dumps(v)},' for k, v in header.items()]
    lines[0] = "{" + lines[0][1:]
    body = ",\n  ".join(json.dumps(e) for e in entries)
    pathlib.Path(path).write_text(
        "\n".join(lines) + f'\n "{key}": [\n  {body}\n ]}}\n')
