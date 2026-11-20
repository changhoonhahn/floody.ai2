# Methods and statistics

Detailed record of every processing step, choice, match rate and check for
the datasets built by `ai2_dataset.py` (moved here from the original
`caus.ai2/bin/README.md`). Paths such as `/Users/chang/data/ai2/` are the
defaults; see `README.md` for overriding them. Figures referenced here are
written to `figures/` at the repository root.


`ai2_dataset.py` builds the AI2 FEMA flood-claims dataset. It is a single
script with several commands. Data lives in `/Users/chang/data/ai2/`; override
it with `--data-dir`.

```bash
python bin/data/ai2_dataset.py build                       # final dataset (~40 s)
python bin/data/ai2_dataset.py plot                        # nitrogen figures in figures/
python bin/data/ai2_dataset.py download                    # PRISM grids, 1973–2020 (~25 min, 1.4 GB)
/opt/homebrew/Caskroom/miniconda/base/envs/ai2-geo/bin/python bin/data/ai2_dataset.py prism   # ~3 min

# Zip-level outcome tables (stand-alone, not yet merged into the final dataset)
python bin/data/ai2_dataset.py download-wqp                # Water Quality Portal, 1990–2024 (hours)
/opt/homebrew/Caskroom/miniconda/base/envs/ai2-geo/bin/python bin/data/ai2_dataset.py wqp      # zip × day
/opt/homebrew/Caskroom/miniconda/base/envs/ai2-geo/bin/python bin/data/ai2_dataset.py sdwis    # zip × month (~2 min)
```

`prism`, `wqp` and `sdwis` need the geospatial packages in the `ai2-geo` conda
env.

`all` runs download → prism → build → plot. The geospatial packages in
`ai2-geo` are geopandas, rasterio, exactextract and scipy. `build` and `plot` run in the base Python, which needs pandas and
matplotlib. `--save-intermediate` also writes the dataset after each `build`
step.

## Output

`ai2.fema.grouped.nitro.fsf.acs.prism.csv` has 336,953 rows × 119 columns.
One row is one (zip code, date of loss).

| Columns | Count | Source |
|---|---|---|
| `reportedZipcode` … `totalTotalInsuranceCoverage` | 12 | FEMA NFIP claims, grouped (`ai2.fema.grouped.csv`, see the data README) |
| `Nitrogen {1 Month, 2 Months} {Before, After}` | 4 | USGS/EPA water-quality nitrogen, mg/L |
| `fsf_*` | 32 | First Street Foundation zip-level flood risk, v1.2 |
| `acs_period`, `acs_SE_*` | 69 | ACS 5-year census estimates by ZCTA |
| `prism_MEAN`, `prism_NCELLS` | 2 | PRISM monthly precipitation |

`ai2.fema.grouped.nitro.fsf.acs.prism.acs_columns.csv` maps each `acs_` code
to its description.

Coverage of the 336,953 rows:

| Step | Rows matched | Zips matched (of 24,615) |
|---|---|---|
| Nitrogen, 1 month before / after / both | 8,064 / 7,481 / 4,266 | 1,573 / 1,553 / 943 |
| Nitrogen, 2 months before / after / both | 12,543 / 11,303 / 8,647 | |
| FSF | 317,201 (94.1%) | 20,523 |
| ACS | 323,348 (96.0%) | 20,934 |
| PRISM | 319,616 (94.9%) | 20,867 |

The upstream steps, `fema.csv` → `ai2.fema.trimmed.csv` →
`ai2.fema.grouped.csv`, were done with one-off scripts that were not saved.
`/Users/chang/data/ai2/README.md` describes them.

---

## SDWIS variant (`build-sdwis`)

```bash
python bin/data/ai2_dataset.py build-sdwis   # needs sdwis_* tables from the `sdwis` command (~45 s)
```

This writes `ai2.fema.grouped.sdwis.fsf.acs.prism.csv` (336,953 rows × 127
columns) and its `.acs_columns.csv` dictionary. It is the same build as
above, with the four nitrogen columns replaced by SDWIS drinking-water
violations. FSF, ACS and PRISM are identical.

**Violation columns.** `SDWIS {HB, Microbial, Tier1} Violations {window}`
count new violations, by start month, in the community water systems
serving the zip:
- `HB` = health-based;
- `Microbial` = health-based in rule group 100;
- `Tier1` = health-based with an acute public notice.

The windows, in calendar months relative to the loss month:

| Window | Months | Value |
|---|---|---|
| `Loss Month` | 0 | count |
| `1 Month After` | +1 | count |
| `Rest (per month)` | −12…−1 and +2…+12 | **average per month**, so it is on the same scale as the other two |

The loss month and the month after are where the flood spike is (see
`sdwis_event_study.png`). `Rest` is the zip's usual level around the event.

**Values.**
- **0:** the zip is served by a mapped community water system and no
  violation began.
- **NaN:** the zip has no mapped system (20,005 rows), or the month falls
  outside 1991-01 … the last SDWIS month (2026-09).
- `Rest` averages only over months inside that range. It needs at least 12
  such months; the count used is in `sdwis_rest_months`.

**Other columns.**
- `sdwis_pop_served_est`: estimated population of the zip served by
  community water systems.
- `sdwis_n_systems`: number of systems serving the zip.

**Coverage, by `crs_treat`.** Mixed means 0 < `crs_treat` < 1.

