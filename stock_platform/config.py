from pathlib import Path

# 日 K 压缩包目录（按年份命名，如 2000.zip）
DAILY_ZIP_DIR = Path(r"C:\Users\bianqi61\Desktop\股票历史数据\全A日K")

# DuckDB 数据库文件（运行脚本后自动生成）
DB_PATH = Path(__file__).resolve().parent / "stock.duckdb"

# 首次测试：只导入哪一年的 zip
TEST_YEAR = 2000

# 首次测试：只导入哪一只股票（zip 内的路径，含年份子目录）
TEST_CODE = "2000/000001.SZ.csv"
