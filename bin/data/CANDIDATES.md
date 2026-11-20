# Candidate non-financial flood-outcome datasets for the CRS treatment effect

These datasets were screened for joining with the existing FEMA/NFIP, FSF,
ACS and PRISM pipeline (`bin/ai2_dataset.py`). The criteria were:

1. Repeated over **many years**, with pre- and post-periods around CRS entry
   and class changes.
2. **National or multi-state coverage** that can be mapped to **zip
   code/ZCTA** (or to county, as a fallback).
3. A **plausible pathway** from CRS activities (open space, higher
   regulatory standards, drainage maintenance, warning, outreach) to the
   outcome.
4. Realistic **access**.

`potential_dataset_table.docx` (Web of Science review, Jun–Jul 2026) mostly
surfaced single-site, survey or qualitative studies. The US datasets it does
name, such as the EPA Water Quality Portal, CDC PLACES/BRFSS, NBI and VIIRS,
are carried forward below where they meet the criteria.

## Tier 1: free, national, multi-year, mappable to zip codes

| # | Outcome | Dataset | Years | Unit → zip | Why it fits CRS | Caveats |
|---|---|---|---|---|---|---|
| 1 | Water quality (turbidity, TSS, E. coli/fecal coliform, phosphorus, dissolved oxygen, nitrogen) | **Water Quality Portal** (USGS NWIS + EPA WQX/STORET), [waterqualitydata.us](https://www.waterqualitydata.us) | 1970s–present; >290M records, >2.7M sites | Station lat/lon → ZCTA (point-in-polygon) | Extends the nitrogen file we already use (nitrogen only, 2007–2021) to every parameter and year. Same before/after pipeline as `add_nitrogen`. | Sampling is not random: it is sometimes triggered by events, and larger (CRS) places are monitored more. Use station fixed effects. Units need cleaning, as with nitrogen. |
| 2 | Drinking-water safety | **SDWIS violations**, from the ECHO SDWA bulk download | Decades, quarterly snapshots | `SDWA_GEOGRAPHIC_AREAS.ZIP_CODE_SERVED`, or EPA CWS service-area polygons (2024+) | Health-based violations (MCL, treatment technique such as turbidity or coliform) and public-notice tier after floods. Treatment plants and wells sitting in floodplains is a direct pathway. | Violations measure compliance, not exposure. ZIP_CODE_SERVED is self-reported and incomplete. There is no explicit boil-water field. |
| 3 | Recreational water / sewage | **EPA BEACON** beach advisories and closures | 2000s–present (online reports 2014+) | Beach points → ZCTA | Advisories are often caused by stormwater or sewer overflow after rain, and coastal CRS communities are heavily represented. | Coastal and Great Lakes only. Reported annually by states. |
| 4 | Land use / ecosystem protection | **Annual NLCD Collection 1.0** (land cover, fractional impervious surface, change) | 1985–2023, annual, 30 m | Raster → ZCTA with our exactextract pipeline | **Most direct link to CRS credits**: open-space preservation (Activity 420) and higher regulatory standards (430) should show up as less floodplain development, wetland loss and impervious growth. Overlay with FSF/FEMA flood zones. | Measures land change, not flood damage. Annual change detection is noisy at pixel level, so aggregate. |
| 5 | Power / recovery | **NASA Black Marble VNP46A2** daily nighttime lights | 2012–present, daily, 500 m | Raster → ZCTA (same pipeline) | Size of the drop and days to recovery after a flood: a proxy for outages, displacement and recovery speed. Available everywhere. | Clouds, snow and moonlight cause gaps. Mostly sensitive in built-up areas. Large data volume. |
| 6 | Power continuity | **ORNL EAGLE-I** customers out, every 15 min | 2014–2023/24 | **County** (FIPS) | Customer-hours out after flood events. | County, not zip. Utility coverage varies by state and year (there is a supplementary coverage file). |
| 7 | Displacement / uninhabitable homes | **OpenFEMA Housing Assistance Owners/Renters** (`/v2/HousingAssistanceOwners`) | 2002 (DR-1439)–present | **Zip code** (+ county) | Number of registrants, inspected homes and damage-severity counts per zip and disaster. Measures homes made uninhabitable, which is not the NFIP payout. | Only for presidentially declared disasters, so it describes outcomes given a declaration. Data are self-reported. Includes assistance amounts, but you can use only the counts. |
| 8 | Displacement (children) | **NCES Common Core of Data**, school enrollment + EDGE school locations | ~1986–present, annual | School points → ZCTA | Drops in enrollment the year after a flood measure displacement; return to baseline measures recovery. | Annual timing is coarse. School choice and charter shifts add noise. |
| 9 | Deaths and injuries | **NOAA Storm Events Database** (flood and flash-flood events) | Flood types 1996–present | County / NWS forecast zone | Direct and indirect deaths and injuries per event. Also gives independent event timing. | Deaths are rare. Spatial unit is coarse. Reporting varies by NWS office. |

## Tier 2: strong outcomes but restricted or costly

| # | Outcome | Dataset | Years | Geography | Notes |
|---|---|---|---|---|---|
| 10 | Hospitalizations and ED visits (injury, GI illness, CO poisoning, mental health) | **HCUP State Inpatient / Emergency Dept. Databases** | 1990s–present, by state | **Patient zip in some states** | Purchased from the HCUP Central Distributor. Check the zip field in AHRQ's availability tables for flood-prone states (TX, LA, FL, NC, NJ, NY). |
| 11 | Hospitalizations among adults 65+ | **CMS Medicare claims** (ResDAC) | ~1999–present | Beneficiary zip | National. A DUA is needed, with cost and lead time. Widely used for hurricane and flood health studies. |
| 12 | Vacancy / displacement | **HUD-USPS vacancy data** | Quarterly since 2005 agreement | Census tract (→ ZCTA crosswalk) | Access only for government and nonprofit registered users; a university should qualify. Address-system changes complicate long time series. |

## Tier 3: limited for causal panels

- **CDC PLACES** (ZCTA, 2020–2024 releases): model-based small-area estimates
  built from BRFSS plus ACS covariates. The modeling smooths away local
  shocks, so the estimates are not suitable for event-study designs.
- **ECHO sewer overflow and bypass events / CSO inventory**: overflow events
  are a good flood outcome, but EPA says the event data are still in
  development and do not yet cover all events. The CSO inventory is static.
- **National Response Center spill reports** (1990–present): chemical and oil
  releases, some flood-caused. Data are initial and unvalidated, and only
  city/state is confirmed (not coordinates).
- **CDC WONDER** mortality: county-month, with cells under 10 suppressed.

## The treatment side needs its own panel

`crs_treat` in our dataset comes from claims, so it is **only observed for
zip-dates that had an NFIP claim**. Outcomes measured continuously (water
quality, NLCD, nightlights, enrollment) need a community-by-year CRS panel
that doesn't depend on claims:

- **OpenFEMA FIMA NFIP Redacted Policies v2** (`/v2/FimaNfipPolicies`):
  policy-level records with the community's CRS class and policy dates. This
  would give a class history per community and zip, including zips with no
  claims. Confirm the exact field names in the v2 data dictionary.
- FEMA's current CRS community list, plus a request to the CRS team
  (fema-crs@fema.dhs.gov) for historical class and entry dates. Class
  changes take effect on fixed dates each year (Apr/Oct or May/Oct,
  depending on the year).

## Suggested order

1. Build the **CRS community-year treatment panel** from NFIP policies.
2. **Water Quality Portal**, all parameters. This reuses `add_nitrogen`,
   generalized to a parameter list with unit tables.
3. **Annual NLCD** and **Black Marble**. Both reuse the exactextract zonal
   code already in `ai2_dataset.py prism`.
4. **SDWIS violations** joined via ZIP_CODE_SERVED or CWS service areas.
5. Then OpenFEMA Housing Assistance, NCES enrollment and EAGLE-I as further
   outcomes; HCUP or Medicare if funding or a DUA allows.

## Sources

- [Water Quality Portal: USGS publication](https://pubs.usgs.gov/publication/70181999), [EOS summary](https://eos.org/research-spotlights/water-quality-database-offers-new-tools-to-study-aquatic-systems)
- [ECHO SDWA data download summary](https://echo.epa.gov/tools/data-downloads/sdwa-download-summary), [EPA CWS service area boundaries](https://www.epa.gov/ground-water-and-drinking-water/community-water-system-service-area-boundaries), [ASDWA on the 2024 release](https://asdwa.org/2024/07/18/epa-releases-community-water-system-service-boundary-dataset)
- [EPA BEACON](https://19january2025snapshot.epa.gov/waterdata/beacon-beach-advisory-and-closing-online-notification)
- [Annual NLCD Collection 1 products](https://usgs.gov/data/annual-national-land-cover-database-nlcd-collection-1-products)
- [NASA Black Marble VNP46A2](https://blackmarble.gsfc.nasa.gov/VNP46A2.html)
- [EAGLE-I outages on Figshare](https://figshare.com/articles/dataset/The_Environment_for_Analysis_of_Geo-Located_Energy_Information_s_Recorded_Electricity_Outages_2014-2022/24237376), [ORNL DOI](https://doi.ccs.ornl.gov/ui/doi/435)
- [OpenFEMA Housing Assistance Owners](https://catalog.data.gov/dataset/housing-assistance-program-data-owners-nemis)
- [NCES EDGE public school locations](https://data.amerigeoss.org/dataset/public-school-locations-2019-20-c07ce)
- [NOAA Storm Events bulk download](https://www.ncei.noaa.gov/stormevents/ftp.jsp), [event-type coverage by year](https://www.ncei.noaa.gov/stormevents/details.jsp)
- [HCUP SID data-element availability](https://hcup-us.ahrq.gov/db/state/siddist/siddistvarnote2025.jsp), [HCUP availability by state/year](https://hcup-us.ahrq.gov/db/availability_public.jsp)
- [HUD-USPS vacancy data](https://www.huduser.gov/PORTAL/node/6568), [HUD USER USPS portal](https://www.huduser.gov/apps/public/usps/home)
- [CDC PLACES ZCTA 2024 release](https://catalog.data.gov/dataset/places-zcta-data-gis-friendly-format-2024-release)
- [ECHO CSO inventory](https://echo.epa.gov/tools/data-downloads/cso-inventory-summary)
- [National Response Center](https://nrc.uscg.mil/)
- [OpenFEMA changelog (FIMA NFIP Redacted Policies v2)](https://fema.gov/about/openfema/changelog), API endpoint `https://www.fema.gov/api/open/v2/FimaNfipPolicies`

## Can each dataset measure before vs. after a flood? (checked 2026-10-15)

| Dataset | Time resolution | Before/after a single event? | Evidence / caveat |
|---|---|---|---|
| NASA Black Marble | Daily, 500 m, 2012– | **Yes** | Clouds, snow and moonlight cause gaps. Use a multi-week baseline. Covers 20% of our zip-days (2012+). |
| ORNL EAGLE-I | 15 min, 2014– | **Yes, but by county** | Baseline from the preceding weeks. Utility coverage varies. Covers 16% of our zip-days (2014+). |
| EPA BEACON | Daily samples and advisory dates | **Yes, for coastal swimming seasons** | No data outside the monitoring season (roughly May–Sep). |
| USGS continuous sensors (NWIS instantaneous values) | 15 min | **Yes, but few sites** | Only 263 turbidity and 76 nitrate sensor sites across TX, LA, FL, NC, NJ, NY, PA. |
| Water Quality Portal | Irregular discrete samples | **Only in heavily monitored places** | County counts in the ±30 days around four floods: Harvey (Harris Co.) had 130–180 sites before but 10–38 after for E. coli, phosphorus and suspended solids. Florence (New Hanover) and Ellicott City (Howard Co.) had 0–3. Baton Rouge 2016 (East Baton Rouge) had 0. Zip-level counts are lower. Use pooled windows (90 days or more, county or HUC level) or anomalies from each station's own seasonal baseline. |
| SDWIS violations | Violation dates (`NON_COMPL_PER_BEGIN_DATE`), mostly monthly or quarterly monitoring periods | **Monthly panel, yes** | Most system-months have no violations. Monitoring-period violations reflect reporting, not contamination. Use health-based violations only. |
| Annual NLCD | Annual | **Year before vs. year after only** | Better suited to long-run CRS effects (development, wetlands) than to single events. |
| NCES enrollment | Annual (October count) | **Year before vs. year after only** | Several floods in one year can't be separated. |
| CDC PLACES | Annual, modeled | **No** | Model-based estimates smooth away shocks. |
| OpenFEMA Housing Assistance | Per declared disaster | **After only** | No pre-event measure. Damage bands are dollar-based. Compare CRS vs. non-CRS zips within the same disaster instead. |
| NOAA Storm Events | Per event | **After only** | Deaths and injuries exist only when an event occurs. Compare across events instead. |

Our own flood dates need cleaning first. 42.5% of FEMA zip-days have another loss in the same zip within the previous 30 days, mostly multi-day storms. Consecutive loss days should be merged into one event before defining "before" windows.

## NOAA Storm Events: overlap with FEMA claims (checked 2026-11-05)

Downloaded to `/Users/chang/data/ai2/stormevents/`: details, locations and
fatalities files for 1996–2026, 93 files, 351 MB.
- **Flood records:** 190,943, of which 113,293 flash floods, 70,984 floods,
  4,650 coastal floods and 1,657 storm surges.
- **Geography:** flash floods and floods are reported by county. Coastal
  floods and storm surges are reported by NWS forecast zone.
- **Coordinates:** start and end lat/lon exist for 100% of flood and flash
  flood records from 2007 on, and almost none before 2005. Zone-based types
  have none.
- **Casualties:** 2,959 direct deaths and 8,995 direct injuries across flood
  types.

### FEMA → Storm Events

For each FEMA zip-day, is there a recorded flood event within ±1 day? The
zip's county is the mode of `countyCode` in the claim-level file. Only
county-reported events are counted, so zone-reported coastal events are
missed.

| FEMA zip-days | n | In a county with a flood event | CRS / no CRS | Same zip, 2007–2020 (event points) | CRS / no CRS |
|---|---|---|---|---|---|
| All, 1996–2020 | 210,648 | 48.9% | 43.8% / 51.1% | 17.8% | 12.1% / 20.7% |
| ≥ 5 claims | 29,942 | 67.2% | 62.8% / 70.2% | 25.9% | 17.9% / 32.1% |
| ≥ 25 claims | 7,656 | 65.4% | 62.4% / 66.1% | 23.3% | 17.8% / 29.7% |

### Storm Events → FEMA

- Only **33%** of county flood events have any NFIP claim in that county
  within ±1 day.
- **58.8%** of the 1,743 county events with deaths or injuries have one.
- Point-located events (2007–2020) have a claim in the same zip **19.3%** of
  the time.
- 21,803 zips have at least one point-located flood.

### Reading

- **Large-claim days are only partly covered.** About two-thirds fall in a
  county with a recorded flood. The rest are mostly hurricane and coastal
  surge losses reported by zone, which this check doesn't count yet.
- **Zip-level matching is weak** (about 20–30%). A single start/end point
  does not cover an areal flood.
- **Storm Events records many floods with no NFIP claims** (two-thirds of
  county events). That makes it useful as a flood-exposure layer
  independent of insurance and as a source of unclaimed comparison areas.
- **CRS zip-days match less often,** consistent with CRS places being more
  coastal (zone-reported) and more urban.
- **Next steps** would be NWS zone-to-county or zone boundary files, so
  coastal events can be included, and checking whether hurricane events
  cover the remaining large-claim days.
