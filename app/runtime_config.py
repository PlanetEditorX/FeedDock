from __future__ import annotations

from collections.abc import Iterable

from .db import connect, transaction, utcnow_iso


def list_hidden(year: int, season: str, weekday: int | None = None) -> list[dict]:
    sql = "SELECT year, season, weekday, bangumi_id, title FROM mikan_hidden WHERE year=? AND season=?"
    params: list[object] = [year, season]
    if weekday is not None:
        sql += " AND weekday=?"
        params.append(weekday)
    sql += " ORDER BY weekday, title, bangumi_id"
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def hidden_id_set(year: int, season: str) -> set[tuple[int, int]]:
    return {(int(row["weekday"]), int(row["bangumi_id"])) for row in list_hidden(year, season)}


def replace_week_hidden(
    year: int,
    season: str,
    weekday: int,
    entries: Iterable[dict],
) -> list[dict]:
    normalized: dict[int, str] = {}
    for entry in entries:
        bangumi_id = int(entry["bangumi_id"])
        if bangumi_id <= 0:
            continue
        normalized[bangumi_id] = str(entry.get("title") or "").strip()[:300]

    now = utcnow_iso()
    with transaction() as conn:
        conn.execute(
            "DELETE FROM mikan_hidden WHERE year=? AND season=? AND weekday=?",
            (year, season, weekday),
        )
        conn.executemany(
            """
            INSERT INTO mikan_hidden(year, season, weekday, bangumi_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (year, season, weekday, bangumi_id, title, now, now)
                for bangumi_id, title in normalized.items()
            ],
        )
    return list_hidden(year, season, weekday)


def clear_week_hidden(year: int, season: str, weekday: int) -> None:
    with transaction() as conn:
        conn.execute(
            "DELETE FROM mikan_hidden WHERE year=? AND season=? AND weekday=?",
            (year, season, weekday),
        )
