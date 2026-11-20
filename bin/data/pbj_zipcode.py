"""Compile CMS PBJ nurse staffing to facility-ZIP daily and weekly panels.

Run pbj_download.py first. No patient-level information is used.
"""
import argparse
import gzip
import json
import os
import re
import shutil
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(os.environ.get('PBJ_DATA_DIR', '/Users/chang/data/ai2/pbj')).expanduser()
HOURS = ['hrs_rndon','hrs_rnadmin','hrs_rn','hrs_lpnadmin','hrs_lpn',
         'hrs_cna','hrs_natrn','hrs_medaide']
ALIASES = {'hrs_rn_donadmin':'hrs_rndon', 'hrs_lpn_admin':'hrs_lpnadmin',
           'hrs_na_trn':'hrs_natrn'}
SUMS = ['facility_days_reported','facility_days_rate_valid','facility_days_zero_census',
        'resident_days_reported','resident_days_rate_valid','rn_hours','lpn_hours',
        'aide_hours','total_nurse_hours','facility_days_location_fallback',
        'facility_days_location_future','facility_days_expected']

def norm(s):
    return re.sub('[^a-z0-9]','',s.lower())

def location_frame(df, date, source):
    lookup={norm(c):c for c in df.columns}
    def col(choices):
        for c in choices:
            if c in lookup: return lookup[c]
        raise ValueError(f'No location column for {choices}; columns={list(df.columns)}')
    cols=[col(['provnum','cmscertificationnumberccn','federalprovidernumber','prvdrnum']),
          col(['zip','zipcode','zipcd','providerzipcode']), col(['state','statecd','providerstate'])]
    x=df[cols].copy();x.columns=['provnum','zipcode','state']
    x=x.fillna('').astype(str).apply(lambda s:s.str.strip())
    x['provnum']=x.provnum.str.replace(r'\.0$','',regex=True).str.zfill(6)
    x['zipcode']=x.zipcode.str.replace(r'\.0$','',regex=True).str.replace('-','').str[:5].str.zfill(5)
    x=x[x.zipcode.str.fullmatch(r'\d{5}') & ~x.zipcode.isin(['00000','99999'])]
    x=x.drop_duplicates()
    if x.duplicated(['provnum','state']).any(): raise ValueError('Conflicting provider ZIPs in snapshot')
    x['snapshot_date']=pd.Timestamp(date);x['location_source']=source
    return x

def locations(manifest):
    frames=[]
    for r in manifest:
        if r['kind']=='pos':
            df=pd.read_csv(ROOT/r['file'],dtype=str,encoding='latin1',low_memory=False)
            frames.append(location_frame(df,r['date'],r['file']))
        elif r['kind']=='provider':
            with zipfile.ZipFile(ROOT/r['file']) as z:
                names=[n for n in z.namelist() if 'providerinfo' in n.lower() and n.lower().endswith('.csv')]
                if len(names)!=1: raise ValueError(f'Provider info ambiguous: {r["file"]}, {names}')
                with z.open(names[0]) as f: df=pd.read_csv(f,dtype=str,encoding='latin1',low_memory=False)
                frames.append(location_frame(df,r['date'],r['file']))
    return pd.concat(frames,ignore_index=True)

def crosswalk(providers, loc, start):
    mid=pd.Timestamp(start)+pd.Timedelta(days=45)
    if mid.year<2019:
        preferred=pd.Timestamp(f'{mid.year}-12-31')
    else:
        dates=loc.loc[loc.location_source.str.contains('providers_'),'snapshot_date'].unique()
        preferred=min(dates,key=lambda d:abs(pd.Timestamp(d)-mid))
    candidates=providers.merge(loc,on=['provnum','state'],how='left')
    candidates['location_lag_days']=(candidates.snapshot_date-mid).dt.days
    candidates['location_fallback']=candidates.snapshot_date.ne(preferred)
    candidates['distance']=candidates.location_lag_days.abs()
    candidates=candidates[candidates.distance.le(366)]
    candidates=candidates.sort_values(['location_fallback','distance','snapshot_date']).drop_duplicates(['provnum','state'])
    return providers.merge(candidates.drop(columns='distance'),on=['provnum','state'],how='left',validate='one_to_one')

