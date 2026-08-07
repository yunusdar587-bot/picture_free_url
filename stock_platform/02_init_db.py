"""第二步：建表，并从 2000.zip 导入 000001.SZ 做验证。"""

import zipfile
from pathlib import Path

import duckdb

from config import DAILY_ZIP_DIR, DB_PATH, TEST_CODE, TEST_YEAR

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


def valid_csv_names(members: list[str]) -> list[str]:
    return [
        name
        for name in members
        if name.lower().endswith(".csv")
        and not name.startswith("__MACOSX")
        and not Path(name).name.startswith("._")
    ]


def extract_one_csv(zip_path: Path, member_name: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / Path(member_name).name

    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(member_name) as src, out_path.open("wb") as dst:
            dst.write(src.read())

    return out_path


def main() -> None:
    zip_path = DAILY_ZIP_DIR / f"{TEST_YEAR}.zip"
    if not zip_path.exists():
        raise FileNotFoundError(f"找不到压缩包: {zip_path}")

    temp_dir = Path(__file__).resolve().parent / "_temp_csv"
    csv_path = extract_one_csv(zip_path, TEST_CODE, temp_dir)

    con = duckdb.connect(str(DB_PATH))
    con.execute(CREATE_TABLE_SQL)

    # 先删掉测试股票旧数据，避免重复运行报错
    code = Path(TEST_CODE).name.replace(".csv", "")
    con.execute("DELETE FROM daily_bars WHERE code = ?", [code])

    con.execute(
        f"""
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
        """,
        [str(csv_path)],
    )

    sample = con.execute(
        """
        SELECT code, trade_date, open, close, volume, pct_chg
        FROM daily_bars
        WHERE code = ?
        ORDER BY trade_date
        LIMIT 5
        """,
        [code],
    ).fetchdf()

    total = con.execute(
        "SELECT COUNT(*) FROM daily_bars WHERE code = ?", [code]
    ).fetchone()[0]

    print(f"数据库: {DB_PATH}")
    print(f"已导入: {code}，共 {total} 条")
    print("\n前 5 条:")
    print(sample.to_string(index=False))

    con.close()


if __name__ == "__main__":
    main()
