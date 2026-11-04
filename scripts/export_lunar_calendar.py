"""Export month boundaries from the project's pinned lunar-python, without timezone math."""
from datetime import date
from importlib.metadata import version
import json
from pathlib import Path

from lunar_python import LunarYear, Solar

root = Path(__file__).resolve().parents[1]
epoch = date(1970, 1, 1)
years: dict[str, list[int]] = {}
previous_end = None
for year in range(1900, 2101):
    months = LunarYear.fromYear(year).getMonthsInYear()
    row: list[int] = []
    for month in months:
        solar = Solar.fromJulianDay(month.getFirstJulianDay())
        start = (date(solar.getYear(), solar.getMonth(), solar.getDay()) - epoch).days
        assert previous_end is None or start == previous_end
        if not row:
            row.append(start)
        row.extend((month.getMonth(), month.getDayCount()))
        previous_end = start + month.getDayCount()
    years[str(year)] = row
target = root / "frontend/src/data/lunar-months.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps({"source": f"lunar-python {version('lunar-python')}",
                             "years": years}, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
print(f"EXPORTED_LUNAR_MONTHS: {len(years)} years; {target.stat().st_size} bytes")
