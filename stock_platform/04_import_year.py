"""第四步：导入某一年（或若干年）的全部日 K 数据。

用法:
    python 04_import_year.py 2018
    python 04_import_year.py 2000 2001 2002
    python 04_import_year.py --range 2000 2024
    python 04_import_year.py --all
"""

import argparse
import tempfile
import zipfile
from pathlib import Path

import duckdb

from config import DAILY_ZIP_DIR, DB_PATH, TEST_YEAR
from schema import CREATE_TABLE_SQL, INSERT_SQL, valid_csv_names


def available_years() -> list[int]:
    years = []
    for path in DAILY_ZIP_DIR.glob("*.zip"):
        if path.stem.isdigit():
            years.append(int(path.stem))
    return sorted(years)


def import_year(year: int) -> int:
    """把某一年的数据导入库中，返回该年的行数。"""
    zip_path = DAILY_ZIP_DIR / f"{year}.zip"
    if not zip_path.exists():
        raise FileNotFoundError(f"找不到压缩包: {zip_path}")

    con = duckdb.connect(str(DB_PATH))
    try:
        con.execute(CREATE_TABLE_SQL)

        # 整年放在一个事务里：中途失败会整体回滚，
        # 不会出现“旧数据已删、新数据只导了一半”的情况。
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(
                "DELETE FROM daily_bars WHERE trade_date >= ? AND trade_date < ?",
                [f"{year}-01-01", f"{year + 1}-01-01"],
            )

            with zipfile.ZipFile(zip_path) as zf:
                members = valid_csv_names(zf.namelist())
                print(f"{year}.zip 内有效 CSV: {len(members)} 个")

                # 一次只解压一个文件，避免整年 CSV 同时占满磁盘
                with tempfile.TemporaryDirectory(prefix=f"stock_{year}_") as tmp:
                    tmp_dir = Path(tmp)
                    for i, member in enumerate(members, start=1):
                        csv_path = tmp_dir / Path(member).name
                        with zf.open(member) as src, csv_path.open("wb") as dst:
                            dst.write(src.read())
                        try:
                            con.execute(INSERT_SQL, [str(csv_path)])
                        finally:
                            csv_path.unlink(missing_ok=True)
                        if i % 200 == 0 or i == len(members):
                            print(f"  已导入 {i}/{len(members)}")

            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            print(f"{year} 年导入失败，已回滚，库内数据保持原样")
            raise

        count = con.execute(
            """
            SELECT COUNT(*)
            FROM daily_bars
            WHERE trade_date >= ? AND trade_date < ?
            """,
            [f"{year}-01-01", f"{year + 1}-01-01"],
        ).fetchone()[0]
    finally:
        con.close()

    print(f"{year} 年导入完成，共 {count} 条")
    return count


def parse_args() -> list[int]:
    parser = argparse.ArgumentParser(description="导入日 K 数据")
    parser.add_argument("years", nargs="*", type=int, help="要导入的年份")
    parser.add_argument(
        "--range", nargs=2, type=int, metavar=("START", "END"), help="导入连续年份区间"
    )
    parser.add_argument(
        "--all", action="store_true", help=f"导入 {DAILY_ZIP_DIR} 下所有年份"
    )
    args = parser.parse_args()

    if args.all:
        years = available_years()
        if not years:
            parser.error(f"{DAILY_ZIP_DIR} 下没有找到形如 2000.zip 的文件")
        return years
    if args.range:
        return list(range(args.range[0], args.range[1] + 1))
    if args.years:
        return args.years
    print(f"未指定年份，默认导入 config.TEST_YEAR = {TEST_YEAR}")
    return [TEST_YEAR]


if __name__ == "__main__":
    total = 0
    for y in parse_args():
        total += import_year(y)
    print(f"\n合计 {total} 条")