| Subset | Rows | crs=1 | crs=0 | mixed | Zips | Zips ever crs=1 | Zips ever crs=0 |
|---|---|---|---|---|---|---|---|
| All FEMA rows | 336,953 | 126,259 | 196,145 | 14,549 | 24,615 | 9,200 | 20,017 |
| SDWIS data in all three windows | 234,398 | 91,886 | 132,388 | 10,124 | 18,720 | 6,089 | 15,296 |
| + FSF/ACS/PRISM | 230,065 | 91,361 | 128,632 | 10,072 | 18,272 | 5,988 | 14,927 |
| + violation in loss month | 9,390 | 3,204 | 5,693 | 493 | 3,284 | 1,081 | 2,357 |
| + violation in month after | 8,643 | 2,927 | 5,301 | 415 | 3,049 | 1,008 | 2,192 |
| + any violation in the rest of ±12 months | 69,635 | 24,230 | 42,212 | 3,193 | 10,146 | 3,286 | 7,878 |

**Raw mean health-based violations per row per month** (rows with
FSF/ACS/PRISM). These are not adjusted for state, season or repeat events;
see the event study for an adjusted comparison.

| | Loss month | Month after | Rest |
|---|---|---|---|
| crs=0 | 0.0587 | 0.0567 | 0.0527 |
| crs=1 | 0.0424 | 0.0393 | 0.0333 |

## PBJ variant (`build-pbj`)

```bash
python bin/data/ai2_dataset.py build-pbj     # needs /Users/chang/data/ai2/pbj/ (~45 s)
```

This writes `ai2.fema.grouped.pbj.fsf.acs.prism.csv` (336,953 rows × 125
columns) and its `.acs_columns.csv` dictionary. It is the same build, with
the nitrogen columns replaced by nursing-home census and staffing from the
CMS Payroll-Based Journal (PBJ) panel in `pbj/`.
- That panel is a separate, already-validated dataset by facility mailing
  ZIP, 2017-01 … 2026-03. Its processing scripts are `bin/data/pbj_*.py`, and the
  details are in `pbj/README.md`.
- I re-verified all 204 transferred files against `transfer_integrity.json`
  on 2026-10-29: no mismatches.

**Columns.** Windows are Monday-start weeks relative to the week containing
the loss date: `4 Weeks Before` (−4…−1), `Loss Week` (0) and `4 Weeks After`
(+1…+4).

| Column | Meaning |
|---|---|
| `PBJ Mean Daily Census {window}` | Resident-days / days in the window: the average number of nursing-home residents in the zip |
| `PBJ Nurse Hours per Day {window}` | Total nurse hours (RN + LPN + aides) / days |
| `PBJ Nurse Hours per Resident-Day {window}` | Sum of hours / sum of eligible resident-days (ratio of sums) |
| `pbj_n_facilities` | Average number of reporting facilities in the 4 weeks before |

**Missing values.** Only complete-reporting weeks are used. A window is NaN
unless every one of its weeks is complete. It is also NaN if the zip has no
reporting nursing home, or if the window falls before 2017.

**Coverage, by `crs_treat`.** FEMA claims end in August 2020, so the overlap
is 2017-01 … 2020-08.

| Subset | Rows | crs=1 | crs=0 | mixed | Zips | Zips ever crs=1 | Zips ever crs=0 |
|---|---|---|---|---|---|---|---|
| All FEMA rows | 336,953 | 126,259 | 196,145 | 14,549 | 24,615 | 9,200 | 20,017 |
| Loss date 2017+ | 30,774 | 12,044 | 17,433 | 1,297 | 9,434 | 3,120 | 6,748 |
| PBJ before, loss week and after | 14,679 | 5,725 | 8,283 | 671 | 4,212 | 1,432 | 3,029 |
| + FSF/ACS/PRISM | 14,586 | 5,712 | 8,203 | 671 | 4,185 | 1,427 | 3,007 |
| + ≥ 25 claims that day | 633 | 252 | 145 | 236 | 301 | 147 | 76 |

In the usable rows, the median zip has 1 nursing home, a median census of
126 residents, and 3.7 nurse hours per resident-day.

## 1. Nitrogen

Source: `Nitrogen_2007-2021_national_with_ZIP.csv`, 702,244 readings.

1. **Zip codes.** `ZipCode` is a float-like string (`"47231.0"`). The script
   strips `.0` and zero-pads to 5 digits.
2. **Numbers.** `ResultMeasureValue` is coerced to float.
   - Detection-limit and annotation strings keep their stated number:
     `"<0.245"` → 0.245, `"[0.026]"` → 0.026, `"300(A)"` → 300.
   - `"0,8"` is read as a decimal comma. `"1,180"` is read as a thousands
     separator.
   - `"ND"`, `"non-detect"`, `"BDL"` and similar become NaN.
3. **Units → mg/L.** Only units for a concentration in water are kept:

   | Unit | Factor | Note |
   |---|---|---|
   | `mg/L`, `mg/l`, `mg N/l******` | 1 | |
   | `ppm` | 1 | 1 ppm in water ≈ 1 mg/L |
   | `ug/L`, `ppb` | 0.001 | |
   | `umol/L` | 0.0140067 | Assumed µmol of N per L |

   Dropped:
   - sediment units: `mg/kg`, `%`, `% by wt`;
   - gas units: `cm3/g`, `% by vol`;
   - amounts with no volume: `ug`, `umol`;
   - non-nitrogen measures: `micron`, `uS/cm`, `NTU`, `MPN/100mL`,
     `#/100mL`;
   - readings with no unit.

   This leaves 632,187 readings. The 60 negative values are dropped. There
   is no upper cutoff: a few test-hole well readings around 790,000 mg/L
   remain in the source, but none of them land in the output, where the
   maximum is 637 mg/L.
