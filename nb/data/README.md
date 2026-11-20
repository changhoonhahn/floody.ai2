# quick flood checks 
One notebook per outcome dataset. Each asks whether the outcome changes
after a flood loss, using one row per FEMA NFIP zip-day (zip code × date of
loss). It makes three comparisons:

1. the outcome **before vs. after** the flood, for all floods;
2. the same, for zip-days in **CRS** communities (`crs_treat = 1`);
3. the same, for **non-CRS** zip-days (`crs_treat = 0`).

| Notebook | Outcome | Before | After |
|---|---|---|---|
| `flood_check_nitrogen.ipynb` | river nitrogen (mg/L) | 30 days before | 30 days after |
| `flood_check_sdwis.ipynb` | health-based drinking-water violations | months −12…−2 | loss month and +1 |
| `flood_check_blackmarble.ipynb` | clear-sky nighttime light | days −14…−2 | days 0…7 |
| `flood_check_pbj.ipynb` | nursing-home census; nurse hours per resident-day | 4 weeks before | 4 weeks after |
| `flood_check_wqp.ipynb` | turbidity, TSS, E. coli, fecal coliform, enterococcus, phosphorus, nitrogen species | 30 days before | 30 days after |