def daily_aggregate(df,start,end):
    x=df.copy()
    numeric=['mdscensus']+HOURS
    for c in numeric: x[c]=pd.to_numeric(x[c],errors='raise')
    if (x[numeric]<0).any().any() or np.isinf(x[numeric]).any().any():
        raise ValueError('Negative or infinite census/hours')
    valid=x[numeric].notna().all(axis=1)&x.mdscensus.gt(0)
    x['facility_days_reported']=1
    x['facility_days_rate_valid']=valid.astype(int)
    x['facility_days_zero_census']=x.mdscensus.eq(0).astype(int)
    x['resident_days_reported']=x.mdscensus
    x['resident_days_rate_valid']=x.mdscensus.where(valid,0)
    x['rn_hours']=x[HOURS[:3]].sum(axis=1,min_count=3).where(valid,0)
    x['lpn_hours']=x[HOURS[3:5]].sum(axis=1,min_count=2).where(valid,0)
    x['aide_hours']=x[HOURS[5:]].sum(axis=1,min_count=3).where(valid,0)
    x['total_nurse_hours']=x[['rn_hours','lpn_hours','aide_hours']].sum(axis=1)
    x['facility_days_location_fallback']=x.location_fallback.astype(int)
    x['facility_days_location_future']=x.snapshot_date.gt(x.date).astype(int)
    keys=['zipcode','date']
    daily=x.groupby(keys,observed=True)[SUMS[:-1]].sum(min_count=1)
    roster=x.groupby('zipcode').provnum.nunique()
    full=pd.MultiIndex.from_product([sorted(roster.index),pd.date_range(start,end)],names=keys)
    daily=daily.reindex(full)
    # Missing facility-days are not imputed as observed zero outcomes.
    for c in ['facility_days_reported','facility_days_rate_valid','facility_days_zero_census',
              'facility_days_location_fallback','facility_days_location_future']:
        daily[c]=daily[c].fillna(0).astype(int)
    daily=daily.reset_index()
    daily['facility_days_expected']=daily.zipcode.map(roster).astype(int)
    daily['reporting_fraction']=daily.facility_days_reported/daily.facility_days_expected
    daily['coverage_complete']=daily.facility_days_reported.eq(daily.facility_days_expected)
    add_rates(daily)
    return daily

def add_rates(df):
    den=df.resident_days_rate_valid.where(df.resident_days_rate_valid.gt(0))
    for kind in ['rn','lpn','aide','total_nurse']:
        df[kind+'_hours_per_resident_day']=df[kind+'_hours']/den

def compile_quarter(r,loc):
    q=r['quarter'];out=ROOT/'daily'/f'pbj_zip_daily_{q}.csv.gz'
    auditpath=ROOT/f'audit_{q}.json'
    if out.exists() and auditpath.exists(): return json.loads(auditpath.read_text())
    raw=ROOT/r['file']
    # Read only the 8 category totals; employee/contract splits are not added again.
    df=pd.read_csv(raw,dtype={'provnum':str,'PROVNUM':str},encoding='latin1',
        usecols=lambda c:c.lower() in ['provnum','state','workdate','mdscensus']+HOURS+list(ALIASES),low_memory=False)
    df.columns=[c.lower() for c in df.columns]
    # 2017 Q2 also contains hrs_rn_donadmin next to medication-aide splits.
    # Prefer the explicit canonical total when present; never add both fields.
    for old,new in ALIASES.items():
        if old in df:
            if new in df: df=df.drop(columns=old)
            else: df=df.rename(columns={old:new})
    df['provnum']=df.provnum.astype(str).str.strip().str.zfill(6)
    df['state']=df.state.str.strip()
    df['date']=pd.to_datetime(df.workdate.astype(str),format='%Y%m%d')
    if not df.date.between(r['start'],r['end']).all(): raise ValueError(f'Dates outside {q}')
    if df.duplicated(['provnum','date']).any(): raise ValueError(f'Duplicate facility-days in {q}')
    p=df[['provnum','state']].drop_duplicates()
    cw=crosswalk(p,loc,r['start']);cw['quarter']=q
    cw.to_csv(ROOT/f'crosswalk_{q}.csv',index=False)
    df=df.merge(cw,on=['provnum','state'],how='left',validate='many_to_one')
    matched=df[df.zipcode.notna()].copy()
    daily=daily_aggregate(matched,r['start'],r['end'])
    daily.to_csv(out,index=False,float_format='%.8f',compression={'method':'gzip','compresslevel':1})
    audit=dict(quarter=q,input_rows=len(df),input_facilities=len(p),matched_rows=len(matched),
        matched_facilities=int(cw.zipcode.notna().sum()),unmatched_facilities=cw.loc[cw.zipcode.isna(),'provnum'].tolist(),
        zipcodes=int(daily.zipcode.nunique()),daily_rows=len(daily),start=str(df.date.min().date()),end=str(df.date.max().date()),
        missing_census_rows=int(matched.mdscensus.isna().sum()),
        reported_resident_days=float(matched.mdscensus.sum()),
        rate_valid_resident_days=float(daily.resident_days_rate_valid.sum()),
        total_nurse_hours=float(daily.total_nurse_hours.sum()),
        location_fallback_facilities=int(cw.location_fallback.fillna(False).sum()),
        source_url=r['url'])
    assert np.isclose(daily.resident_days_reported.sum(),matched.mdscensus.sum())
    auditpath.write_text(json.dumps(audit,indent=2))
    print(f'{q}: {len(df):,} rows, {len(matched)/len(df):.2%} mapped, {audit["zipcodes"]:,} ZIPs',flush=True)
    return audit

