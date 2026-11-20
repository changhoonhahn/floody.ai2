"""Download public CMS source files using the saved catalogs; resumable.

If the saved CMS catalog (source/cms_catalog.json) is not in PBJ_DATA_DIR, the
frozen 2026-10-15 file list shipped in bin/data/pbj_sources/manifest.json is
used instead, so the original source selection is reproduced exactly."""
import concurrent.futures
import gzip
import json
import os
from pathlib import Path
import shutil
import urllib.request

ROOT = Path(os.environ.get('PBJ_DATA_DIR', '/Users/chang/data/ai2/pbj')).expanduser()

def manifest():
    catalog = json.loads((ROOT/'source/cms_catalog.json').read_text())['dataset']
    archives = json.loads((ROOT/'source/provider_archive_index.json').read_text())['data']
    archives = [x for x in archives if x['type'] == 'theme']
    rows = []
    import datetime as dt
    selected = {}
    for d in catalog:
        if d['title'].startswith('Payroll Based Journal Daily Nurse Staffing :'):
            t = d['temporal'][0]
            start = t['startDate']; q = f'{start[:4]}Q{(int(start[5:7])-1)//3+1}'
            url = next(x['downloadURL'] for x in d['distribution'] if x.get('format') == 'CSV')
            rows.append(dict(kind='pbj', quarter=q, start=start, end=t['endDate'], url=url,
                             file=f'source/pbj_{q}.csv.gz', modified=d['modified']))
            if start[:4] >= '2019':
                mid = dt.date.fromisoformat(start) + dt.timedelta(days=45)
                a = min(archives, key=lambda x: abs((dt.date.fromisoformat(x['date'])-mid).days))
                selected[a['date']] = dict(kind='provider', date=a['date'],
                    url='https://data.cms.gov'+a['url'], file=f"source/providers_{a['date']}.zip")
        if d['title'].startswith('Provider of Services File - Quality Improvement and Evaluation System :'):
            if d['temporal'][0]['endDate'][:4] in ['2017','2018']:
                year=d['temporal'][0]['endDate'][:4]
                url=next(x['downloadURL'] for x in d['distribution'] if x.get('format')=='CSV')
                rows.append(dict(kind='pos', date=f'{year}-12-31', url=url, file=f'source/pos_{year}.csv.gz'))
    rows += list(selected.values())
    (ROOT/'source/manifest.json').write_text(json.dumps(rows, indent=2))
    return rows

def fetch(row):
    p=ROOT/row['file']
    if p.exists(): return f"cached {p.name}"
    temp=p.with_suffix(p.suffix+'.part')
    for attempt in range(3):
        try:
            req=urllib.request.Request(row['url'], headers={'User-Agent':'Research PBJ aggregation/1.0'})
            with urllib.request.urlopen(req, timeout=180) as src:
                with (gzip.open(temp,'wb',compresslevel=1) if p.name.endswith('.gz') else open(temp,'wb')) as dst:
                    shutil.copyfileobj(src,dst,1024*1024)
            temp.replace(p)
            return f"downloaded {p.name} ({p.stat().st_size//1024//1024} MB)"
        except Exception:
            if attempt==2: raise

if __name__=='__main__':
    shipped=Path(__file__).with_name('pbj_sources')/'manifest.json'
    (ROOT/'source').mkdir(parents=True, exist_ok=True)
    if (ROOT/'source/cms_catalog.json').exists():
        rows=manifest()
    else:
        rows=json.loads(shipped.read_text())
        shutil.copy(shipped, ROOT/'source/manifest.json')
        print(f'no saved CMS catalog; using frozen manifest {shipped}',flush=True)
    print(f'{len(rows)} source files',flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        jobs=[pool.submit(fetch,r) for r in rows]
        for job in concurrent.futures.as_completed(jobs): print(job.result(),flush=True)
