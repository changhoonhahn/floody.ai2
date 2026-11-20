"""Reconcile compiled weekly partitions against daily-source quarter audits."""
import hashlib
import gzip
import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(os.environ.get('PBJ_DATA_DIR', '/Users/chang/data/ai2/pbj')).expanduser()

def main():
    manifest=json.loads((ROOT/'source/manifest.json').read_text())
    audits=[json.loads((ROOT/f'audit_{r["quarter"]}.json').read_text())
            for r in manifest if r['kind']=='pbj']
    totals=dict(rows=0,resident_days=0.,hours=0.,reported=0.,valid=0.,complete=0)
    zips=set();boundaries=[]
    for path in sorted((ROOT/'weekly').glob('*.csv.gz')):
        d=pd.read_csv(path,dtype={'zipcode':str},parse_dates=['week_start'])
        assert d.zipcode.str.fullmatch(r'\d{5}').all()
        assert not d.duplicated(['zipcode','week_start']).any()
        assert d.week_start.dt.dayofweek.eq(0).all()
        assert d.days_in_source.between(1,7).all()
        assert d.days_observed.le(d.days_in_source).all()
        assert d.facility_days_rate_valid.le(d.facility_days_reported).all()
        assert d.reporting_fraction.between(0,1).all()
        den=d.resident_days_rate_valid.where(d.resident_days_rate_valid.gt(0))
        assert np.allclose(d.total_nurse_hours_per_resident_day,d.total_nurse_hours/den,equal_nan=True,atol=1e-7)
        totals['rows']+=len(d);totals['resident_days']+=d.resident_days_reported.sum()
        totals['hours']+=d.total_nurse_hours.sum();totals['reported']+=d.facility_days_reported.sum()
        totals['valid']+=d.facility_days_rate_valid.sum();totals['complete']+=int(d.complete_reporting_week.sum())
        zips.update(d.zipcode)
        # April 1 2017 is a quarter boundary inside a Monday-start week.
        b=d[(d.zipcode=='02138') & (d.week_start==pd.Timestamp('2017-03-27'))]
        if len(b):boundaries.append(b)
    assert np.isclose(totals['resident_days'],sum(a['reported_resident_days'] for a in audits),rtol=1e-12)
    assert np.isclose(totals['hours'],sum(a['total_nurse_hours'] for a in audits),rtol=1e-12)
    assert totals['reported']==sum(a['matched_rows'] for a in audits)
    # Independently select one ZIP/week from raw files, including both quarters.
    raw_parts=[]
    for q in ['2017Q1','2017Q2']:
        cw=pd.read_csv(ROOT/f'crosswalk_{q}.csv',dtype={'zipcode':str,'provnum':str})
        ids=set(cw.loc[cw.zipcode=='02138','provnum'])
        for d in pd.read_csv(ROOT/f'source/pbj_{q}.csv.gz',dtype={'provnum':str},chunksize=200000,encoding='latin1'):
            d=d[d.provnum.isin(ids)&d.workdate.between(20170327,20170402)].copy()
            if not len(d):continue
            if 'hrs_rndon' not in d:d['hrs_rndon']=d.hrs_rn_donadmin
            cols=['hrs_rndon','hrs_rnadmin','hrs_rn','hrs_lpn_admin','hrs_lpn','hrs_cna','hrs_na_trn','hrs_medaide']
            eligible=d.mdscensus.gt(0)&d[cols].notna().all(axis=1)
            raw_parts.append((d.mdscensus.sum(),d.loc[eligible,cols].sum().sum(),len(d)))
    assert len(boundaries)==1 and raw_parts
    b=boundaries[0].iloc[0]
    assert b.days_in_source==7
    assert np.isclose(b.resident_days_reported,sum(x[0] for x in raw_parts))
    assert np.isclose(b.total_nurse_hours,sum(x[1] for x in raw_parts))
    assert b.facility_days_reported==sum(x[2] for x in raw_parts)
    expected=hashlib.sha256();actual=hashlib.sha256()
    for i,path in enumerate(sorted((ROOT/'weekly').glob('*.csv.gz'))):
        with gzip.open(path,'rb') as f:
            if i:f.readline()
            for chunk in iter(lambda:f.read(1024*1024),b''):expected.update(chunk)
    with gzip.open(ROOT/'pbj_zip_weekly.csv.gz','rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):actual.update(chunk)
    assert actual.digest()==expected.digest()
    hashes=[]
    for r in manifest:
        p=ROOT/r['file'];h=hashlib.sha256()
        with p.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
        hashes.append(dict(file=r['file'],bytes=p.stat().st_size,sha256=h.hexdigest()))
    (ROOT/'source/checksums.json').write_text(json.dumps(hashes,indent=2))
    facilities=set()
    for r in manifest:
        if r['kind']=='pbj':
            cw=pd.read_csv(ROOT/f'crosswalk_{r["quarter"]}.csv',dtype={'provnum':str,'zipcode':str})
            facilities.update(cw.loc[cw.zipcode.notna(),'provnum'])
    result=dict(status='passed',quarters=len(audits),weekly_rows=totals['rows'],zipcodes=len(zips),
        validated_at_utc=datetime.now(timezone.utc).isoformat(),
        software=dict(python=platform.python_version(),pandas=pd.__version__,numpy=np.__version__),
        daily_rows=sum(a['daily_rows'] for a in audits),matched_unique_facilities=len(facilities),
        first_date=min(a['start'] for a in audits),last_date=max(a['end'] for a in audits),
        input_facility_days=sum(a['input_rows'] for a in audits),mapped_facility_days=int(totals['reported']),
        matched_fraction=totals['reported']/sum(a['input_rows'] for a in audits),
        rate_valid_fraction=totals['valid']/totals['reported'],
        complete_week_fraction=totals['complete']/totals['rows'],
        cross_quarter_raw_check='02138, week starting 2017-03-27: passed',
        combined_file_matches_partitions=True,
        source_files_hashed=len(hashes))
    (ROOT/'validation.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
