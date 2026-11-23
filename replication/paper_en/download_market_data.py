from pathlib import Path
import urllib.request,json,concurrent.futures
R=Path(__file__).resolve().parent/'raw'
def get(ticker):
 u='https://query2.finance.yahoo.com/v8/finance/chart/'+ticker+'?period1=1230768000&period2=1793491200&interval=1d'
 try:
  b=urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=35).read();x=json.loads(b);assert x['chart']['result'];(R/(ticker+'_daily.json')).write_bytes(b);return (ticker,len(x['chart']['result'][0]['timestamp']))
 except Exception as e:return(ticker,str(e))
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:print(list(ex.map(get,['REMX','LIT','COPX','SPY'])))
u='https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF&cosd=2009-01-01&coed=2026-10-31'
try:
 b=urllib.request.urlopen(u,timeout=30).read();(R/'DFF.csv').write_bytes(b);print('DFF',len(b),b[:100])
except Exception as e:print('DFF',e)