4. **Same zip, same day → mean.** All readings for one zip code and day,
   across stations and repeat samples, are averaged with equal weight. This
   gives 321,344 zip-day values. Before this step, `merge_asof` picked one of
   several tied readings arbitrarily.
5. **Nearest reading within a window.** `merge_asof` is run by zip code:
   backward for Before, forward for After, with a 30-day window and then a
   60-day window.
   - **Readings dated on `dateOfLoss` are used for neither side**
     (`allow_exact_matches=False`). A reading has a date but no time of day,
     so it cannot be placed before or after the loss.
   - "1 month" is a fixed 30 days and "2 months" a fixed 60 days.
   - The two windows are independent lookups. The 2-month value equals the
     1-month value whenever a reading exists within 30 days.
   - Nitrogen data covers 2007–2021. Losses before about Dec 2006 cannot
     match.

## 2. FSF flood risk

Source: `fsf/01_DATA/Climate_Risk_Statistics/v1.2/Zip_level_risk_FEMA_FSF_v1.2.csv`,
32,162 zips with one row each.

- The script zero-pads `zipcode`, which is stored as an integer
  (`1001` → `01001`). It then prefixes every column with `fsf_`, drops the
  duplicate `fsf_zipcode`, and left-joins on zip.
- **The values are static:** one snapshot per zip, covering 2020 and
  projected 2050 scenarios. The same values repeat for every loss date,
  including losses from the 1970s.
- **Column meanings** are in
  `fsf/.../v1.2/Supporting_Documentation/FSF_AggregateDataCodebook_v1.2.csv`.
  - `count_*` and `pct_*` give the properties at risk: in a FEMA special
    flood hazard area (`fema_sfha`), or flooded in the FSF 5-, 100- or
    500-year scenario (`fs_risk_<year>_<rp>`).
  - `avg_risk_score_*` is the average Flood Factor, from 1 (minimal) to 10.
  - `count_floodfactor1`–`10` give the number of properties at each Flood
    Factor.
- **Unmatched rows (5.9%):**
  - Puerto Rico, the Virgin Islands, Hawaii, Alaska and Guam, which FSF does
    not cover;
  - 3,726 contiguous-US zips that are not in FSF, probably PO-box or retired
    zip codes.

## 3. ACS census

Source: `acs_census/`, Social Explorer ZCTA exports with 33,120 ZCTAs and 68
`SE_*` columns each.

| Period | File |
|---|---|
| 2008–2012 | `ACS2008_12socialexplorer.csv` |
| 2012–2016 | `ACS2012_16socexplnew.csv` |
| 2016–2020 | `ACS2016_20new.csv` |

`ACS2016_20socialexplorer.csv` is **not used**: it is byte-identical to the
2012–2016 file.

- **Format.** The first row holds descriptions and the second row codes. The
  script keeps `Geo_ZCTA5` and the `SE_*` value columns.
- **Period by loss year:**

  | Loss year | Period | Rows |
  |---|---|---|
  | ≤ 2012, including **all losses before 2008** | 2008–2012 | 277,843 |
  | 2013–2016 | 2012–2016 | 28,336 |
  | 2017–2020 | 2016–2020 | 30,774 |

  The shared end years 2012 and 2016 go to the earlier period. Its survey
  years are before or during the loss year, so the data describes the area
  before the flood.
- **Join.** Left join on (zip = ZCTA, period). The columns are named
  `acs_<code>`, plus `acs_period`. Codes are kept rather than descriptions
  because some descriptions repeat; see the `acs_columns.csv` dictionary.
- **Caveats:**
  - **67% of rows (losses before 2008) get census data from after the
    loss.**
  - **Income columns are in each period's end-year dollars and are not
    inflation-adjusted:** `SE_A14006`, `SE_A14007_*`, `SE_A14024` and
    `SE_A14026_*`.
  - ZCTAs approximate zip codes, so PO-box and single-building zips have no
    ZCTA. The Virgin Islands are not covered.

## 4. PRISM precipitation

### Why the precipitation was rebuilt

The original zip-level table, `rainfall_PRISM.zipcode_year_month.csv`, was
probably made with ArcGIS "Zonal Statistics as Table". That method only
counts grid cells whose *center* falls inside a zip polygon. Zips smaller
than about one 4 km PRISM cell, or thin ones, get no row at all.

As a result, 6,526 ZCTAs were missing, with a median area of 3.9 km² against
123 km² for those present. These included residential zips in flood-heavy
areas, such as 70124 (New Orleans) and 77024 (Houston). Only 85% of the
1990–2020 losses matched.

The table also covered only 1990–2020.

### Download

The `download` command fetches PRISM AN monthly precipitation, 4 km
(2.5 arcmin), CONUS, as `prism_ppt_us_25m_YYYYMM.zip`. The source is
`https://data.prism.oregonstate.edu/time_series/us/an/4km/ppt/monthly/YYYY/`.

- Files go to `prism_ppt/`: 576 files for 1973–2020, 1.4 GB.
- Valid zips that are already present are skipped, so re-running resumes the
  download.
- The script pauses 0.5 s between requests.
- The grids are NAD83 geographic (EPSG:4269), 1405 × 621 cells, with nodata
  −9999, and every month is checked to be on the same grid.

### Zip-code averages

The `prism` command averages each month over the 2020 Census ZCTA polygons
(`/Users/chang/data/noah/floody/tl_2022_us_zcta520`, 33,791 ZCTAs).

1. **Coverage weights.** exactextract (`cell_id`, `coverage`) gives, for each
   ZCTA, every overlapping cell and the fraction of that cell it covers. This
   is computed once as a sparse 33,791 × 872,505 matrix with 760,037 nonzero
   entries. **Partly covered cells count**, so even tiny ZCTAs get a value.
   The calculation was checked against exactextract's own coverage-weighted
   mean.
