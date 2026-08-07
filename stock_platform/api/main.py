"""Web API：为前端提供股票搜索和 K 线数据。"""

import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from db import DatabaseUnavailable, connection

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# 一次请求最多返回多少根 K 线；A 股单只股票 30 年日线约 7000 根，留足余量。
MAX_BARS = 100_000

UP_COLOR = "#ef5350"    # A 股习惯：红涨
DOWN_COLOR = "#26a69a"  # 绿跌

app = FastAPI(title="Stock Chart API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DatabaseUnavailable)
def _db_unavailable(request, exc: DatabaseUnavailable):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=503, content={"detail": str(exc)})


def _parse_date(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"{field} 日期格式应为 YYYY-MM-DD，收到: {value}"
        )


def _shift_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 2 月 29 日
        return day.replace(month=2, day=28, year=day.year - years)


def _clean(value) -> float | None:
    """DuckDB 的 NULL 经 pandas 变成 NaN，而 NaN 不是合法 JSON。"""
    if value is None:
        return None
    number = float(value)
    return None if math.isnan(number) or math.isinf(number) else number


@app.get("/api/instruments")
def search_instruments(
    q: str = Query("", min_length=0),
    limit: int = Query(50, ge=1, le=10000),
):
    """按股票代码搜索，例如 000001。"""
    keyword = q.strip()
    sql = """
        SELECT code, COUNT(*) AS bar_count,
               MIN(trade_date) AS first_date,
               MAX(trade_date) AS last_date
        FROM daily_bars
        {where}
        GROUP BY code
        ORDER BY code
        LIMIT ?
    """
    with connection() as con:
        if keyword:
            rows = con.execute(
                sql.format(where="WHERE code ILIKE ?"), [f"%{keyword}%", limit]
            ).fetchdf()
        else:
            rows = con.execute(sql.format(where=""), [limit]).fetchdf()

    rows["first_date"] = rows["first_date"].astype(str)
    rows["last_date"] = rows["last_date"].astype(str)
    return rows.to_dict(orient="records")


@app.get("/api/kline")
def get_kline(
    code: str = Query(..., description="例如 000001.SZ"),
    start: str | None = Query(None, description="YYYY-MM-DD"),
    end: str | None = Query(None, description="YYYY-MM-DD"),
    years: int | None = Query(
        None, ge=1, le=100, description="最近 N 年，以该股票最后交易日为基准"
    ),
    limit: int | None = Query(None, ge=1, le=MAX_BARS),
):
    """返回 OHLCV，供 TradingView Lightweight Charts 使用。"""
    start_date = _parse_date(start, "start")
    end_date = _parse_date(end, "end")

    cap = limit or MAX_BARS

    with connection() as con:
        bounds = con.execute(
            "SELECT MIN(trade_date), MAX(trade_date) FROM daily_bars WHERE code = ?",
            [code],
        ).fetchone()
        if bounds[0] is None:
            raise HTTPException(status_code=404, detail=f"未找到股票: {code}")
        first_available, last_available = bounds

        # “最近 N 年”必须以该股票最后有数据的那天为基准；
        # 若以今天为基准，历史数据库会永远查不到东西。
        if years is not None:
            end_date = last_available
            start_date = _shift_years(last_available, years)

        start_date = start_date or first_available
        end_date = end_date or last_available
        if start_date > end_date:
            raise HTTPException(
                status_code=400, detail=f"start ({start_date}) 晚于 end ({end_date})"
            )

        # 倒序取再翻转：万一超出上限，丢掉的是最老的数据而不是最新的。
        df = con.execute(
            """
            SELECT trade_date, open, high, low, close, volume
            FROM daily_bars
            WHERE code = ?
              AND trade_date BETWEEN ? AND ?
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            [code, start_date, end_date, cap + 1],
        ).fetchdf()

    if df.empty:
        raise HTTPException(status_code=404, detail="该日期范围内无数据")

    truncated = len(df) > cap
    if truncated:
        df = df.iloc[:cap]
    df = df.iloc[::-1]

    bars = []
    volumes = []
    skipped = 0
    for row in df.itertuples(index=False):
        ohlc = [_clean(row.open), _clean(row.high), _clean(row.low), _clean(row.close)]
        if any(v is None for v in ohlc):
            skipped += 1  # 停牌等缺 OHLC 的日子画不出蜡烛，直接跳过
            continue
        open_, high, low, close = ohlc
        date_str = row.trade_date.strftime("%Y-%m-%d")
        bars.append(
            {"time": date_str, "open": open_, "high": high, "low": low, "close": close}
        )
        volumes.append(
            {
                "time": date_str,
                "value": _clean(row.volume) or 0.0,
                "color": UP_COLOR if close >= open_ else DOWN_COLOR,
            }
        )

    if not bars:
        raise HTTPException(status_code=404, detail="该日期范围内没有可绘制的 K 线")

    return {
        "code": code,
        # 回显实际返回的区间，而不是请求的区间，否则截断后前端会显示错误的日期跨度
        "start": bars[0]["time"],
        "end": bars[-1]["time"],
        "count": len(bars),
        "truncated": truncated,
        "skipped": skipped,
        "first_available": str(first_available),
        "last_available": str(last_available),
        "bars": bars,
        "volumes": volumes,
    }


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