def weekly(manifest):
    pieces=[]
    for r in manifest:
        if r['kind']!='pbj':continue
        d=pd.read_csv(ROOT/'daily'/f'pbj_zip_daily_{r["quarter"]}.csv.gz',dtype={'zipcode':str},parse_dates=['date'])
        d['week_start']=d.date-pd.to_timedelta(d.date.dt.dayofweek,unit='D')
        d['days_in_source']=1; d['days_observed']=d.facility_days_reported.gt(0).astype(int)
        d['days_complete']=d.coverage_complete.astype(int)
        g=d.groupby(['zipcode','week_start'])
        a=g[SUMS+['days_in_source','days_observed','days_complete']].sum(min_count=1)
        a['observed_start']=g.date.min();a['observed_end']=g.date.max()
        pieces.append(a.reset_index())
    combined=pd.concat(pieces,ignore_index=True)
    g=combined.groupby(['zipcode','week_start'])
    w=g[SUMS+['days_in_source','days_observed','days_complete']].sum(min_count=1)
    w['observed_start']=g.observed_start.min();w['observed_end']=g.observed_end.max()
    w=w.reset_index();add_rates(w)
    w['reporting_fraction']=w.facility_days_reported/w.facility_days_expected
    w['full_week_observed']=w.days_observed.eq(7)
    w['complete_reporting_week']=w.days_complete.eq(7)
    assert w.days_in_source.le(7).all()
    assert not w.duplicated(['zipcode','week_start']).any()
    assert w.reporting_fraction.le(1).all()
    for year,part in w.groupby(w.week_start.dt.year):
        part.to_csv(ROOT/'weekly'/f'pbj_zip_weekly_{year}.csv.gz',index=False,float_format='%.8f',compression={'method':'gzip','compresslevel':1})
    summary=dict(weekly_rows=len(w),zipcodes=w.zipcode.nunique(),start=str(w.observed_start.min().date()),
        end=str(w.observed_end.max().date()),complete_week_fraction=float(w.complete_reporting_week.mean()),
        resident_days=float(w.resident_days_reported.sum()),total_nurse_hours=float(w.total_nurse_hours.sum()))
    (ROOT/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary),flush=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--quarter');parser.add_argument('--weekly-only',action='store_true')
    parser.add_argument('--combine-weekly',action='store_true');a=parser.parse_args()
    if a.combine_weekly:
        combine_weekly();return
    manifest=json.loads((ROOT/'source/manifest.json').read_text())
    if not a.weekly_only:
        history=ROOT/'provider_location_history.csv.gz'
        if history.exists():
            loc=pd.read_csv(history,dtype={'provnum':str,'zipcode':str,'state':str},parse_dates=['snapshot_date'])
        else:
            loc=locations(manifest)
            loc.to_csv(history,index=False,compression='gzip')
        for r in sorted(manifest,key=lambda x:x.get('start','')):
            if r['kind']=='pbj' and (not a.quarter or r['quarter']==a.quarter): compile_quarter(r,loc)
    if not a.quarter:
        weekly(manifest)
        combine_weekly()

def combine_weekly():
    paths=sorted((ROOT/'weekly').glob('pbj_zip_weekly_*.csv.gz'))
    if not paths:raise ValueError('No weekly partitions to combine')
    out=ROOT/'pbj_zip_weekly.csv.gz';temp=out.with_suffix('.gz.part')
    header=None
    with gzip.open(temp,'wb',compresslevel=1) as dst:
        for path in paths:
            with gzip.open(path,'rb') as src:
                current=src.readline()
                if header is None:
                    header=current;dst.write(header)
                elif current!=header:raise ValueError(f'Inconsistent header: {path}')
                shutil.copyfileobj(src,dst,1024*1024)
    temp.replace(out)
    print(f'Combined {len(paths)} weekly partitions into {out}',flush=True)

if __name__=='__main__':main()