2. **Monthly mean.** Each month's value is the coverage-weighted mean over
   valid (non-nodata) cells. The output is
   `rainfall_PRISM_zcta2020.zipcode_year_month.csv`, with 19,463,616 rows:
   - `ZIP_CODE`, `year`, `month`;
   - `MEAN`: precipitation in mm;
   - `NCELLS`: the effective number of valid cells covered, which is the sum
     of the coverage fractions.
3. **Result.** Every contiguous-US ZCTA has a value for every month. The 491
   ZCTAs with no values are in Alaska, Hawaii, Puerto Rico, the Virgin
   Islands and Guam, all outside the PRISM CONUS grid.
4. **Agreement with the old table.** On the 10.1M (zip, month) pairs both
   tables have, the correlation is 0.997, the median difference is 0.9%, and
   the mean bias is −0.04 mm. The differences most likely come from the polygon
   vintage, the partly-covered-cell weighting, and any PRISM revisions since
   the old table was made. For
   example, 77096 in Aug 2017 is 860.8 mm now against 863.2 mm before.

### Match

Left join on (zip, year, month of `dateOfLoss`). The columns are named
`prism_MEAN` and `prism_NCELLS`.

- **The value is the whole calendar month's total, not rainfall at the
  event.** A loss on Aug 31 gets August, and every loss in the same zip and
  month gets the same value.
- **Coverage.** Matched rows are 94.9% of all rows and 96.1% of 1990–2020
  rows; before the rebuild they were 63.9% and 85.3%.
- **Unmatched rows (17,337):**
  - 5,593 are outside CONUS;
  - 11,744 (3,382 zips) are contiguous-US zip codes with no ZCTA, such as
    PO-box zips.

---

## 5. Water Quality Portal → zip code × day (`download-wqp`, `wqp`)

### Download

`download-wqp` fetches data from the
[Water Quality Portal](https://www.waterqualitydata.us) (USGS NWIS + EPA
WQX/STORET):
- **Coverage:** every state, DC and Puerto Rico, 1990–2024, in 5-year chunks.
- **Site types:** stream, lake/reservoir, estuary and ocean.
- **Parameters:**

  | WQP name | Short name |
  |---|---|
  | Turbidity | `turbidity` |
  | Total suspended solids | `tss` |
  | Escherichia coli | `ecoli` |
  | Fecal Coliform | `fecal_coliform` |
  | Enterococcus | `enterococcus` |
  | Phosphorus | `phosphorus` |
  | Nitrogen | `nitrogen` |
  | Inorganic nitrogen (nitrate and nitrite) | `nitrate_nitrite` |
  | Nitrate | `nitrate` |

- **Files:** each state × chunk gives one zipped `narrowResult` file in
  `wqp/results/` and one site file (with coordinates) in `wqp/stations/`.
  Site requests are also chunked by date, because a whole state's site
  request is too large and the server resets it.
- **Behavior:** 3 parallel requests, with retries. Valid files that already
  exist are skipped.

### Zip-code summary

`wqp` builds `wqp_zcta2020.zipcode_day.csv`.

1. **Site → 2020 ZCTA.** Each site is placed in a ZCTA by point-in-polygon.
   Sites in open water outside every ZCTA polygon are snapped to the nearest
   ZCTA within 2 km; the rest are dropped.
2. **Values.** `ResultMeasureValue` is parsed with the nitrogen cleaner and
   converted to one unit per parameter. Negative values and unconvertible
   units are dropped.

   | Parameter | Standard unit | Units accepted |
   |---|---|---|
   | turbidity | NTU | NTU/FNU/NTRU/FTU/FAU/FBU/FNMU/NTMU, treated as equivalent. JTU is dropped |
   | bacteria | count/100 mL | CFU, MPN, #, count or colonies per 100 mL, treated as equivalent |
   | tss | mg/L | mg/L or ppm; µg/L or ppb × 0.001 |
   | phosphorus | mg/L as P | as above; PO₄ units × 30.974/94.971 |
   | nitrogen species | mg/L as N | as above; NO₃, NO₂, NH₄, NH₃ units × the N mass ratio, unless already "as N" |

3. **Fractions.** For phosphorus and total nitrogen, only whole-water
   samples are kept (fraction "Total" or blank), so dissolved and total
   values are not mixed. On the Delaware 2015–19 test, this drops 656
   dissolved-phosphorus results out of 10,014.
4. **Aggregate.** One row per (zip code, date, parameter):
   - `median` and `mean` of the standardized values;
   - `n_results` and `n_sites`;
   - `unit`.

   Zip-days with no samples are not listed.

**Caveats.**
- Sampling is irregular and sometimes triggered by events. See
  `docs/candidate_outcome_datasets.md`: dense sampling in metro areas, sparse
  elsewhere, and fewer samples right after big floods.
- Some WQP data after March 2024 is only in the newer WQX 3.0 profile, so
  2024 may be incomplete.
- This table replaces nothing in the build. The nitrogen columns in the final
  dataset still come from `Nitrogen_2007-2021_national_with_ZIP.csv`.

## 6. SDWIS drinking-water violations → zip code × month (`sdwis`)

### Sources

