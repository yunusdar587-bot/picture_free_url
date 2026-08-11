"""从 Baostock 下载全 A 股不复权日 K，默认区间 2018-05-17 ~ 2026-08-11。

走的是 `query_daily_history_k_AStock(date)`：一次请求拿回某个交易日的全市场数据。
相比逐只股票拉取，它请求次数少（2000 次 vs 5450 次）、快一些，而且不需要先取股票
列表——当天有交易的标的都会返回，包含后来退市的，没有幸存者偏差。该接口返回的
adjustflag 恒为 3，即不复权，正是我们要的口径。

下载与入库分成两步，因为下载要跑 20 小时以上，不能一直占着 DuckDB 的写锁
（那会让网页接口一直返回 503）：

    python 06_download_baostock.py                  # 下载，每个交易日一个 .csv.gz
    python 06_download_baostock.py --import-db      # 落盘文件导入 daily_bars

下载是可中断续跑的：已经下好的日期会跳过，Ctrl-C 之后重新运行即可接着下。

其他用法:
    python 06_download_baostock.py --limit 5                  # 只下最近 5 个交易日，试跑
    python 06_download_baostock.py --start 2024-01-01         # 自定义区间
    python 06_download_baostock.py --retry-failed             # 只重试失败清单里的日期
    python 06_download_baostock.py --status                   # 看进度，不联网
"""

import argparse
import contextlib
import csv
import gzip
import os
import sys
import time
from datetime import date as date_cls
from pathlib import Path

import baostock as bs
import baostock.common.context as bs_context
import duckdb

from config import BAOSTOCK_DIR, BAOSTOCK_END, BAOSTOCK_START, DB_PATH
from schema import CREATE_TABLE_SQL

# Baostock 日线的 18 个字段，query_daily_history_k_AStock 返回的就是这一组
FIELDS = [
    "date", "code", "open", "high", "low", "close", "preclose", "volume",
    "amount", "adjustflag", "turn", "tradestatus", "pctChg", "peTTM",
    "pbMRQ", "psTTM", "pcfNcfTTM", "isST",
]

# 单次 recv 的超时。baostock 的 send_msg 里是不带超时的 recv 循环，
# 服务端一卡就会永久阻塞（实测遇到过一次 5 分钟无响应），必须自己设。
# 正常一次请求 30~50 秒，但那是多次 recv 累加出来的，单次 recv 不会这么久。
SOCKET_TIMEOUT_SEC = float(os.environ.get("STOCK_BAOSTOCK_SOCKET_TIMEOUT", "120"))

# 每个日期失败后的重试次数，每次重试都会重新登录
MAX_RETRY = int(os.environ.get("STOCK_BAOSTOCK_MAX_RETRY", "3"))

CALENDAR_CACHE = BAOSTOCK_DIR / "_trade_dates.txt"
FAILED_LIST = BAOSTOCK_DIR / "_failed.txt"


# ---------------------------------------------------------------- baostock 连接


def _apply_socket_timeout() -> None:
    sock = getattr(bs_context, "default_socket", None)
    if sock is not None:
        sock.settimeout(SOCKET_TIMEOUT_SEC)


def login() -> None:
    result = bs.login()
    if result.error_code != "0":
        raise RuntimeError(f"Baostock 登录失败: {result.error_code} {result.error_msg}")
    _apply_socket_timeout()


def relogin() -> None:
    """连接卡死或出错后重建连接。logout 本身可能也失败，忽略即可。"""
    with contextlib.suppress(Exception):
        bs.logout()
    time.sleep(2)
    login()


# ---------------------------------------------------------------- 交易日历


def trade_dates(start: str, end: str) -> list[str]:
    """区间内的交易日列表。结果按 (start, end) 缓存到磁盘，避免重复请求。"""
    cache_key = f"{start}~{end}"
    if CALENDAR_CACHE.exists():
        lines = CALENDAR_CACHE.read_text(encoding="utf-8").splitlines()
        if lines and lines[0] == cache_key:
            return [d for d in lines[1:] if d]

    result = bs.query_trade_dates(start_date=start, end_date=end)
    if result.error_code != "0":
        raise RuntimeError(
            f"query_trade_dates 失败: {result.error_code} {result.error_msg}"
        )
    days = []
    while result.next():
        calendar_date, is_trading = result.get_row_data()
        if is_trading == "1":
            days.append(calendar_date)

    CALENDAR_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CALENDAR_CACHE.write_text("\n".join([cache_key] + days) + "\n", encoding="utf-8")
    return days


