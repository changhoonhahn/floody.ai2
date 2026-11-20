"""
Build the AI2 FEMA flood-claims dataset.

Starts from ai2.fema.grouped.csv (FEMA NFIP claims grouped by zip code and
date of loss) and adds, in order:

  1. nitrogen   nearest USGS/EPA nitrogen reading before/after the loss (mg/L)
  2. fsf        First Street Foundation zip-level flood risk     (fsf_ prefix)
  3. acs        ACS 5-year census data for the loss-year period  (acs_ prefix)
  4. prism      PRISM monthly precipitation for the loss month   (prism_ prefix)

The PRISM zip-level table is built from the raw PRISM grids by the
`download` and `prism` commands. See bin/data/README.md for every step and choice.

Commands:
    download   download PRISM monthly precipitation grids
    prism      average the PRISM grids over 2020 ZCTA polygons
               (needs geopandas, rasterio, exactextract, scipy: conda env ai2-geo)
    download-wqp  download Water Quality Portal results + sites, 1990-2024
    wqp        Water Quality Portal -> zip code x day x parameter table (ai2-geo)
    sdwis      SDWIS health-based violations -> zip code x month table (ai2-geo)
    blackmarble  NASA Black Marble daily nighttime lights around flood dates
               -> zip code x day table (ai2-geo + h5py; needs Earthdata login in ~/.netrc)
    build      add nitrogen, FSF, ACS and PRISM data and write the final dataset
    build-sdwis  same, with SDWIS violation windows in place of nitrogen
    build-pbj    same, with CMS PBJ nursing-home census/staffing weeks in place of nitrogen
    plot       nitrogen distribution and change figures
    all        download, prism, build, plot

Usage:
    python bin/data/ai2_dataset.py build [--data-dir DIR] [--out FILE] [--save-intermediate]
    <ai2-geo python> bin/data/ai2_dataset.py prism [--start 1973] [--end 2020]
"""

import argparse
import os
import re
import time
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

# Locations can be overridden with environment variables (see bin/data/README.md).
DATA_DIR = Path(os.environ.get("AI2_DATA_DIR", "/Users/chang/data/ai2"))
FIGURES = Path(os.environ.get("AI2_FIGURES_DIR",
                              Path(__file__).resolve().parents[2] / "figures"))

FEMA_CSV = "ai2.fema.grouped.csv"
NITROGEN_CSV = "Nitrogen_2007-2021_national_with_ZIP.csv"
FSF_CSV = "fsf/01_DATA/Climate_Risk_Statistics/v1.2/Zip_level_risk_FEMA_FSF_v1.2.csv"
ACS_DIR = "acs_census"
PRISM_DIR = "prism_ppt"
PRISM_ZIP_CSV = "rainfall_PRISM_zcta2020.zipcode_year_month.csv"
ZCTA_SHP = Path(os.environ.get("AI2_ZCTA_SHP",
                              "/Users/chang/data/noah/floody/tl_2022_us_zcta520/tl_2022_us_zcta520.shp"))
FINAL_CSV = "ai2.fema.grouped.nitro.fsf.acs.prism.csv"
SDWIS_FINAL_CSV = "ai2.fema.grouped.sdwis.fsf.acs.prism.csv"
PBJ_FINAL_CSV = "ai2.fema.grouped.pbj.fsf.acs.prism.csv"
PBJ_WEEKLY = "pbj/pbj_zip_weekly.csv.gz"   # CMS PBJ nursing-home panel; see pbj/README.md

PRISM_URL = "https://data.prism.oregonstate.edu/time_series/us/an/4km/ppt/monthly"
PRISM_YEARS = (1973, 2020)


# ---------------------------------------------------------------------------
# 1. Nitrogen
# ---------------------------------------------------------------------------

NON_DETECT_TOKENS = {
    "non-detect", "*non-detect", "not detected", "*not detected",
    "below detection limits", "nd", "bdl", "no data", "not reported", "-",
}
NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+")

N_MOLAR_MASS = 14.0067  # g/mol, nitrogen

# Factor converting each aqueous-concentration unit to mg/L. Any other unit
# (sediment/tissue, gas fractions, particle sizes, amounts, missing) is dropped.
TO_MG_PER_L = {
    "mg/L": 1.0,
    "mg/l": 1.0,
    "mg N/l******": 1.0,
    "ppm": 1.0,  # 1 ppm in water ~= 1 mg/L
    "ug/L": 1e-3,
    "ppb": 1e-3,  # 1 ppb in water ~= 1 ug/L
    "umol/L": N_MOLAR_MASS * 1e-3,  # umol N/L -> mg N/L
}

NITROGEN_WINDOWS = [
    (30, "Nitrogen 1 Month Before", "Nitrogen 1 Month After"),
    (60, "Nitrogen 2 Months Before", "Nitrogen 2 Months After"),
]


def clean_result_value(value):
    """Coerce ResultMeasureValue to float, handling detection-limit/annotation strings
    like '<0.245', '< 0.05', '300(A)', '[0.026]', '0,8' (comma decimal), 'ND', etc.
    Returns NaN for values with no extractable number (e.g. 'non-detect')."""
    if pd.isna(value):
        return float("nan")
    s = str(value).strip()
    if s.lower() in NON_DETECT_TOKENS:
        return float("nan")
    s = s.strip("[]")
    s = re.sub(r"\(.*?\)", "", s)  # drop qualifier annotations like "(A)"
    s = re.sub(r"^[<>]\s*", "", s)  # drop detection-limit inequality signs
    s = s.strip()
    if "," in s and "." not in s:
        s = s.replace(",", ".")  # comma used as decimal separator
    else:
        s = s.replace(",", "")  # comma used as thousands separator
    try:
        return float(s)
    except ValueError:
        m = NUMBER_RE.search(s)
        return float(m.group()) if m else float("nan")


def load_nitrogen(path):
    """Nitrogen readings in mg/L, averaged to one value per (zip5, day)."""
    nit = pd.read_csv(path, dtype={"ZipCode": "string"}, low_memory=False,
                      parse_dates=["ActivityStartDate"])
    nit["zip5"] = nit["ZipCode"].str.replace(r"\.0$", "", regex=True).str.zfill(5)
    value = nit["ResultMeasureValue"].map(clean_result_value)
    nit["mg_per_L"] = value * nit["ResultMeasure/MeasureUnitCode"].map(TO_MG_PER_L)

    keep = nit["zip5"].notna() & nit["mg_per_L"].notna()
    negative = keep & (nit["mg_per_L"] < 0)  # physically impossible
    nit = nit[keep & ~negative]
    print(f"  nitrogen: {keep.sum()} readings in concentration units, "
          f"{negative.sum()} negative dropped")

    daily = (
        nit.groupby(["zip5", "ActivityStartDate"], as_index=False)["mg_per_L"]
        .mean()
        .sort_values("ActivityStartDate")
        .reset_index(drop=True)
    )
    print(f"  nitrogen: averaged into {len(daily)} (zip, day) values")
    return daily


def add_nitrogen(fema, data_dir):
    daily = load_nitrogen(data_dir / NITROGEN_CSV)
    order = fema["dateOfLoss"].argsort(kind="stable")
    keys = fema[["reportedZipcode", "dateOfLoss"]].iloc[order]
    for days, before_col, after_col in NITROGEN_WINDOWS:
        for direction, col in (("backward", before_col), ("forward", after_col)):
            matched = pd.merge_asof(
                keys, daily,
                left_on="dateOfLoss", right_on="ActivityStartDate",
                left_by="reportedZipcode", right_by="zip5",
                direction=direction,
                tolerance=pd.Timedelta(days=days),
                # Readings dated on dateOfLoss are skipped: their time of day
                # is unknown, so they cannot be placed before or after the loss.
                allow_exact_matches=False,
            )
            values = np.empty(len(fema))
            values[order] = matched["mg_per_L"].to_numpy()
            fema[col] = values
        both = (fema[before_col].notna() & fema[after_col].notna()).sum()
        print(f"  nitrogen {days}-day window: before={fema[before_col].notna().sum()} "
              f"after={fema[after_col].notna().sum()} both={both}")
    return fema


# ---------------------------------------------------------------------------
# 2. First Street Foundation flood risk
# ---------------------------------------------------------------------------

def add_fsf(fema, data_dir):
    fsf = pd.read_csv(data_dir / FSF_CSV, dtype={"zipcode": "string"})
    fsf["zipcode"] = fsf["zipcode"].str.zfill(5)  # stored as int: 1001 -> 01001
    fsf = fsf.add_prefix("fsf_")
    fema = fema.merge(fsf, how="left", left_on="reportedZipcode",
                      right_on="fsf_zipcode", validate="many_to_one")
    fema = fema.drop(columns="fsf_zipcode")
    report_match(fema, "fsf", "fsf_count_property")
    return fema


# ---------------------------------------------------------------------------
# 3. ACS census
# ---------------------------------------------------------------------------

# ACS period -> source file. ACS2016_20socialexplorer.csv is not used: it is a
# byte-identical copy of ACS2012_16socexplnew.csv.
ACS_FILES = {
    "2008-2012": "ACS2008_12socialexplorer.csv",
    "2012-2016": "ACS2012_16socexplnew.csv",
    "2016-2020": "ACS2016_20new.csv",
}


def acs_period(year):
    """ACS period for a loss year. Periods share end years (2012, 2016); a
    shared year goes to the earlier period, the one it ends."""
    if year <= 2012:
        return "2008-2012"  # includes every loss before 2008
    if year <= 2016:
        return "2012-2016"
    return "2016-2020"


def load_acs(path):
    """Social Explorer export: row 1 holds descriptions, row 2 codes."""
    header = pd.read_csv(path, nrows=2, header=None, low_memory=False)
    descriptions = dict(zip(header.iloc[1], header.iloc[0].str.strip()))
    acs = pd.read_csv(path, skiprows=[0], dtype={"Geo_ZCTA5": "string"}, low_memory=False)
    value_cols = [c for c in acs.columns if c.startswith("SE_")]
    acs = acs[["Geo_ZCTA5"] + value_cols]
    assert not acs["Geo_ZCTA5"].duplicated().any(), f"duplicate ZCTAs in {path}"
    return acs, {c: descriptions[c] for c in value_cols}


def add_acs(fema, data_dir):
    fema["acs_period"] = fema["dateOfLoss"].dt.year.map(acs_period)
    frames, dictionary = [], {}
    for period, name in ACS_FILES.items():
        acs, descriptions = load_acs(data_dir / ACS_DIR / name)
        acs["acs_period"] = period
        frames.append(acs)
        for code, desc in descriptions.items():
            dictionary.setdefault(code, {})[period] = desc
    acs = pd.concat(frames, ignore_index=True)
    acs = acs.rename(columns={c: "acs_" + c for c in acs.columns if c.startswith("SE_")})
    fema = fema.merge(acs, how="left",
                      left_on=["reportedZipcode", "acs_period"],
                      right_on=["Geo_ZCTA5", "acs_period"],
                      validate="many_to_one").drop(columns="Geo_ZCTA5")
    report_match(fema, "acs", "acs_SE_A00001_001")

    rows = [{"column": "acs_period", "code": "",
             "description": "ACS 5-year period matched to the loss year"}]
    for code, by_period in dictionary.items():
        row = {"column": "acs_" + code, "code": code, "description": by_period["2008-2012"]}
        if len(set(by_period.values())) > 1:  # only income columns: dollar year
            row.update({f"description_{p}": d for p, d in by_period.items()})
        rows.append(row)
    return fema, pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 4. PRISM precipitation
# ---------------------------------------------------------------------------

def prism_zip_path(prism_dir, year, month):
    return prism_dir / f"prism_ppt_us_25m_{year}{month:02d}.zip"


def is_valid_zip(path):
    try:
        with zipfile.ZipFile(path) as z:
            return z.testzip() is None
    except (zipfile.BadZipFile, OSError):
        return False


def download_prism(data_dir, start, end):
    """Download PRISM AN 4 km monthly precipitation grids; valid files are skipped."""
    out_dir = data_dir / PRISM_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    for year in range(start, end + 1):
        for month in range(1, 13):
            path = prism_zip_path(out_dir, year, month)
            if path.exists() and is_valid_zip(path):
                continue
            url = f"{PRISM_URL}/{year}/{path.name}"
            for attempt in range(3):
                try:
                    tmp = path.with_suffix(".part")
                    urllib.request.urlretrieve(url, tmp)
                    if not is_valid_zip(tmp):
                        raise ValueError("not a valid zip")
                    tmp.rename(path)
                    print(f"ok   {path.name}", flush=True)
                    break
                except Exception as err:  # retry network hiccups
                    print(f"retry {path.name}: {err}", flush=True)
                    time.sleep(5 * (attempt + 1))
            else:
                print(f"FAIL {path.name}", flush=True)
            time.sleep(0.5)  # be polite to the server


def prism_grid(prism_dir, year, month):
    """GDAL path to the raster inside a monthly PRISM zip."""
    zpath = prism_zip_path(prism_dir, year, month)
    with zipfile.ZipFile(zpath) as z:
        name = next(n for n in z.namelist() if n.endswith((".tif", ".bil")))
    return f"/vsizip/{zpath}/{name}"


