"""
Textual Log Viewer backed by SQLite + in-memory LRU cache.

Features:
- Append raw 3-byte packets into SQLite (batched transaction)
- Query pages backwards (latest -> older) with filters and LIMIT
- LRU cache for expanded log text to avoid re-decoding
- Textual UI with pause, filters, and smooth paging

Run: python textual_sqlite_logviewer.py
Deps: textual, python >=3.10 (asyncio), optionally pyserial for real serial input.

This application simulates a serial feeder if pyserial isn't provided.
Replace `simulate_feeder()` with real serial reader that calls store.insert_raw_packet(...)

Note: `decode_raw_packet()` is a stub — replace it with your ELF-based decoder.
"""

import asyncio
import sqlite3
import time
import struct
from collections import OrderedDict
from dataclasses import dataclass
from typing import List, Optional, Tuple

from textual.app import App, ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Header, Footer, Input, Button, Static, Checkbox
from textual.reactive import reactive

PAGE_SIZE = 100  # number of visible log entries per page
CACHE_SIZE = 1000  # number of decoded entries to keep in RAM
DB_PATH = "logs.sqlite3"


@dataclass
class LogRow:
    id: int
    ts: int
    raw: bytes
    level: int
    file_id: int
    line: int


class LRUCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.od = OrderedDict()

    def get(self, key):
        if key not in self.od:
            return None
        self.od.move_to_end(key)
        return self.od[key]

    def put(self, key, value):
        self.od[key] = value
        self.od.move_to_end(key)
        if len(self.od) > self.capacity:
            self.od.popitem(last=False)

    def clear(self):
        self.od.clear()


