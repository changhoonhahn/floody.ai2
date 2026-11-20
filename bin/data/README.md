# AI2 flood datasets

zip-code-level flood datasets used to study the effect of FEMA's Community
Rating System (CRS) on non-economic flood outcomes.

| File | Contents |
|---|---|
| `README.md` | this file: setup, run order, outputs |
| `SOURCES.md` | every input data source: origin, version, access, expected path |
| `METHODS.md` | detailed processing steps, choices, match rates and checks for each step and figure |
| `fema_grouped.py` | `fema.csv` → `ai2.fema.trimmed.csv` → `ai2.fema.grouped.csv` (FEMA claims by zip code and loss date) |
| `ai2_dataset.py` | the main pipeline: downloads, zip-code aggregation of every source, dataset builds, figures |
| `pbj_download.py`, `pbj_zipcode.py`, `pbj_validate.py`, `test_pbj_zipcode.py` | CMS PBJ nursing-home panel (download, zip-code aggregation, validation, unit tests) |
| `pbj_sources/` | frozen PBJ source list (download manifest, provider archive index, SHA-256 checksums); metadata only |
| `../../nb/data/flood_check_*.ipynb` | before/after flood checks per dataset (all floods, CRS, non-CRS) |
| `candidate_outcome_datasets.md` | dataset search, before/after suitability check, NOAA Storm Events overlap |

## Output catalogs

| File | Rows | Description |
|---|---|---|
| `ai2.fema.trimmed.csv` | ~1.87M claims | claims with a zip code and a non-zero payment; `crs_treat` added |
| `ai2.fema.grouped.csv` | 336,953 | one row per (zip code, loss date), 1973–2020 |
| `rainfall_PRISM_zcta2020.zipcode_year_month.csv` | 19.5M | monthly precipitation per 2020 ZCTA, 1973–2020 |
| `ai2.fema.grouped.nitro.fsf.acs.prism.csv` | 336,953 × 119 | FEMA + nitrogen windows + FSF + ACS + PRISM |
| `ai2.fema.grouped.sdwis.fsf.acs.prism.csv` | 336,953 × 127 | FEMA + SDWIS violation windows + FSF + ACS + PRISM |
| `ai2.fema.grouped.pbj.fsf.acs.prism.csv` | 336,953 × 125 | FEMA + PBJ week windows + FSF + ACS + PRISM |
| `*.acs_columns.csv` | 69 | dictionary of `acs_` column codes |
| `sdwis_zcta2020.zipcode_month.csv`, `sdwis_cws_zcta2020.csv` | 387,957; 88,849 | violations by zip code and month; water system ↔ ZCTA crosswalk |
| `blackmarble_zcta2020.zipcode_day.csv.gz` | 23.1M | nighttime light per ZCTA and day, around large floods, 2012–2020 |
| `wqp_zcta2020.zipcode_day.csv` | 10.3M | water quality per ZCTA, day and parameter, 1990–2024 |
| `pbj/pbj_zip_weekly.csv.gz` | 4.3M | nursing-home census and staffing per zip code and week, 2017–2026 |
