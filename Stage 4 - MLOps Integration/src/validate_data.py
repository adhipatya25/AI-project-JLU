"""Stage 1 of the pipeline: check the dataset before any training happens.

Fails (exit code 1) if the data cannot be trained on; otherwise writes
reports/data_validation.json, which DVC tracks as a metrics file.
"""

import json
import sys

from common import CLASSES, FEATURES, NUMERIC_FEATURES, REPORTS, load_data, load_params


def main() -> int:
    params = load_params()
    target = params["data"]["target"]
    df = load_data(params)

    errors, warnings = [], []

    missing_cols = [c for c in FEATURES + [target] if c not in df.columns]
    if missing_cols:
        errors.append(f"missing columns: {missing_cols}")

    if len(df) < 1000:
        errors.append(f"too few rows: {len(df)}")

    if not missing_cols:
        unknown = sorted(set(df[target].dropna().unique()) - set(CLASSES))
        if unknown:
            errors.append(f"unknown target labels: {unknown}")
        if df[target].isna().any():
            errors.append(f"{int(df[target].isna().sum())} rows have no target label")

        negative = {c: int((df[c] < 0).sum()) for c in NUMERIC_FEATURES if (df[c] < 0).any()}
        if negative:
            errors.append(f"negative values in numeric columns: {negative}")

        # Missing feature values are allowed (the pipeline imputes them) but reported
        null_share = {c: round(float(df[c].isna().mean()), 4) for c in FEATURES if df[c].isna().any()}
        heavy = {c: s for c, s in null_share.items() if s > 0.5}
        if heavy:
            warnings.append(f"columns more than 50% empty: {heavy}")

    report = {
        "rows": int(len(df)),
        "columns": int(df.shape[1]),
        "duplicate_rows": int(df.duplicated().sum()),
        "class_counts": {k: int(v) for k, v in df[target].value_counts().items()} if target in df else {},
        "null_share": null_share if not missing_cols else {},
        "errors": errors,
        "warnings": warnings,
        "passed": not errors,
    }
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "data_validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Rows: {report['rows']}  classes: {report['class_counts']}")
    for w in warnings:
        print("WARNING:", w)
    if errors:
        for e in errors:
            print("ERROR:", e)
        return 1
    print("Data validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