class LogStore:
    """SQLite-backed append-only store for raw log packets."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self._ensure_schema()
        self.insert_stmt = None
        self.insert_buffer: List[Tuple[int, bytes, int, int]] = []
        self._lock = asyncio.Lock()

    def _ensure_schema(self):
        cur = self.conn.cursor()
        cur.execute(
            """
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            raw BLOB NOT NULL,
            level INTEGER DEFAULT 0,
            file_id INTEGER DEFAULT 0,
            line INTEGER DEFAULT 0
        );
        """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_logs_file ON logs(file_id);")
        self.conn.commit()

    def insert_batch_sync(self, rows: List[Tuple[int, bytes, int, int]]):
        """Synchronous helper to insert a batch of (ts, raw, level, file_id, line)
        rows as tuples: (ts, raw_bytes, level, file_id, line)
        """
        cur = self.conn.cursor()
        cur.executemany(
            "INSERT INTO logs (ts, raw, level, file_id, line) VALUES (?, ?, ?, ?, ?);",
            rows,
        )
        self.conn.commit()

    async def insert_batch(self, rows: List[Tuple[int, bytes, int, int]]):
        async with self._lock:
            # buffer and flush in a background thread to keep UI responsive
            await asyncio.get_event_loop().run_in_executor(None, self.insert_batch_sync, rows)

    def query_page(self, limit: int = PAGE_SIZE, before_id: Optional[int] = None, filters: dict = None) -> List[LogRow]:
        """Query logs in descending id order. If before_id is None -> latest.
        filters: { 'level': int or None, 'file_id': int or None }
        Returns list ordered newest->oldest
        """
        filters = filters or {}
        cur = self.conn.cursor()
        where = []
        args = []
        if before_id is not None:
            where.append("id < ?")
            args.append(before_id)
        if filters.get("level") is not None:
            where.append("level = ?")
            args.append(filters["level"])
        if filters.get("file_id") is not None:
            where.append("file_id = ?")
            args.append(filters["file_id"])
        where_clause = ("WHERE " + " AND ".join(where)) if where else ""
        q = f"SELECT id, ts, raw, level, file_id, line FROM logs {where_clause} ORDER BY id DESC LIMIT ?"
        args.append(limit)
        cur.execute(q, args)
        rows = []
        for r in cur.fetchall():
            rows.append(LogRow(id=r[0], ts=r[1], raw=r[2], level=r[3], file_id=r[4], line=r[5]))
        return rows

    def count(self, filters: dict = None) -> int:
        filters = filters or {}
        cur = self.conn.cursor()
        where = []
        args = []
        if filters.get("level") is not None:
            where.append("level = ?")
            args.append(filters["level"])
        if filters.get("file_id") is not None:
            where.append("file_id = ?")
            args.append(filters["file_id"])
        where_clause = ("WHERE " + " AND ".join(where)) if where else ""
        q = f"SELECT COUNT(1) FROM logs {where_clause}"
        cur.execute(q, args)
        return cur.fetchone()[0]


# Stub decoder - replace with your ELF-based decoder
def decode_raw_packet(raw: bytes) -> Tuple[int, str]:
    """Return (level, expanded_text) for a raw 3-byte packet.
    This stub simply unpacks as (file_id, line) and synthesizes text.
    Replace with a decoder that consults the ELF.
    """
    if len(raw) == 3:
        file_id = raw[0]
        line = (raw[1] << 8) | raw[2]
        level = (file_id >> 6) & 0x3  # fake
        text = f"[decoded] file_id={file_id} line={line} (expanded text from ELF)"
        return level, text
    return 0, "<malformed>"


class LogPane(VerticalScroll):
    """Widget responsible for rendering a page of logs."""

    def __init__(self, store: LogStore, cache: LRUCache):
        super().__init__()
        self.store = store
        self.cache = cache
        self.paused = False
        self.current_before_id = None  # for backward paging
        self.filters = {}

    async def refresh_latest(self):
        # fetch latest page
        rows = await asyncio.get_event_loop().run_in_executor(
            None, self.store.query_page, PAGE_SIZE, None, self.filters)
        await self._render_rows(rows)
        if rows:
            self.current_before_id = rows[-1].id

    async def page_backwards(self):
        if self.current_before_id is None:
            # get latest first
            await self.refresh_latest()
            return
        rows = await asyncio.get_event_loop().run_in_executor(
            None, self.store.query_page, PAGE_SIZE, self.current_before_id, self.filters)
        if rows:
            # append to view (older entries)
            await self._render_rows(rows, append=True)
            self.current_before_id = rows[-1].id

    async def _render_rows(self, rows: List[LogRow], append: bool = False):
        if not append:
            self.clear()
        for r in rows:
            cached = self.cache.get(r.id)
            if cached is None:
                level, text = decode_raw_packet(r.raw)
                self.cache.put(r.id, text)
            else:
                text = cached
            item = Static(f"{r.id:8d} {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r.ts))} {text}")
            await self.mount(item)


class Controls(Static):
    pass


class LogViewerApp(App):
    CSS = """
    Screen {
      layout: vertical;
    }
    """

    def __init__(self):
        super().__init__()
        self.store = LogStore()
        self.cache = LRUCache(CACHE_SIZE)
        self.pane = LogPane(self.store, self.cache)
        self.paused = reactive(False)

    async def on_mount(self) -> None:
        header = Header(show_clock=True)
        footer = Footer()
        await self.view.dock(header, edge="top")
        await self.view.dock(footer, edge="bottom")
        controls = Container(Input(placeholder="filter file_id=..."), Button("Apply"), Button("Latest"), Button("Load more"))
        await self.view.dock(controls, edge="left", size=40)
        await self.view.dock(self.pane, edge="right")
        # initial load
        await self.pane.refresh_latest()
        # background refresher
        self.set_interval(0.5, self.background_refresh)

    async def background_refresh(self):
        if not self.pane.paused:
            await self.pane.refresh_latest()

    async def action_load_more(self):
        await self.pane.page_backwards()


# Simple simulator to feed data into the DB
async def simulate_feeder(store: LogStore, rate_hz: float = 200):
    """Simulate raw 3-byte packets at `rate_hz` per second."""
    while True:
        rows = []
        now = int(time.time())
        for _ in range(20):
            # random-ish packet
            file_id = 1
            line = int(time.time()) % 65536
            raw = bytes([file_id, (line >> 8) & 0xFF, line & 0xFF])
            rows.append((now, raw, 0, file_id, 0))
        # adapt to insert_batch signature: (ts, raw, level, file_id, line)
        await store.insert_batch(rows)
        await asyncio.sleep(0.1)


async def main():
    store = LogStore()
    # start a feeder
    asyncio.create_task(simulate_feeder(store))
    app = LogViewerApp()
    await app.run_async()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("exiting")
