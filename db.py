import sqlite3
from datetime import date
from pathlib import Path
from typing import Iterable

DB_PATH = Path("database.sqlite3")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_user_id INTEGER NOT NULL UNIQUE,
                tg_username TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS habit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                habit_id INTEGER NOT NULL,
                log_date TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (habit_id) REFERENCES habits(id),
                UNIQUE(habit_id, log_date)
            )
            """
        )


def upsert_user(tg_user_id: int, tg_username: str | None) -> int:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (tg_user_id, tg_username)
            VALUES (?, ?)
            ON CONFLICT(tg_user_id) DO UPDATE SET tg_username = excluded.tg_username
            """,
            (tg_user_id, tg_username),
        )
        row = conn.execute("SELECT id FROM users WHERE tg_user_id = ?", (tg_user_id,)).fetchone()
        return int(row["id"])


def add_habit(user_id: int, title: str) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO habits (user_id, title) VALUES (?, ?)",
            (user_id, title.strip()),
        )
        return int(cursor.lastrowid)


def list_habits(user_id: int) -> list[sqlite3.Row]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title
            FROM habits
            WHERE user_id = ? AND is_active = 1
            ORDER BY id ASC
            """,
            (user_id,),
        ).fetchall()
        return list(rows)


def mark_done(habit_id: int, target_date: date) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO habit_logs (habit_id, log_date, done)
            VALUES (?, ?, 1)
            ON CONFLICT(habit_id, log_date) DO UPDATE SET done = 1
            """,
            (habit_id, target_date.isoformat()),
        )
        return cursor.rowcount > 0


def mark_done_for_user(user_id: int, habit_id: int, target_date: date) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO habit_logs (habit_id, log_date, done)
            SELECT h.id, ?, 1
            FROM habits h
            WHERE h.id = ? AND h.user_id = ? AND h.is_active = 1
            ON CONFLICT(habit_id, log_date) DO UPDATE SET done = 1
            """,
            (target_date.isoformat(), habit_id, user_id),
        )
        return cursor.rowcount > 0


def weekly_status(habit_ids: Iterable[int], week_dates: list[date]) -> dict[tuple[int, str], int]:
    habit_id_list = list(habit_ids)
    if not habit_id_list:
        return {}

    placeholders = ",".join(["?"] * len(habit_id_list))
    params = habit_id_list
    params.extend([week_dates[0].isoformat(), week_dates[-1].isoformat()])

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT habit_id, log_date, done
            FROM habit_logs
            WHERE habit_id IN ({placeholders})
              AND log_date BETWEEN ? AND ?
            """,
            params,
        ).fetchall()

    return {(int(r["habit_id"]), str(r["log_date"])): int(r["done"]) for r in rows}
