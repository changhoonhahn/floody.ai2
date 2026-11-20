# Data sources

Every input used to build the AI2 flood datasets: where it comes from, which
version was used, and how to obtain it. No data are stored in this
repository. All inputs live in a data directory, by default
`/Users/chang/data/ai2/` (set `AI2_DATA_DIR`), laid out as listed below.
"Automated" means a command in this folder downloads it. "Manual" means it
must be obtained and placed by hand.

Snapshot dates matter: several sources are revised by their publishers, so
re-downloading later can give slightly different files. Use the dates below
to identify the versions used here.

| # | Source | Expected path in data dir | How obtained | Version used |
|---|---|---|---|---|
| 1 | FEMA NFIP redacted claims | `fema.csv` | Manual | OpenFEMA v1 snapshot, `asOfDate` 2020-08-23 |
| 2 | Nitrogen water-quality readings | `Nitrogen_2007-2021_national_with_ZIP.csv` | Manual (provided file) | 2007–2021 |
| 3 | First Street Foundation flood risk | `fsf/01_DATA/Climate_Risk_Statistics/v1.2/` | Manual | v1.2 |
| 4 | American Community Survey (Social Explorer) | `acs_census/` | Manual | 5-year 2008–12, 2012–16, 2016–20 |
| 5 | Census 2020 ZCTA boundaries | any path, set `AI2_ZCTA_SHP` | Manual (one download) | TIGER/Line 2022, ZCTA520 |
| 6 | PRISM monthly precipitation | `prism_ppt/` | Automated: `ai2_dataset.py download` | AN 4 km, downloaded 2026-10-15 |
| 7 | Water Quality Portal | `wqp/` | Automated: `ai2_dataset.py download-wqp` | downloaded 2026-10-15 … 10-29 |
| 8 | EPA SDWIS (ECHO SDWA download) | `sdwis/SDWA_latest_downloads.zip` | Manual (one download) | snapshot 2026Q3, file dated 2026-10-14 |
| 9 | EPA community water system service areas | `sdwis/3_0/Service_Areas_V_3_0.gpkg` | Manual (one download + unzip) | v3.0, March 2026 |
| 10 | NASA Black Marble VNP46A2 | `blackmarble/` (streamed, then deleted) | Automated: `ai2_dataset.py blackmarble` (Earthdata login) | collection 2 |
| 11 | CMS Payroll-Based Journal (PBJ) | `pbj/` | Automated: `pbj_download.py` | catalog snapshot 2026-10-15 |
| 12 | NOAA Storm Events (explored, not in the pipeline) | `stormevents/` | Manual | 1996–2026, files dated 2026 |

---

## 1. FEMA NFIP redacted claims: `fema.csv`

- **What:** one row per NFIP flood-insurance claim. It has 2,478,927 rows
  and 40 columns, including `dateOfLoss`, `reportedZipcode`, `countyCode`,
  `communityRatingSystemDiscount` (CRS class), payments, coverage and
  `policyCount`.
- **Source:** OpenFEMA "FIMA NFIP Redacted Claims" (v1). Every row has
  `asOfDate` = 2020-08-23, so the file covers losses through 2020-08.