# ---------------------------------------------------------------- 下载


def shard_path(date: str) -> Path:
    return BAOSTOCK_DIR / f"{date}.csv.gz"


def fetch_one_date(date: str) -> list[list[str]]:
    """取某个交易日的全市场日 K。返回行列表，失败抛 RuntimeError。

    注意只能用 while rs.next() 手动遍历，不能用 rs.get_data()——后者内部是
    DataFrame.append，这个方法在 pandas 2.0 就被删了，一旦结果跨页必然抛
    AttributeError。
    """
    result = bs.query_daily_history_k_AStock(date=date)
    if result.error_code != "0":
        raise RuntimeError(f"{result.error_code} {result.error_msg}")

    rows = []
    while result.next():
        rows.append(result.get_row_data())
    return rows


def write_shard(date: str, rows: list[list[str]]) -> None:
    """先写临时文件再改名，避免中途被杀留下半截文件被当成已完成。"""
    final = shard_path(date)
    tmp = final.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(FIELDS)
        writer.writerows(rows)
    tmp.replace(final)


def record_failure(date: str, reason: str) -> None:
    with FAILED_LIST.open("a", encoding="utf-8") as fh:
        fh.write(f"{date}\t{reason}\n")


def failed_dates() -> list[str]:
    if not FAILED_LIST.exists():
        return []
    seen = []
    for line in FAILED_LIST.read_text(encoding="utf-8").splitlines():
        date = line.split("\t")[0].strip()
        if date and date not in seen:
            seen.append(date)
    return seen


def _fmt_eta(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} 秒"
    if seconds < 5400:
        return f"{seconds / 60:.0f} 分钟"
    return f"{seconds / 3600:.1f} 小时"


def download(dates: list[str], sleep_sec: float) -> None:
    BAOSTOCK_DIR.mkdir(parents=True, exist_ok=True)

    todo = [d for d in dates if not shard_path(d).exists()]
    done_already = len(dates) - len(todo)
    print(f"区间内交易日 {len(dates)} 个，已下载 {done_already} 个，待下载 {len(todo)} 个")
    if not todo:
        print("没有需要下载的日期。")
        return

    # 新数据更可能被马上用到，所以从最近的日期往回下
    todo.sort(reverse=True)

    # 最近几个交易日拿不到数据，通常只是还没发布，提示语要和真失败区分开
    recent_cutoff = dates[-3] if len(dates) >= 3 else dates[0]

    started = time.time()
    ok = 0
    failed = 0
    total_rows = 0

    for i, date in enumerate(todo, start=1):
        for attempt in range(1, MAX_RETRY + 1):
            try:
                rows = fetch_one_date(date)
            # 网络错误、socket 超时、协议解析失败、服务端报错都要一视同仁地重试，
            # baostock 不保证异常类型，这里只能全接。
            except Exception as exc:  # noqa: BLE001
                if attempt == MAX_RETRY:
                    failed += 1
                    record_failure(date, str(exc))
                    print(f"  [{i}/{len(todo)}] {date} 失败（已重试 {MAX_RETRY} 次）: {exc}")
                    break
                print(f"  [{i}/{len(todo)}] {date} 第 {attempt} 次失败，重连后重试: {exc}")
                relogin()
                continue

            if not rows:
                # 交易日历说是交易日却没有数据。最常见的原因是当天收盘后
                # Baostock 还没发布（一般要等到晚上），这不是错误，但也不能
                # 落一个空分片，否则下次运行会当成已完成而永远补不上。
                failed += 1
                record_failure(date, "返回 0 行")
                hint = "，可能尚未发布，晚些用 --retry-failed 补" if date >= recent_cutoff else ""
                print(f"  [{i}/{len(todo)}] {date} 返回 0 行{hint}")
                break

            write_shard(date, rows)
            ok += 1
            total_rows += len(rows)
            break

        elapsed = time.time() - started
        if i % 10 == 0 or i == len(todo):
            per_date = elapsed / i
            eta = per_date * (len(todo) - i)
            print(
                f"  [{i}/{len(todo)}] {date}  累计 {total_rows:,} 行  "
                f"均速 {per_date:.1f} 秒/日  剩余约 {_fmt_eta(eta)}"
            )

        if sleep_sec > 0 and i < len(todo):
            time.sleep(sleep_sec)

    print(
        f"\n下载结束：成功 {ok} 个交易日，失败 {failed} 个，共 {total_rows:,} 行，"
        f"耗时 {_fmt_eta(time.time() - started)}"
    )
    if failed:
        print(f"失败清单见 {FAILED_LIST}，可用 --retry-failed 重试")