def compute_prism_zcta(data_dir, start, end, zcta_shp=ZCTA_SHP):
    """Monthly PRISM precipitation averaged over each 2020 ZCTA polygon.

    Every grid cell overlapping a ZCTA counts, weighted by the fraction of the
    cell the ZCTA covers (exactextract coverage fractions). The weights depend
    only on the grid and polygons, so they are computed once; each month is a
    sparse weighted average of that month's grid over its valid cells."""
    import geopandas as gpd
    import rasterio
    from exactextract import exact_extract
    from scipy import sparse

    prism_dir = data_dir / PRISM_DIR
    zcta = gpd.read_file(zcta_shp, columns=["ZCTA5CE20"])
    first = prism_grid(prism_dir, start, 1)
    with rasterio.open(first) as src:
        ref_transform, ref_shape = src.transform, src.shape
        zcta = zcta.to_crs(src.crs)
        print(f"ZCTAs: {len(zcta)}; grid {src.crs} {src.res} {ref_shape}", flush=True)

    cov = exact_extract(first, zcta, ["cell_id", "coverage"], output="pandas")
    rows = np.concatenate([np.full(len(ids), i) for i, ids in enumerate(cov["cell_id"])])
    W = sparse.csr_matrix(
        (np.concatenate([np.asarray(c, float) for c in cov["coverage"]]),
         (rows, np.concatenate([np.asarray(ids, np.int64) for ids in cov["cell_id"]]))),
        shape=(len(zcta), ref_shape[0] * ref_shape[1]),
    )
    print(f"coverage weights: {W.nnz} (ZCTA, cell) pairs", flush=True)

    frames = []
    for year in range(start, end + 1):
        for month in range(1, 13):
            path = prism_grid(prism_dir, year, month)
            with rasterio.open(path) as src:
                assert src.transform == ref_transform and src.shape == ref_shape, \
                    f"grid of {path} differs from {first}"
                values = src.read(1, masked=True).astype(float).filled(np.nan).ravel()
            valid = ~np.isnan(values)
            wsum = W @ valid.astype(float)
            total = W @ np.where(valid, values, 0.0)
            with np.errstate(invalid="ignore", divide="ignore"):
                mean = np.where(wsum > 0, total / wsum, np.nan)
            frames.append(pd.DataFrame({
                "ZIP_CODE": zcta["ZCTA5CE20"].to_numpy(),
                "year": year, "month": month,
                "MEAN": mean,     # mm, coverage-weighted mean over the ZCTA
                "NCELLS": wsum,   # effective number of valid grid cells covered
            }))
        print(f"{year} done", flush=True)

    out = pd.concat(frames, ignore_index=True)
    path = data_dir / PRISM_ZIP_CSV
    out.to_csv(path, index=False, float_format="%.4f")
    print(f"saved {len(out)} rows to {path}")


def add_prism(fema, data_dir):
    keys = ["ZIP_CODE", "year", "month"]
    rain = pd.read_csv(data_dir / PRISM_ZIP_CSV, dtype={"ZIP_CODE": "string"})
    rain["ZIP_CODE"] = rain["ZIP_CODE"].str.zfill(5)
    assert not rain.duplicated(keys).any(), "duplicate (zip, year, month) in PRISM table"
    rain = rain.rename(columns={c: "prism_" + c for c in rain.columns if c not in keys})
    lookup = pd.DataFrame({"ZIP_CODE": fema["reportedZipcode"],
                           "year": fema["dateOfLoss"].dt.year,
                           "month": fema["dateOfLoss"].dt.month})
    matched = lookup.merge(rain, how="left", on=keys, validate="many_to_one")
    prism_cols = [c for c in matched.columns if c.startswith("prism_")]
    fema = pd.concat([fema, matched[prism_cols].set_index(fema.index)], axis=1)
    report_match(fema, "prism", "prism_MEAN")
    return fema


# ---------------------------------------------------------------------------
# 5. Water Quality Portal, all parameters -> zip code x day
# ---------------------------------------------------------------------------

WQP_URL = "https://www.waterqualitydata.us/data"
WQP_DIR = "wqp"
WQP_YEARS = (1990, 2024)
WQP_CHUNK_YEARS = 5
WQP_ZIP_CSV = "wqp_zcta2020.zipcode_day.csv"
WQP_SITE_TYPES = ["Stream", "Lake, Reservoir, Impoundment", "Estuary", "Ocean"]
# WQP CharacteristicName -> short parameter name.
WQP_CHARACTERISTICS = {
    "Turbidity": "turbidity",
    "Total suspended solids": "tss",
    "Escherichia coli": "ecoli",
    "Fecal Coliform": "fecal_coliform",
    "Enterococcus": "enterococcus",
    "Phosphorus": "phosphorus",
    "Nitrogen": "nitrogen",
    "Inorganic nitrogen (nitrate and nitrite)": "nitrate_nitrite",
    "Nitrate": "nitrate",
}
WQP_UNITS = {  # standard unit per parameter (values are converted to it)
    "turbidity": "NTU", "tss": "mg/L",
    "ecoli": "count/100mL", "fecal_coliform": "count/100mL", "enterococcus": "count/100mL",
    "phosphorus": "mg/L as P",
    "nitrogen": "mg/L as N", "nitrate_nitrite": "mg/L as N", "nitrate": "mg/L as N",
}
STATE_FIPS = [
    "01", "02", "04", "05", "06", "08", "09", "10", "11", "12", "13", "15", "16", "17",
    "18", "19", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29", "30", "31",
    "32", "33", "34", "35", "36", "37", "38", "39", "40", "41", "42", "44", "45", "46",
    "47", "48", "49", "50", "51", "53", "54", "55", "56", "72",
]
ZCTA_SNAP_M = 2000  # sites outside every ZCTA (open water) snap to one within 2 km


def wqp_query(state, start=None, end=None):
    params = [("statecode", f"US:{state}")]
    params += [("characteristicName", c) for c in WQP_CHARACTERISTICS]
    params += [("siteType", t) for t in WQP_SITE_TYPES]
    if start:
        params += [("startDateLo", f"01-01-{start}"), ("startDateHi", f"12-31-{end}")]
    return params


def fetch_zip(url, params, path, attempts=4):
    """Download a zipped WQP response to path (skipped if a valid file exists)."""
    from urllib.parse import urlencode

    import socket

    if path.exists() and is_valid_zip(path):
        return "skip"
    # Without a timeout a dropped connection can hang a request indefinitely.
    socket.setdefaulttimeout(600)
    full = f"{url}?{urlencode(params + [('mimeType', 'csv'), ('zip', 'yes')])}"
    for attempt in range(attempts):
        try:
            tmp = path.with_suffix(".part")
            urllib.request.urlretrieve(full, tmp)
            if not is_valid_zip(tmp):
                raise ValueError("not a valid zip")
            tmp.rename(path)
            return "ok"
        except Exception as err:  # retry server timeouts
            print(f"retry {path.name}: {err}", flush=True)
            time.sleep(30 * (attempt + 1))
    return "FAIL"


def download_wqp(data_dir, workers=3):
    """Per state and 5-year chunk: one station file and one result file.
    (A state's all-years station request is too large; the server resets it.)"""
    from concurrent.futures import ThreadPoolExecutor

    out = data_dir / WQP_DIR
    (out / "stations").mkdir(parents=True, exist_ok=True)
    (out / "results").mkdir(parents=True, exist_ok=True)
    jobs = []
    for st in STATE_FIPS:
        for y0 in range(WQP_YEARS[0], WQP_YEARS[1] + 1, WQP_CHUNK_YEARS):
            y1 = min(y0 + WQP_CHUNK_YEARS - 1, WQP_YEARS[1])
            jobs.append((f"{WQP_URL}/Station/search", wqp_query(st, y0, y1),
                         out / "stations" / f"{st}_{y0}-{y1}.zip"))
            jobs.append((f"{WQP_URL}/Result/search",
                         wqp_query(st, y0, y1) + [("dataProfile", "narrowResult")],
                         out / "results" / f"{st}_{y0}-{y1}.zip"))

    def yearly(path):  # one-year station files that stand in for a 5-year chunk
        st, span = path.stem.split("_")
        y0, y1 = map(int, span.split("-"))
        return st, [(y, path.with_name(f"{st}_{y}-{y}.zip")) for y in range(y0, y1 + 1)]

    def run(job):
        url, params, path = job
        is_station = path.parent.name == "stations"
        st, years = yearly(path) if is_station else (None, [])
        if is_station and not path.exists() and all(p.exists() and is_valid_zip(p) for _, p in years):
            status = "skip"  # already covered by one-year files
        else:
            # Large states' 5-year station requests can be reset by the server:
            # try twice, then fall back to one-year requests.
            status = fetch_zip(url, params, path, attempts=2 if is_station else 4)
            if status == "FAIL" and is_station:
                parts = [fetch_zip(url, wqp_query(st, y, y), p) for y, p in years]
                status = "ok1y" if "FAIL" not in parts else "FAIL"
        print(f"{status:4s} {path.parent.name}/{path.name}", flush=True)
        time.sleep(1)  # be polite to the server

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(run, jobs))


def wqp_unit_factor(param, unit):
    """Factor converting a WQP unit to the parameter's standard unit, or NaN."""
    if not isinstance(unit, str):
        return np.nan
    u = unit.lower().replace(" ", "")
    if param == "turbidity":  # nephelometric units, treated as equivalent
        return 1.0 if u in {"ntu", "fnu", "ntru", "ftu", "fau", "fbu", "fnmu", "ntmu"} else np.nan
    if param in ("ecoli", "fecal_coliform", "enterococcus"):  # CFU ~ MPN ~ count
        return 1.0 if re.fullmatch(r"(cfu|mpn|#|count|colonies)/100ml", u) else np.nan
    base = (1.0 if u.startswith(("mg/l", "ppm")) else
            1e-3 if u.startswith(("ug/l", "ppb")) else np.nan)
    if param == "tss":
        return base
    if param == "phosphorus":  # report as P
        return base * (30.974 / 94.971 if "po4" in u else 1.0)
    # nitrogen species, report as N
    for ion, factor in (("no3", 14.007 / 62.004), ("no2", 14.007 / 46.005),
                        ("nh4", 14.007 / 18.038), ("nh3", 14.007 / 17.031)):
        if ion in u and "asn" not in u:
            return base * factor
    return base


def read_zipped_csv(path, **kwargs):
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.endswith(".csv"))
        with z.open(name) as f:
            return pd.read_csv(f, low_memory=False, **kwargs)


def wqp_sites_to_zcta(data_dir, zcta_shp=ZCTA_SHP):
    """Monitoring site -> 2020 ZCTA by point-in-polygon, snapping sites in open
    water to the nearest ZCTA within ZCTA_SNAP_M meters."""
    import geopandas as gpd

    cols = ["MonitoringLocationIdentifier", "LatitudeMeasure", "LongitudeMeasure"]
    sites = pd.concat([read_zipped_csv(p, usecols=cols, dtype=str)
                       for p in sorted((data_dir / WQP_DIR / "stations").glob("*.zip"))])
    # Files are concatenated, so reset the index: duplicate labels would make the
    # de-duplication of spatial-join matches below drop most sites.
    sites = sites.drop_duplicates("MonitoringLocationIdentifier").reset_index(drop=True)
    sites[cols[1:]] = sites[cols[1:]].apply(pd.to_numeric, errors="coerce")
    sites = sites.dropna(subset=cols[1:])
    pts = gpd.GeoDataFrame(sites, geometry=gpd.points_from_xy(
        sites["LongitudeMeasure"], sites["LatitudeMeasure"]), crs="EPSG:4269")
    zcta = gpd.read_file(zcta_shp, columns=["ZCTA5CE20"])
    inside = gpd.sjoin(pts, zcta, how="left", predicate="within")
    inside = inside[~inside.index.duplicated()]
    miss = inside["ZCTA5CE20"].isna()
    snapped = gpd.sjoin_nearest(pts[miss].to_crs(5070), zcta.to_crs(5070), how="left",
                                max_distance=ZCTA_SNAP_M)
    snapped = snapped[~snapped.index.duplicated()]
    inside.loc[miss, "ZCTA5CE20"] = snapped["ZCTA5CE20"]
    print(f"sites: {len(pts)}; inside a ZCTA {(~miss).sum()}, snapped "
          f"{snapped['ZCTA5CE20'].notna().sum()}, unmatched {inside['ZCTA5CE20'].isna().sum()}")
    return inside.set_index("MonitoringLocationIdentifier")["ZCTA5CE20"].dropna()


