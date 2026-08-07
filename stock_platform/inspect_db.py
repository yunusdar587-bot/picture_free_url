"""查看 DuckDB 库结构。"""

import duckdb

from config import DB_PATH


def inspect() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)

    print("=" * 40)
    print("所有表")
    print("=" * 40)
    print(con.execute("SHOW TABLES").fetchdf())

    print("\n" + "=" * 40)
    print("daily_bars 表结构")
    print("=" * 40)
    print(con.execute("DESCRIBE daily_bars").fetchdf())

    print("\n" + "=" * 40)
    print("daily_bars 数据概况")
    print("=" * 40)
    print(con.execute("""
        SELECT
            COUNT(*) AS total_rows,
            COUNT(DISTINCT code) AS stocks,
            MIN(trade_date) AS first_date,
            MAX(trade_date) AS last_date
        FROM daily_bars
    """).fetchdf())

    con.close()


if __name__ == "__main__":
    inspect()