Both are downloaded manually into `sdwis/`:
- [`SDWA_latest_downloads.zip`](https://echo.epa.gov/files/echodownloads/SDWA_latest_downloads.zip):
  EPA ECHO, 558 MB, snapshot 2026Q3.
- [`PWS_Boundaries_Latest.zip`](https://github.com/USEPA/ORD_SAB_Model): EPA
  community water system service areas v3, 570 MB. Unzip
  `3_0/Service_Areas_V_3_0.gpkg` from it.

### Why service-area polygons

SDWIS's own `ZIP_CODE_SERVED` field is filled for only **2% of active
community water systems**, almost all of them in South Dakota and
Massachusetts. So systems are mapped to zip codes with EPA's service-area
polygons instead.

### Steps

1. **Crosswalk** (`sdwis_cws_zcta2020.csv`). The 44,643 community water
   system service areas are intersected with the 2020 ZCTAs in an
   equal-area projection (EPSG:5070). For each (PWSID, ZCTA) pair:
   - `area_share` = the share of the system's area that lies in the ZCTA;
   - `pop_est` = the system's population served × `area_share`.

   This gives 88,849 pairs covering 30,122 ZCTAs. Slivers below 0.01% of a
   system's area are dropped.
2. **Violations.** The script reads `SDWA_VIOLATIONS_ENFORCEMENT.csv` (4.1 GB)
   in chunks and keeps health-based violations (`IS_HEALTH_BASED_IND = Y`) of
   mapped community systems. The file has one row per violation × enforcement
   action, so it is de-duplicated on (PWSID, VIOLATION_ID). Each violation is
   dated by the month of `NON_COMPL_PER_BEGIN_DATE`. The result is 259,794
   violations.
3. **Zip × month** (`sdwis_zcta2020.zipcode_month.csv`). The table is sparse:
   it lists 387,957 zip-months that had at least one new health-based
   violation, and all other zip-months had none. Columns:

   | Column | Meaning |
   |---|---|
   | `n_hb_violations` | Health-based violations beginning that month |
   | `n_microbial_violations` | Of those, microbial: rule group 100, covering coliform and surface-water treatment/turbidity rules |
   | `n_tier1_violations` | Of those, tier 1 (acute) public notice |
   | `n_systems_hb` | Systems with such a violation |
   | `pop_in_hb_systems`, `pop_in_microbial_systems`, `pop_in_tier1_systems` | Estimated population of the zip served by those systems |
   | `pop_served_est` | Estimated population of the zip served by any mapped community water system |
   | `share_pop_hb` | `pop_in_hb_systems` / `pop_served_est` |

### Caveats

- **Usable from 1991.** Earlier years have only a few hundred zip-months
  each, because federal reporting was thinner then.
- **Today's systems only.** Service areas exist for 89% of *active*
  community systems but only 1% of inactive ones. Violations by systems that
  have since closed or merged are lost, so earlier years under-count.
- **Population is allocated by area, not by where people live.** The EPA
  package also has building-weighted block tables that could refine this.
- **Violations measure compliance, not contamination.** Monitoring and
  reporting violations are excluded by keeping health-based ones only.

## 7. NASA Black Marble nighttime lights → zip code × day (`blackmarble`)

**Run in `ai2-geo`.** This step also needs `h5py`, and a NASA Earthdata
login in `~/.netrc` (`machine urs.earthdata.nasa.gov`).

**Product.** VNP46A2 collection 2 from LAADS DAAC: daily, moonlight- and
BRDF-corrected VIIRS nighttime radiance, nW/(cm² sr). The grid is 15
arc-seconds (~500 m), in 10°×10° tiles of 2400×2400 cells, about 21 MB each.
Coverage starts 2012-01-19.

### Which days

Daily tiles for the whole US over 2012–2020 would be about 26 tiles × 3,100
days. Even ±30-day windows around every loss come to about 48,000 tile-days,
roughly 950 GB. So the step downloads only:
- **flood dates:** zip-days with **≥ 25 NFIP claims** (`BM_MIN_CLAIMS`);
  there are 430 such loss dates, covering 77% of 2012–2020 claims;
- **window:** **± 14 days** around each (`BM_WINDOW`);
- **tile:** the tile that holds the zip's center.

That is 7,734 tile-days in 18 tiles, about 160 GB transferred.

### Steps

1. **Find files.** For each tile, NASA's CMR search service (no login
   needed) lists the granule URLs. The search is padded by a day on each
   side, because granule time spans are offset from the file date.
2. **Stream.** Each tile-day is downloaded with `curl -n` (the Earthdata
   login), with 4 in parallel. It is averaged over every 2020 ZCTA in the
   tile, the small result is written to `blackmarble/parts/hXXvYY_DATE.csv`,
   and the tile is deleted. Disk use stays small, and re-running resumes.
3. **Weights.** Per tile, exactextract coverage fractions are computed once
   for every ZCTA cell, the same method as PRISM.
4. **Two radiance values per zip-day:**
   - `ntl_hq`: the coverage-weighted mean of `DNB_BRDF-Corrected_NTL` over
     cells that are high quality (`Mandatory_Quality_Flag = 0`), clear sky
     (cloud mask bits 6–7 = confident or probably clear) and snow-free. NaN
     if no such cells.
   - `hq_coverage`: the share of the zip, by coverage weight, that has such
     high-quality cells that day.
   - `ntl_gapfilled`: the same mean over NASA's
     `Gap_Filled_DNB_BRDF-Corrected_NTL`, which fills cloudy cells with the
     latest good retrieval.
5. **Combine.** Zip codes that straddle tile edges are summed across tiles
   before dividing. The output is `blackmarble_zcta2020.zipcode_day.csv.gz`.
   It includes **every** ZCTA in a downloaded tile, not just flooded ones,
   so unflooded zips on the same days are available as controls.

### Result (run 2026-10-15)

- **Coverage:** 7,688 of 7,734 tile-days processed. The other 46 have no
  granule at LAADS, and there were no download failures.
- **Output:** `blackmarble_zcta2020.zipcode_day.csv.gz`, 236 MB:
  23,114,293 zip-days across 33,262 ZCTAs and 2,748 days
  (2012-01-19 … 2020-08-18).
- **Clear-sky coverage:** 65% of zip-days have some high-quality cloud-free
  coverage (`hq_coverage` > 0), and 48% have at least half the zip covered.
- **Values:** the median `ntl_hq` is 1.0 nW/(cm² sr). A few zip-days reach
  ~13,600, probably gas flares or industrial sites.
- **Harvey check:** Houston zips 77024/77079/77082/77096 read 45–70 before
  landfall. There are no clear-sky readings from Aug 24–30, 2017 (storm
  clouds), and similar levels return from Aug 31.

### Coverage of FEMA zip-days

Each FEMA zip-day (loss dates 2012-02 … 2020-08) is checked over ±14 days of
its loss date. A day counts as clear if `hq_coverage` ≥ 0.5. Mixed means
0 < `crs_treat` < 1.

| Subset | Rows | crs=1 | crs=0 | mixed | Zips | Zips ever crs=1 | Zips ever crs=0 |
|---|---|---|---|---|---|---|---|
| FEMA zip-days 2012-02 … 2020-08 | 65,663 | 26,877 | 36,033 | 2,753 | 13,701 | 4,402 | 10,160 |
| Inside a downloaded window | 50,826 | 21,501 | 26,765 | 2,560 | 11,039 | 3,512 | 8,192 |
| ≥ 1 clear day before and after | 43,676 | 19,212 | 22,022 | 2,442 | 9,980 | 3,334 | 7,211 |
| ≥ 3 clear days before, ≥ 1 after | 39,079 | 17,567 | 19,230 | 2,282 | 9,204 | 3,186 | 6,522 |
| + pre-flood light ≥ 2 (lit areas) | 27,108 | 14,815 | 10,523 | 1,770 | 5,590 | 2,500 | 3,471 |
| + FSF/ACS/PRISM | 26,898 | 14,796 | 10,335 | 1,767 | 5,478 | 2,489 | 3,370 |

Usable rows have a median of 6 clear days before and 7 after. For the large
flood days themselves (≥ 25 claims): 2,271 of 2,767 zip-days are usable, in
987 zips (crs=1 1,042, crs=0 485, mixed 744).

### Caveats

- **Clouds.** Storms are cloudy, so `ntl_hq` is often missing on the flood
  days themselves. The gap-filled value then repeats an older retrieval, so
  it can't show an outage that happens under clouds. Use `hq_coverage`, and
  compare multi-day windows.
- **Only urban and suburban zips have usable signal.** Dark rural zips have
  near-zero radiance.
- **Time range.** Coverage runs through the FEMA data's end (August 2020).

## Plots (`plot`)

The plots are built from the final dataset and saved in `figures/`.

- **`nitrogen_distributions.png`** overlays the Before and After nitrogen
  distributions as step histograms, with log-spaced bins over 10^-2.5–10^3
  mg/L. There is one panel per window, with a shared y-axis. Medians are
  dashed, and the count of zeros (which a log axis cannot show) is printed.
- **`nitrogen_change_{1,2}month.png`** is a histogram of After − Before for
  rows with both values. It shows ±3 mg/L with 0.1 mg/L bins centered on 0;
  values outside that range are counted on the plot.

- **`corner_nitrogen_1month.png`** is a corner plot made with the `corner`
  package. It overlays the 1-month-before set (blue) and the
  1-month-after set (orange). Each shows the joint and marginal distributions
  of five variables:
  - log10 nitrogen (mg/L);
  - median household income (`acs_SE_A14006_001`, in k$);
  - log10 population (`acs_SE_A00001_001`);
  - FSF average risk score (`fsf_avg_risk_score_all`, the Flood Factor, 1–10);
  - rainfall in the loss month (`prism_MEAN`, mm).

  The rows are those with that nitrogen reading plus FSF, ACS and PRISM data:
  7,975 before and 7,385 after. Rows with missing income, or with zero
  nitrogen or population (which log10 cannot take), are dropped: 13 and 14
  respectively.

  The two sets have different sizes, so histograms are normalized to unit
  area. The 2-D panels show contours only, at 39% and 86% (1σ and 2σ for a
  2-D Gaussian), without points or fills, so both sets stay visible. Dashed
  lines are medians. Both sets share axis ranges: the central 99.5% of the
  combined data. Income is in each row's ACS period dollars, not
  inflation-adjusted.

- **`corner_crs_1month_{before,after}.png`** use the same corner layout and
  variables. Each compares rows with `crs_treat = 1` (all of the zip-day's
  claims in a CRS community, aqua) against rows with `crs_treat = 0` (none,
  violet), separately for the 1-month-before and 1-month-after nitrogen
  sets. Mixed rows (0 < `crs_treat` < 1) are left out: 330 before and 251
  after.

  | | CRS = 1 | CRS = 0 |
  |---|---|---|
  | Rows, before set | 3,193 | 4,452 |
  | Rows, after set | 2,820 | 4,314 |

- **`corner_crs_1month.png`** puts all four sets on one corner plot:
  - color shows CRS status (aqua = CRS, violet = no CRS);
  - line style shows timing (solid = 1 month before, dashed = 1 month after).

  There are no median lines, to avoid clutter; the legend gives each set's
  size and median nitrogen.
- **`correlations_1month.png`** shows Spearman rank correlations among
  zip-day characteristics. The rows are the 11,167 with a 1-month nitrogen
  reading (before or after) plus FSF, ACS and PRISM data. Pairs are computed
  on whatever rows have both values, so the nitrogen pairs use n = 7,988,
  7,399 or 4,220.

  The variables are:
  - nitrogen before, after, and the change (after − before);
  - `crs_treat`, primary-residence share, policies, total paid, and paid per
    policy;
  - median income, population, population density;
  - FSF % of properties in a FEMA special flood hazard area (SFHA), FSF risk
    score;
  - rainfall and loss year.

  Spearman is used because most of these are heavily skewed. Rows are not
  independent, since there are several per zip code. A bootstrap that
  resamples whole zip codes (400 resamples, run during the analysis but not
  part of the script) shows that |ρ| ≲ 0.06 is consistent with zero.

| | 1 month | 2 months |
|---|---|---|
| Rows with both | 4,266 | 8,647 |
| Median / mean change (mg/L) | +0.010 / +0.036 | −0.005 / +0.011 |
| Increase / decrease / zero | 2,206 / 2,000 / 60 | 4,157 / 4,369 / 121 |
- **`sdwis_event_study.png`**: drinking-water violations around flood
  events, 1992–2019. Built by `flood_events` and `sdwis_event_study`.
  - **Events.** A zip's NFIP loss dates less than 14 days apart are merged
    into one event. That gives 131,683 events in zips served by a mapped
    community water system, 7,819 of them with ≥ 25 claims.
  - **Outcome.** For each event and month k = −12…+12, the outcome is
    whether the zip had a new health-based, microbial or tier-1 violation.
    From it the script subtracts the share of all served zips in the same
    state with one that month, which removes season, trend and state
    reporting differences. It then subtracts the event's own pre-flood mean.
  - **Bands.** 95% bootstrap intervals, resampling zip codes (200 resamples).

  **Result.** After large floods, the share of zips with a new health-based
  violation rises by about 1.3 percentage points in the flood month and 0.6
  in month 1. The usual rate is about 3.6% per month, so that is roughly a
  third higher. It is back to baseline by month 2. Microbial violations show
  the same spike, and tier-1 (acute) violations peak in month 1. The same
  analysis on dates shifted ±6 or 12 months shows no spike: month 0 is
  between −0.2 and +0.3 percentage points. Analysis-only checks (not in the
  script): over months 0–3 the increase is +9% for health-based and +10% for
  microbial, and the microbial share of violation months rises from 66% to
  73%.
- **`blackmarble_event_study.png`**: nighttime light around large floods,
  split by CRS. Built by `blackmarble_event_study`.
  - **Events.** A zip's loss dates less than 14 days apart are merged into
    one event, keeping events with at least one ≥ 25-claim day in
    2012-02 … 2020-08. That gives 1,779 events.
  - **CRS group.** The claim-weighted mean `crs_treat` over the event:
    1 → CRS (651 events), 0 → no CRS (445), otherwise mixed (683, not
    plotted).
  - **Outcome.** For each day k = −14…+14 from the first loss date: the log of
    the zip's clear-sky light (`hq_coverage` ≥ 0.5) relative to its own mean
    over days −14…−2. The event must have ≥ 3 clear pre-flood days and a
    pre-flood mean ≥ 2 nW/(cm² sr). 1,393 events qualify.
  - **Nearby zips.** The "net" panel subtracts, each day, the median of the
    same quantity in nearby zips: same 3-digit zip prefix, no NFIP claim
    within 30 days, about 17 per event.
  - **Bands.** 95% bootstrap over events.

  **Result.**

  | Window | Measure | All events | CRS | No CRS | CRS − no CRS (log points) |
  |---|---|---|---|---|---|
  | Days 0–3 | Raw | −14% [−16, −12] | −14% | −11% | −2.6 [−8.5, +3.4] |
  | Days 4–14 | Raw | −7% [−8, −6] | −4% | −7% | +2.6 [−0.5, +5.9] |
  | Days 0–3 | Net of nearby zips | ≈ 0 [−3, +2] | +2% | −1% | +3.4 [−2.1, +8.9] |
  | Days 4–14 | Net of nearby zips | ≈ 0 [−2, +1] | +3% | −3% | **+5.8 [+2.9, +8.8]** |

  The raw ~1 log point dip before day 0 is mostly arithmetic: the mean of
  log ratios sits below the log of the mean ratio.

  So:
  - The drop in light after a flood is mostly shared with nearby zips with
    no claims: regional outages, storm haze or wet surfaces.
  - In days 4–14, CRS flood zips stay brighter than their neighbors while
    non-CRS flood zips stay darker.

  **Caveats.**
  - CRS zips are larger and more urban.
  - Events from one storm are not independent, so the bootstrap over events
    understates uncertainty.
  - Nearby zips are themselves often affected by the storm.
- **`pbj_event_study.png`**: nursing homes around flood events, 2017–2020.
  Built by `pbj_event_study`.
  - **Events.** From `flood_events`, starting 2017-03 or later, in zips with
    a PBJ facility.
  - **Outcome.** For weeks −8…+8: log census and log nurse hours per
    resident-day, each relative to the zip's own mean over weeks −8…−2 (at
    least 4 complete weeks). The script subtracts the weekly median change
    in nearby PBJ zips: same 3-digit prefix, no NFIP claim within 60 days.
  - **Groups.** CRS (`crs_treat` = 1) vs no CRS (0), for all floods and for
    large floods (≥ 25 claims in a day). Bands are 95% bootstrap intervals
    over events.

  **Result** (weeks +1…+4, net of nearby zips):

  | Sample | Measure | CRS | No CRS | CRS − no CRS (log points) |
  |---|---|---|---|---|
  | All floods (2,698 / 5,282 events) | Census | −0.2% | −0.2% | +0.0 [−0.6, +0.7] |
  | All floods | Hours per resident-day | +0.2% | +0.1% | +0.1 [−0.3, +0.5] |
  | Large floods (74 / 70) | Census | −2.3% | +1.4% | −3.8 [−13.6, +4.7] |
  | Large floods | Hours per resident-day | +0.4% | +0.3% | +0.1 [−3.6, +3.6] |

  Typical floods leave nursing-home census and staffing unchanged. For large
  floods the sample is small and noisy, with no CRS difference
  distinguishable from zero.

  **Caveats.**
  - PBJ locates facilities by mailing ZIP, not exact address, so a flooded
    zip doesn't mean the facility itself flooded.
  - Census falls for many reasons (evacuation, discharge, death), and
    facilities that stop reporting drop out. Check reporting around events
    before reading a missing week as "no effect".