def compute_wqp_zcta(data_dir):
    """Zip code x day x parameter summary of Water Quality Portal results:
    median and mean of the standardized values, number of results and sites."""
    site_zip = wqp_sites_to_zcta(data_dir)
    cols = ["ActivityStartDate", "MonitoringLocationIdentifier", "CharacteristicName",
            "ResultSampleFractionText", "ResultMeasureValue", "ResultMeasure/MeasureUnitCode"]
    frames, n_raw, n_kept = [], 0, 0
    for path in sorted((data_dir / WQP_DIR / "results").glob("*.zip")):
        r = read_zipped_csv(path, usecols=cols, dtype=str)
        n_raw += len(r)
        r["param"] = r["CharacteristicName"].map(WQP_CHARACTERISTICS)
        # Nutrients: whole-water ("Total" or unspecified) only, so dissolved and
        # total fractions are not mixed. Bacteria and turbidity have no fraction.
        nutrient = r["param"].isin(["phosphorus", "nitrogen"])
        r = r[r["param"].notna() & ~(nutrient & r["ResultSampleFractionText"].notna()
                                     & (r["ResultSampleFractionText"] != "Total"))]
        factor = [wqp_unit_factor(p, u) for p, u in
                  zip(r["param"], r["ResultMeasure/MeasureUnitCode"])]
        r = r.assign(value=r["ResultMeasureValue"].map(clean_result_value) * np.array(factor),
                     ZIP_CODE=r["MonitoringLocationIdentifier"].map(site_zip))
        r = r[r["value"].notna() & (r["value"] >= 0) & r["ZIP_CODE"].notna()]
        n_kept += len(r)
        frames.append(r[["ZIP_CODE", "ActivityStartDate", "param",
                         "MonitoringLocationIdentifier", "value"]])
        print(f"{path.name}: {len(r)} usable results", flush=True)
    res = pd.concat(frames, ignore_index=True)
    out = (res.groupby(["ZIP_CODE", "ActivityStartDate", "param"])
              .agg(median=("value", "median"), mean=("value", "mean"),
                   n_results=("value", "size"),
                   n_sites=("MonitoringLocationIdentifier", "nunique"))
              .reset_index().rename(columns={"ActivityStartDate": "date"}))
    out["unit"] = out["param"].map(WQP_UNITS)
    path = data_dir / WQP_ZIP_CSV
    out.to_csv(path, index=False, float_format="%.6g")
    print(f"results: {n_raw} downloaded, {n_kept} usable; "
          f"saved {len(out)} zip-day-parameter rows to {path}")


# ---------------------------------------------------------------------------
# 6. SDWIS drinking-water violations -> zip code x month
# ---------------------------------------------------------------------------

SDWIS_DIR = "sdwis"
SDWIS_ZIP = "SDWA_latest_downloads.zip"
SDWIS_URL = "https://echo.epa.gov/files/echodownloads/SDWA_latest_downloads.zip"
CWS_BOUNDARIES = "3_0/Service_Areas_V_3_0.gpkg"  # unzipped from PWS_Boundaries_Latest.zip
CWS_BOUNDARIES_URL = ("https://github.com/USEPA/ORD_SAB_Model/raw/refs/heads/main/"
                      "Version_History/PWS_Boundaries_Latest.zip")
SDWIS_SYSTEMS_CSV = "sdwis_cws_zcta2020.csv"
SDWIS_ZIP_CSV = "sdwis_zcta2020.zipcode_month.csv"


def cws_zcta_crosswalk(data_dir, zcta_shp=ZCTA_SHP):
    """Overlay community water system service areas (EPA, v3) on 2020 ZCTAs.
    Each (PWSID, ZCTA) pair gets the share of the system's service area in
    the ZCTA and the system population allocated by that area share."""
    import geopandas as gpd
    import shapely

    cws = gpd.read_file(data_dir / SDWIS_DIR / CWS_BOUNDARIES, layer="CWS",
                        columns=["PWSID", "Population_Served_Count"]).to_crs(5070)
    cws = cws[cws.geometry.notna() & ~cws.geometry.is_empty]
    cws["geometry"] = shapely.make_valid(cws.geometry.values)
    zcta = gpd.read_file(zcta_shp, columns=["ZCTA5CE20"]).to_crs(5070)
    pairs = gpd.sjoin(cws, zcta, how="inner", predicate="intersects")
    inter = shapely.intersection(pairs.geometry.values,
                                 zcta.geometry.values[pairs["index_right"].to_numpy()])
    pairs["area_share"] = shapely.area(inter) / shapely.area(pairs.geometry.values)
    pairs = pairs[pairs["area_share"] > 1e-4]  # drop boundary slivers
    out = pd.DataFrame({
        "PWSID": pairs["PWSID"].to_numpy(),
        "ZIP_CODE": pairs["ZCTA5CE20"].to_numpy(),
        "area_share": pairs["area_share"].to_numpy(),
        "pop_est": (pd.to_numeric(pairs["Population_Served_Count"], errors="coerce")
                    * pairs["area_share"]).to_numpy(),
    })
    out.to_csv(data_dir / SDWIS_SYSTEMS_CSV, index=False, float_format="%.6g")
    print(f"crosswalk: {cws['PWSID'].nunique()} systems, {len(out)} (system, ZCTA) pairs, "
          f"{out['ZIP_CODE'].nunique()} ZCTAs")
    return out


def compute_sdwis_zcta(data_dir):
    """Zip code x month counts of health-based drinking-water violations that
    began that month, in community water systems serving the zip code."""
    xwalk = cws_zcta_crosswalk(data_dir)
    systems = set(xwalk["PWSID"])
    cols = ["PWSID", "VIOLATION_ID", "NON_COMPL_PER_BEGIN_DATE", "IS_HEALTH_BASED_IND",
            "RULE_GROUP_CODE", "PUBLIC_NOTIFICATION_TIER"]
    frames, n_hb_all = [], 0
    with zipfile.ZipFile(data_dir / SDWIS_DIR / SDWIS_ZIP) as z:
        with z.open("SDWA_VIOLATIONS_ENFORCEMENT.csv") as f:
            # One row per violation x enforcement action; violations repeat.
            for chunk in pd.read_csv(f, usecols=cols, dtype=str, chunksize=2_000_000):
                hb = chunk[chunk["IS_HEALTH_BASED_IND"] == "Y"]
                n_hb_all += hb["VIOLATION_ID"].nunique()
                frames.append(hb[hb["PWSID"].isin(systems)])
    viol = pd.concat(frames).drop_duplicates(["PWSID", "VIOLATION_ID"])
    viol["month"] = pd.to_datetime(viol["NON_COMPL_PER_BEGIN_DATE"],
                                   format="%m/%d/%Y", errors="coerce").dt.strftime("%Y-%m")
    viol = viol.dropna(subset=["month"])
    viol["microbial"] = viol["RULE_GROUP_CODE"] == "100"
    viol["tier1"] = viol["PUBLIC_NOTIFICATION_TIER"] == "1"
    print(f"health-based violations: {len(viol)} in mapped community systems "
          f"(of ~{n_hb_all} across all systems/chunks)")

    sys_month = (viol.groupby(["PWSID", "month"])
                     .agg(n_hb=("VIOLATION_ID", "size"), n_microbial=("microbial", "sum"),
                          n_tier1=("tier1", "sum"))
                     .reset_index())
    m = sys_month.merge(xwalk, on="PWSID")
    zip_pop = xwalk.groupby("ZIP_CODE")["pop_est"].sum()
    out = (m.assign(pop_hb=m["pop_est"],
                    pop_microbial=m["pop_est"].where(m["n_microbial"] > 0, 0.0),
                    pop_tier1=m["pop_est"].where(m["n_tier1"] > 0, 0.0))
             .groupby(["ZIP_CODE", "month"])
             .agg(n_hb_violations=("n_hb", "sum"),
                  n_microbial_violations=("n_microbial", "sum"),
                  n_tier1_violations=("n_tier1", "sum"),
                  n_systems_hb=("PWSID", "nunique"),
                  pop_in_hb_systems=("pop_hb", "sum"),
                  pop_in_microbial_systems=("pop_microbial", "sum"),
                  pop_in_tier1_systems=("pop_tier1", "sum"))
             .reset_index())
    out["pop_served_est"] = out["ZIP_CODE"].map(zip_pop)
    out["share_pop_hb"] = (out["pop_in_hb_systems"] / out["pop_served_est"]).clip(upper=1)
    path = data_dir / SDWIS_ZIP_CSV
    out.to_csv(path, index=False, float_format="%.6g")
    print(f"saved {len(out)} zip-months with >=1 health-based violation "
          f"({out['ZIP_CODE'].nunique()} zips, {out['month'].min()} to {out['month'].max()}) "
          f"to {path}; zip-months not listed had none")


# ---------------------------------------------------------------------------
# 7. NASA Black Marble nighttime lights -> zip code x day
# ---------------------------------------------------------------------------

BM_DIR = "blackmarble"
BM_ZIP_CSV = "blackmarble_zcta2020.zipcode_day.csv.gz"
BM_CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"
BM_PRODUCT = "VNP46A2"           # daily, moonlight-adjusted, gap-filled NTL, collection 2
BM_FIRST_DAY = "2012-01-19"
BM_MIN_CLAIMS = 25               # flood dates: zip-days with >= this many claims
BM_WINDOW = 14                   # days before and after each flood date
BM_RES = 1 / 240                 # 15 arc-seconds
BM_FIELDS = "/HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields/"


