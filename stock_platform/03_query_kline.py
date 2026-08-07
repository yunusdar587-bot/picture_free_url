"""第三步：查询日 K 线，确认读取正常。

用法:
    python 03_query_kline.py
    python 03_query_kline.py 000001.SZ 2000-04-01 2000-04-30
"""

import sys

from config import TEST_STOCK
from db import DatabaseUnavailable, connection


def get_daily_kline(code: str, start: str | None = None, end: str | None = None):
    sql = """
        SELECT trade_date, open, high, low, close, volume, pct_chg
        FROM daily_bars
        WHERE code = ?
          {date_filter}
        ORDER BY trade_date
    """
    params: list = [code]
    if start and end:
        sql = sql.format(date_filter="AND trade_date BETWEEN ? AND ?")
        params += [start, end]
    else:
        sql = sql.format(date_filter="")

    with connection(read_only=True) as con:
        return con.execute(sql, params).fetchdf()


if __name__ == "__main__":
    args = sys.argv[1:]
    code = args[0] if args else TEST_STOCK
    start = args[1] if len(args) > 1 else None
    end = args[2] if len(args) > 2 else None

    try:
        df = get_daily_kline(code, start, end)
    except DatabaseUnavailable as exc:
        sys.exit(str(exc))

    print(f"{code} 共 {len(df)} 条")
    print(df.head(20).to_string(index=False))
