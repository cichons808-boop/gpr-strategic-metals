"""Download additional primary-source data without changing the original snapshots."""
from pathlib import Path
import concurrent.futures,json,urllib.request
import pandas as pd

R=Path(__file__).resolve().parent;D=R/'raw';D.mkdir(exist_ok=True)
series=['TWEXBGSMTH','IGREA','CHNLOLITOAASTSAM','CHNPRINTO01IXPYM']
urls={s+'.csv':'https://fred.stlouisfed.org/graph/fredgraph.csv?id='+s+'&cosd=1999-01-01&coed=2026-10-31' for s in series}
urls.update({
 'FF5_daily.zip':'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip',
 'MOM_daily.zip':'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_daily_CSV.zip',
 'EEM_daily.json':'https://query2.finance.yahoo.com/v8/finance/chart/EEM?period1=1230768000&period2=1793491200&interval=1d',
})
def download(item):
    name,url=item;path=D/name
    if not path.exists():
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req,timeout=40) as response:path.write_bytes(response.read())
    result={'name':name,'url':url,'bytes':path.stat().st_size}
    if name.endswith('.csv'):
        x=pd.read_csv(path,index_col=0,parse_dates=True);x=x.apply(pd.to_numeric,errors='coerce').dropna();result.update(first=str(x.index.min().date()),last=str(x.index.max().date()),n=len(x))
    return result
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:results=list(ex.map(download,urls.items()))
(D/'source_downloads.json').write_text(json.dumps(results,indent=2))
for row in results:print(json.dumps(row))
