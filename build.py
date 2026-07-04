#!/usr/bin/env python3
"""
Rebuild index.html by embedding the current forecast_scorecard_data.csv into it.

The interactive page carries its data inline (so it renders standalone, including
the copy archived on Zenodo). Edit the CSV, run `python3 build.py`, commit.

Pure standard library, no dependencies.
"""
import re
import sys
import pathlib

HERE = pathlib.Path(__file__).parent
HTML = HERE / "index.html"
CSV = HERE / "forecast_scorecard_data.csv"
PATTERN = re.compile(r"(const CSV = `)(.*?)(`;)", re.DOTALL)


def main() -> int:
    if not HTML.exists() or not CSV.exists():
        print("error: run this from the folder with index.html and forecast_scorecard_data.csv")
        return 1
    csv_text = CSV.read_text(encoding="utf-8").strip()
    if "`" in csv_text:
        print("error: the CSV contains a backtick, which would break the embedded string")
        return 1
    html = HTML.read_text(encoding="utf-8")
    if not PATTERN.search(html):
        print("error: could not find the `const CSV = ` ... `;` block in index.html")
        return 1
    html = PATTERN.sub(lambda m: m.group(1) + csv_text + m.group(3), html)
    HTML.write_text(html, encoding="utf-8")
    print(f"embedded {csv_text.count(chr(10))} data rows from {CSV.name} into index.html")
    print("next: commit index.html (and the CSV) and push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