# ---------------------------------------------------------------- 入库

# Baostock 18 字段 -> daily_bars 26 列。
#   code       sh.600000 -> 600000.SH，和库里已有数据保持一致
#   volume     股 -> 手（÷100）
#   amount     元 -> 千元（÷1000）
#   change     Baostock 不给，用 close - preclose 补
#   pb         Baostock 的 pbMRQ 就是最近报告期口径，直接对应
# 剩下 11 列 Baostock 没有，留 NULL：turnover_free、volume_ratio、pe、ps、
# dv_yield、dv_ttm、total_share、float_share、free_share、total_mv、circ_mv。
# 其中 free_share / turnover_free 需要自由流通股本，Baostock 完全没有这项数据。
IMPORT_SQL = """
INSERT INTO daily_bars BY NAME
SELECT
    split_part(code, '.', 2) || '.' || upper(split_part(code, '.', 1)) AS code,
    CAST(date AS DATE)                                                AS trade_date,
    TRY_CAST(open  AS DOUBLE)                                         AS open,
    TRY_CAST(high  AS DOUBLE)                                         AS high,
    TRY_CAST(low   AS DOUBLE)                                         AS low,
    TRY_CAST(close AS DOUBLE)                                         AS close,
    TRY_CAST(preclose AS DOUBLE)                                      AS pre_close,
    TRY_CAST(close AS DOUBLE) - TRY_CAST(preclose AS DOUBLE)          AS change,
    TRY_CAST(pctChg AS DOUBLE)                                        AS pct_chg,
    TRY_CAST(volume AS DOUBLE) / 100.0                                AS volume,
    TRY_CAST(amount AS DOUBLE) / 1000.0                               AS amount,
    TRY_CAST(turn   AS DOUBLE)                                        AS turnover,
    TRY_CAST(peTTM  AS DOUBLE)                                        AS pe_ttm,
    TRY_CAST(pbMRQ  AS DOUBLE)                                        AS pb,
    TRY_CAST(psTTM  AS DOUBLE)                                        AS ps_ttm
FROM read_csv(?, header = true, all_varchar = true)
WHERE tradestatus = '1'
"""


def import_to_db(dates: list[str]) -> None:
    """把已下载的分片导入 daily_bars。同一天重复导入不会翻倍：先删该日再插。"""
    shards = [(d, shard_path(d)) for d in dates if shard_path(d).exists()]
    if not shards:
        print(f"{BAOSTOCK_DIR} 下没有可导入的分片，请先运行下载。")
        return

    print(f"待导入 {len(shards)} 个交易日的分片 -> {DB_PATH}")
    con = duckdb.connect(str(DB_PATH))
    try:
        con.execute(CREATE_TABLE_SQL)
        inserted = 0
        for i, (date, path) in enumerate(shards, start=1):
            # 每个日期一个事务。整批放一个事务会在 20 小时的量级上占满内存，
            # 而且中途失败要全部重来；按日提交，失败时只丢当天。
            con.execute("BEGIN TRANSACTION")
            try:
                con.execute("DELETE FROM daily_bars WHERE trade_date = ?", [date])
                con.execute(IMPORT_SQL, [str(path)])
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                print(f"  {date} 导入失败，已回滚该日")
                raise

            count = con.execute(
                "SELECT COUNT(*) FROM daily_bars WHERE trade_date = ?", [date]
            ).fetchone()[0]
            inserted += count
            if i % 100 == 0 or i == len(shards):
                print(f"  [{i}/{len(shards)}] {date}  累计 {inserted:,} 行")

        total = con.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
        codes = con.execute("SELECT COUNT(DISTINCT code) FROM daily_bars").fetchone()[0]
        span = con.execute(
            "SELECT MIN(trade_date), MAX(trade_date) FROM daily_bars"
        ).fetchone()
    finally:
        con.close()

    print(f"\n本次导入 {inserted:,} 行")
    print(f"daily_bars 现有 {total:,} 行，{codes} 只股票，区间 {span[0]} ~ {span[1]}")


