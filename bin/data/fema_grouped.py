"""
Build the FEMA claims tables that every other step starts from:

    fema.csv  ->  ai2.fema.trimmed.csv  ->  ai2.fema.grouped.csv

`fema.csv` is the OpenFEMA "FIMA NFIP Redacted Claims" (v1) snapshot dated
2020-08-23 (see SOURCES.md). The original one-off scripts for these two steps
were not saved. This script re-implements them:

* trimmed: rules reconstructed on 2026-11-17 by comparing the two original
  files. It reproduces the original 1,871,315 kept claims except for 166
  extra claims (positive payments, mostly pre-2000, that the original dropped
  for reasons the reconstruction cannot explain) and 3 missing ones. The
  rebuilt grouped file contains every original zip-day, plus 36 extra; 99.95%
  of the shared zip-days are numerically identical.
* grouped: follows the documented steps (data README, 2026-09-24).

Usage:
    python bin/data/fema_grouped.py [--data-dir DIR] [--trimmed-out FILE] [--grouped-out FILE]
"""

import argparse
import os
from pathlib import Path

import pandas as pd

DATA_DIR = Path(os.environ.get("AI2_DATA_DIR", "/Users/chang/data/ai2"))

GROUP_MEAN = ["crs_treat", "communityRatingSystemDiscount", "primaryResidence"]
GROUP_SUM = ["policyCount", "amountPaidOnBuildingClaim", "amountPaidOnContentsClaim",
             "totalBuildingInsuranceCoverage", "totalContentsInsuranceCoverage",
             "amountPaidOnTotalClaim", "totalTotalInsuranceCoverage"]


def trim(raw):
    """fema.csv -> trimmed claims.

    * keep claims with a reportedZipcode and a non-zero building + contents
      payment (missing payments counted as 0; negative refund adjustments
      are kept, as in the original);
    * communityRatingSystemDiscount: missing -> 11 (11 is NOT a FEMA class;
      it marks an unknown class, and such claims end up with crs_treat = 0);
    * crs_treat = class <= 9;
    * amountPaidOnTotalClaim = building + contents payments (no ICC);
    * totalTotalInsuranceCoverage = building + contents coverage.
    """
    paid = raw["amountPaidOnBuildingClaim"].fillna(0) + raw["amountPaidOnContentsClaim"].fillna(0)
    t = raw[raw["reportedZipcode"].notna() & (paid != 0)].copy()
    t["communityRatingSystemDiscount"] = t["communityRatingSystemDiscount"].fillna(11)
    t["amountPaidOnTotalClaim"] = (t["amountPaidOnBuildingClaim"].fillna(0)
                                   + t["amountPaidOnContentsClaim"].fillna(0))
    t["totalTotalInsuranceCoverage"] = (t["totalBuildingInsuranceCoverage"].fillna(0)
                                        + t["totalContentsInsuranceCoverage"].fillna(0))
    t["crs_treat"] = t["communityRatingSystemDiscount"] <= 9
    print(f"trimmed: kept {len(t)} of {len(raw)} claims "
          f"(no zip {raw['reportedZipcode'].isna().sum()}, "
          f"zero payment {(raw['reportedZipcode'].notna() & (paid == 0)).sum()})")
    return t


def group(t):
    """Trimmed claims -> one row per (zip code, date of loss).

    Documented steps that affect the output:
      1. drop zip "0", zero-pad zips to 5 digits;
      2. crs_treat = communityRatingSystemDiscount <= 9;
      5. dateOfLoss -> calendar date (times are local midnight stored as UTC);
      6. group: mean of crs_treat, CRS class, primaryResidence; sum of counts,
         payments and coverage.
    The original steps 3-4 (state/city clean-up, lat/lon fill) do not survive
    into the grouped output and are omitted.
    """
    g = t.copy()
    zip_str = pd.to_numeric(g["reportedZipcode"], errors="coerce").astype("Int64").astype("string")
    g = g[zip_str.notna() & (zip_str != "0")]
    g["reportedZipcode"] = zip_str[g.index].str.zfill(5)
    g["crs_treat"] = (g["communityRatingSystemDiscount"] <= 9).astype(float)
    g["dateOfLoss"] = pd.to_datetime(g["dateOfLoss"], utc=True).dt.strftime("%Y-%m-%d")
    out = (g.groupby(["reportedZipcode", "dateOfLoss"])
             .agg({**{c: "mean" for c in GROUP_MEAN}, **{c: "sum" for c in GROUP_SUM}})
             .reset_index())
    print(f"grouped: {len(out)} zip-days, {out['reportedZipcode'].nunique()} zips")
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--trimmed-out", type=Path, default=None,
                        help="default: <data-dir>/ai2.fema.trimmed.csv")
    parser.add_argument("--grouped-out", type=Path, default=None,
                        help="default: <data-dir>/ai2.fema.grouped.csv")
    args = parser.parse_args()

    raw = pd.read_csv(args.data_dir / "fema.csv", low_memory=False)
    t = trim(raw)
    t.to_csv(args.trimmed_out or args.data_dir / "ai2.fema.trimmed.csv", index=False)
    group(t).to_csv(args.grouped_out or args.data_dir / "ai2.fema.grouped.csv", index=False)


if __name__ == "__main__":
    main()