- **`check_{nitrogen, sdwis, blackmarble, pbj_census, pbj_hprd}.png`**:
  quick before-vs-after flood checks, one figure per outcome. Built by
  `flood_checks`. Each figure has columns for all floods, CRS
  (`crs_treat` = 1) and no CRS (0); all floods includes mixed rows.
  - **Top row:** the outcome's distribution before vs after the flood.
    SDWIS instead shows the share of zip-months with 0/1/2/3+ violations.
  - **Bottom row:** each FEMA zip-day's own change, with n, median and mean
    change, the share up/down, and a Wilcoxon signed-rank p.
  - **No adjustment** for season, region or repeat floods. Rows from the
    same zip or event are not independent, so the p-values are optimistic.

  | Outcome | Before | After | Median change: all / CRS / no CRS |
  |---|---|---|---|
  | Nitrogen (mg/L) | 30 days before | 30 days after | +2.2% / +2.9% / +2.9% (mean +3.0 / +1.9 / +4.0%) |
  | SDWIS health-based violations | months −12…−2 | loss month, +1 | zip-months with ≥ 1 violation: 3.7% → 4.2% (all), 2.8% → 3.4% (CRS), 4.3% → 4.8% (no CRS) |
  | Black Marble clear-sky light | days −14…−2 | days 0…7 | −2.4% / −2.4% / −2.2% (mean −4.5 / −3.8 / −4.8%) |
  | PBJ census | 4 weeks before | 4 weeks after | 0.0% / +0.1% / −0.1% |
  | PBJ nurse hours per resident-day | 4 weeks before | 4 weeks after | −0.3% / −0.5% / −0.1% |

  Black Marble keeps zips whose median clear-sky light over all their days
  is ≥ 2. Selecting on the pre-flood window instead would bias the change
  downward (regression to the mean).
