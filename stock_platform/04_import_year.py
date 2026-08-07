"""第四步（可选）：导入某一年的全部日 K 数据。"""

import shutil
import zipfile
from pathlib import Path

import duckdb

from config import DAILY_ZIP_DIR, DB_PATH

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
    return [
        name
        for name in members
        if name.lower().endswith(".csv")
        and not name.startswith("__MACOSX")
        and not Path(name).name.startswith("._")
    ]


def import_year(year: int) -> None:
    zip_path = DAILY_ZIP_DIR / f"{year}.zip"
    if not zip_path.exists():
        raise FileNotFoundError(f"找不到压缩包: {zip_path}")

    temp_dir = Path(__file__).resolve().parent / "_temp_year" / str(year)
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)

    with zipfile.ZipFile(zip_path) as zf:
        members = valid_csv_names(zf.namelist())
        print(f"{year}.zip 内有效 CSV: {len(members)} 个")

        for member in members:
            out_path = temp_dir / Path(member).name
            with zf.open(member) as src, out_path.open("wb") as dst:
                dst.write(src.read())

    con = duckdb.connect(str(DB_PATH))
    con.execute(CREATE_TABLE_SQL)

    # 重复导入前先删掉该年旧数据，避免翻倍
    con.execute(
        """
        DELETE FROM daily_bars
        WHERE trade_date >= ? AND trade_date < ?
        """,
        [f"{year}-01-01", f"{year + 1}-01-01"],
    )

    csv_files = sorted(temp_dir.glob("*.csv"))
    for i, csv_path in enumerate(csv_files, start=1):
        con.execute(INSERT_SQL, [str(csv_path)])
        if i % 200 == 0 or i == len(csv_files):
            print(f"  已导入 {i}/{len(csv_files)}")

    count = con.execute(
        """
        SELECT COUNT(*)
        FROM daily_bars
        WHERE trade_date >= ? AND trade_date < ?
        """,
        [f"{year}-01-01", f"{year + 1}-01-01"],
    ).fetchone()[0]

    print(f"{year} 年导入完成，共 {count} 条")
    con.close()

    shutil.rmtree(temp_dir)


if __name__ == "__main__":

    import_year(2018)