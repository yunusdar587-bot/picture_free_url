# picture_free_url

`stock_platform/`：A 股日 K 线数据平台。把按年份打包的行情 zip 导入 DuckDB，
再由 FastAPI 提供接口，前端用 TradingView Lightweight Charts 画图。

## 准备

```bash
cd stock_platform
pip install -r requirements.txt
```

数据目录和数据库位置可以用环境变量指定，不必改代码：

| 环境变量 | 含义 | 默认值 |
| --- | --- | --- |
| `STOCK_DAILY_ZIP_DIR` | 存放 `2000.zip` 这类年份压缩包的目录 | `C:\Users\bianqi61\Desktop\股票历史数据\全A日K` |
| `STOCK_DB_PATH` | DuckDB 文件位置 | `stock_platform/stock.duckdb` |
| `STOCK_TEST_YEAR` | `02_init_db.py` 试导入的年份 | `2000` |
| `STOCK_TEST_STOCK` | `02_init_db.py` 试导入的股票 | `000001.SZ` |

## 步骤

```bash
python 01_explore.py          # 看 zip 和 CSV 长什么样（此时还没有数据库）
python 02_init_db.py          # 建表，试导入一只股票
python 03_query_kline.py      # 命令行查一下，确认读得到
python 04_import_year.py --all  # 导入全部年份
python inspect_db.py          # 查看库内现状
```

`04_import_year.py` 的几种用法：

```bash
python 04_import_year.py 2018             # 单个年份
python 04_import_year.py 2000 2001 2002   # 若干年份
python 04_import_year.py --range 2000 2024  # 连续区间
python 04_import_year.py --all            # 目录下所有年份
```

重复导入同一年不会让数据翻倍（会先删掉该年旧数据再导）。若曾用旧版本导入过
而出现重复，运行 `python 05_dedupe.py` 清理。

## 启动网页

```bash
python -m uvicorn api.main:app --reload
```

打开 http://127.0.0.1:8000/ ，输入股票代码即可看 K 线。红涨绿跌，
下方为成交量。区间下拉框里的「近 N 年」以该股票最后一个交易日为基准，
因此历史数据也能正常查看。

导入脚本运行期间会独占数据库写锁，此时网页接口会返回 503 并提示稍后再试。