- **Availability:**
  - OpenFEMA has since retired v1/v2. The current release is NFIP Redacted
    Claims v3:
    [dataset page](https://www.fema.gov/openfema-data-page/nfip-redacted-claims-v3),
    API `https://www.fema.gov/api/open/v3/NfipClaims`, and a parquet/CSV
    bulk download on that page.
  - v3 is revised continuously and renames columns. It will **not**
    reproduce the 2020 snapshot exactly, so keep the original `fema.csv`.
- **Used by:** `fema_grouped.py`, which writes `ai2.fema.trimmed.csv` and
  `ai2.fema.grouped.csv`.
- **Caveat:** 37% of claims have no CRS class. `fema_grouped.py` codes these
  as class 11 and `crs_treat = 0`, so "not CRS" includes "unknown".

## 2. Nitrogen readings: `Nitrogen_2007-2021_national_with_ZIP.csv`

- **What:** 702,244 water-quality readings with characteristic "Nitrogen",
  2007–2021. Columns include `ActivityStartDate`,
  `MonitoringLocationIdentifier`, `Latitude/Longitude`, `ZipCode`,
  `ResultMeasureValue`, `ResultMeasure/MeasureUnitCode` and `ProviderName`
  (NWIS or STORET).
- **Source:** a provided file. It is a Water Quality Portal extract (USGS
  NWIS + EPA STORET) with a `ZipCode` column added. The script that made it
  (extract query and zip assignment) is not available.
- **Approximate reproduction:** the Water Quality Portal step (source 7)
  downloads the same characteristic ("Nitrogen") for all years and assigns
  sites to 2020 ZCTAs.
- **Used by:** `ai2_dataset.py build` (nitrogen columns: unit conversion to
  mg/L, same-day averaging, ±30/60-day windows).

## 3. First Street Foundation flood risk: `fsf/`

- **What:** zip-level flood-risk statistics, v1.2. 32,162 zips with counts
  and shares of properties at risk (FEMA special flood hazard area; FSF 5-,
  100- and 500-year scenarios for 2020 and 2050) and average Flood Factor
  scores.
- **Files used:**
  - `fsf/01_DATA/Climate_Risk_Statistics/v1.2/Zip_level_risk_FEMA_FSF_v1.2.csv`;
  - the codebook,
    `.../v1.2/Supporting_Documentation/FSF_AggregateDataCodebook_v1.2.csv`.
- **Source:** First Street Foundation aggregate flood-risk statistics, v1.2
  (file dated 2021-04-21), obtained as a data package (<https://firststreet.org/>).
- **License:** Creative Commons Attribution-NonCommercial-ShareAlike 4.0;
  see `Supporting_Documentation/LICENSE.txt`.
- **Used by:** `ai2_dataset.py build` (`fsf_` columns, joined by zip).

## 4. American Community Survey: `acs_census/`

- **What:** ACS 5-year estimates by ZCTA, exported from Social Explorer
  (<https://www.socialexplorer.com/>; subscription), with 68 `SE_*` columns:
  population, race, education, income, housing, poverty and more.
- **Files used:**
  - `ACS2008_12socialexplorer.csv` (2008–2012);
  - `ACS2012_16socexplnew.csv` (2012–2016);
  - `ACS2016_20new.csv` (2016–2020).
- **Not used:** `ACS2016_20socialexplorer.csv`, which is byte-identical to
  the 2012–16 file.
- **Format:** Social Explorer two-header CSV (descriptions, then codes).
- **Without Social Explorer:** the same tables come from the Census Bureau's
  ACS 5-year detailed tables (data.census.gov or the Census API) at ZCTA
  level. Column codes would differ.
- **Used by:** `ai2_dataset.py build` (`acs_` columns, chosen by loss year).

## 5. Census 2020 ZCTA boundaries

- **What:** TIGER/Line 2022 ZCTA polygons, 2020 ZCTAs, 33,791 features.
- **Download:**
  <https://www2.census.gov/geo/tiger/TIGER2022/ZCTA520/tl_2022_us_zcta520.zip>.
  Unzip it and set `AI2_ZCTA_SHP` to `tl_2022_us_zcta520.shp`; the default
  path is `/Users/chang/data/noah/floody/tl_2022_us_zcta520/`.
- **Used by:** every zip-level aggregation (PRISM, Water Quality Portal,
  SDWIS, Black Marble).

## 6. PRISM monthly precipitation: `prism_ppt/`

- **What:** PRISM AN 4 km (2.5 arc-minute) monthly precipitation grids for
  CONUS, as `prism_ppt_us_25m_YYYYMM.zip`, 1973–2020 (576 files, 1.4 GB).
- **Source:** PRISM Group, Oregon State University,
  <https://data.prism.oregonstate.edu/time_series/us/an/4km/ppt/monthly/YYYY/>.
  Free, no login.
- **Get it:** `python bin/data/ai2_dataset.py download`.
- **Processed by:** `ai2_dataset.py prism`, which writes
  `rainfall_PRISM_zcta2020.zipcode_year_month.csv`.
- **Revisions:** PRISM revises grids, so a later download can differ
  slightly.
- **Not used:** an older zip-level table, `rainfall_PRISM.zipcode_year_month.csv`
  (from `../noah`), which is missing about 6,500 small zip codes.

## 7. Water Quality Portal: `wqp/`

- **What:** discrete water-quality results and site locations, 1990–2024,
  for stream, lake/reservoir, estuary and ocean sites. Characteristics:
  Turbidity, Total suspended solids, Escherichia coli, Fecal Coliform,
  Enterococcus, Phosphorus, Nitrogen, Inorganic nitrogen (nitrate and
  nitrite), and Nitrate.
- **Source:** Water Quality Portal (USGS NWIS + EPA WQX/STORET),
  <https://www.waterqualitydata.us/>, legacy `/data/Result/search` (profile
  `narrowResult`) and `/data/Station/search`. Free, no login.
- **Get it:** `python bin/data/ai2_dataset.py download-wqp`.
  - It downloads per state and 5-year chunk, with a one-year fallback for
    site requests the server resets, and resumes if interrupted.
  - Downloaded 2026-10-15 … 10-29: 364 result files and all site chunks
    except Oregon 2013, which the server rejected.
- **Processed by:** `ai2_dataset.py wqp`, which writes
  `wqp_zcta2020.zipcode_day.csv`.
- **Caveats:**
  - USGS data after March 2024 is partly only in the newer WQX 3.0
    profiles.
  - WQP content changes as agencies upload.

## 8. EPA SDWIS: `sdwis/SDWA_latest_downloads.zip`

- **What:** the Safe Drinking Water Information System bulk download (11
  CSV tables): public water systems, geographic areas, and violations and
  enforcement (one row per violation × enforcement action).
- **Source:** EPA ECHO,
  <https://echo.epa.gov/files/echodownloads/SDWA_latest_downloads.zip>
  (558 MB). The file used is dated 2026-10-14 (submission quarter 2026Q3).
- **Revisions:** ECHO replaces this file every quarter, so later downloads
  will differ.
- **Used by:** `ai2_dataset.py sdwis`, which writes
  `sdwis_zcta2020.zipcode_month.csv` and `sdwis_cws_zcta2020.csv`.

## 9. EPA community water system service areas: `sdwis/3_0/`

- **What:** service-area polygons for about 44,600 community water systems,
  keyed by PWSID. Version 3.0 (CWS layer identical to v2.1).
- **Source:** EPA Office of Research and Development,
  <https://github.com/USEPA/ORD_SAB_Model> (download
  `Version_History/PWS_Boundaries_Latest.zip`, 570 MB). Unzip
  `3_0/Service_Areas_V_3_0.gpkg` into `sdwis/`.
- **Why needed:** SDWIS's own `ZIP_CODE_SERVED` is filled for only about 2%
  of active systems.
- **Used by:** `ai2_dataset.py sdwis` (polygon overlay with ZCTAs).

## 10. NASA Black Marble VNP46A2: `blackmarble/`

- **What:** daily moonlight- and BRDF-corrected VIIRS nighttime radiance,
  500 m, in 10°×10° HDF5 tiles of about 21 MB each. Collection 2, from
  2012-01-19.
- **Source:** NASA LAADS DAAC. Granules are found with NASA CMR
  (<https://cmr.earthdata.nasa.gov/search/granules.json>,
  `short_name=VNP46A2`) and downloaded from
  `https://data.laadsdaac.earthdatacloud.nasa.gov/prod-lads/VNP46A2/…`.
  Product page: <https://blackmarble.gsfc.nasa.gov/VNP46A2.html>.
- **Access:** a free NASA Earthdata login is required. Put
  `machine urs.earthdata.nasa.gov login <user> password <pass>` in
  `~/.netrc` (permissions 600).
- **Get and process:** `ai2_dataset.py blackmarble`.
  - It streams only the tile-days within ±14 days of flood dates with ≥ 25
    claims in a zip-day, 2012–2020: 7,734 tile-days, about 160 GB
    transferred.
  - Each tile is averaged over ZCTAs, then deleted.
  - The output is `blackmarble_zcta2020.zipcode_day.csv.gz`. NASA had no
    granule for 46 of the 7,734 tile-days.

## 11. CMS Payroll-Based Journal (PBJ): `pbj/`

- **What:** daily nursing-home nurse staffing and resident census by
  facility, 2017Q1–2026Q1 (37 quarters).
- **Source:** CMS public files (no restricted data).
  - [PBJ Daily Nurse Staffing](https://data.cms.gov/quality-of-care/payroll-based-journal-daily-nurse-staffing).
  - Provider of Services files (December 2017 and 2018).
  - 29 CMS nursing-home provider archive snapshots, used for facility zip
    codes.
- **Exact inputs:** the 68 files listed with URLs in
  `pbj_sources/manifest.json`. `pbj_sources/checksums.json` has their
  SHA-256 hashes, and `pbj_sources/provider_archive_index.json` is the saved
  archive index.
- **Get and process:** `pbj_download.py`, then `pbj_zipcode.py`, then
  `pbj_validate.py`. Set `PBJ_DATA_DIR`; the default is
  `/Users/chang/data/ai2/pbj`.
  - Without the saved CMS catalog, the downloader uses the shipped frozen
    manifest.
  - Output: `pbj/pbj_zip_weekly.csv.gz` and the daily/weekly partitions.
  - The full method is in the PBJ data folder's `README.md`.
- **Used by:** `ai2_dataset.py build-pbj` and the PBJ event study.

## 12. NOAA Storm Events (explored, not in the pipeline): `stormevents/`

- **What:** NCEI Storm Events Database details, locations and fatalities
  files, 1996–2026: 93 files, 351 MB, about 191,000 flood-type events.
- **Source:** <https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/>
  (`StormEvents_{details,locations,fatalities}-ftp_v1.0_dYYYY_c*.csv.gz`).
  Free, no login. Files are re-issued with new `c` (creation) dates.
- **Status:** used only for a one-off check of overlap with the FEMA claims,
  recorded in `notes/candidate_outcome_datasets.md`. No script in this folder depends on it.
