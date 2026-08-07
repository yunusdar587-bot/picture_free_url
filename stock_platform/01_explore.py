import duckdb
from config import DB_PATH
def inspect():
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
    print("\n" + "=" * 40)
    print("按年份统计")
    print("=" * 40)
    print(con.execute("""
        SELECT
            year(trade_date) AS year,
            COUNT(*) AS rows,
            COUNT(DISTINCT code) AS stocks
        FROM daily_bars
        GROUP BY 1
        ORDER BY 1
    """).fetchdf())
    print("\n" + "=" * 40)
    print("样例数据（前 3 行）")
    print("=" * 40)
    print(con.execute("SELECT * FROM daily_bars LIMIT 3").fetchdf())
    con.close()
if __name__ == "__main__":
    inspect()