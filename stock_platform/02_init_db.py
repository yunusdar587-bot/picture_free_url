"""第二步：建表，并从 <TEST_YEAR>.zip 导入一只股票做验证。"""

import tempfile
import zipfile
from pathlib import Path

import duckdb

from config import DAILY_ZIP_DIR, DB_PATH, TEST_CODE, TEST_YEAR
from schema import CREATE_TABLE_SQL, INSERT_SQL, valid_csv_names


def extract_one_csv(zip_path: Path, member_name: str, out_dir: Path) -> Path:
    out_path = out_dir / Path(member_name).name

    with zipfile.ZipFile(zip_path) as zf:
        if member_name not in zf.namelist():
            available = valid_csv_names(zf.namelist())[:5]
            raise KeyError(
                f"{zip_path.name} 里没有 {member_name}；"
                f"该包内的 CSV 形如: {available}"
            )
        with zf.open(member_name) as src, out_path.open("wb") as dst:
            dst.write(src.read())

    return out_path


def main() -> None:
    zip_path = DAILY_ZIP_DIR / f"{TEST_YEAR}.zip"
    if not zip_path.exists():
        raise FileNotFoundError(f"找不到压缩包: {zip_path}")

    code = Path(TEST_CODE).name.removesuffix(".csv")

    # 用临时目录，避免在项目里留下 _temp_csv 残骸
    with tempfile.TemporaryDirectory(prefix="stock_csv_") as tmp:
        csv_path = extract_one_csv(zip_path, TEST_CODE, Path(tmp))

        con = duckdb.connect(str(DB_PATH))
        try:
            con.execute(CREATE_TABLE_SQL)
            con.execute("BEGIN TRANSACTION")
            # 先删掉这只股票的旧数据，避免重复运行后数据翻倍
            con.execute("DELETE FROM daily_bars WHERE code = ?", [code])
            con.execute(INSERT_SQL, [str(csv_path)])
            con.execute("COMMIT")

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
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    print(f"数据库: {DB_PATH}")
    print(f"已导入: {code}，共 {total} 条")
    print("\n前 5 条:")
    print(sample.to_string(index=False))


if __name__ == "__main__":
    main()