def bm_tile(lon, lat):
    """Black Marble 10-degree tile (h, v) containing a point."""
    return int((lon + 180) // 10), int((90 - lat) // 10)


def bm_targets(data_dir, min_claims=BM_MIN_CLAIMS, window=BM_WINDOW, zcta_shp=ZCTA_SHP):
    """(tile, day) pairs within +/- window days of a flood date: a zip-day with
    at least min_claims NFIP claims, in the tile holding the zip's center."""
    import geopandas as gpd

    z = gpd.read_file(zcta_shp, columns=["ZCTA5CE20", "INTPTLAT20", "INTPTLON20"],
                      ignore_geometry=True)
    tiles = {zc: bm_tile(float(lon), float(lat))
             for zc, lat, lon in zip(z["ZCTA5CE20"], z["INTPTLAT20"], z["INTPTLON20"])}
    fema = pd.read_csv(data_dir / FEMA_CSV, usecols=["reportedZipcode", "dateOfLoss", "policyCount"],
                       dtype={"reportedZipcode": "string"}, parse_dates=["dateOfLoss"])
    fema = fema[(fema["dateOfLoss"] >= BM_FIRST_DAY) & (fema["policyCount"] >= min_claims)]
    targets = set()
    for zc, day in zip(fema["reportedZipcode"], fema["dateOfLoss"]):
        if zc in tiles:
            for k in range(-window, window + 1):
                targets.add((tiles[zc], (day + pd.Timedelta(days=k)).date()))
    return sorted(targets)


def bm_granules(tile, start, end):
    """{date: download URL} for one tile from NASA CMR (no login needed)."""
    import json
    from urllib.parse import urlencode

    h, v = tile
    urls, page = {}, 1
    while True:
        q = urlencode({"short_name": BM_PRODUCT, "version": "2", "page_size": 2000, "page_num": page,
                       "temporal": f"{start}T00:00:00Z,{end}T23:59:59Z",
                       "bounding_box": f"{h * 10 - 180 + 1},{80 - v * 10 + 1},"
                                       f"{h * 10 - 170 - 1},{90 - v * 10 - 1}"})
        with urllib.request.urlopen(f"{BM_CMR}?{q}") as r:
            entries = json.load(r)["feed"]["entry"]
        for e in entries:  # titles are IDs; date and tile come from the file URL
            for link in e["links"]:
                href = link["href"]
                m = re.search(r"\.A(\d{4})(\d{3})\.h(\d\d)v(\d\d)\..*\.h5$", href)
                if href.startswith("https://") and m and (int(m[3]), int(m[4])) == tile:
                    day = (pd.Timestamp(f"{m[1]}-01-01") + pd.Timedelta(days=int(m[2]) - 1)).date()
                    urls[day] = href
        if len(entries) < 2000:
            return urls
        page += 1


def bm_weights(tile, zcta):
    """Sparse (n_zcta_in_tile x 2400*2400) coverage matrix for one tile, and
    the ZCTA codes of its rows. Cached as an .npz next to the parts."""
    import rasterio
    from exactextract import exact_extract
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin
    from scipy import sparse

    h, v = tile
    west, north = h * 10 - 180, 90 - v * 10
    sub = zcta.cx[west:west + 10, north - 10:north]
    if sub.empty:
        return None, []
    profile = {"driver": "GTiff", "width": 2400, "height": 2400, "count": 1, "dtype": "uint8",
               "crs": "EPSG:4326", "transform": from_origin(west, north, BM_RES, BM_RES)}
    with MemoryFile() as mem:
        with mem.open(**profile) as dst:
            dst.write(np.zeros((1, 2400, 2400), np.uint8))
        with mem.open() as src:
            cov = exact_extract(src, sub, ["cell_id", "coverage"], output="pandas")
    rows = np.concatenate([np.full(len(c), i) for i, c in enumerate(cov["cell_id"])])
    W = sparse.csr_matrix(
        (np.concatenate([np.asarray(c, float) for c in cov["coverage"]]),
         (rows, np.concatenate([np.asarray(c, np.int64) for c in cov["cell_id"]]))),
        shape=(len(sub), 2400 * 2400))
    return W, sub["ZCTA5CE20"].to_numpy()


def bm_tile_day(path, W, zips, day):
    """Zip partial sums for one tile-day: coverage-weighted sums of high-quality
    clear-sky radiance and of gap-filled radiance, with their weights."""
    import h5py

    with h5py.File(path, "r") as f:
        lat = f[BM_FIELDS + "lat"][:]
        assert lat[0] > lat[-1], "expected north-up rows"
        ntl = f[BM_FIELDS + "DNB_BRDF-Corrected_NTL"][:].astype(float).ravel()
        gap = f[BM_FIELDS + "Gap_Filled_DNB_BRDF-Corrected_NTL"][:].astype(float).ravel()
        qf = f[BM_FIELDS + "Mandatory_Quality_Flag"][:].ravel()
        cloud = f[BM_FIELDS + "QF_Cloud_Mask"][:].ravel()
        snow = f[BM_FIELDS + "Snow_Flag"][:].ravel()
    clear = ((cloud >> 6) & 0b11) <= 1  # confident or probably clear
    hq = (qf == 0) & clear & (snow == 0) & (ntl >= 0)
    gq = gap >= 0
    out = pd.DataFrame({
        "ZIP_CODE": zips, "date": day,
        "hq_sum": W @ np.where(hq, ntl, 0.0), "hq_w": W @ hq.astype(float),
        "gf_sum": W @ np.where(gq, gap, 0.0), "gf_w": W @ gq.astype(float),
        "w": np.asarray(W.sum(axis=1)).ravel(),
    })
    return out[out["w"] > 0]


def compute_blackmarble(data_dir, workers=4):
    """Stream Black Marble tiles for the flood windows: download, average over
    ZCTAs, keep the small result, delete the tile. Resumable."""
    import subprocess
    import geopandas as gpd
    from concurrent.futures import ThreadPoolExecutor

    base = data_dir / BM_DIR
    (base / "parts").mkdir(parents=True, exist_ok=True)
    (base / "tiles").mkdir(parents=True, exist_ok=True)
    cookies = base / ".cookies"
    targets = bm_targets(data_dir)
    by_tile = {}
    for tile, day in targets:
        by_tile.setdefault(tile, []).append(day)
    print(f"{len(targets)} tile-days in {len(by_tile)} tiles", flush=True)
    zcta = gpd.read_file(ZCTA_SHP, columns=["ZCTA5CE20"]).to_crs("EPSG:4326")

    for tile, days in sorted(by_tile.items()):
        tag = f"h{tile[0]:02d}v{tile[1]:02d}"
        todo = [d for d in days if not (base / "parts" / f"{tag}_{d}.csv").exists()]
        if not todo:
            continue
        W, zips = bm_weights(tile, zcta)
        if W is None:
            continue
        # Granule time spans are offset from the file date; pad the search.
        urls = bm_granules(tile, min(todo) - pd.Timedelta(days=1), max(todo) + pd.Timedelta(days=1))
        print(f"{tag}: {len(todo)} days to do, {len(zips)} ZCTAs, "
              f"{sum(d in urls for d in todo)} granules found", flush=True)

        def run(day):
            part = base / "parts" / f"{tag}_{day}.csv"
            if day not in urls:
                print(f"MISS {tag} {day}", flush=True)
                return
            tmp = base / "tiles" / urls[day].rsplit("/", 1)[1]
            for attempt in range(3):
                r = subprocess.run(["curl", "-s", "-f", "-n", "-L", "-c", str(cookies),
                                    "-b", str(cookies), "-o", str(tmp), urls[day]])
                if r.returncode == 0:
                    break
                time.sleep(10 * (attempt + 1))
            else:
                print(f"FAIL {tag} {day}", flush=True)
                return
            try:
                bm_tile_day(tmp, W, zips, day).to_csv(part, index=False, float_format="%.6g")
            finally:
                tmp.unlink(missing_ok=True)

        with ThreadPoolExecutor(workers) as pool:
            list(pool.map(run, todo))

    combine_blackmarble(data_dir)


def combine_blackmarble(data_dir):
    """Combine tile-day parts into zip x day values. ZCTAs that straddle tile
    edges are summed across tiles before dividing."""
    parts = sorted((data_dir / BM_DIR / "parts").glob("*.csv"))
    df = pd.concat([pd.read_csv(p, dtype={"ZIP_CODE": "string"}) for p in parts])
    g = df.groupby(["ZIP_CODE", "date"])[["hq_sum", "hq_w", "gf_sum", "gf_w", "w"]].sum()
    out = pd.DataFrame({
        "ntl_hq": g["hq_sum"] / g["hq_w"].where(g["hq_w"] > 0),   # nW/(cm^2 sr)
        "hq_coverage": g["hq_w"] / g["w"],                          # share of zip with clear HQ obs
        "ntl_gapfilled": g["gf_sum"] / g["gf_w"].where(g["gf_w"] > 0),
    }).reset_index()
    path = data_dir / BM_ZIP_CSV
    out.to_csv(path, index=False, float_format="%.6g")
    print(f"saved {len(out)} zip-days ({out['ZIP_CODE'].nunique()} zips, "
          f"{out['date'].nunique()} days) from {len(parts)} tile-days to {path}")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

# SDWIS columns for the build, by calendar month relative to the loss month:
# the loss month (0), the month after (+1), and the rest of a +/-12-month
# window (-12..-1, +2..+12) as an average per month, so all three are on the
# same per-month scale.
SDWIS_REST_WINDOW = 12
SDWIS_REST_MIN_MONTHS = 12        # rest needs at least this many usable months
SDWIS_MEASURES = [("HB Violations", "n_hb_violations"),
                  ("Microbial Violations", "n_microbial_violations"),
                  ("Tier1 Violations", "n_tier1_violations")]
SDWIS_FIRST_MONTH = pd.Period("1991-01", freq="M")  # earlier SDWIS data is sparse


def add_sdwis(fema, data_dir):
    """New health-based (and microbial, tier-1) violations in the community
    water systems serving the zip: in the loss month, in the month after, and
    the average per month over the rest of a +/-12-month window. 0 = served
    zip with no violation; NaN = no mapped system, or months outside
    1991-01..last SDWIS month."""
    v = pd.read_csv(data_dir / SDWIS_ZIP_CSV, dtype={"ZIP_CODE": "string"})
    xw = pd.read_csv(data_dir / SDWIS_SYSTEMS_CSV, dtype={"ZIP_CODE": "string"})
    per_zip = xw.groupby("ZIP_CODE").agg(pop=("pop_est", "sum"), n=("PWSID", "nunique"))
    per_zip = per_zip[per_zip["pop"] > 0]
    v["mi"] = pd.PeriodIndex(v["month"], freq="M").astype("int64")
    first, last = SDWIS_FIRST_MONTH.ordinal, v["mi"].max()
    v = v.set_index(["ZIP_CODE", "mi"])

    zips = fema["reportedZipcode"]
    m0 = fema["dateOfLoss"].dt.to_period("M").astype("int64").to_numpy()
    served = zips.isin(per_zip.index).to_numpy()
    rest_offsets = [k for k in range(-SDWIS_REST_WINDOW, SDWIS_REST_WINDOW + 1) if k not in (0, 1)]

    def counts(col, k):
        idx = pd.MultiIndex.from_arrays([zips.to_numpy(), m0 + k])
        return v[col].reindex(idx).fillna(0).to_numpy()

    def in_range(k):
        return (m0 + k >= first) & (m0 + k <= last)

    n_rest = sum(in_range(k).astype(int) for k in rest_offsets)
    valid = {"Loss Month": served & in_range(0), "1 Month After": served & in_range(1),
             "Rest": served & (n_rest >= SDWIS_REST_MIN_MONTHS)}
    cols = {}
    for name, col in SDWIS_MEASURES:
        cols[f"SDWIS {name} Loss Month"] = np.where(valid["Loss Month"], counts(col, 0), np.nan)
        cols[f"SDWIS {name} 1 Month After"] = np.where(valid["1 Month After"], counts(col, 1), np.nan)
        rest = sum(np.where(in_range(k), counts(col, k), 0.0) for k in rest_offsets)
        with np.errstate(invalid="ignore", divide="ignore"):
            cols[f"SDWIS {name} Rest (per month)"] = np.where(valid["Rest"], rest / n_rest, np.nan)
    cols["sdwis_rest_months"] = np.where(valid["Rest"], n_rest, np.nan)
    cols["sdwis_pop_served_est"] = zips.map(per_zip["pop"]).to_numpy()
    cols["sdwis_n_systems"] = zips.map(per_zip["n"]).to_numpy()
    fema = pd.concat([fema, pd.DataFrame(cols, index=fema.index)], axis=1)
    for label, ok in valid.items():
        c = f"SDWIS HB Violations {label}" + (" (per month)" if label == "Rest" else "")
        print(f"  sdwis {label}: rows with data {ok.sum()}, with >0 health-based violations "
              f"{(fema[c] > 0).sum()}")
    return fema


# PBJ columns: (label, first week offset, last week offset) relative to the
# Monday-start week containing the loss date.
PBJ_WINDOWS = [("4 Weeks Before", -4, -1), ("Loss Week", 0, 0), ("4 Weeks After", 1, 4)]


def load_pbj_weekly(data_dir):
    """PBJ zip x week panel, complete-reporting weeks only (see pbj/README.md)."""
    w = pd.read_csv(data_dir / PBJ_WEEKLY, dtype={"zipcode": "string"}, parse_dates=["week_start"],
                    usecols=["zipcode", "week_start", "facility_days_reported", "resident_days_reported",
                             "resident_days_rate_valid", "total_nurse_hours", "complete_reporting_week"])
    return w[w["complete_reporting_week"]].drop(columns="complete_reporting_week")


def add_pbj(fema, data_dir):
    """Nursing-home census and nurse staffing (CMS PBJ) in the zip, in week
    windows around the loss week. A window is filled only if every week in it
    is a complete-reporting week; otherwise NaN (also NaN for zips without a
    reporting nursing home and for losses before 2017)."""
    w = load_pbj_weekly(data_dir).set_index(["zipcode", "week_start"])
    zips = fema["reportedZipcode"].to_numpy()
    w0 = (fema["dateOfLoss"] - pd.to_timedelta(fema["dateOfLoss"].dt.weekday, "D")).to_numpy()
    offsets = range(min(x[1] for x in PBJ_WINDOWS), max(x[2] for x in PBJ_WINDOWS) + 1)
    weekly = {}
    for k in offsets:
        idx = pd.MultiIndex.from_arrays([zips, w0 + np.timedelta64(7 * k, "D")])
        weekly[k] = w.reindex(idx)
    cols = {}
    for label, k0, k1 in PBJ_WINDOWS:
        ks = range(k0, k1 + 1)
        tot = lambda c: sum(weekly[k][c].to_numpy() for k in ks)   # NaN if any week missing
        days = 7 * len(ks)
        cols[f"PBJ Mean Daily Census {label}"] = tot("resident_days_reported") / days
        cols[f"PBJ Nurse Hours per Day {label}"] = tot("total_nurse_hours") / days
        with np.errstate(invalid="ignore", divide="ignore"):
            hprd = tot("total_nurse_hours") / tot("resident_days_rate_valid")
        cols[f"PBJ Nurse Hours per Resident-Day {label}"] = np.where(np.isfinite(hprd), hprd, np.nan)
        print(f"  pbj {label}: rows with data {np.isfinite(cols[f'PBJ Mean Daily Census {label}']).sum()}")
    pre = PBJ_WINDOWS[0]
    cols["pbj_n_facilities"] = (sum(weekly[k]["facility_days_reported"].to_numpy()
                                    for k in range(pre[1], pre[2] + 1)) / (7 * (pre[2] - pre[1] + 1)))
    return pd.concat([fema, pd.DataFrame(cols, index=fema.index)], axis=1)


def report_match(df, name, col):
    hit = df[col].notna()
    print(f"  {name}: rows matched {hit.sum()} of {len(df)} ({hit.mean():.1%}); "
          f"zips {df.loc[hit, 'reportedZipcode'].nunique()} of {df['reportedZipcode'].nunique()}")


def build(data_dir, out, save_intermediate=False, outcome="nitro"):
    """FEMA grouped claims + an outcome (nitrogen or SDWIS) + FSF + ACS + PRISM."""
    fema = pd.read_csv(data_dir / FEMA_CSV, dtype={"reportedZipcode": "string"},
                       parse_dates=["dateOfLoss"])
    n = len(fema)
    print(f"fema: {n} rows, {fema['reportedZipcode'].nunique()} zips")

    def save(df, name):
        if save_intermediate:
            df.to_csv(data_dir / name, index=False)
            print(f"  saved {name}")

    add_outcome = {"nitro": add_nitrogen, "sdwis": add_sdwis, "pbj": add_pbj}[outcome]
    fema = add_outcome(fema, data_dir)
    save(fema, f"ai2.fema.grouped.{outcome}.csv")
    fema = add_fsf(fema, data_dir)
    save(fema, f"ai2.fema.grouped.{outcome}.fsf.csv")
    fema, acs_columns = add_acs(fema, data_dir)
    save(fema, f"ai2.fema.grouped.{outcome}.fsf.acs.csv")
    fema = add_prism(fema, data_dir)
    assert len(fema) == n, "row count changed"

    fema = fema.sort_values(["reportedZipcode", "dateOfLoss"]).reset_index(drop=True)
    fema.to_csv(out, index=False)
    acs_columns.to_csv(out.with_name(out.stem + ".acs_columns.csv"), index=False)
    print(f"saved {fema.shape[0]} rows x {fema.shape[1]} columns to {out}")


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

BLUE, ORANGE = "#2a78d6", "#eb6834"  # categorical slots 1 and 2
TEXT, MUTED, GRID = "#1f1f1e", "#6b6a63", "#e4e3dc"


def style_axes(ax):
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED)


