from __future__ import annotations

from app.domain.calendar.solar_terms import SolarTermRepository


def main() -> None:
    """验证正式支持范围1901—2100年恰好包含4800条节气。"""
    repository = SolarTermRepository()
    guaranteed = sum(len(repository.for_year(year)) for year in range(1901, 2101))
    if guaranteed != 4800:
        raise SystemExit(f"expected 4800 guaranteed records, got {guaranteed}")
    print(f"valid: {len(repository.terms)} total records; {guaranteed} guaranteed records")


if __name__ == "__main__":
    main()