- **`check_wqp_{param}.png`**: the same before-vs-after check for each Water
  Quality Portal parameter. For each FEMA zip-day (1990-02+), the before and
  after values are the geometric mean of the zip's daily median values in the
  30 days before and after the loss date, excluding the loss date
  (`wqp_flood_windows`). Built from the complete download (all states, DC
  and PR; 2026-10-29).

  | Parameter | Paired zip-days (CRS / no CRS) | Median change: all / CRS / no CRS | Mean change (all) |
  |---|---|---|---|
  | turbidity | 30,804 (16,241 / 13,119) | +2.9% / +3.1% / +2.5% | +5.7% |
  | total suspended solids | 27,195 (13,416 / 12,435) | −1.3% / −2.3% / 0.0% | −1.5% |
  | phosphorus | 21,904 (9,100 / 11,786) | 0.0% / 0.0% / 0.0% | −1.3% |
  | fecal coliform | 20,155 (12,033 / 7,079) | 0.0% / 0.0% / +3.6% | +7.4% |
  | enterococcus | 12,871 (9,031 / 3,256) | +6.1% / +5.2% / +8.1% | +14.5% |
  | nitrate | 9,859 (4,278 / 5,204) | 0.0% / +0.9% / 0.0% | +2.7% |
  | E. coli | 8,677 (3,672 / 4,610) | 0.0% / 0.0% / 0.0% | +5.0% |
  | total nitrogen | 4,956 (1,640 / 3,143) | +1.1% / −0.1% / +1.4% | −0.2% |
  | nitrate + nitrite | 4,953 (1,470 / 3,272) | −4.2% / −5.6% / −3.5% | −7.7% |

  Medians of exactly 0.0% mostly mean that most zip-days had the same value
  before and after, often a single sample at a reporting or detection value.

**WQP download completed 2026-10-29.**
- **Coverage:** all 364 result chunks and all site chunks except Oregon 2013.
  The server resets that request even one year at a time. The 339 Oregon
  2010–14 results (0.28%) from 91 sites listed only there have no
  coordinates and drop out.
- **Final table:** 381,229 sites (347,428 inside a ZCTA, 20,914 snapped,
  12,887 unmatched). 22.9M of 28.7M results are usable. The table has
  10,288,726 zip-day-parameter rows across 24,548 zips, 1990–2024.
- **Download fixes:**
  - one-year fallback for site chunks the server resets;
  - a 10-minute socket timeout per request, after a dropped connection hung
    the downloader for hours.

**WQP build fix (2026-10-29).** `wqp_sites_to_zcta` concatenated site files
without resetting the index. The de-duplication of spatial-join matches then
dropped most sites: only ~25,500 of 343,000 matched, and 3% of results were
usable. Resetting the index fixed it. The partial build now has:
- **Sites:** 312,232 inside a ZCTA, 19,434 snapped to one, 12,044 unmatched.
- **Results:** 20.9M of 26.4M usable (79%).
- **Table:** 9.5M zip-day-parameter rows across 22,559 zips.
