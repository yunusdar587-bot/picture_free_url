"""查看 DuckDB 库里已有的数据。"""

import sys

from db import DatabaseUnavailable, connection

SEP = "=" * 40


def inspect() -> None:
    with connection(read_only=True) as con:
        tables = con.execute("SHOW TABLES").fetchdf()
        print(SEP)
        print("所有表")
        print(SEP)
        print(tables)

        if "daily_bars" not in set(tables.get("name", [])):
            print("\n还没有 daily_bars 表，请先运行 02_init_db.py 或 04_import_year.py")
            return

        print("\n" + SEP)
        print("daily_bars 表结构")
        print(SEP)
        print(con.execute("DESCRIBE daily_bars").fetchdf())

        print("\n" + SEP)
        print("daily_bars 数据概况")
        print(SEP)
        print(con.execute("""
            SELECT
                COUNT(*) AS total_rows,
                COUNT(DISTINCT code) AS stocks,
                MIN(trade_date) AS first_date,
                MAX(trade_date) AS last_date
            FROM daily_bars
        """).fetchdf())

        print("\n" + SEP)
        print("按年份统计")
        print(SEP)
        print(con.execute("""
            SELECT
                year(trade_date) AS year,
                COUNT(*) AS row_count,
                COUNT(DISTINCT code) AS stocks
            FROM daily_bars
            GROUP BY 1
            ORDER BY 1
        """).fetchdf().to_string(index=False))

        print("\n" + SEP)
        print("重复检查（同一 code + trade_date 多条）")
        print(SEP)
        dupes = con.execute("""
            SELECT COUNT(*) AS duplicate_rows
            FROM (
                SELECT code, trade_date, COUNT(*) - 1 AS extra
                FROM daily_bars GROUP BY 1, 2 HAVING COUNT(*) > 1
            )
        """).fetchone()[0]
        if dupes:
            print(f"有 {dupes} 组重复，建议运行 05_dedupe.py")
        else:
            print("无重复")

        print("\n" + SEP)
        print("样例数据（前 3 行）")
        print(SEP)
        print(con.execute("SELECT * FROM daily_bars LIMIT 3").fetchdf())


if __name__ == "__main__":
    try:
        inspect()
    except DatabaseUnavailable as exc:
        sys.exit(str(exc))
