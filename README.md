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

## 从 Baostock 下载日 K

除了导入本地 zip，也可以直接从 [Baostock](http://baostock.com/) 拉数据。默认区间
2018-05-17 ~ 2026-08-11（即从 2026-08-11 往前数 2000 个交易日），**不复权**。

```bash
python 06_download_baostock.py                 # 下载，每个交易日一个 .csv.gz
python 06_download_baostock.py --import-db     # 落盘文件导入 daily_bars
python 06_download_baostock.py --status        # 看进度，不联网
```

下载和入库分成两步，因为整个区间要跑十几个小时，不能一直占着 DuckDB 的写锁
（那会让网页接口一直返回 503）。下载可中断续跑：已下好的日期会跳过，Ctrl-C 之后
重新运行即可接着下。

| 环境变量 | 含义 | 默认值 |
| --- | --- | --- |
| `STOCK_BAOSTOCK_DIR` | 分片落盘目录 | `stock_platform/baostock_daily` |
| `STOCK_BAOSTOCK_START` | 起始交易日 | `2018-05-17` |
| `STOCK_BAOSTOCK_END` | 结束交易日 | `2026-08-11` |
| `STOCK_BAOSTOCK_SOCKET_TIMEOUT` | 单次 recv 超时秒数 | `120` |
| `STOCK_BAOSTOCK_MAX_RETRY` | 每个日期的重试次数 | `3` |

其他用法：`--limit 5` 只下最近 5 个交易日用来试跑，`--start/--end` 自定义区间，
`--retry-failed` 重试失败清单里的日期，`--sleep` 调请求间隔（默认 0.5 秒，别设成 0）。

Baostock 的日线只覆盖 `daily_bars` 26 列中的 15 列，余下 11 列会是 NULL：
`turnover_free`、`volume_ratio`、`pe`、`ps`、`dv_yield`、`dv_ttm`、`total_share`、
`float_share`、`free_share`、`total_mv`、`circ_mv`。这些列目前没有任何代码读取，
K 线图和搜索功能只用到 `code` / `trade_date` / OHLC / `volume`，所以不影响使用。
其中 `free_share` 和 `turnover_free` 需要自由流通股本，Baostock 完全没有这项数据。

## 启动网页

```bash
python -m uvicorn api.main:app --reload
```

打开 http://127.0.0.1:8000/ ，输入股票代码即可看 K 线。红涨绿跌。
区间下拉框里的「近 N 年」以该股票最后一个交易日为基准，因此历史数据也能正常查看。

K 线和成交量分别占一块画板，各有独立的纵轴，互不遮挡。图上的操作：

| 操作 | 效果 |
| --- | --- |
| 在画板内按住拖动 | 左右移动时间，上下移动价格 |
| 拖动右侧纵轴 | 拉伸纵向刻度 |
| 双击右侧纵轴 | 还原该轴刻度 |
| 滚轮 | 缩放时间轴 |
| 拖动两块画板之间的分隔条 | 调整上下高度 |
| 「重置视图」按钮 | 恢复纵向自适应并让数据铺满时间轴 |

上下平移或拉伸纵轴后，该轴的自动适应会关闭，以免每次重绘都被拉回数据范围；
点「重置视图」即可恢复。

## 画线

图表左侧的竖排工具栏提供四种图形：

| 工具 | 画法 |
| --- | --- |
| 线段 | 点一下定起点，再点一下定终点 |
| 射线 | 同样两点，方向上一直延伸到画布边缘 |
| 矩形 | 两个对角点，只画边框不填充 |
| 斐波那契回撤 | 先点的那头是 1，后点的那头是 0，画出 0 / 0.236 / 0.382 / 0.5 / 0.618 / 0.786 / 1 |

四种工具都可以「点—移动—再点」，也可以按下拖动再松手。画完自动回到选择状态。

图形的端点记的是「哪根 K 线 + 价格」，所以缩放、平移、拉伸纵轴时都贴着原来的
位置走；换时间区间后按日期重新定位。图形按股票分开存，切走再切回来还在。

| 操作 | 效果 |
| --- | --- |
| 选择工具下点中图形 | 选中，两端出现拖动手柄 |
| 拖动图形本体 | 整体移动 |
| 拖动手柄 | 只移动这一个端点 |
| `Delete` | 删除选中的图形 |
| `Esc` | 放弃正在画的图形，退回选择状态 |
| `Ctrl+Z` | 撤销 |
| `Ctrl+Y` 或 `Ctrl+Shift+Z` | 重做 |
| 工具栏最下方的垃圾桶 | 清除该股票的全部图形 |

没点中图形时鼠标事件照常交给图表，所以平移和缩放不受影响。

导入脚本运行期间会独占数据库写锁，此时网页接口会返回 503 并提示稍后再试。
