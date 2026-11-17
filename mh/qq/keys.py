"""Read-only extraction of the NTQQ SQLCipher key from QQ process memory."""
from __future__ import annotations

import contextlib
import ctypes
import ctypes.wintypes as wt
import os
import re
import time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
READABLE = {0x02, 0x04, 0x08, 0x20, 0x40, 0x80}
CHUNK = 8 << 20
HEADER_BYTES = 1024

SQLCIPHER_PRAGMAS = [
    "PRAGMA cipher_page_size = 4096",
    "PRAGMA key = '%s'",
    "PRAGMA kdf_iter = 4000",
    "PRAGMA cipher_hmac_algorithm = HMAC_SHA1",
    "PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512",
]


class MEMORY_BASIC_INFORMATION64(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_ulonglong),
        ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", ctypes.c_ulong),
        ("__alignment1", ctypes.c_ulong),
        ("RegionSize", ctypes.c_ulonglong),
        ("State", ctypes.c_ulong),
        ("Protect", ctypes.c_ulong),
        ("Type", ctypes.c_ulong),
        ("__alignment2", ctypes.c_ulong),
    ]


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _blob_bytes(blob: DATA_BLOB) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def dpapi_protect(data: bytes) -> bytes:
    out = DATA_BLOB()
    if not crypt32.CryptProtectData(ctypes.byref(_blob(data)), "PicManager", None, None, None, 0, ctypes.byref(out)):
        raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
    try:
        return _blob_bytes(out)
    finally:
        k32.LocalFree(out.pbData)


def dpapi_unprotect(data: bytes) -> bytes:
    out = DATA_BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(_blob(data)), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError(ctypes.get_last_error(), "CryptUnprotectData failed")
    try:
        return _blob_bytes(out)
    finally:
        k32.LocalFree(out.pbData)


def enum_pids() -> list[int]:
    pids = (wt.DWORD * 8192)()
    needed = wt.DWORD()
    psapi.EnumProcesses(ctypes.byref(pids), ctypes.sizeof(pids), ctypes.byref(needed))
    return [pids[i] for i in range(needed.value // ctypes.sizeof(wt.DWORD))]


def process_image(pid: int) -> str | None:
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
    finally:
        k32.CloseHandle(h)
    return None


def find_qq_pids() -> list[tuple[int, str]]:
    found = []
    for pid in enum_pids():
        img = process_image(pid)
        if img and img.lower().endswith(("\\qq.exe", "\\qqex.exe")):
            found.append((pid, img))
    return found


def scan_memory_candidates(progress=None, cancel=None) -> list[str]:
    """Return 16-char printable ASCII strings from private readable memory (NUL-terminated first)."""
    pattern = re.compile(rb"[\x20-\x7e]{16,}")
    tagged: set[bytes] = set()
    plain: set[bytes] = set()
    procs = find_qq_pids()
    if not procs:
        return []
    for idx, (pid, img) in enumerate(procs):
        if cancel is not None and cancel.is_set():
            break
        h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            continue
        try:
            mbi = MEMORY_BASIC_INFORMATION64()
            addr = 0
            regions = []
            while addr < 0x7FFF_FFFF_FFFF:
                if not k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                    break
                base, size, state, protect, typ = mbi.BaseAddress, mbi.RegionSize, mbi.State, mbi.Protect, mbi.Type
                addr = base + size
                if (
                    state == MEM_COMMIT
                    and typ == MEM_PRIVATE
                    and not (protect & (PAGE_GUARD | PAGE_NOACCESS))
                    and (protect & 0xFF) in READABLE
                ):
                    regions.append((base, size))
            buf = ctypes.create_string_buffer(CHUNK)
            read = ctypes.c_size_t()
            done = 0
            rate = 0.0
            for base, size in regions:
                if cancel is not None and cancel.is_set():
                    break
                off = 0
                carry = b""
                while off < size:
                    n = min(CHUNK, size - off)
                    if not k32.ReadProcessMemory(h, ctypes.c_void_p(base + off), buf, n, ctypes.byref(read)):
                        break
                    if read.value == 0:
                        break
                    chunk = buf.raw[: read.value]
                    data = carry + chunk
                    done += len(chunk)
                    for m in pattern.finditer(data):
                        s = m.group()
                        if len(s) == 16:
                            if data[m.end():m.end() + 1] == b"\x00":
                                tagged.add(s)
                            else:
                                plain.add(s)
                    carry = data[-15:]
                    off += read.value
                    if progress is not None and time.time() - rate > 0.15:
                        rate = time.time()
                        progress(
                            f"正在读取 QQ 进程内存…（{done / 1e6:.0f} MB）",
                            idx + 1,
                            len(procs),
                        )
        finally:
            k32.CloseHandle(h)
    ordered = [s.decode("ascii") for s in tagged]
    ordered += [s.decode("ascii") for s in plain if s not in tagged]
    return ordered


@contextlib.contextmanager
def suppress_stderr():
    """SQLCipher logs every failed HMAC check; hide that noise during key trials."""
    try:
        saved = os.dup(2)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        os.close(devnull)
    except OSError:
        saved = None
    try:
        yield
    finally:
        if saved is not None:
            try:
                os.dup2(saved, 2)
                os.close(saved)
            except OSError:
                pass


def make_head_copy(db_path: str, dst: str, size: int = 2 << 20) -> None:
    with open(db_path, "rb") as f:
        f.seek(HEADER_BYTES)
        data = f.read(size)
    with open(dst, "wb") as f:
        f.write(data)


def validate_key(head_db: str, key: str) -> bool:
    from sqlcipher3 import dbapi2 as sq

    try:
        con = sq.connect(head_db, timeout=1)
        try:
            for stmt in SQLCIPHER_PRAGMAS:
                if "%s" in stmt:
                    con.execute(stmt % key.replace("'", "''"))
                else:
                    con.execute(stmt)
            con.execute("select count(*) from sqlite_master").fetchall()
            return True
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        return "not a database" not in str(exc).lower()


def find_key(nt_qq_dir: str, progress=None, cancel=None) -> str | None:
    """Scan running QQ processes and validate candidates against nt_msg.db."""
    import tempfile

    db_path = os.path.join(nt_qq_dir, "nt_db", "nt_msg.db")
    if not os.path.isfile(db_path):
        return None
    if progress:
        progress("正在读取 QQ 进程内存…", 0, 0)
    candidates = scan_memory_candidates(progress, cancel)
    if not candidates:
        return None
    head = os.path.join(tempfile.gettempdir(), "picmgr_key_head.db")
    make_head_copy(db_path, head)
    try:
        total = len(candidates)
        with suppress_stderr():
            for i, key in enumerate(candidates, 1):
                if cancel is not None and cancel.is_set():
                    return None
                if validate_key(head, key):
                    return key
                if progress and (i % 200 == 0 or i == total):
                    progress("正在验证密钥候选…", i, total)
    finally:
        try:
            os.remove(head)
        except OSError:
            pass
    return None
