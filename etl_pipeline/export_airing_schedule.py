"""
Campaign airing per station, for the Airing Timeline tab on the app's
Baseline vs. Follow-up page.

Reads meta/Niger-2 years Radioairing planning.xlsx, sheet "Gantt Airing Per
Station": one row per station (from row 6) with its region and start / end of
broadcast ("Date début / fin diffusion", columns E / F; dates or text such as
"15 Mai 2026"). The daily grid from column G (2026-03-12 onwards; dates read
from the day numbers in row 5) is used only as a check: every day between start and end should be
filled (blue = on air; orange = survey date; yellow / green = funding and file
deliveries), so any empty day inside a station's run is printed as a possible
break in airing. Survey weeks can also be left blank (e.g. 21-28 Oct 2026, round 2
fieldwork): that marks the survey, not a break, so the station's run is kept whole.

Usage (from etl_pipeline/):
    python export_airing_schedule.py

Output: etl_pipeline/outputs/airing_schedule.csv
    station, region, start_date, end_date   (planned end; the app shows up to today)
Upload it to Drive and set AIRING_SCHEDULE_ID in niger_app/src/data_loader.py.
"""

import datetime as dt
import re
import sys

import openpyxl
import pandas as pd

import rounds

PLANNING_XLSX = rounds.PULSE_DIR / "meta" / "Niger-2 years Radioairing planning.xlsx"
SHEET = "Gantt Airing Per Station"
FIRST_ROW, COL_STATION, COL_REGION, COL_START, COL_END = 6, 1, 2, 5, 6
FIRST_DAY_COL, FIRST_DAY = 7, dt.date(2026, 3, 12)
OUT_CSV = rounds.ETL_DIR / "outputs" / "airing_schedule.csv"
FR_MONTHS = {"janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
             "juillet": 7, "aout": 8, "août": 8, "septembre": 9, "octobre": 10, "novembre": 11,
             "decembre": 12, "décembre": 12}


def _date(value) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    m = re.match(r"\s*(\d{1,2})\s+([^\s\d]+)\s+(\d{4})", str(value or ""))
    if m and m.group(2).lower() in FR_MONTHS:
        return dt.date(int(m.group(3)), FR_MONTHS[m.group(2).lower()], int(m.group(1)))
    return None


MONTH_PREFIXES = {"jan": 1, "fev": 2, "feb": 2, "mar": 3, "avr": 4, "apr": 4, "mai": 5, "may": 5,
                  "juin": 6, "jun": 6, "juil": 7, "jul": 7, "aou": 8, "aug": 8, "sep": 9, "oct": 10,
                  "nov": 11, "dec": 12}


def _month(header) -> tuple[int, int] | None:
    """(year, month) of a row-1 month header: a date, or text such as 'Mai 2027' / 'Décember 2026'."""
    if isinstance(header, (dt.datetime, dt.date)):
        return header.year, header.month
    text = str(header or "").lower().replace("é", "e").replace("è", "e").replace("û", "u")
    year = re.search(r"\d{4}", text)
    month = next((m for p, m in sorted(MONTH_PREFIXES.items(), key=lambda kv: -len(kv[0]))
                  if text.startswith(p)), None)
    return (int(year.group()), month) if year and month else None


def _blank(cell) -> bool:
    """No fill, or a white one."""
    return not cell.fill.fill_type or cell.fill.fgColor.rgb in ("FFFFFFFF", "00000000")


def main() -> None:
    ws = openpyxl.load_workbook(PLANNING_XLSX, data_only=True)[SHEET]
    # Calendar of the daily grid: the month of each column from the merged
    # month headers in row 1, the day from row 5.
    col_date, months = {}, []
    for rng in sorted(ws.merged_cells.ranges, key=lambda r: r.min_col):
        if rng.min_row != 1 or rng.min_col < FIRST_DAY_COL:
            continue
        ym = _month(ws.cell(1, rng.min_col).value)
        if ym is None:
            print(f"  ! unreadable month header {ws.cell(1, rng.min_col).value!r} -- its days are ignored")
            continue
        months.append(ym)
        for col in range(rng.min_col, rng.max_col + 1):
            day = ws.cell(FIRST_ROW - 1, col).value
            if day is not None:
                col_date[col] = dt.date(ym[0], ym[1], int(day))
    for (y0, m0), (y1, m1) in zip(months, months[1:]):
        if (y1 * 12 + m1) - (y0 * 12 + m0) != 1:
            print(f"  ! the grid goes from {y0}-{m0:02d} to {y1}-{m1:02d}: month(s) missing in the sheet")
    if col_date[FIRST_DAY_COL] != FIRST_DAY:
        sys.exit(f"Grid starts {col_date[FIRST_DAY_COL]}, expected {FIRST_DAY} -- the sheet layout changed.")
    date_col = {d: c for c, d in col_date.items()}
    grid_end = max(col_date.values())

    rows = []
    for r in range(FIRST_ROW, ws.max_row + 1):
        station = ws.cell(r, COL_STATION).value
        if not station:
            continue
        start, end = _date(ws.cell(r, COL_START).value), _date(ws.cell(r, COL_END).value)
        if start is None or end is None:
            print(f"  ! {station}: unreadable start/end date -- skipped")
            continue
        rows.append({"station": str(station).strip(), "region": ws.cell(r, COL_REGION).value,
                     "start_date": start.isoformat(), "end_date": end.isoformat()})
        # Check: empty days inside the run (up to the grid's last day).
        empty = [d for d in sorted(date_col) if start <= d <= min(end, grid_end)
                 and _blank(ws.cell(r, date_col[d]))]
        if empty:
            print(f"  ! {station}: {len(empty)} empty day(s) between start and end, "
                  f"first {empty[0]}, last {empty[-1]} -- possible break in airing")

    out = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"{len(out)} stations, first on air {out['start_date'].min()}, last start {out['start_date'].max()}")
    print(f"Written: {OUT_CSV}")


if __name__ == "__main__":
    main()
