"""Deterministic fixture services; model providers are implemented separately."""
import csv
import io
import re
from decimal import Decimal, InvalidOperation


def requirements(source):
    found = []
    for line in source.splitlines():
        text = line.strip()
        if re.match(r"(?i)^(must|required|essential|preferred|nice to have)\s*:", text):
            priority, value = text.split(":", 1)
            found.append({"requirement": value.strip(), "priority": "preferred" if priority.lower() in ["preferred", "nice to have"] else "required", "evidence": text})
    return {"requirements": found, "source_lines": len(source.splitlines())}


def csv_audit(source, ranges):
    reader = csv.DictReader(io.StringIO(source))
    columns = reader.fieldnames
    if not columns or len(columns) != len(set(columns)) or len(columns) > 40:
        raise ValueError("invalid CSV header")
    rows = list(reader)
    if len(rows) > 5000 or any(None in r or None in r.values() for r in rows):
        raise ValueError("invalid CSV row width or count")
    if not set(ranges) <= set(columns):
        raise ValueError("unknown range column")
    missing = {c: sum(not r[c].strip() for r in rows) for c in columns}
    duplicates = len(rows) - len({tuple(r[c] for c in columns) for r in rows})
    stats, invalid = {}, {}
    for c, bounds in ranges.items():
        if len(bounds) != 2:
            raise ValueError("range requires two bounds")
        low, high = map(lambda v: Decimal(str(v)), bounds)
        if not low.is_finite() or not high.is_finite() or low > high:
            raise ValueError("invalid range")
        values, bad = [], []
        for i, row in enumerate(rows, 2):
            value = row[c].strip()
            if not value:
                continue
            try:
                n = Decimal(value)
                if not n.is_finite():
                    raise InvalidOperation
                values.append(n)
                if n < low or n > high:
                    bad.append(i)
            except InvalidOperation:
                bad.append(i)
        invalid[c] = bad
        stats[c] = {"count": len(values), "min": str(min(values)) if values else None,
                    "max": str(max(values)) if values else None,
                    "mean": str(sum(values) / len(values)) if values else None}
    return {"rows": len(rows), "columns": columns, "missing": missing, "duplicate_rows": duplicates,
            "invalid_rows": invalid, "statistics": stats}


def execute(payload):
    service = payload["service"]
    if service == "requirements":
        return requirements(payload["source"])
    if service == "csv-audit":
        return csv_audit(payload["source"], payload["ranges"])
    if service == "verify":
        from exchange.verification import verify
        return verify(payload["submission"], payload["artifact"])
    if service == "match":
        from exchange.matchmaking import propose
        return propose(payload["profiles"])
    raise ValueError("unsupported service")
