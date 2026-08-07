"""daily_bars 的表结构与导入语句，供各导入脚本共用。"""

from pathlib import Path

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS daily_bars (
    code           VARCHAR,
    trade_date     DATE,
    open           DOUBLE,
    high           DOUBLE,
    low            DOUBLE,
    close          DOUBLE,
    pre_close      DOUBLE,
    change         DOUBLE,
    pct_chg        DOUBLE,
    volume         DOUBLE,
    amount         DOUBLE,
    turnover       DOUBLE,
    turnover_free  DOUBLE,
    volume_ratio   DOUBLE,
    pe             DOUBLE,
    pe_ttm         DOUBLE,
    pb             DOUBLE,
    ps             DOUBLE,
    ps_ttm         DOUBLE,
    dv_yield       DOUBLE,
    dv_ttm         DOUBLE,
    total_share    DOUBLE,
    float_share    DOUBLE,
    free_share     DOUBLE,
    total_mv       DOUBLE,
    circ_mv        DOUBLE
)
"""

INSERT_SQL = """
INSERT INTO daily_bars
SELECT
    code,
    CAST(datetime AS DATE) AS trade_date,
    open, high, low, close, pre_close,
    change, pct_chg, volume, amount,
    turnover, turnover_free, volume_ratio,
    pe, pe_ttm, pb, ps, ps_ttm,
    dv_yield, dv_ttm,
    total_share, float_share, free_share,
    total_mv, circ_mv
FROM read_csv_auto(?, header=true)
"""


def valid_csv_names(members: list[str]) -> list[str]:
    """挑出 zip 里真正的行情 CSV，跳过 macOS 打包产生的垃圾条目。"""
    return [
        name
        for name in members
        if name.lower().endswith(".csv")
        and not name.startswith("__MACOSX")
        and not Path(name).name.startswith("._")
    ]
