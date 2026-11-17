"""xmega65.py — drive xmega65 (Xemu's MEGA65 emulator) for Tier X.

Owner: doc/build_system.md

Contract source: [doc/testing.md § Tier X](../doc/testing.md#tier-x--xmega65-m65-automated).

Starts xmega65 headless at full speed on a copy-on-write clone of the
user's configured SD image and talks to its `-uartmon` monitor socket:
`r` registers, `m` / `s` read and write linear (28-bit) memory, `g` set
PC, `t1` trace mode, an empty line one step.  The socket path is
relative to the run directory (Unix-domain socket paths are limited to
104 characters), so the driver changes into it.
"""
import os
import pathlib
import re
import shutil
import socket
import subprocess
import time

XMEGA65 = "/Applications/xmega65.app/Contents/MacOS/xmega65"
SDIMG = pathlib.Path.home() / "Library/Application Support/xemu-lgb/mega65/mega65.img"


def available():
    """Why Tier X cannot run here, or None when it can."""
    if not pathlib.Path(XMEGA65).exists():
        return f"xmega65 not installed ({XMEGA65})"
    if not SDIMG.exists():
        return f"no configured MEGA65 SD image ({SDIMG})"
    if shutil.which("cp") is None:
        return "no cp"
    return None


class XMega65:
    def __init__(self, work):
        self.work = work
        work.mkdir(parents=True, exist_ok=True)
        sd = work / "sd.img"
        if not sd.exists():
            subprocess.run(["cp", "-c", str(SDIMG), str(sd)], check=True)
        sock = work / "um.sock"
        if sock.exists():
            sock.unlink()
        self.log = open(work / "xmega65.log", "w")
        self.proc = subprocess.Popen(
            [XMEGA65, "-skipconfigfile", "-headless", "-sleepless", "-besure",
             "-sdimg", "sd.img", "-uartmon", "um.sock"],
            cwd=work, stdout=self.log, stderr=subprocess.STDOUT)
        for _ in range(200):
            if sock.exists():
                break
            time.sleep(0.05)
        os.chdir(work)                  # AF_UNIX paths are limited to 104 chars
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.connect("um.sock")
        self.sock.settimeout(10)

    def cmd(self, line):
        self.sock.sendall((line + "\n").encode())
        buf = b""
        while not buf.endswith(b"\r\n.\r\n"):
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("xmega65 closed the monitor")
            buf += chunk
        return buf.decode(errors="replace")

    _REGS = re.compile(
        r"^([0-9A-F]{4}) ([0-9A-F]{2}) ([0-9A-F]{2}) ([0-9A-F]{2}) "
        r"([0-9A-F]{2}) ([0-9A-F]{2}) ([0-9A-F]{4}) ([0-9A-F]{4}) "
        r"([0-9A-F]{4}) [0-9A-F]{2} +([0-9A-F]{2}) ", re.M)

    def regs(self, out=None):
        m = self._REGS.search(out if out is not None else self.cmd("r"))
        if not m:
            raise RuntimeError(f"cannot parse registers: {out!r}")
        v = [int(g, 16) for g in m.groups()]
        return dict(pc=v[0], a=v[1], x=v[2], y=v[3], z=v[4], b=v[5],
                    sp=v[6], maph=v[7], mapl=v[8], p=v[9])

    def step(self):
        return self.regs(self.cmd(""))

    def write(self, addr, data):
        for k in range(0, len(data), 64):
            chunk = data[k:k + 64]
            self.cmd(f"s {addr + k:x} " + " ".join(f"{b:02x}" for b in chunk))

    def read(self, addr, length):
        out = bytearray()
        for k in range(0, length, 16):
            line = self.cmd(f"m {addr + k:x}")
            m = re.search(r":([0-9A-F]{8}):([0-9A-F]{32})", line)
            out += bytes.fromhex(m.group(2))
        return bytes(out[:length])

    def version(self):
        """The VERSION line this headless instance logged at start-up.

        (Never `xmega65 -h`: without -headless it opens the GUI and
        blocks on an error dialog.)
        """
        self.log.flush()
        m = re.search(r"VERSION: (.*)", (self.work / "xmega65.log").read_text(errors="replace"))
        return m.group(1).strip() if m else "unknown"

    def close(self):
        self.proc.terminate()
        self.proc.wait()
        self.log.close()
