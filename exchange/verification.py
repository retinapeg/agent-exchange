"""Buyer's independent checks: never import seller implementations or oracle data."""
import csv
import io
import re
from collections import Counter
from decimal import Decimal, InvalidOperation

from exchange.common import canonical


def same_json(actual, expected):
    # Python equality conflates True with 1 and False with 0. Compare JSON
    # values while preserving A2A Struct's equivalent integral-float encoding.
    return canonical(actual) == canonical(expected)


def verify(request, artifact):
    errors = []
    try:
        service = request["service"]
        source = request.get("source", "")
        if service == "requirements":
            evidence = []
            for line in source.splitlines():
                line = line.strip()
                match = re.fullmatch(r"(Must|Required|Essential|Preferred|Nice to have)\s*:(.*)", line, flags=re.I)
                if match:
                    evidence.append({"requirement": match[2].strip(), "priority": "preferred" if match[1].lower() in ("preferred", "nice to have") else "required", "evidence": line})
            if not same_json(artifact, {"requirements": evidence, "source_lines": len(source.splitlines())}):
                errors.append("requirements_or_evidence_mismatch")
        elif service == "csv-audit":
            matrix = list(csv.reader(io.StringIO(source)))
            names = matrix[0]
            # CSV readers skip empty physical records, but preserve records with
            # empty cells and quoted newlines. Check source validity independently
            # before considering any provider-supplied statistics.
            rows = [row for row in matrix[1:] if row]
            if not names or len(names) != len(set(names)) or len(names) > 40:
                raise ValueError("invalid CSV header")
            if len(rows) > 5000 or any(len(row) != len(names) for row in rows):
                raise ValueError("invalid CSV row width or count")
            ranges = request["ranges"]
            if not isinstance(ranges, dict) or not set(ranges) <= set(names):
                raise ValueError("unknown range column")
            expected = {"rows": len(rows), "columns": names,
                        "missing": {name: sum(row[j].strip() == "" for row in rows) for j, name in enumerate(names)},
                        "duplicate_rows": sum(n-1 for n in Counter(map(tuple, rows)).values()),
                        "invalid_rows": {}, "statistics": {}}
            for name, bounds in ranges.items():
                if not isinstance(bounds, list) or len(bounds) != 2:
                    raise ValueError("range requires two bounds")
                low, high = (Decimal(str(value)) for value in bounds)
                if not low.is_finite() or not high.is_finite() or low > high:
                    raise ValueError("invalid range")
                j, numbers, bad = names.index(name), [], []
                for i, row in enumerate(rows, 2):
                    if not row[j].strip():
                        continue
                    try:
                        number = Decimal(row[j])
                        if not number.is_finite():
                            raise InvalidOperation
                        numbers.append(number)
                        if not low <= number <= high:
                            bad.append(i)
                    except InvalidOperation:
                        bad.append(i)
                expected["invalid_rows"][name] = bad
                expected["statistics"][name] = {"count": len(numbers), "min": str(min(numbers)) if numbers else None,
                    "max": str(max(numbers)) if numbers else None, "mean": str(sum(numbers)/len(numbers)) if numbers else None}
            if not same_json(artifact, expected):
                errors.append("csv_audit_mismatch")
        elif service == "verify":
            expected = verify(request["submission"], request["artifact"])
            if not same_json(artifact, expected):
                errors.append("verifier_result_mismatch")
        elif service == "match":
            # Independently enumerate all eligible pairs; never trust provider consent claims.
            profiles = request["profiles"]
            expected = []
            for i, left in enumerate(profiles):
                for right in profiles[i+1:]:
                    intersections = {field: sorted(set(left.get(field, [])) & set(right.get(field, []))) for field in ("interests", "goals", "availability", "communication")}
                    # Availability is required only when both profiles state it (matchmaking.propose).
                    if not (left.get("availability") and right.get("availability")):
                        intersections.pop("availability")
                    if all(intersections.values()):
                        expected.append({"participants": sorted([left["id"], right["id"]]), "shared_interests": intersections["interests"], "shared_goals": intersections["goals"],
                                         "availability": intersections.get("availability", []), "communication": intersections["communication"], "status": "proposal-only", "contact_disclosed": False})
            exact = {"purpose": "developer-introduction", "proposals": sorted(expected, key=lambda p: p["participants"]),
                     "identity": "synthetic pseudonymous; not anonymous", "consent": "separate explicit consent from both profile owners required"}
            if not same_json(artifact, exact):
                errors.append("match_disclosure_or_constraint_mismatch")
        else:
            errors.append("no_acceptance_rule")
    except (KeyError, TypeError, ValueError, IndexError, InvalidOperation):
        errors.append("verification_input_invalid")
    return {"policy": "deterministic-evidence-v1", "accepted": not errors, "errors": errors}
