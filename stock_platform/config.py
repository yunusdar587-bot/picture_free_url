import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _path_from_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


# 日 K 压缩包目录（按年份命名，如 2000.zip）。
# 换机器或换系统时用环境变量 STOCK_DAILY_ZIP_DIR 覆盖，不必改代码。
DAILY_ZIP_DIR = _path_from_env(
    "STOCK_DAILY_ZIP_DIR",
    Path(r"C:\Users\bianqi61\Desktop\股票历史数据\全A日K"),
)

# DuckDB 数据库文件（运行导入脚本后自动生成）
DB_PATH = _path_from_env("STOCK_DB_PATH", HERE / "stock.duckdb")

# 06_download_baostock.py 的落盘目录，每个交易日一个 .csv.gz
BAOSTOCK_DIR = _path_from_env("STOCK_BAOSTOCK_DIR", HERE / "baostock_daily")

# 下载区间：2018-05-17 是 2026-08-11 往前第 2000 个交易日
BAOSTOCK_START = os.environ.get("STOCK_BAOSTOCK_START", "2018-05-17")
BAOSTOCK_END = os.environ.get("STOCK_BAOSTOCK_END", "2026-08-11")

# 首次测试：只导入哪一年的 zip
TEST_YEAR = int(os.environ.get("STOCK_TEST_YEAR", "2000"))

# 首次测试：只导入哪一只股票。zip 内的路径含年份子目录，
# 因此这里跟着 TEST_YEAR 走，避免改了年份却仍指向旧年份的 CSV。
TEST_STOCK = os.environ.get("STOCK_TEST_STOCK", "000001.SZ")
TEST_CODE = f"{TEST_YEAR}/{TEST_STOCK}.csv"
