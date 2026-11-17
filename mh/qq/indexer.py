"""Build a plain SQLite index that maps media MD5 -> QQ chat (friend/group)."""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass

from .wire import classify, extract_media

HEADER_BYTES = 1024
PRAGMAS = [
    "PRAGMA cipher_page_size = 4096",
    "PRAGMA key = '%s'",
    "PRAGMA kdf_iter = 4000",
    "PRAGMA cipher_hmac_algorithm = HMAC_SHA1",
    "PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512",
]


@dataclass
class BuildStats:
    c2c_rows: int = 0
    group_rows: int = 0
    media_rows: int = 0
    chats: int = 0
    seconds: float = 0.0


def connect_encrypted(path: str, key: str):
    from sqlcipher3 import dbapi2 as sq

    con = sq.connect(path, timeout=15)
    for stmt in PRAGMAS:
        con.execute(stmt % key.replace("'", "''") if "%s" in stmt else stmt)
    con.execute("select count(*) from sqlite_master").fetchall()
    return con


def strip_copy(src: str, dst: str) -> None:
    with open(src, "rb") as f:
        f.seek(HEADER_BYTES)
        with open(dst, "wb") as o:
            while True:
                chunk = f.read(16 << 20)
                if not chunk:
                    break
                o.write(chunk)


def _cell_text(v) -> str:
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).decode("utf-8", "ignore")
    if isinstance(v, str):
        return v
    return ""


def load_names(profile_copy: str, group_copy: str, key: str):
    friend: dict[str, str] = {}
    friend_uin: dict[str, str] = {}
    groups: dict[str, str] = {}
    if os.path.isfile(profile_copy):
        con = connect_encrypted(profile_copy, key)
        try:
            cur = con.cursor()
            try:
                for uid, uin, nick in cur.execute('SELECT "1000","1002","20002" FROM profile_info_v6'):
                    uid, nick = _cell_text(uid), _cell_text(nick)
                    if uid:
                        if nick:
                            friend[uid] = nick
                        if uin:
                            friend_uin[uid] = str(uin)
            except Exception:
                pass
            try:
                for uid, remark, uin in cur.execute('SELECT "1000","1001","1002" FROM buddy_list'):
                    uid, remark = _cell_text(uid), _cell_text(remark)
                    if uid and remark:
                        friend[uid] = remark
                    if uid and uin:
                        friend_uin.setdefault(uid, str(uin))
            except Exception:
                pass
        finally:
            con.close()
    if os.path.isfile(group_copy):
        con = connect_encrypted(group_copy, key)
        try:
            cur = con.cursor()
            try:
                for code, name in cur.execute('SELECT "60001","60007" FROM group_list'):
                    code, name = str(code), _cell_text(name)
                    if code and name:
                        groups[code] = name
            except Exception:
                pass
        finally:
            con.close()
    return friend, friend_uin, groups


def _count_rows(con, table: str) -> int:
    try:
        return con.execute(f'SELECT count(*) FROM {table} WHERE "40800" IS NOT NULL').fetchone()[0]
    except Exception:
        return 0


def _iter_messages(con, table: str, batch: int = 2000):
    last = -(1 << 63)
    while True:
        rows = con.execute(
            f'SELECT rowid,"40021","40030","40050","40013","40093","40090","40800" '
            f'FROM {table} WHERE rowid > ? AND "40800" IS NOT NULL ORDER BY rowid LIMIT ?',
            (last, batch),
        ).fetchall()
        if not rows:
            return
        last = rows[-1][0]
        for row in rows:
            yield row


def _self_uin(nt_qq_dir: str) -> str:
    parent = os.path.basename(os.path.dirname(os.path.abspath(nt_qq_dir)))
    return parent if parent.isdigit() else ""


