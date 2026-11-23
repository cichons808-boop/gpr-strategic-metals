from pathlib import Path
import numpy as np,pandas as pd,json,statsmodels.api as sm
from statsmodels.stats.multitest import multipletests
R=Path(__file__).resolve().parent;D=R/'raw';O=R/'results'
g=pd.read_excel(R.parent/'data/gpr.xls').set_index('month')[['GPR','GPRT','GPRA','GPRC_CHN']].loc['2009-01-01':'2026-10-01']
p=pd.read_csv(R.parent/'output/poziomy.csv',index_col=0,parse_dates=True).iloc[:,:10]
p=p.join(pd.read_csv(D/'guk_prices.csv',index_col=0,parse_dates=True),how='outer')
prnd=pd.read_csv(D/'prnd_long.csv',skiprows=[1]);prnd.columns=['date','PrNd'];prnd.date=pd.to_datetime(prnd.date);prnd=prnd.sort_values('date').drop_duplicates('date').set_index('date').loc[:'2026-01-31'];p=p.join(prnd.resample('MS').mean(),how='outer')
for a in ['REMX','LIT','COPX','MP','LYC.AX','SPY','EEM']:
 d=json.load(open(D/(a.replace('.','_')+'.json')))['chart']['result'][0];idx=pd.to_datetime(d['timestamp'],unit='s',utc=True).tz_convert('America/New_York' if a!='LYC.AX' else 'Australia/Sydney').tz_localize(None).to_period('M').to_timestamp();s=pd.Series(d['indicators']['adjclose'][0]['adjclose'],index=idx,name=a);s=s[~s.index.duplicated(keep='last')].loc[:'2026-10-01'];p=p.join(s,how='outer')
p=p.loc['2009-01-01':'2026-10-01'];rets=100*np.log(p).diff();rets.to_csv(O/'returns.csv');p.to_csv(O/'prices.csv');g.to_csv(O/'gpr.csv')
assets=[a for a in p if a not in ['Brent','Zloto','SPY','EEM']];rows=[]
for a in assets:
 for gi in ['GPR','GPRC_CHN']:
  for transform in ['level','change']:
   x=np.log1p(g[gi]);x=x if transform=='level' else x.diff();x=(x-x.loc[:'2022-12-01'].mean())/x.loc[:'2022-12-01'].std()
   for lag in [0,1]:
    for dep in ['return','amplitude']:
     y=rets[a] if dep=='return' else rets[a].abs();X=pd.DataFrame({'x':x.shift(lag),'ylag':y.shift(1)})
     if a in ['REMX','LIT','COPX','MP','LYC.AX']:
      X['SPY']=rets.SPY if dep=='return' else rets.SPY.abs();X['EEM']=rets.EEM if dep=='return' else rets.EEM.abs()
     t=pd.concat([y.rename('y'),X],axis=1).dropna()
     for sample,sub in [('discovery',t.loc[:'2022-12-01']),('test',t.loc['2023-01-01':]),('full',t)]:
      if len(sub)<24:continue
      f=sm.OLS(sub.y,sm.add_constant(sub.drop(columns='y'))).fit(cov_type='HAC',cov_kwds={'maxlags':3,'use_correction':True})
      rows.append(dict(asset=a,gpr=gi,transform=transform,lag=lag,dep=dep,sample=sample,n=len(sub),beta=f.params.x,se=f.bse.x,p=f.pvalues.x,lo=f.conf_int().loc['x',0],hi=f.conf_int().loc['x',1],R2=f.rsquared))
r=pd.DataFrame(rows)
for sample in r['sample'].unique():
 ix=r['sample']==sample;r.loc[ix,'q_BH']=multipletests(r.loc[ix,'p'],method='fdr_bh')[1];r.loc[ix,'p_Holm']=multipletests(r.loc[ix,'p'],method='holm')[1]
r.to_csv(O/'screen.csv',index=False);print('Specifications',len(r.query('sample=="discovery"')));print(p[['PrNd','neodymium','samarium','REMX']].count().to_dict())
