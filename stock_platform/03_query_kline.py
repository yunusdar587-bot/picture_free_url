"""第三步：查询日 K 线，确认读取正常。"""

import duckdb

from config import DB_PATH


def get_daily_kline(code: str, start: str, end: str):
    con = duckdb.connect(str(DB_PATH), read_only=True)
    df = con.execute(
        """
        SELECT trade_date, open, high, low, close, volume, pct_chg
        FROM daily_bars
        WHERE code = ?
          AND trade_date BETWEEN ? AND ?
        ORDER BY trade_date
        """,
        [code, start, end],
    ).fetchdf()
    con.close()
    return df


if __name__ == "__main__":
    df = get_daily_kline("000001.SZ", "2000-04-01", "2000-04-30")
    print(f"共 {len(df)} 条")
    print(df.to_string(index=False))
