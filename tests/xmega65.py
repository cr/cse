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
import time

# $XMEGA65 overrides the binary, as the Makefile's XMEGA65 option does.
XMEGA65 = os.environ.get(
    "XMEGA65", "/Applications/xmega65.app/Contents/MacOS/xmega65")
SDIMG = pathlib.Path.home() / "Library/Application Support/xemu-lgb/mega65/mega65.img"

POST_BOOT_MAP = (0xE300, 0xB300)   # MAPL, MAPH once BASIC 65 is up

_REGS = re.compile(
    r"^([0-9A-F]{4}) ([0-9A-F]{2}) ([0-9A-F]{2}) ([0-9A-F]{2}) "
    r"([0-9A-F]{2}) ([0-9A-F]{2}) ([0-9A-F]{4}) ([0-9A-F]{4}) "
    r"([0-9A-F]{4}) [0-9A-F]{2} +([0-9A-F]{2}) ", re.M)
_REG_NAMES = ("pc", "a", "x", "y", "z", "b", "sp", "maph", "mapl", "p")
_DUMP = re.compile(r":[0-9A-F]{8}:([0-9A-F]{32})")
_PROMPT = b"\r\n.\r\n"


class Interrupted(RuntimeError):
    """A stepped sequence did not run straight through (an interrupt
    got in); the caller may retry it."""


class XMega65:
    def __init__(self, work):
        self.work = pathlib.Path(work)
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
        subprocess.run(["cp", "-c", str(SDIMG), str(self.work / "sd.img")],
                       check=True)
        sock = self.work / "um.sock"
        sock.unlink(missing_ok=True)
        self.proc = subprocess.Popen(
            [XMEGA65, "-skipconfigfile", "-headless", "-sleepless", "-besure",
             "-sdimg", "sd.img", "-uartmon", "um.sock"],
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

    def read_cpu(self, addr, length):
        """`length` bytes as the CPU sees them at the 16-bit `addr`."""
        assert addr + length <= 0x10000
        return self.read(0x7770000 | addr, length)

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
def recording(work):
    """An xmega65 in trace mode at the BASIC 65 prompt, for a golden-file
    recorder; the run directory is removed afterwards."""
    try:
        with XMega65(work) as xm:
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
