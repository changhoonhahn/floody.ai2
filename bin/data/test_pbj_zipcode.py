import importlib.util
from pathlib import Path
import unittest
import pandas as pd

s=importlib.util.spec_from_file_location('pbj',Path(__file__).with_name('pbj_zipcode.py'))
p=importlib.util.module_from_spec(s);s.loader.exec_module(p)

class PBJTests(unittest.TestCase):
    def test_ratio_of_sums_zero_census_and_missing_days(self):
        rows=[]
        for provider,census,hours in [('000001',10,20),('000002',30,90),('000003',0,50)]:
            r=dict(provnum=provider,zipcode='01001',date=pd.Timestamp('2020-01-01'),mdscensus=census,
                   location_fallback=False,snapshot_date=pd.Timestamp('2019-12-01'))
            r.update({c:0 for c in p.HOURS});r['hrs_rn']=hours;rows.append(r)
        d=p.daily_aggregate(pd.DataFrame(rows),'2020-01-01','2020-01-02')
        self.assertEqual(d.iloc[0].total_nurse_hours_per_resident_day,110/40)
        self.assertEqual(d.iloc[0].facility_days_zero_census,1)
        self.assertEqual(d.iloc[1].facility_days_reported,0)
        self.assertTrue(pd.isna(d.iloc[1].total_nurse_hours_per_resident_day))
        self.assertEqual(d.iloc[1].reporting_fraction,0)

    def test_state_and_time_guard_for_locations(self):
        loc=pd.DataFrame([
            dict(provnum='000001',state='MA',zipcode='01001',snapshot_date=pd.Timestamp('2020-02-01'),location_source='providers_2020'),
            dict(provnum='000002',state='CA',zipcode='90001',snapshot_date=pd.Timestamp('2020-02-01'),location_source='providers_2020'),
            dict(provnum='000003',state='MA',zipcode='01002',snapshot_date=pd.Timestamp('2024-02-01'),location_source='providers_2024')])
        providers=pd.DataFrame({'provnum':['000001','000002','000003'],'state':['MA']*3})
        cw=p.crosswalk(providers,loc,'2020-01-01')
        self.assertEqual(cw.iloc[0].zipcode,'01001')
        self.assertTrue(cw.iloc[1:].zipcode.isna().all())

    def test_leading_zeros(self):
        f=p.location_frame(pd.DataFrame({'PROVNUM':['1001'],'ZIP':['1001'],'STATE':['MA']}),'2020-01-01','test')
        self.assertEqual(f.iloc[0].provnum,'001001')
        self.assertEqual(f.iloc[0].zipcode,'01001')

if __name__=='__main__':unittest.main()