def plot_distributions(df, out):
    import matplotlib.pyplot as plt

    bins = np.logspace(-2.5, 3, 56)  # zeros cannot sit on a log axis; counted instead
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), sharey=True)
    for ax, (days, before_col, after_col) in zip(axes, NITROGEN_WINDOWS):
        notes, zeros = [], 0
        for col, label, color in ((before_col, "Before loss", BLUE),
                                  (after_col, "After loss", ORANGE)):
            v = df[col].dropna()
            ax.hist(v[v > 0], bins=bins, histtype="step", linewidth=2, color=color,
                    label=f"{label} (n={len(v):,})")
            ax.axvline(v.median(), color=color, linewidth=1, linestyle="--")
            notes.append(f"{label.split()[0]} median {v.median():.2f}")
            zeros += (v == 0).sum()
        if zeros:
            notes.append(f"{zeros} zero values not shown")
        ax.set_xscale("log")
        ax.set_title(f"{days // 30} month{'s' if days > 30 else ''} ({days}-day window)",
                     loc="left", color=TEXT, fontsize=12)
        ax.set_xlabel("Nitrogen (mg/L, log scale)", color=MUTED)
        ax.text(0.02, 0.97, "\n".join(notes), transform=ax.transAxes, va="top",
                fontsize=8.5, color=MUTED)
        ax.legend(frameon=False, loc="upper right", fontsize=9, labelcolor=TEXT)
        style_axes(ax)
    axes[0].set_ylabel("FEMA zip-day rows", color=MUTED)
    fig.suptitle("Nearest nitrogen reading before vs. after flood loss, same zip code",
                 x=0.01, ha="left", color=TEXT, fontsize=13)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print("saved", out)


def plot_change(df, days, before_col, after_col, out, lim=3.0, width=0.1):
    import matplotlib.pyplot as plt

    label = f"{days // 30} month{'s' if days > 30 else ''}"
    diff = (df[after_col] - df[before_col]).dropna()
    below, above = (diff < -lim).sum(), (diff > lim).sum()
    bins = np.arange(-lim - width / 2, lim + width, width)  # centered on 0

    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.hist(diff[diff.abs() <= lim], bins=bins, color=BLUE, edgecolor="white", linewidth=0.6)
    ax.axvline(0, color=MUTED, linewidth=1)
    stats = [
        f"n = {len(diff):,} zip-days with both readings",
        f"median {diff.median():+.3f}, mean {diff.mean():+.3f} mg/L",
        f"up {(diff > 0).sum():,}  ·  down {(diff < 0).sum():,}  ·  zero {(diff == 0).sum():,}",
        f"not shown: {below} < −{lim:g}, {above} > +{lim:g}",
        f"(full range {diff.min():.1f} to {diff.max():+.1f})",
    ]
    ax.text(0.98, 0.97, "\n".join(stats), transform=ax.transAxes, va="top", ha="right",
            fontsize=8.5, color=MUTED)
    ax.set_title(f"Change in nitrogen around a flood loss: {label} after − {label} before",
                 loc="left", color=TEXT, fontsize=12)
    ax.set_xlabel("After − before (mg/L)", color=MUTED)
    ax.set_ylabel("FEMA zip-day rows", color=MUTED)
    ax.set_xlim(-lim, lim)
    style_axes(ax)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print("saved", out)


# (column, axis label, transform) for the corner plots. Nitrogen and
# population are log10 because of their long right tails.
CORNER_VARS = [
    ("acs_SE_A14006_001", r"median income (k\$)", lambda v: v / 1e3),
    ("acs_SE_A00001_001", "log$_{10}$ population", np.log10),
    ("fsf_avg_risk_score_all", "FSF risk score", lambda v: v),
    ("prism_MEAN", "rainfall (mm)", lambda v: v),
]
CORNER_SUPPORT = ["fsf_count_property", "acs_SE_A00001_001", "prism_MEAN"]


def corner_data(df, nitrogen_col, mask=None):
    """(n, 5) array for the corner plot, from rows with the nitrogen reading
    and FSF, ACS and PRISM data (and `mask`, if given). Also returns how many
    rows were dropped for missing income or zero nitrogen/population (log10
    needs positive values)."""
    keep = df[nitrogen_col].notna() & df[CORNER_SUPPORT].notna().all(axis=1)
    if mask is not None:
        keep &= mask
    rows = df[keep]
    cols = [nitrogen_col] + [c for c, _, _ in CORNER_VARS]
    usable = rows[cols].notna().all(axis=1) & (rows[nitrogen_col] > 0) \
        & (rows["acs_SE_A00001_001"] > 0)
    data = np.column_stack(
        [np.log10(rows.loc[usable, nitrogen_col])]
        + [f(rows.loc[usable, c].to_numpy(float)) for c, _, f in CORNER_VARS])
    return data, len(rows) - len(data)


def plot_corner(sets, title, notes, out, medians=True):
    """Overlaid corner plots of several sets, each (label, color, data,
    n_dropped[, linestyle]). Histograms are normalized to unit area so sets
    of different size compare by shape. medians=False drops the median lines
    (the legend still gives each set's median nitrogen)."""
    import corner
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    sets = [(*st, "-") if len(st) == 4 else st for st in sets]
    both = np.vstack([d for _, _, d, _, _ in sets])
    ranges = [tuple(np.quantile(both[:, k], [0.0025, 0.9975])) for k in range(both.shape[1])]
    labels = ["log$_{10}$ nitrogen (mg/L)"] + [lbl for _, lbl, _ in CORNER_VARS]

    fig = plt.figure(figsize=(13, 13))
    for _, color, data, _, ls in sets:
        corner.corner(
            data, fig=fig, labels=labels, range=ranges, bins=30, color=color,
            weights=np.full(len(data), 1 / len(data)),
            quantiles=[0.5] if medians else [], plot_datapoints=False, plot_density=False,
            fill_contours=False, levels=(0.39, 0.86), smooth=1.0,
            hist_kwargs={"linewidth": 1.8, "linestyle": ls},
            contour_kwargs={"linewidths": 1.6, "linestyles": ls},
            label_kwargs={"fontsize": 11},
        )

    handles = [Line2D([], [], color=color, linewidth=2, linestyle=ls,
                      label=f"{label}: n = {len(data):,}"
                            f" (median N {10 ** np.median(data[:, 0]):.2f} mg/L)")
               for label, color, data, _, ls in sets]
    fig.legend(handles=handles, loc="upper right", bbox_to_anchor=(0.97, 0.93),
               frameon=False, fontsize=12, labelcolor=TEXT)
    dropped = " / ".join(str(n) for _, _, _, n, _ in sets)
    fig.suptitle(title, x=0.97, y=0.97, ha="right", fontsize=14, color=TEXT)
    fig.text(0.97, 0.80,
             "Histograms normalized to unit area. Contours: 1σ and 2σ (39%, 86%).\n"
             + ("Dashed vertical lines: medians. " if medians else "")
             + "Axes show the central 99.5% of all sets.\n"
             + f"Dropped (missing income or zero N/population): {dropped}.\n"
             + "Income in each row's ACS-period dollars (not inflation-adjusted)."
             + "".join("\n" + n for n in notes),
             ha="right", va="top", fontsize=10, color=MUTED)
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print("saved", out)


AQUA, VIOLET = "#1baf7a", "#4a3aa7"  # categorical slots 3 and 7

# Characteristics for the correlation matrix: (label, function of the frame).
CORR_VARS = [
    ("N before", lambda d: d["Nitrogen 1 Month Before"]),
    ("N after", lambda d: d["Nitrogen 1 Month After"]),
    ("N change", lambda d: d["Nitrogen 1 Month After"] - d["Nitrogen 1 Month Before"]),
    ("crs_treat", lambda d: d["crs_treat"]),
    ("primary residence", lambda d: d["primaryResidence"]),
    ("policies", lambda d: d["policyCount"]),
    ("paid total", lambda d: d["amountPaidOnTotalClaim"]),
    ("paid per policy", lambda d: d["amountPaidOnTotalClaim"] / d["policyCount"]),
    ("median income", lambda d: d["acs_SE_A14006_001"]),
    ("population", lambda d: d["acs_SE_A00001_001"]),
    ("pop. density", lambda d: d["acs_SE_A00002_002"]),
    ("FSF % in SFHA", lambda d: d["fsf_pct_fema_sfha"]),
    ("FSF risk score", lambda d: d["fsf_avg_risk_score_all"]),
    ("rainfall", lambda d: d["prism_MEAN"]),
    ("loss year", lambda d: d["dateOfLoss"].dt.year),
]
CORR_COLUMNS = ["primaryResidence", "policyCount", "amountPaidOnTotalClaim",
                "acs_SE_A00002_002", "fsf_pct_fema_sfha", "dateOfLoss"]


