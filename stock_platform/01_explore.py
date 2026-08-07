"""第一步：探查原始数据长什么样。此时还没有数据库，只看 zip 和 CSV。

看库里已有什么数据请用 inspect_db.py。
"""

import csv
import io
import zipfile
from pathlib import Path

from config import DAILY_ZIP_DIR, TEST_YEAR
from schema import valid_csv_names

SEP = "=" * 40


def explore() -> None:
    if not DAILY_ZIP_DIR.exists():
        raise FileNotFoundError(
            f"找不到数据目录: {DAILY_ZIP_DIR}\n"
            f"用环境变量 STOCK_DAILY_ZIP_DIR 指向存放 2000.zip 这类文件的目录。"
        )

    zips = sorted(p for p in DAILY_ZIP_DIR.glob("*.zip") if p.stem.isdigit())
    print(SEP)
    print(f"数据目录: {DAILY_ZIP_DIR}")
    print(SEP)
    if not zips:
        print("目录下没有形如 2000.zip 的年份压缩包")
        return
    print(f"共 {len(zips)} 个年份压缩包: {zips[0].stem} ~ {zips[-1].stem}")
    total_mb = sum(p.stat().st_size for p in zips) / 1024 / 1024
    print(f"合计 {total_mb:.1f} MB")

    sample_zip = DAILY_ZIP_DIR / f"{TEST_YEAR}.zip"
    if not sample_zip.exists():
        sample_zip = zips[0]

    with zipfile.ZipFile(sample_zip) as zf:
        members = valid_csv_names(zf.namelist())
        print("\n" + SEP)
        print(f"{sample_zip.name} 内容")
        print(SEP)
        print(f"有效 CSV: {len(members)} 个（总条目 {len(zf.namelist())} 个）")
        print(f"前 5 个: {members[:5]}")

        if not members:
            return

        with zf.open(members[0]) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8-sig")
            reader = csv.reader(text)
            header = next(reader)
            rows = [next(reader, None) for _ in range(3)]

    print("\n" + SEP)
    print(f"{members[0]} 的列（共 {len(header)} 列）")
    print(SEP)
    for i, name in enumerate(header):
        print(f"  {i:>2}  {name}")

    print("\n" + SEP)
    print("前 3 行")
    print(SEP)
    for row in rows:
        if row is None:
            break
        print("  " + ", ".join(f"{k}={v}" for k, v in list(zip(header, row))[:8]) + " ...")


if __name__ == "__main__":
    explore()