def build_index(nt_qq_dir: str, key: str, out_path: str, progress=None, cancel=None) -> BuildStats:
    t0 = time.time()
    stats = BuildStats()
    self_uin = _self_uin(nt_qq_dir)
    nt_db = os.path.join(nt_qq_dir, "nt_db")
    src_msg = os.path.join(nt_db, "nt_msg.db")
    if not os.path.isfile(src_msg):
        raise FileNotFoundError(f"未找到 {src_msg}")

    tempdir = tempfile.mkdtemp(prefix="picmgr_qq_")
    tmp_index = out_path + ".tmp"
    try:
        if progress:
            progress("复制数据库…", 0, 0)
        msg_copy = os.path.join(tempdir, "msg.db")
        strip_copy(src_msg, msg_copy)
        for suffix in ("-wal", "-shm"):
            src = src_msg + suffix
            if os.path.isfile(src):
                shutil.copyfile(src, msg_copy + suffix)

        profile_copy = os.path.join(tempdir, "profile.db")
        src = os.path.join(nt_db, "profile_info.db")
        if os.path.isfile(src):
            strip_copy(src, profile_copy)
        group_copy = os.path.join(tempdir, "group.db")
        src = os.path.join(nt_db, "group_info.db")
        if os.path.isfile(src):
            strip_copy(src, group_copy)

        if progress:
            progress("读取联系人与群资料…", 0, 0)
        friend, friend_uin, groups = load_names(profile_copy, group_copy, key)

        con = None
        for attempt in (0, 1):
            try:
                con = connect_encrypted(msg_copy, key)
                _count_rows(con, "c2c_msg_table")
                break
            except Exception:
                if con is not None:
                    con.close()
                    con = None
                if attempt == 0 and os.path.exists(msg_copy + "-wal"):
                    os.remove(msg_copy + "-wal")
                    continue
                raise
        if con is None:
            raise RuntimeError("无法打开解密后的消息数据库")

        try:
            c2c_total = _count_rows(con, "c2c_msg_table")
            group_total = _count_rows(con, "group_msg_table")
            media: dict[tuple[str, str, str], tuple] = {}
            chats: dict[tuple[str, str], dict] = {}

            def remember(md5, kind, chat_kind, chat_id, chat_name, ts, sender, fname, fsize, chat_uin=""):
                key3 = (md5, chat_kind, chat_id)
                old = media.get(key3)
                if old is None or ts >= old[1]:
                    media[key3] = (kind, ts, sender, fname, fsize)
                ck = (chat_kind, chat_id)
                c = chats.get(ck)
                if c is None:
                    chats[ck] = {"name": chat_name, "last": ts, "count": 1, "uin": chat_uin or chat_id}
                else:
                    c["count"] += 1
                    if ts > c["last"]:
                        c["last"] = ts
                        if chat_name and chat_kind != "self":
                            c["name"] = chat_name
                    if chat_uin:
                        c["uin"] = chat_uin

            processed = 0
            for rowid, peer21, peer30, ts, direction, nick, card, blob in _iter_messages(con, "c2c_msg_table"):
                if cancel is not None and cancel.is_set():
                    raise InterruptedError
                processed += 1
                uid = _cell_text(peer21) or (str(peer30) if peer30 else "")
                if not uid:
                    continue
                peer_qq = str(peer30) if peer30 else friend_uin.get(uid, "")
                if self_uin and peer_qq == self_uin:
                    chat_kind = "self"
                    display = "我的设备（文件传输）"
                else:
                    chat_kind = "c2c"
                    display = friend.get(uid) or _cell_text(nick) or peer_qq or uid[:12]
                for seg in extract_media(bytes(blob) if isinstance(blob, (bytearray, memoryview)) else blob):
                    kind = classify(seg)
                    sender = _cell_text(card) or _cell_text(nick)
                    remember(seg.md5, kind, chat_kind, uid, display, int(ts or 0), sender,
                             seg.filename, seg.file_size, peer_qq)
                if progress and processed % 1000 == 0:
                    progress("解析私聊消息…", processed, c2c_total)

            stats.c2c_rows = processed
            processed = 0
            for rowid, peer21, peer30, ts, direction, nick, card, blob in _iter_messages(con, "group_msg_table"):
                if cancel is not None and cancel.is_set():
                    raise InterruptedError
                processed += 1
                gid = _cell_text(peer21) or (str(peer30) if peer30 else "")
                if not gid:
                    continue
                gname = groups.get(gid) or f"群 {gid}"
                for seg in extract_media(bytes(blob) if isinstance(blob, (bytearray, memoryview)) else blob):
                    kind = classify(seg)
                    sender = _cell_text(card) or _cell_text(nick)
                    remember(seg.md5, kind, "group", gid, gname, int(ts or 0), sender,
                             seg.filename, seg.file_size, gid)
                if progress and processed % 2000 == 0:
                    progress("解析群聊消息…", processed, group_total)
            stats.group_rows = processed
        finally:
            con.close()

        if progress:
            progress("写入索引…", 0, 1)
        if os.path.exists(tmp_index):
            os.remove(tmp_index)
        idx = sqlite3.connect(tmp_index)
        try:
            idx.execute("PRAGMA journal_mode=OFF")
            idx.execute("PRAGMA synchronous=OFF")
            idx.executescript(
                """
                CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE chats(kind TEXT NOT NULL, chat_id TEXT NOT NULL, name TEXT, uin TEXT,
                                   media_count INTEGER, last_time INTEGER,
                                   PRIMARY KEY(kind, chat_id));
                CREATE TABLE media(md5 TEXT NOT NULL, kind TEXT, chat_kind TEXT NOT NULL,
                                   chat_id TEXT NOT NULL, chat_name TEXT, msg_time INTEGER,
                                   sender TEXT, filename TEXT, file_size INTEGER,
                                   PRIMARY KEY(md5, chat_kind, chat_id));
                CREATE INDEX idx_media_md5 ON media(md5);
                """
            )
            idx.executemany(
                "INSERT INTO chats(kind,chat_id,name,uin,media_count,last_time) VALUES(?,?,?,?,?,?)",
                [(k, cid, v["name"], v["uin"], v["count"], v["last"]) for (k, cid), v in chats.items()],
            )
            idx.executemany(
                "INSERT INTO media(md5,kind,chat_kind,chat_id,chat_name,msg_time,sender,filename,file_size) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                [
                    (md5, v[0], ck, cid, chats[(ck, cid)]["name"], v[1], v[2], v[3], v[4])
                    for (md5, ck, cid), v in media.items()
                ],
            )
            idx.execute("INSERT INTO meta VALUES('built_at', ?)", (str(int(time.time())),))
            idx.execute("INSERT INTO meta VALUES('source', ?)", (nt_qq_dir,))
            idx.commit()
        finally:
            idx.close()
        os.replace(tmp_index, out_path)
        stats.media_rows = len(media)
        stats.chats = len(chats)
        stats.seconds = time.time() - t0
        return stats
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)
        if os.path.exists(tmp_index):
            try:
                os.remove(tmp_index)
            except OSError:
                pass


def load_index(index_path: str):
    """Return (chat_rows, md5 -> list[(kind, chat_id, name)], meta dict)."""
    if not os.path.isfile(index_path):
        return [], {}, {}
    con = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
    try:
        chats = con.execute("SELECT kind,chat_id,name,uin,media_count,last_time FROM chats").fetchall()
        mapping: dict[str, list[tuple[str, str, str]]] = {}
        for md5, ck, cid, name in con.execute("SELECT md5,chat_kind,chat_id,chat_name FROM media"):
            mapping.setdefault(md5, []).append((ck, cid, name or ""))
        meta = dict(con.execute("SELECT key,value FROM meta"))
        return chats, mapping, meta
    finally:
        con.close()