def plot_correlations(df, out):
    """Spearman rank correlations among zip-day characteristics, for rows with
    a 1-month nitrogen reading (before or after) and FSF, ACS and PRISM data.
    Pairwise-complete: nitrogen pairs use only rows that have those readings."""
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    before_col, after_col = NITROGEN_WINDOWS[0][1:]
    rows = df[(df[before_col].notna() | df[after_col].notna())
              & df[CORNER_SUPPORT].notna().all(axis=1)]
    values = pd.DataFrame({label: f(rows) for label, f in CORR_VARS})
    corr = values.corr(method="spearman", min_periods=500)
    n = len(corr)

    # Diverging: orange (negative) - neutral gray - blue (positive).
    cmap = LinearSegmentedColormap.from_list("div", [ORANGE, "#efeee9", BLUE])
    masked = np.ma.masked_where(np.triu(np.ones((n, n), bool)), corr.to_numpy())
    fig, ax = plt.subplots(figsize=(11, 9.5))
    im = ax.imshow(masked, cmap=cmap, vmin=-1, vmax=1)
    for i in range(n):
        for j in range(i):
            v = corr.iat[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8,
                    color="white" if abs(v) > 0.55 else TEXT)
    ax.set_xticks(range(n), corr.columns, rotation=45, ha="right", color=TEXT)
    ax.set_yticks(range(n), corr.index, color=TEXT)
    for side in ax.spines.values():
        side.set_visible(False)
    ax.tick_params(length=0)
    cb = fig.colorbar(im, ax=ax, shrink=0.6, pad=0.02)
    cb.set_label("Spearman ρ", color=MUTED)
    cb.outline.set_visible(False)
    ax.set_title(f"Correlations among zip-day characteristics ({len(rows):,} rows with "
                 f"1-month nitrogen + FSF/ACS/PRISM)", loc="left", color=TEXT, fontsize=12)
    fig.text(0.01, 0.01,
             f"Pairwise complete: N before n={values['N before'].notna().sum():,}, "
             f"N after n={values['N after'].notna().sum():,}, "
             f"N change n={values['N change'].notna().sum():,}; other pairs n≈{len(rows):,}. "
             "Rows are not independent (several per zip code).",
             fontsize=8.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print("saved", out)


EVENT_GAP_DAYS = 14       # loss dates closer than this in a zip are one flood event
EVENT_WINDOW = 12         # months before and after a flood


def flood_events(data_dir):
    """Flood events: a zip's loss dates merged when < EVENT_GAP_DAYS apart.
    `isolated` = no other event in the zip within 12 months either side."""
    f = pd.read_csv(data_dir / FEMA_CSV,
                    usecols=["reportedZipcode", "dateOfLoss", "policyCount", "crs_treat"],
                    dtype={"reportedZipcode": "string"}, parse_dates=["dateOfLoss"])
    f = f.sort_values(["reportedZipcode", "dateOfLoss"])
    gap = f.groupby("reportedZipcode")["dateOfLoss"].diff().dt.days
    f["event"] = (gap.isna() | (gap > EVENT_GAP_DAYS)).cumsum()
    ev = (f.assign(w=f["crs_treat"] * f["policyCount"])
           .groupby("event").agg(zip=("reportedZipcode", "first"), start=("dateOfLoss", "min"),
                                 claims=("policyCount", "sum"), maxday=("policyCount", "max"),
                                 w=("w", "sum"))
            .reset_index(drop=True).sort_values(["zip", "start"]))
    ev["crs"] = ev.pop("w") / ev["claims"]   # claim-weighted crs_treat over the event
    ev["group"] = np.select([ev["crs"] == 1, ev["crs"] == 0],
                            ["CRS (crs_treat=1)", "no CRS (crs_treat=0)"], "mixed")
    prev = ev.groupby("zip")["start"].diff().dt.days
    nxt = -ev.groupby("zip")["start"].diff(-1).dt.days
    ev["isolated"] = (prev.isna() | (prev > 365)) & (nxt.isna() | (nxt > 365))
    return ev


def sdwis_event_study(data_dir, n_boot=200, seed=0):
    """Share of event zips with a new violation in each month around a flood,
    minus the share of all served zips in the same state that month (removes
    season, trend and state reporting). Returns {(outcome, sample): (k, est,
    lo, hi, n)} relative to the event's pre-flood average, with 95% bootstrap
    bands that resample zip codes."""
    v = pd.read_csv(data_dir / SDWIS_ZIP_CSV, dtype={"ZIP_CODE": "string"})
    xw = pd.read_csv(data_dir / SDWIS_SYSTEMS_CSV, dtype={"ZIP_CODE": "string"})
    served = xw.groupby("ZIP_CODE")["pop_est"].sum()
    served = served[served > 0]
    state = (xw.sort_values("pop_est", ascending=False).drop_duplicates("ZIP_CODE")
               .set_index("ZIP_CODE")["PWSID"].str[:2])          # state of main system
    n_zips = pd.Series(served.index).map(state).value_counts()
    v = v[v["ZIP_CODE"].isin(served.index)]
    v["mi"] = pd.PeriodIndex(v["month"], freq="M").astype("int64")
    v["state"] = v["ZIP_CODE"].map(state)

    ev = flood_events(data_dir)
    # SDWIS is reliable from 1991; FEMA claims end in 2020.
    ev = ev[(ev["start"] >= "1992-01-01") & (ev["start"] <= "2019-12-31")
            & ev["zip"].isin(served.index)]
    ev["state"] = ev["zip"].map(state)
    ev["m0"] = ev["start"].dt.to_period("M").astype("int64")
    K = np.arange(-EVENT_WINDOW, EVENT_WINDOW + 1)
    samples = {"all floods": np.ones(len(ev), bool),
               "large (≥25 claims)": (ev["claims"] >= 25).to_numpy()}
    outcomes = {"any health-based": v["n_hb_violations"] > 0,
                "any microbial": v["n_microbial_violations"] > 0,
                "any tier 1 (acute)": v["n_tier1_violations"] > 0}
    _, zip_idx = np.unique(ev["zip"].to_numpy(), return_inverse=True)
    rng = np.random.default_rng(seed)
    results = {}
    for oname, mask in outcomes.items():
        hit = v[mask]
        have = set(zip(hit["ZIP_CODE"], hit["mi"]))
        cnt = hit.groupby(["state", "mi"]).size()
        rate = (cnt / cnt.index.get_level_values(0).map(n_zips).to_numpy()).to_dict()
        D = np.array([[((z, m + k) in have) - rate.get((st, m + k), 0.0) for k in K]
                      for z, st, m in zip(ev["zip"], ev["state"], ev["m0"])])
        D = D - D[:, K < 0].mean(axis=1, keepdims=True)   # relative to own pre-period
        for sname, sel in samples.items():
            d, zi = D[sel], zip_idx[sel]
            sums = pd.DataFrame(d).groupby(zi).sum().to_numpy()
            counts = np.bincount(zi)[np.unique(zi)]
            est = sums.sum(0) / counts.sum()
            boots = []
            for _ in range(n_boot):
                i = rng.integers(0, len(counts), len(counts))
                boots.append(sums[i].sum(0) / counts[i].sum())
            lo, hi = np.percentile(boots, [2.5, 97.5], axis=0)
            results[(oname, sname)] = (K, est, lo, hi, int(sel.sum()))
    return results


def plot_sdwis_event_study(data_dir, out):
    import matplotlib.pyplot as plt

    res = sdwis_event_study(data_dir)
    outcomes = list(dict.fromkeys(o for o, _ in res))
    fig, axes = plt.subplots(1, len(outcomes), figsize=(15, 4.6), sharex=True)
    for ax, oname in zip(axes, outcomes):
        for (o, sname), (K, est, lo, hi, n) in res.items():
            if o != oname:
                continue
            color = ORANGE if sname.startswith("large") else BLUE
            ax.fill_between(K, lo * 100, hi * 100, color=color, alpha=0.15, linewidth=0)
            ax.plot(K, est * 100, color=color, linewidth=2, marker="o", ms=3,
                    label=f"{sname} (n={n:,})")
        ax.axhline(0, color=MUTED, linewidth=1)
        ax.axvline(-0.5, color=MUTED, linewidth=1, linestyle="--")
        ax.set_title(oname, loc="left", color=TEXT, fontsize=12)
        ax.set_xlabel("Months relative to flood (0 = flood month)", color=MUTED)
        style_axes(ax)
    axes[0].set_ylabel("Change in % of zips with a new violation\n(vs. pre-flood, net of state-month rate)",
                       color=MUTED)
    axes[0].legend(frameon=False, fontsize=9, loc="upper left", labelcolor=TEXT)
    fig.suptitle("Drinking-water violations (SDWIS) around NFIP flood events, 1992–2019",
                 x=0.01, ha="left", color=TEXT, fontsize=13)
    fig.text(0.01, 0.005, "Bands: 95% bootstrap over zip codes. Events = loss dates within 14 days merged. "
             "Community water systems mapped to ZCTAs by EPA service areas.",
             fontsize=8.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print("saved", out)


BM_MIN_HQ_COVERAGE = 0.5   # use a zip-day only if >= half the zip has clear high-quality pixels
BM_MIN_PRE_LIGHT = 2.0     # nW/(cm^2 sr); dark zips carry no outage signal


def blackmarble_event_study(data_dir, n_boot=1000, seed=0):
    """Nighttime light around large floods (an event with a >= BM_MIN_CLAIMS
    claim day), relative to the event zip's own pre-flood level (days -14..-2),
    raw and net of nearby zips (same 3-digit zip prefix, no claims within 30
    days). Returns per-day log changes by CRS group with bootstrap bands over
    events, and per-event window means."""
    f = pd.read_csv(data_dir / FEMA_CSV,
                    usecols=["reportedZipcode", "dateOfLoss", "policyCount", "crs_treat"],
                    dtype={"reportedZipcode": "string"}, parse_dates=["dateOfLoss"])
    f = f.sort_values(["reportedZipcode", "dateOfLoss"])
    gap = f.groupby("reportedZipcode")["dateOfLoss"].diff().dt.days
    f["event"] = (gap.isna() | (gap > EVENT_GAP_DAYS)).cumsum()
    ev = (f.assign(w=f["crs_treat"] * f["policyCount"])
           .groupby("event").agg(zip=("reportedZipcode", "first"), start=("dateOfLoss", "min"),
                                 claims=("policyCount", "sum"), maxday=("policyCount", "max"),
                                 w=("w", "sum"))
           .reset_index(drop=True))
    ev["crs"] = ev["w"] / ev["claims"]          # claim-weighted crs_treat over the event
    ev = ev[(ev["maxday"] >= BM_MIN_CLAIMS) & (ev["start"] >= pd.Timestamp(BM_FIRST_DAY) + pd.Timedelta(days=BM_WINDOW))
            & (ev["start"] <= "2020-08-04")].reset_index(drop=True)
    ev["group"] = np.select([ev["crs"] == 1, ev["crs"] == 0],
                            ["CRS (crs_treat=1)", "no CRS (crs_treat=0)"], "mixed")
    ev["eid"] = ev.index
    ev["p3"] = ev["zip"].str[:3]

    b = pd.read_csv(data_dir / BM_ZIP_CSV, usecols=["ZIP_CODE", "date", "ntl_hq", "hq_coverage"],
                    dtype={"ZIP_CODE": "string"}, parse_dates=["date"])
    b = b[b["hq_coverage"] >= BM_MIN_HQ_COVERAGE][["ZIP_CODE", "date", "ntl_hq"]]
    K = pd.DataFrame({"k": np.arange(-BM_WINDOW, BM_WINDOW + 1)})

    def with_days(df):
        df = df.merge(K, how="cross")
        df["date"] = df["start"] + pd.to_timedelta(df["k"], "D")
        return df

    def rel(df, key):  # log of light relative to the unit's own pre-flood mean
        pre = df[df["k"] <= -2].groupby(key)["ntl_hq"].agg(["mean", "count"])
        df = df.merge(pre, left_on=key, right_index=True)
        df = df[(df["count"] >= 3) & (df["mean"] >= BM_MIN_PRE_LIGHT)]
        return df.assign(lr=np.log(df["ntl_hq"].clip(lower=0.05) / df["mean"]))

    t = with_days(ev[["eid", "zip", "start"]]).merge(
        b.rename(columns={"ZIP_CODE": "zip"}), on=["zip", "date"])
    t = rel(t, "eid")
    # Nearby zips: same 3-digit prefix, no NFIP claim within 30 days of the event start.
    zips = b[["ZIP_CODE"]].drop_duplicates().rename(columns={"ZIP_CODE": "czip"})
    zips["p3"] = zips["czip"].str[:3]
    c = ev[["eid", "p3", "start", "zip"]].merge(zips, on="p3")
    c = c[c["czip"] != c["zip"]]
    near = c.merge(f[["reportedZipcode", "dateOfLoss"]], left_on="czip", right_on="reportedZipcode")
    near = near[(near["dateOfLoss"] - near["start"]).dt.days.abs() <= 30][["eid", "czip"]].drop_duplicates()
    c = c.merge(near, on=["eid", "czip"], how="left", indicator=True)
    c = c[c["_merge"] == "left_only"].drop(columns="_merge")
    c = with_days(c).merge(b.rename(columns={"ZIP_CODE": "czip"}), on=["czip", "date"])
    c = rel(c, ["eid", "czip"])
    t = t.merge(c.groupby(["eid", "k"])["lr"].median().rename("clr"),
                left_on=["eid", "k"], right_index=True, how="left")
    t["dlr"] = t["lr"] - t["clr"]
    t = t.merge(ev[["eid", "group"]], on="eid")

    rng = np.random.default_rng(seed)
    profiles = {}
    for col in ("lr", "dlr"):
        for g, sub in t.groupby("group"):
            piv = sub.pivot_table(index="eid", columns="k", values=col)  # events x days
            est = piv.mean()
            boots = [piv.iloc[rng.integers(0, len(piv), len(piv))].mean() for _ in range(n_boot)]
            lo, hi = np.nanpercentile(np.vstack(boots), [2.5, 97.5], axis=0)
            profiles[(col, g)] = (est.index.to_numpy(), est.to_numpy(), lo, hi, piv.shape[0])
    return t, ev, profiles


def plot_blackmarble_event_study(data_dir, out):
    import matplotlib.pyplot as plt

    _, _, profiles = blackmarble_event_study(data_dir)
    colors = {"CRS (crs_treat=1)": AQUA, "no CRS (crs_treat=0)": VIOLET}
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.8), sharey=True)
    titles = {"lr": "Raw: vs. the zip's own pre-flood level",
              "dlr": "Net of nearby zips (same 3-digit prefix, no claims)"}
    for ax, col in zip(axes, ("lr", "dlr")):
        for g, color in colors.items():
            k, est, lo, hi, n = profiles[(col, g)]
            ax.fill_between(k, np.expm1(lo) * 100, np.expm1(hi) * 100, color=color, alpha=0.15, linewidth=0)
            ax.plot(k, np.expm1(est) * 100, color=color, linewidth=2, marker="o", ms=3,
                    label=f"{g} (n={n} events)")
        ax.axhline(0, color=MUTED, linewidth=1)
        ax.axvline(-0.5, color=MUTED, linewidth=1, linestyle="--")
        ax.set_title(titles[col], loc="left", color=TEXT, fontsize=12)
        ax.set_xlabel("Days relative to flood start (0 = first loss date)", color=MUTED)
        style_axes(ax)
    axes[0].set_ylabel("Change in nighttime light (%)", color=MUTED)
    axes[0].legend(frameon=False, fontsize=9, loc="lower left", labelcolor=TEXT)
    fig.suptitle("NASA Black Marble nighttime light around large NFIP floods (≥25 claims in a day), 2012–2020",
                 x=0.01, ha="left", color=TEXT, fontsize=13)
    fig.text(0.01, 0.005, "Clear-sky high-quality pixels only (≥50% of zip covered); zips with pre-flood "
             "light ≥ 2 nW/cm²/sr and ≥ 3 clear pre-flood days. Bands: 95% bootstrap over events. "
             "Mixed-CRS events not shown.", fontsize=8.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print("saved", out)


PBJ_EVENT_WEEKS = 8          # weeks before/after the flood week
PBJ_CONTROL_DAYS = 60        # nearby zips: no NFIP claim within this many days


def pbj_event_study(data_dir, n_boot=1000, seed=0):
    """Nursing-home census and nurse hours per resident-day around floods.
    Weekly log change vs the zip's own mean over weeks -8..-2 (>= 4 complete
    weeks), net of the median change in nearby PBJ zips (same 3-digit prefix,
    no NFIP claim within PBJ_CONTROL_DAYS days). Per sample (all floods,
    large) and CRS group, with bootstrap bands over events."""
    ev = flood_events(data_dir)
    w = load_pbj_weekly(data_dir)
    w["hprd"] = w["total_nurse_hours"] / w["resident_days_rate_valid"].where(w["resident_days_rate_valid"] > 0)
    w["census"] = w["resident_days_reported"].where(w["resident_days_reported"] > 0)
    w = w[["zipcode", "week_start", "census", "hprd"]]
    pbj_zips = set(w["zipcode"])
    ev = ev[(ev["start"] >= "2017-03-01") & ev["zip"].isin(pbj_zips)].reset_index(drop=True)
    ev["eid"] = ev.index
    ev["w0"] = ev["start"] - pd.to_timedelta(ev["start"].dt.weekday, "D")
    K = pd.DataFrame({"k": np.arange(-PBJ_EVENT_WEEKS, PBJ_EVENT_WEEKS + 1)})

    def with_weeks(df, zipcol):
        df = df.merge(K, how="cross")
        df["week_start"] = df["w0"] + pd.to_timedelta(7 * df["k"], "D")
        return df.merge(w.rename(columns={"zipcode": zipcol}), on=[zipcol, "week_start"])

    def rel(df, key, col):
        d = df[df[col] > 0]   # logs need positive census and hours
        pre = d[d["k"] <= -2].groupby(key)[col].agg(["mean", "count"])
        d = d.merge(pre, left_on=key, right_index=True)
        d = d[d["count"] >= 4]
        return d.assign(lr=np.log(d[col] / d["mean"]))

    t = with_weeks(ev[["eid", "zip", "w0"]], "zip")
    # nearby zips with nursing homes and no claims around the event
    f = pd.read_csv(data_dir / FEMA_CSV, usecols=["reportedZipcode", "dateOfLoss"],
                    dtype={"reportedZipcode": "string"}, parse_dates=["dateOfLoss"])
    near = pd.DataFrame({"czip": sorted(pbj_zips)})
    near["p3"] = near["czip"].str[:3]
    c = ev.assign(p3=ev["zip"].str[:3])[["eid", "p3", "zip", "start", "w0"]].merge(near, on="p3")
    c = c[c["czip"] != c["zip"]]
    hit = c.merge(f, left_on="czip", right_on="reportedZipcode")
    hit = hit[(hit["dateOfLoss"] - hit["start"]).dt.days.abs() <= PBJ_CONTROL_DAYS][["eid", "czip"]]
    c = c.merge(hit.drop_duplicates(), on=["eid", "czip"], how="left", indicator=True)
    c = with_weeks(c[c["_merge"] == "left_only"].drop(columns="_merge"), "czip")

    samples = {"all floods": ev["eid"], "large floods (≥25 claims in a day)": ev.loc[ev["maxday"] >= 25, "eid"]}
    rng = np.random.default_rng(seed)
    out = {}
    for col in ("census", "hprd"):
        tt = rel(t, "eid", col)
        cc = rel(c, ["eid", "czip"], col)
        tt = tt.merge(cc.groupby(["eid", "k"])["lr"].median().rename("clr"),
                      left_on=["eid", "k"], right_index=True)
        tt["dlr"] = tt["lr"] - tt["clr"]
        tt = tt.merge(ev[["eid", "group"]], on="eid")
        for sname, ids in samples.items():
            for g in ("CRS (crs_treat=1)", "no CRS (crs_treat=0)"):
                sub = tt[tt["eid"].isin(ids) & (tt["group"] == g)]
                piv = sub.pivot_table(index="eid", columns="k", values="dlr")
                if piv.empty:
                    continue
                boots = [piv.iloc[rng.integers(0, len(piv), len(piv))].mean() for _ in range(n_boot)]
                lo, hi = np.nanpercentile(np.vstack(boots), [2.5, 97.5], axis=0)
                post = sub[sub["k"].between(1, 4)].groupby("eid")["dlr"].mean()
                out[(col, sname, g)] = dict(k=piv.columns.to_numpy(), est=piv.mean().to_numpy(),
                                            lo=lo, hi=hi, n=len(piv), post=post)
    return out


def plot_pbj_event_study(data_dir, out):
    import matplotlib.pyplot as plt

    res = pbj_event_study(data_dir)
    colors = {"CRS (crs_treat=1)": AQUA, "no CRS (crs_treat=0)": VIOLET}
    titles = {"census": "Resident census", "hprd": "Nurse hours per resident-day"}
    samples = ["all floods", "large floods (≥25 claims in a day)"]
    fig, axes = plt.subplots(2, 2, figsize=(14, 8.5), sharex=True)
    for i, sname in enumerate(samples):
        for j, col in enumerate(("census", "hprd")):
            ax = axes[i, j]
            for g, color in colors.items():
                r = res.get((col, sname, g))
                if r is None:
                    continue
                ax.fill_between(r["k"], np.expm1(r["lo"]) * 100, np.expm1(r["hi"]) * 100,
                                color=color, alpha=0.15, linewidth=0)
                ax.plot(r["k"], np.expm1(r["est"]) * 100, color=color, linewidth=2, marker="o", ms=3,
                        label=f"{g} (n={r['n']} events)")
            ax.axhline(0, color=MUTED, linewidth=1)
            ax.axvline(-0.5, color=MUTED, linewidth=1, linestyle="--")
            ax.set_title(f"{titles[col]}: {sname}", loc="left", color=TEXT, fontsize=11)
            if i == 1:
                ax.set_xlabel("Weeks relative to flood week (0 = week of first loss date)", color=MUTED)
            style_axes(ax)
            ax.legend(frameon=False, fontsize=8.5, loc="lower left", labelcolor=TEXT)
        axes[i, 0].set_ylabel("Change vs. pre-flood, net of nearby zips (%)", color=MUTED)
    fig.suptitle("Nursing homes (CMS PBJ) around NFIP flood events, 2017–2020",
                 x=0.01, ha="left", color=TEXT, fontsize=13)
    fig.text(0.01, 0.005, "Complete-reporting weeks only; pre-flood = weeks −8…−2 (≥4 weeks). Nearby = PBJ zips "
             "with the same 3-digit prefix and no NFIP claim within 60 days. Bands: 95% bootstrap over events. "
             "Mixed-CRS events not shown.", fontsize=8.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print("saved", out)


# ---- Quick flood checks: before vs after, all / CRS / no CRS -----------------

CHECK_GROUPS = [("All floods", None), ("CRS (crs_treat = 1)", 1.0), ("No CRS (crs_treat = 0)", 0.0)]


def _paired_stats(b, a, log):
    """Text summary of a paired before/after sample."""
    from scipy.stats import wilcoxon

    d = np.log(a / b) if log else a - b
    up, down = (d > 0).mean(), (d < 0).mean()
    try:
        p = wilcoxon(d[d != 0]).pvalue if (d != 0).sum() > 10 else np.nan
    except ValueError:
        p = np.nan
    change = (f"median change {np.expm1(np.median(d)):+.1%}, mean {np.expm1(d.mean()):+.1%}" if log
              else f"median change {np.median(d):+.3f}, mean {d.mean():+.4f}")
    return d, f"n = {len(d):,}\n{change}\nup {up:.0%} · down {down:.0%}\nWilcoxon p = {p:.2g}"


def plot_flood_check(name, unit, before, after, crs, out, log=True, counts=None):
    """Two rows x three columns (all / CRS / no CRS).
    Top: distribution of the outcome before vs after (log-x if `log`; for
    count outcomes, `counts` = (before_counts, after_counts, crs_before,
    crs_after) gives bar charts of the share of months with 0/1/2/3+).
    Bottom: distribution of each row's change (log ratio if `log`)."""
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    for j, (gname, gval) in enumerate(CHECK_GROUPS):
        sel = np.ones(len(before), bool) if gval is None else (crs == gval)
        b, a = before[sel], after[sel]
        if log:
            pos = (b > 0) & (a > 0)
            b, a = b[pos], a[pos]
        ax = axes[0, j]
        if counts is not None:
            cb, ca, gb, ga = counts
            cb = cb if gval is None else cb[gb == gval]
            ca = ca if gval is None else ca[ga == gval]
            cats = ["0", "1", "2", "3+"]
            share = lambda x: [np.mean(x == 0), np.mean(x == 1), np.mean(x == 2), np.mean(x >= 3)]
            xs = np.arange(4)
            ax.bar(xs - 0.2, np.array(share(cb)) * 100, 0.38, color=BLUE,
                   label=f"before (months −12…−2, n={len(cb):,})")
            ax.bar(xs + 0.2, np.array(share(ca)) * 100, 0.38, color=ORANGE,
                   label=f"after (loss month, +1; n={len(ca):,})")
            ax.set_yscale("log")
            ax.set_xticks(xs, cats)
            ax.set_xlabel(f"{unit} per zip-month", color=MUTED)
            ax.set_ylabel("% of zip-months" if j == 0 else "", color=MUTED)
            for x, (pb, pa) in enumerate(zip(share(cb), share(ca))):
                ax.text(x, max(pb, pa) * 100 * 1.3, f"{pb:.1%} → {pa:.1%}", ha="center",
                        fontsize=8, color=TEXT)
        else:
            lo, hi = np.percentile(np.r_[b, a], [0.5, 99.5])
            bins = np.logspace(np.log10(lo), np.log10(hi), 50) if log else np.linspace(lo, hi, 50)
            ax.hist(b, bins=bins, histtype="step", linewidth=2, color=BLUE, density=True,
                    label=f"before (median {np.median(b):.3g})")
            ax.hist(a, bins=bins, histtype="step", linewidth=2, color=ORANGE, density=True,
                    label=f"after (median {np.median(a):.3g})")
            if log:
                ax.set_xscale("log")
            ax.set_xlabel(unit, color=MUTED)
            ax.set_ylabel("density" if j == 0 else "", color=MUTED)
        ax.set_title(gname, loc="left", color=TEXT, fontsize=12)
        ax.legend(frameon=False, fontsize=8.5, loc="upper right", labelcolor=TEXT)
        style_axes(ax)

        ax = axes[1, j]
        d, text = _paired_stats(b, a, log)
        lim = np.percentile(np.abs(d), 99) or 1
        if log:
            ax.hist(d, bins=np.linspace(-lim, lim, 61), color=BLUE, edgecolor="white", linewidth=0.5)
            ax.set_xlabel("log(after / before)", color=MUTED)
        else:
            ax.hist(d, bins=np.linspace(-lim, lim, 61), color=BLUE, edgecolor="white", linewidth=0.5)
            ax.set_xlabel(f"after − before ({unit} per month)", color=MUTED)
        ax.set_yscale("log")
        ax.axvline(0, color=MUTED, linewidth=1)
        ax.text(0.98, 0.97, text, transform=ax.transAxes, ha="right", va="top", fontsize=8.5, color=TEXT,
                bbox=dict(facecolor="white", edgecolor=GRID, boxstyle="round,pad=0.4", alpha=0.92))
        ax.set_ylabel("zip-days (log scale)" if j == 0 else "", color=MUTED)
        style_axes(ax)
    fig.suptitle(name, x=0.01, ha="left", color=TEXT, fontsize=13)
    fig.text(0.01, 0.005, "Top: outcome distribution before vs. after. Bottom: each FEMA zip-day's own change. "
             "Rows from the same zip/event are not independent, so p-values are optimistic. "
             "All floods includes mixed-CRS rows.", fontsize=8.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print("saved", out)


WQP_CHECK_DAYS = 30          # window before/after the loss date (loss date excluded)
WQP_CHECK_MIN_N = 200        # skip parameters with fewer paired zip-days
WQP_LABELS = {
    "turbidity": "turbidity (NTU)", "tss": "total suspended solids (mg/L)",
    "ecoli": "E. coli (count/100 mL)", "fecal_coliform": "fecal coliform (count/100 mL)",
    "enterococcus": "enterococcus (count/100 mL)", "phosphorus": "phosphorus (mg/L as P)",
    "nitrogen": "total nitrogen (mg/L as N)", "nitrate_nitrite": "nitrate + nitrite (mg/L as N)",
    "nitrate": "nitrate (mg/L as N)",
}


def wqp_flood_windows(data_dir, days=WQP_CHECK_DAYS):
    """For each FEMA zip-day and WQP parameter: geometric mean of the zip's
    daily median values in the `days` days before and after the loss date
    (loss date excluded). Uses cumulative sums over (zip, day) keys."""
    wq = pd.read_csv(data_dir / WQP_ZIP_CSV, usecols=["ZIP_CODE", "date", "param", "median"],
                     dtype={"ZIP_CODE": "string"}, parse_dates=["date"])
    wq = wq[(wq["median"] > 0) & wq["ZIP_CODE"].str.fullmatch(r"\d{5}")]
    f = pd.read_csv(data_dir / FEMA_CSV, usecols=["reportedZipcode", "dateOfLoss", "crs_treat"],
                    dtype={"reportedZipcode": "string"}, parse_dates=["dateOfLoss"])
    f = f[(f["dateOfLoss"] >= f"{WQP_YEARS[0]}-02-01")
          & f["reportedZipcode"].str.fullmatch(r"\d{5}")].reset_index(drop=True)
    day = lambda t: (t - pd.Timestamp("1900-01-01")).dt.days.to_numpy()
    fkey = f["reportedZipcode"].astype(int).to_numpy() * 100_000
    fday = day(f["dateOfLoss"])
    out = {}
    for param, g in wq.groupby("param"):
        key = g["ZIP_CODE"].astype(int).to_numpy() * 100_000 + day(g["date"])
        order = np.argsort(key)
        key, logv = key[order], np.log(g["median"].to_numpy()[order])
        csum = np.r_[0, np.cumsum(logv)]

        def window(lo, hi):  # geometric mean over days [lo, hi] relative to loss
            a = np.searchsorted(key, fkey + fday + lo, "left")
            b = np.searchsorted(key, fkey + fday + hi, "right")
            n = b - a
            with np.errstate(invalid="ignore", divide="ignore"):
                return np.where(n > 0, np.exp((csum[b] - csum[a]) / np.maximum(n, 1)), np.nan)

        before, after = window(-days, -1), window(1, days)
        ok = np.isfinite(before) & np.isfinite(after)
        out[param] = (before[ok], after[ok], f.loc[ok, "crs_treat"].where(
            f.loc[ok, "crs_treat"].isin([0, 1])).to_numpy())
    return out


def wqp_flood_checks(data_dir, note=""):
    for param, (b, a, crs) in wqp_flood_windows(data_dir).items():
        if len(b) < WQP_CHECK_MIN_N:
            print(f"skip {param}: {len(b)} paired zip-days")
            continue
        plot_flood_check(f"Water Quality Portal: {WQP_LABELS.get(param, param)}, 30 days before vs. after "
                         f"a flood loss{note}", WQP_LABELS.get(param, param), b, a, crs,
                         FIGURES / f"check_wqp_{param}.png")


def _crs_of(df):
    """crs_treat as 1/0, NaN for mixed (0 < crs_treat < 1)."""
    return df["crs_treat"].where(df["crs_treat"].isin([0, 1])).to_numpy()


def check_data_nitrogen(data_dir=DATA_DIR):
    """Nitrogen (mg/L) within 30 days before vs after a loss, for zip-days
    with both. Returns before, after, crs (1/0/NaN) arrays."""
    df = pd.read_csv(data_dir / FINAL_CSV, usecols=["crs_treat", "Nitrogen 1 Month Before",
                                                    "Nitrogen 1 Month After"])
    df = df.dropna(subset=["Nitrogen 1 Month Before", "Nitrogen 1 Month After"])
    return (df["Nitrogen 1 Month Before"].to_numpy(), df["Nitrogen 1 Month After"].to_numpy(),
            _crs_of(df))


def check_data_sdwis(data_dir=DATA_DIR, pre_k=range(-12, -1), post_k=(0, 1)):
    """Health-based SDWIS violations per zip-month, months -12..-2 (before)
    vs the loss month and +1 (after), for FEMA zip-days 1992-2019 in zips
    served by a mapped community water system. Returns (pre, post, crs):
    pre/post are (n_months, n_zipdays) count arrays."""
    v = pd.read_csv(data_dir / SDWIS_ZIP_CSV, dtype={"ZIP_CODE": "string"})
    xw = pd.read_csv(data_dir / SDWIS_SYSTEMS_CSV, dtype={"ZIP_CODE": "string"})
    served = xw.groupby("ZIP_CODE")["pop_est"].sum()
    served = set(served[served > 0].index)
    v["mi"] = pd.PeriodIndex(v["month"], freq="M").astype("int64")
    v = v.set_index(["ZIP_CODE", "mi"])["n_hb_violations"]
    f = pd.read_csv(data_dir / FEMA_CSV, usecols=["reportedZipcode", "dateOfLoss", "crs_treat"],
                    dtype={"reportedZipcode": "string"}, parse_dates=["dateOfLoss"])
    f = f[(f["dateOfLoss"] >= "1992-01-01") & (f["dateOfLoss"] <= "2019-12-31")
          & f["reportedZipcode"].isin(served)]
    m0 = f["dateOfLoss"].dt.to_period("M").astype("int64").to_numpy()
    z = f["reportedZipcode"].to_numpy()
    get = lambda k: v.reindex(pd.MultiIndex.from_arrays([z, m0 + k])).fillna(0).to_numpy()
    pre = np.vstack([get(k) for k in pre_k])
    post = np.vstack([get(k) for k in post_k])
    return pre, post, _crs_of(f)


def check_data_blackmarble(data_dir=DATA_DIR):
    """Clear-sky nighttime light (nW/cm^2/sr), mean over days -14..-2 (>= 3
    clear days) vs days 0..7, for lit zips (median clear-day light >= 2 over
    all their days; selecting on the pre window would bias the change).
    Returns before, after, crs."""
    b = pd.read_csv(data_dir / BM_ZIP_CSV, usecols=["ZIP_CODE", "date", "ntl_hq", "hq_coverage"],
                    dtype={"ZIP_CODE": "string"}, parse_dates=["date"])
    b = b[b["hq_coverage"] >= BM_MIN_HQ_COVERAGE][["ZIP_CODE", "date", "ntl_hq"]]
    typical = b.groupby("ZIP_CODE")["ntl_hq"].median()
    b = b[b["ZIP_CODE"].isin(typical[typical >= BM_MIN_PRE_LIGHT].index)]
    f = pd.read_csv(data_dir / FEMA_CSV, usecols=["reportedZipcode", "dateOfLoss", "crs_treat"],
                    dtype={"reportedZipcode": "string"}, parse_dates=["dateOfLoss"])
    f = f[(f["dateOfLoss"] >= pd.Timestamp(BM_FIRST_DAY) + pd.Timedelta(days=BM_WINDOW))
          & (f["dateOfLoss"] <= "2020-08-31")].reset_index(drop=True)
    f["rid"] = f.index
    x = f[["rid", "reportedZipcode", "dateOfLoss"]].merge(pd.DataFrame({"k": np.arange(-14, 8)}), how="cross")
    x["date"] = x["dateOfLoss"] + pd.to_timedelta(x["k"], "D")
    x = x.merge(b.rename(columns={"ZIP_CODE": "reportedZipcode"}), on=["reportedZipcode", "date"])
    pre = x[x["k"] <= -2].groupby("rid")["ntl_hq"].agg(["mean", "count"])
    post = x[x["k"] >= 0].groupby("rid")["ntl_hq"].mean()
    ok = pre[pre["count"] >= 3].join(post.rename("post"), how="inner")
    g = f.set_index("rid").loc[ok.index]
    return ok["mean"].to_numpy(), ok["post"].to_numpy(), _crs_of(g)


PBJ_CHECK_COLUMNS = {"census": ("PBJ Mean Daily Census", "nursing-home residents (mean daily census)"),
                     "hprd": ("PBJ Nurse Hours per Resident-Day", "nurse hours per resident-day")}


def check_data_pbj(data_dir=DATA_DIR):
    """Nursing-home census and nurse hours per resident-day, 4 weeks before
    vs after the loss week. Returns {key: (before, after, crs)}."""
    df = pd.read_csv(data_dir / PBJ_FINAL_CSV, usecols=["crs_treat"] + [
        f"{c} {w}" for c, _ in PBJ_CHECK_COLUMNS.values() for w in ("4 Weeks Before", "4 Weeks After")])
    out = {}
    for key, (c, _) in PBJ_CHECK_COLUMNS.items():
        d = df.dropna(subset=[f"{c} 4 Weeks Before", f"{c} 4 Weeks After"])
        out[key] = (d[f"{c} 4 Weeks Before"].to_numpy(), d[f"{c} 4 Weeks After"].to_numpy(), _crs_of(d))
    return out


def flood_checks(data_dir):
    """Before/after flood checks for every outcome dataset that exists."""
    b, a, crs = check_data_nitrogen(data_dir)
    plot_flood_check("Nitrogen within 30 days before vs. after a flood loss (zip-days with both)",
                     "nitrogen (mg/L)", b, a, crs, FIGURES / "check_nitrogen.png")

    if (data_dir / SDWIS_ZIP_CSV).exists():
        pre, post, crs = check_data_sdwis(data_dir)
        plot_flood_check("Drinking-water health-based violations (SDWIS) before vs. after a flood loss, 1992–2019",
                         "health-based violations", pre.mean(0), post.mean(0), crs,
                         FIGURES / "check_sdwis.png", log=False,
                         counts=(pre.ravel(), post.ravel(), np.tile(crs, len(pre)),
                                 np.tile(crs, len(post))))

    if (data_dir / BM_ZIP_CSV).exists():
        b, a, crs = check_data_blackmarble(data_dir)
        plot_flood_check("Nighttime light (NASA Black Marble) before vs. after a flood loss, 2012–2020",
                         "clear-sky radiance (nW/cm²/sr)", b, a, crs, FIGURES / "check_blackmarble.png")

    if (data_dir / PBJ_FINAL_CSV).exists():
        for key, (b, a, crs) in check_data_pbj(data_dir).items():
            unit = PBJ_CHECK_COLUMNS[key][1]
            plot_flood_check(f"Nursing homes (CMS PBJ): {unit}, 4 weeks before vs. after a flood loss, 2017–2020",
                             unit, b, a, crs, FIGURES / f"check_pbj_{key}.png")

    # Water Quality Portal: every parameter, 30 days before vs after.
    if (data_dir / WQP_ZIP_CSV).exists():
        wqp_flood_checks(data_dir)


def plot(dataset):
    nitrogen = [c for _, b, a in NITROGEN_WINDOWS for c in (b, a)]
    df = pd.read_csv(dataset, usecols=nitrogen + CORNER_SUPPORT + ["crs_treat"] + CORR_COLUMNS
                     + [c for c, _, _ in CORNER_VARS if c not in CORNER_SUPPORT],
                     parse_dates=["dateOfLoss"])
    FIGURES.mkdir(parents=True, exist_ok=True)
    plot_distributions(df, FIGURES / "nitrogen_distributions.png")
    for days, before_col, after_col in NITROGEN_WINDOWS:
        plot_change(df, days, before_col, after_col,
                    FIGURES / f"nitrogen_change_{days // 30}month.png")
    _, before_col, after_col = NITROGEN_WINDOWS[0]
    plot_corner([("1 month before loss", BLUE, *corner_data(df, before_col)),
                 ("1 month after loss", ORANGE, *corner_data(df, after_col))],
                "Nitrogen before vs. after a flood loss, with zip covariates", [],
                FIGURES / "corner_nitrogen_1month.png")
    # CRS-treated vs untreated zip-days. crs_treat is the share of a zip-day's
    # claims in a CRS community; mixed rows (0 < share < 1) are left out.
    for side, col in (("before", before_col), ("after", after_col)):
        mixed = ((df["crs_treat"] > 0) & (df["crs_treat"] < 1)
                 & df[col].notna() & df[CORNER_SUPPORT].notna().all(axis=1)).sum()
        plot_corner([("CRS (crs_treat = 1)", AQUA, *corner_data(df, col, df["crs_treat"] == 1)),
                     ("no CRS (crs_treat = 0)", VIOLET, *corner_data(df, col, df["crs_treat"] == 0))],
                    f"CRS vs. no CRS: nitrogen 1 month {side} a flood loss",
                    [f"Mixed rows (0 < crs_treat < 1) excluded: {mixed}."],
                    FIGURES / f"corner_crs_1month_{side}.png")
    # All four together: color = CRS group, line style = before/after.
    sets, mixed = [], []
    for side, col, ls in (("before", before_col, "-"), ("after", after_col, "--")):
        for name, color, value in (("CRS", AQUA, 1), ("no CRS", VIOLET, 0)):
            sets.append((f"{name}, {side}", color,
                         *corner_data(df, col, df["crs_treat"] == value), ls))
        mixed.append(((df["crs_treat"] > 0) & (df["crs_treat"] < 1) & df[col].notna()
                      & df[CORNER_SUPPORT].notna().all(axis=1)).sum())
    sets = [sets[0], sets[2], sets[1], sets[3]]  # group legend by CRS status
    plot_corner(sets, "CRS vs. no CRS, nitrogen 1 month before and after a flood loss",
                ["Color: CRS status. Line style: solid = before, dashed = after.",
                 f"Mixed rows (0 < crs_treat < 1) excluded: {mixed[0]} before / {mixed[1]} after."],
                FIGURES / "corner_crs_1month.png", medians=False)
    plot_correlations(df, FIGURES / "correlations_1month.png")
    data_dir = Path(dataset).parent
    if (data_dir / SDWIS_ZIP_CSV).exists():
        plot_sdwis_event_study(data_dir, FIGURES / "sdwis_event_study.png")
    if (data_dir / BM_ZIP_CSV).exists():
        plot_blackmarble_event_study(data_dir, FIGURES / "blackmarble_event_study.png")
    if (data_dir / PBJ_WEEKLY).exists():
        plot_pbj_event_study(data_dir, FIGURES / "pbj_event_study.png")
    flood_checks(data_dir)


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["download", "prism", "download-wqp", "wqp", "sdwis", "blackmarble", "build-sdwis", "build-pbj",
                                            "build", "plot", "all"])
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--out", type=Path, default=None,
                        help=f"final dataset (default: <data-dir>/{FINAL_CSV})")
    parser.add_argument("--start", type=int, default=PRISM_YEARS[0], help="first PRISM year")
    parser.add_argument("--end", type=int, default=PRISM_YEARS[1], help="last PRISM year")
    parser.add_argument("--save-intermediate", action="store_true",
                        help="also write the dataset after each step")
    args = parser.parse_args()
    out = args.out or args.data_dir / FINAL_CSV

    if args.command in ("download", "all"):
        download_prism(args.data_dir, args.start, args.end)
    if args.command in ("prism", "all"):
        compute_prism_zcta(args.data_dir, args.start, args.end)
    if args.command == "download-wqp":
        download_wqp(args.data_dir)
    if args.command == "wqp":
        compute_wqp_zcta(args.data_dir)
    if args.command == "sdwis":
        compute_sdwis_zcta(args.data_dir)
    if args.command == "blackmarble":
        compute_blackmarble(args.data_dir)
    if args.command in ("build", "all"):
        build(args.data_dir, out, args.save_intermediate)
    if args.command == "build-pbj":
        build(args.data_dir, args.out or args.data_dir / PBJ_FINAL_CSV,
              args.save_intermediate, outcome="pbj")
    if args.command == "build-sdwis":
        build(args.data_dir, args.out or args.data_dir / SDWIS_FINAL_CSV,
              args.save_intermediate, outcome="sdwis")
    if args.command in ("plot", "all"):
        plot(out)


if __name__ == "__main__":
    main()
