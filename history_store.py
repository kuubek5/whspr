"""SQLite take history: storage, word counts and dashboard stats. Moved verbatim out of flow.py."""

import sqlite3
import time

import flow

# ---------------- History (SQLite) ----------------
# Set once the `words` column is known to exist, so the migration check below
# runs at most once per process instead of on every _db() call.
_schema_migrated = False


def _migrate_word_counts(con: sqlite3.Connection) -> None:
    """Add and backfill the per-row `words` column.

    The dashboard's "words" and "wpm" are sums of len(text.split()) over the
    whole table. Computing that in SQL is not possible without changing what a
    word means (SQLite has no split(); the LENGTH/REPLACE trick miscounts runs
    of spaces, tabs and newlines, all of which the LLM corrector emits), and
    computing it in Python meant SELECTing every transcript ever recorded on
    every UI start. Storing the count at insert time gets both: the number is
    still exactly len(text.split()), and the dashboard becomes a pure SQL
    aggregate that never loads a transcript.

    Existing rows are backfilled once, the only time the column is missing."""
    global _schema_migrated
    if _schema_migrated:
        return
    cols = {r[1] for r in con.execute("PRAGMA table_info(history)")}
    if "words" not in cols:
        con.execute("ALTER TABLE history ADD COLUMN words INTEGER")
        rows = con.execute(
            "SELECT id, text FROM history WHERE words IS NULL").fetchall()
        con.executemany("UPDATE history SET words=? WHERE id=?",
                        [(len((t or "").split()), i) for i, t in rows])
        # commit before returning: the ALTER and the backfill sit in one
        # transaction, and if the caller never enters a `with con` block it
        # would be rolled back at close — leaving the column gone while this
        # process still believed it existed, so every INSERT would then fail
        con.commit()
        flow.log(f"history: added word counts for {len(rows)} existing row(s)")
    _schema_migrated = True


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(flow.DB_PATH)
    con.execute(
        "CREATE TABLE IF NOT EXISTS history ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, lang TEXT, "
        "duration REAL, text TEXT)"
    )
    # ts is the only column we filter on (the "today" counters in
    # history_stats), and the table grows without bound, so index it.
    con.execute("CREATE INDEX IF NOT EXISTS idx_history_ts ON history(ts)")
    _migrate_word_counts(con)
    # WAL: the dictation path does many small single-row INSERTs, and in the
    # default rollback-journal mode each one rewrites the journal and blocks
    # readers. WAL lets the UI read history while a take is being written.
    # It is a persistent property of the file — setting it again is a no-op.
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass  # e.g. db on a network share, which cannot do WAL — plain mode is fine
    return con


def history_add(text: str, lang: str, duration: float) -> int | None:
    """Store one take. Returns its rowid, or None if the write failed.

    The rowid matters because the transcript is not necessarily final when it is
    first written: with llm_async the raw text is pasted (and recorded) at once
    and the polished version arrives a second later, so the caller needs a
    handle to amend the row rather than insert a near-duplicate."""
    try:
        with _db() as con:
            # words is stored, not derived: see _migrate_word_counts
            cur = con.execute(
                "INSERT INTO history (ts, lang, duration, text, words) "
                "VALUES (?,?,?,?,?)",
                (time.strftime("%Y-%m-%d %H:%M:%S"), lang, round(duration, 1),
                 text, len(text.split())),
            )
            return cur.lastrowid
    except sqlite3.Error as e:
        flow.log(f"history write failed: {e}")
        return None


def history_update_text(row_id: int | None, text: str) -> None:
    """Replace a stored transcript in place (async LLM polish landing late).

    A no-op for a missing rowid, so the caller does not have to branch on the
    insert having failed — losing the polished wording from the history list is
    a cosmetic loss, and never worth an exception on the paste path."""
    if not row_id:
        return
    try:
        with _db() as con:
            con.execute("UPDATE history SET text = ?, words = ? WHERE id = ?",
                        (text, len(text.split()), row_id))
    except sqlite3.Error as e:
        flow.log(f"history update failed: {e}")


def history_last(n: int = 100) -> list[tuple]:
    try:
        with _db() as con:
            return con.execute(
                "SELECT id, ts, lang, duration, text FROM history ORDER BY id DESC LIMIT ?", (n,)
            ).fetchall()
    except sqlite3.Error:
        return []


def history_delete(row_id: int) -> None:
    try:
        with _db() as con:
            con.execute("DELETE FROM history WHERE id=?", (row_id,))
    except sqlite3.Error as e:
        flow.log(f"history delete failed: {e}")


def history_clear() -> None:
    try:
        with _db() as con:
            con.execute("DELETE FROM history")
    except sqlite3.Error as e:
        flow.log(f"history clear failed: {e}")


def history_stats() -> dict:
    """Aggregate numbers for the dashboard.

    Called from Api.bootstrap() on every UI start, and the table only ever
    grows, so it must not haul the whole history into Python. Every number here
    is a SQL aggregate: no transcript is loaded at all. Word counts come from
    the stored `words` column, which holds exactly len(text.split()) as computed
    at insert time (see _migrate_word_counts), so the meaning of "words" and
    "wpm" is unchanged from when they were summed in Python.

    Today's rows are found through idx_history_ts. GLOB, not LIKE: LIKE is
    case-insensitive by default and so cannot use the index, while a prefix GLOB
    can. On a 'YYYY-MM-DD HH:MM:SS' ts it is exactly ts.startswith(today)."""
    today = time.strftime("%Y-%m-%d")
    total, secs, words, dictations_today, words_today = 0, 0, 0, 0, 0
    try:
        with _db() as con:
            # duration and words can be NULL (rows written before each column
            # existed); SUM skips NULLs and COALESCE turns the empty-table SUM
            # into 0 — the same result the old Python generators produced
            total, secs, words = con.execute(
                "SELECT COUNT(*), COALESCE(SUM(duration), 0), "
                "COALESCE(SUM(words), 0) FROM history"
            ).fetchone()
            dictations_today, words_today = con.execute(
                "SELECT COUNT(*), COALESCE(SUM(words), 0) FROM history "
                "WHERE ts GLOB ?", (today + "*",)
            ).fetchone()
    except sqlite3.Error:
        pass
    # words per minute across all dictated audio time
    wpm = (words / (secs / 60)) if secs else 0
    return {
        "total": total, "words": words, "words_today": words_today,
        "dictations_today": dictations_today, "seconds": secs, "wpm": wpm,
    }
