"""清理重复导入的数据，只保留每个 (code, trade_date) 一条。"""

import duckdb

from config import DB_PATH


def dedupe_daily_bars() -> None:
    con = duckdb.connect(str(DB_PATH))

    before = con.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]

    con.execute("""
        CREATE TABLE daily_bars_deduped AS
        SELECT * EXCLUDE (rn)
        FROM (
            SELECT
                *,
                row_number() OVER (
                    PARTITION BY code, trade_date
                    ORDER BY code
                ) AS rn
            FROM daily_bars
        )
        WHERE rn = 1
    """)
    con.execute("DROP TABLE daily_bars")
    con.execute("ALTER TABLE daily_bars_deduped RENAME TO daily_bars")

    after = con.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
    print(f"去重前: {before} 条")
    print(f"去重后: {after} 条")
    print(f"删除重复: {before - after} 条")

    con.close()


if __name__ == "__main__":
    dedupe_daily_bars()
