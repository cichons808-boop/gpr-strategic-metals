from pathlib import Path
import re,json,urllib.request,concurrent.futures
import pandas as pd
from bs4 import BeautifulSoup
R=Path(__file__).resolve().parent;D=R/'raw'
s=(D/'guk.html').read_text();config=json.JSONDecoder().raw_decode(s.split('const CONFIG=')[1])[0]
p=pd.DataFrame(index=pd.to_datetime(config['months'],format='%b %Y'))
for key in ['neodymium','samarium']:p[key]=json.loads(re.search("id:'"+key+"'.*?values:(\\[[^\\]]*\\])",s).group(1))
p.to_csv(D/'guk_prices.csv',index_label='month')
s=BeautifulSoup((D/'sdm_official_alt.html').read_text(),'html.parser')
texts=[]
for a in s.select('[data-clipboard-text]'):
 txt=a.get('data-clipboard-text');texts.append(txt)
 print('SDM',a.get('data-visualizer-chart-id'),len(txt),txt[-120:])
assert texts
(D/'prnd_long.csv').write_text(max(texts,key=len))
def dl(ticker):
 path=D/(ticker.replace('.','_')+'.json')
 if path.exists() and path.read_text().startswith('{"chart"'):return (ticker,'cached')
 u='https://query2.finance.yahoo.com/v8/finance/chart/'+ticker+'?period1=1230768000&period2=1794873600&interval=1mo'
 try:
  b=urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=30).read();x=json.loads(b);assert x['chart']['result'];path.write_bytes(b);return (ticker,len(x['chart']['result'][0]['timestamp']))
 except Exception as e:return (ticker,str(e))
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:print(list(ex.map(dl,['REMX','SPY','EEM','LIT','COPX','MP','LYC.AX'])))
