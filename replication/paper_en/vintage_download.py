from pathlib import Path
import pandas as pd,json,concurrent.futures,urllib.request
R=Path(__file__).resolve().parent;D=R/'raw/vintages';D.mkdir(exist_ok=True)
items=json.load(open(R/'raw/gpr_archive_list.json'));items=[x for x in items if x['name'].startswith('data_gpr_export_') and x['name'].endswith('.dta') and '202202'<=x['name'][-10:-4]<='202610']
def get(x):
 path=D/x['name']
 try:
  if not path.exists():
   b=urllib.request.urlopen(x['download_url'],timeout=30).read();path.write_bytes(b)
  d=pd.read_stata(path);return dict(vintage=x['name'][-10:-4],n=len(d),last=str(d.month.max()),ok=True)
 except Exception as e:return dict(vintage=x['name'][-10:-4],ok=False,error=str(e))
results=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
 for i,x in enumerate(ex.map(get,items)):
  results.append(x)
  if (i+1)%10==0:print('Processed',i+1,'of',len(items),flush=True)
pd.DataFrame(results).to_csv(R/'results/vintage_download_log.csv',index=False);print(pd.DataFrame(results).tail().to_string(index=False));print('Failures',[x for x in results if not x['ok']])
