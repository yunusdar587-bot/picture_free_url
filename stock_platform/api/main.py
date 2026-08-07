"""Web API：为前端提供股票搜索和 K 线数据。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from db import get_connection

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Stock Chart API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/instruments")
def search_instruments(q: str = Query("", min_length=0), limit: int = 999999):
    """按股票代码搜索，例如 000001。"""
    con = get_connection(read_only=True)
    if q.strip():
        rows = con.execute(
            """
            SELECT code, COUNT(*) AS bar_count,
                   MIN(trade_date) AS first_date,
                   MAX(trade_date) AS last_date
            FROM daily_bars
            WHERE code ILIKE ?
            GROUP BY code
            ORDER BY code
            LIMIT ?
            """,
            [f"%{q.strip()}%", limit],
        ).fetchdf()
    else:
        rows = con.execute(
            """
            SELECT code, COUNT(*) AS bar_count,
                   MIN(trade_date) AS first_date,
                   MAX(trade_date) AS last_date
            FROM daily_bars
            GROUP BY code
            ORDER BY code
            LIMIT ?
            """,
            [limit],
        ).fetchdf()
    con.close()
    return rows.to_dict(orient="records")


@app.get("/api/kline")
def get_kline(
    code: str = Query(..., description="例如 000001.SZ"),
    start: str | None = Query(None, description="YYYY-MM-DD"),
    end: str | None = Query(None, description="YYYY-MM-DD"),
    limit: int = Query(2000, ge=1, le=10000),
):
    """返回 OHLCV，供 TradingView Lightweight Charts 使用。"""
    con = get_connection(read_only=True)

    bounds = con.execute(
        """
        SELECT MIN(trade_date), MAX(trade_date)
        FROM daily_bars
        WHERE code = ?
        """,
        [code],
    ).fetchone()
    if bounds[0] is None:
        con.close()
        raise HTTPException(status_code=404, detail=f"未找到股票: {code}")

    start_date = start or str(bounds[0])
    end_date = end or str(bounds[1])

    df = con.execute(
        """
        SELECT trade_date, open, high, low, close, volume
        FROM daily_bars
        WHERE code = ?
          AND trade_date BETWEEN ? AND ?
        ORDER BY trade_date
        LIMIT ?
        """,
        [code, start_date, end_date, limit],
    ).fetchdf()
    con.close()

    if df.empty:
        raise HTTPException(status_code=404, detail="该日期范围内无数据")

    bars = []
    volumes = []
    for row in df.itertuples(index=False):
        date_str = row.trade_date.strftime("%Y-%m-%d")
        bars.append(
            {
                "time": date_str,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
            }
        )
        volumes.append(
            {
                "time": date_str,
                "value": float(row.volume),
                "color": "#ef5350" if row.close < row.open else "#26a69a",
            }
        )

    return {
        "code": code,
        "start": start_date,
        "end": end_date,
        "count": len(bars),
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