# ---------------------------------------------------------------- 进度


def show_status(dates: list[str]) -> None:
    have = [d for d in dates if shard_path(d).exists()]
    missing = [d for d in dates if not shard_path(d).exists()]
    size_mb = sum(shard_path(d).stat().st_size for d in have) / 1024 / 1024

    print(f"落盘目录: {BAOSTOCK_DIR}")
    print(f"区间 {dates[0]} ~ {dates[-1]}，交易日 {len(dates)} 个")
    print(f"  已下载 {len(have)} 个（{size_mb:.1f} MB）")
    print(f"  未下载 {len(missing)} 个")
    if missing:
        preview = ", ".join(missing[:5])
        more = " ..." if len(missing) > 5 else ""
        print(f"    最早缺失: {preview}{more}")
    failed = failed_dates()
    if failed:
        print(f"  失败清单 {len(failed)} 个: {', '.join(failed[:5])}"
              f"{' ...' if len(failed) > 5 else ''}")


# ---------------------------------------------------------------- 入口


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从 Baostock 下载全 A 股不复权日 K",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--start", default=BAOSTOCK_START, help=f"起始日，默认 {BAOSTOCK_START}")
    parser.add_argument("--end", default=BAOSTOCK_END, help=f"结束日，默认 {BAOSTOCK_END}")
    parser.add_argument(
        "--limit", type=int, default=0,
        help="只处理最近 N 个交易日，用于试跑（0 表示全部）",
    )
    parser.add_argument(
        "--sleep", type=float, default=0.5,
        help="每个日期之间的间隔秒数，默认 0.5，别设成 0",
    )
    parser.add_argument("--import-db", action="store_true", help="把已下载的分片导入 daily_bars")
    parser.add_argument("--retry-failed", action="store_true", help="只重试失败清单里的日期")
    parser.add_argument("--status", action="store_true", help="只看进度，不联网")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    for label, value in (("--start", args.start), ("--end", args.end)):
        try:
            date_cls.fromisoformat(value)
        except ValueError:
            print(f"{label} 日期格式应为 YYYY-MM-DD，收到: {value}")
            return 2
    if args.start > args.end:
        print(f"--start ({args.start}) 晚于 --end ({args.end})")
        return 2

    # --status 和 --import-db 都不需要联网，但要拿到交易日列表；
    # 日历有缓存时就不必登录。
    need_calendar_network = not CALENDAR_CACHE.exists()
    offline_ok = (args.status or args.import_db) and not need_calendar_network

    if offline_ok:
        dates = trade_dates(args.start, args.end)
    else:
        login()
        try:
            dates = trade_dates(args.start, args.end)
        except Exception:
            bs.logout()
            raise

    if not dates:
        print(f"{args.start} ~ {args.end} 之间没有交易日")
        if not offline_ok:
            bs.logout()
        return 1

    if args.limit > 0:
        dates = dates[-args.limit:]

    try:
        if args.status:
            show_status(dates)
        elif args.import_db:
            import_to_db(dates)
        else:
            targets = dates
            if args.retry_failed:
                failed = set(failed_dates())
                targets = [d for d in dates if d in failed]
                if not targets:
                    print("失败清单是空的，没什么要重试的。")
                    return 0
                # 重试前把旧的失败记录清掉，免得越积越长
                FAILED_LIST.unlink(missing_ok=True)
                print(f"重试 {len(targets)} 个失败日期")
            download(targets, args.sleep)
    except KeyboardInterrupt:
        print("\n已中断。已下载的分片都保留着，重新运行会接着下。")
        return 130
    finally:
        if not offline_ok:
            with contextlib.suppress(Exception):
                bs.logout()

    return 0


if __name__ == "__main__":
    sys.exit(main())
