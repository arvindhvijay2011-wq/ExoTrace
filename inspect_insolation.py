
"""Investigate zero insolation values in the NASA PSCompPars snapshot."""

from pathlib import Path

import pandas as pd

CSV_PATH = Path("data/processed/planets_validated.csv")
OUTPUT_PATH = Path("data/manifests/insolation_zero_diagnostic.csv")
SOLAR_EFFECTIVE_TEMPERATURE_K = 5772.0


def main() -> None:
    """Inspect calculated zero-insolation records without modifying source data."""
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"Dataset not found: {CSV_PATH}")

    df = pd.read_csv(CSV_PATH)

    required_columns = [
        "pl_name",
        "hostname",
        "discoverymethod",
        "pl_insol",
        "pl_insol_reflink",
        "pl_insollim",
        "pl_orbsmax",
        "st_teff",
        "st_rad",
        "pl_eqt",
    ]
    missing_columns = [c for c in required_columns if c not in df.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")

    numeric_columns = [
        "pl_insol",
        "pl_orbsmax",
        "st_teff",
        "st_rad",
        "pl_eqt",
    ]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    reference = df["pl_insol_reflink"].fillna("")
    mask = df["pl_insol"].eq(0) & reference.str.contains(
        "CALCULATED_VALUE", case=False, regex=False
    )
    suspicious = df.loc[mask].copy()

    # Approximate diagnostic only:
    # L_star / L_sun ~= (R_star / R_sun)^2 * (T_star / T_sun)^4
    # Insolation / Earth flux ~= (L_star / L_sun) / (a / AU)^2
    valid_inputs = (
        suspicious["st_rad"].gt(0)
        & suspicious["st_teff"].gt(0)
        & suspicious["pl_orbsmax"].gt(0)
    )

    suspicious["diagnostic_insol_estimate"] = float("nan")
    suspicious.loc[valid_inputs, "diagnostic_insol_estimate"] = (
        suspicious.loc[valid_inputs, "st_rad"] ** 2
        * (
            suspicious.loc[valid_inputs, "st_teff"]
            / SOLAR_EFFECTIVE_TEMPERATURE_K
        )
        ** 4
        / suspicious.loc[valid_inputs, "pl_orbsmax"] ** 2
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    suspicious.to_csv(OUTPUT_PATH, index=False)

    print(f"Calculated zero-insolation records: {len(suspicious)}")
    print(f"Records with usable diagnostic inputs: {int(valid_inputs.sum())}")
    print(
        "Records missing one or more positive inputs: "
        f"{int((~valid_inputs).sum())}"
    )

    estimates = suspicious["diagnostic_insol_estimate"].dropna()
    if not estimates.empty:
        print(f"Positive diagnostic estimates: {int(estimates.gt(0).sum())}")
        print(f"Smallest estimate: {estimates.min():.8g}")
        print(f"Median estimate: {estimates.median():.8g}")
        print(f"Largest estimate: {estimates.max():.8g}")

    display_columns = [
        "pl_name",
        "hostname",
        "discoverymethod",
        "pl_orbsmax",
        "st_teff",
        "st_rad",
        "pl_eqt",
        "pl_insol",
        "pl_insollim",
        "diagnostic_insol_estimate",
    ]
    print("\nFirst 15 records:")
    print(suspicious[display_columns].head(15).to_string(index=False))
    print(f"\nFull diagnostic saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
