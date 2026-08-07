"""清理重复导入的数据，只保留每个 (code, trade_date) 一条。"""

import duckdb

from config import DB_PATH

# 同一天同一只股票若有多条，按数值列排序取第一条。
# 表里没有导入时间可依据，这里的目的只是让重复运行得到一致结果。
DEDUPE_SQL = """
CREATE OR REPLACE TABLE daily_bars_deduped AS
SELECT * EXCLUDE (rn)
FROM (
    SELECT
        *,
        row_number() OVER (
            PARTITION BY code, trade_date
            ORDER BY close NULLS LAST, volume NULLS LAST, amount NULLS LAST
        ) AS rn
    FROM daily_bars
)
WHERE rn = 1
"""


def dedupe_daily_bars() -> None:
    con = duckdb.connect(str(DB_PATH))
    try:
        before = con.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
        distinct = con.execute(
            "SELECT COUNT(*) FROM (SELECT DISTINCT code, trade_date FROM daily_bars)"
        ).fetchone()[0]

        if before == distinct:
            print(f"共 {before} 条，没有重复，无需处理")
            return

        # 建表、删表、改名放在一个事务里；
        # 中途失败不会出现原表已删、新表还没改名的半成品状态。
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(DEDUPE_SQL)
            con.execute("DROP TABLE daily_bars")
            con.execute("ALTER TABLE daily_bars_deduped RENAME TO daily_bars")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            print("去重失败，已回滚，原表保持原样")
            raise

        after = con.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
        print(f"去重前: {before} 条")
        print(f"去重后: {after} 条")
        print(f"删除重复: {before - after} 条")
    finally:
        con.close()


if __name__ == "__main__":
    dedupe_daily_bars()
