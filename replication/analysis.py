from pathlib import Path
import pandas as pd, numpy as np, json, hashlib
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parent
D=ROOT/'data'; O=ROOT/'output'; C=ROOT/'charts'
for p in [D,O,C]:p.mkdir(exist_ok=True)
x=pd.read_excel(D/'imf.xlsx',header=None)
dates=pd.to_datetime(x.iloc[4:,0].str.replace('M','-',regex=False)+'-01')
cols={'REE':92,'Lit':90,'Kobalt':75,'Nikiel':43,'Miedz':29,'Platyna':79,'Pallad':78,'Krzem':93,'Zloto':76,'Brent':45}
names={'REE':'Ziemie rzadkie','Lit':'Lit','Kobalt':'Kobalt','Nikiel':'Nikiel','Miedz':'Miedź','Platyna':'Platyna','Pallad':'Pallad','Krzem':'Krzem','Zloto':'Złoto','Brent':'Brent'}
p=pd.DataFrame({k:pd.to_numeric(x.iloc[4:,j],errors='coerce').values for k,j in cols.items()},index=dates)
g=pd.read_excel(D/'gpr.xls').set_index('month')[['GPR','GPRT','GPRA','GPRC_CHN']]
levels=p.join(g).loc['2012-06-01':'2026-08-01'].copy();assert not levels.isna().any().any();assert (levels>0).all().all()
r=100*np.log(levels[list(cols)]).diff()
q=np.log1p(levels[['GPR','GPRT','GPRA','GPRC_CHN']]).diff()
z=(q-q.mean())/q.std(ddof=1);z.columns=['z','zt','za','zc']
df=levels.join(r.add_prefix('r_')).join(z).iloc[1:]
assets=list(cols)[:8]; df.to_csv(O/'dane_miesieczne.csv',index_label='month')
levels.to_csv(O/'poziomy.csv',index_label='month')
meta={k:{'column_zero_based':j,'source_header':str(x.iloc[1,j]),'source_code':str(x.iloc[0,j])} for k,j in cols.items()}
json.dump(meta,open(O/'slownik_danych.json','w'),ensure_ascii=False,indent=2)
# OLS + Bartlett HAC, finite sample n/(n-k), asymptotic normal p-values.
def fit(y,X,L=3):
 t=pd.concat([y.rename('y'),X],axis=1).dropna(); Y=t.pop('y').to_numpy(float); X=t.to_numpy(float); X=np.column_stack([np.ones(len(Y)),X]); n,k=X.shape
 b=np.linalg.lstsq(X,Y,rcond=None)[0]; e=Y-X@b; bread=np.linalg.inv(X.T@X); v=X*e[:,None]; S=v.T@v
 scores=pd.DataFrame(v,index=t.index).reindex(pd.date_range(t.index.min(),t.index.max(),freq="MS"),fill_value=0).to_numpy()
 for lag in range(1,min(L,n-1)+1):
  A=scores[lag:].T@scores[:-lag];S+=(1-lag/(L+1))*(A+A.T)
 cov=bread@S@bread*n/(n-k);se=np.sqrt(np.maximum(np.diag(cov),0));pv=2*stats.norm.sf(np.abs(b/se)); R2=1-e@e/np.sum((Y-Y.mean())**2)
 return dict(beta=b[1],se=se[1],p=pv[1],lo=b[1]-1.96*se[1],hi=b[1]+1.96*se[1],n=n,R2=R2),b

def design(a,zcol='z',lag=False,control=False):
 X=pd.DataFrame({'z':df[zcol].shift(1) if lag else df[zcol], 'r_lag':df['r_'+a].shift(1)},index=df.index)
 if control:
  X['Brent']=df.r_Brent;X['Zloto']=df.r_Zloto
 return X
rows=[]
for a in assets:
 for m,lag,ctrl in [('Biezacy',False,False),('Warunkowy',False,True),('Predykcyjny',True,False)]:
  o,b=fit(df['r_'+a],design(a,lag=lag,control=ctrl));rows.append(dict(asset=a,model=m,**o))
res=pd.DataFrame(rows)
# Holm correction separately within each family of eight tests, arbitrary dependence.
def holm(p):
 p=np.array(p);order=np.argsort(p);out=np.empty(len(p));out[order]=np.minimum(1,np.maximum.accumulate(p[order]*(len(p)-np.arange(len(p)))));return out
for m in res.model.unique():
 ix=res.model==m;res.loc[ix,'p_holm']=holm(res.loc[ix,'p'])
res.to_csv(O/'regresje.csv',index=False)
desc=[]
for a in assets:
 s=df['r_'+a];desc.append(dict(asset=a,n=len(s),mean=s.mean(),sd=s.std(),min=s.min(),max=s.max(),skew=s.skew(),kurt=s.kurt(),acf1=s.autocorr(),cum=100*(levels[a].iloc[-1]/levels[a].iloc[0]-1),corr=s.corr(df.z),spearman=stats.spearmanr(s,df.z).statistic))
desc=pd.DataFrame(desc);desc.to_csv(O/'statystyki.csv',index=False)
# robustness: same standardization full sample; no transformed time index.
rob=[]
for a in assets:
 for variant in ['HAC6','HAC12','Winsor1','Bez2022','Do2019','Od2020','GPRT','GPRA','Chiny','AsymPlus','AsymMinus','AbsReturn']:
  X=design(a);y=df['r_'+a].copy();L=3
  if variant.startswith('HAC'):L=int(variant[3:])
  if variant=='Winsor1':
   y=y.clip(y.quantile(.01),y.quantile(.99));X['r_lag']=y.shift(1);X['z']=df.z.clip(df.z.quantile(.01),df.z.quantile(.99))
  if variant=='Bez2022':y=y.where(df.index.year!=2022)
  if variant=='Do2019':y=y.where(df.index.year<=2019)
  if variant=='Od2020':y=y.where(df.index.year>=2020)
  if variant in ['GPRT','GPRA','Chiny']:X=design(a,{'GPRT':'zt','GPRA':'za','Chiny':'zc'}[variant])
  if variant in ['AsymPlus','AsymMinus']:
   pos=df.z.clip(lower=0);neg=df.z.clip(upper=0)
   X=pd.DataFrame({'z':pos if variant=='AsymPlus' else neg,'other':neg if variant=='AsymPlus' else pos,'r_lag':df['r_'+a].shift(1)})
  if variant=='AbsReturn': y=y.abs();X['r_lag']=y.shift(1)
  o,b=fit(y,X,L);rob.append(dict(asset=a,variant=variant,**o))
rob=pd.DataFrame(rob);rob.to_csv(O/'odpornosc.csv',index=False)
# Local projections cumulative from t-1 through t+h, with lagged returns and GPR changes.
lp=[]
for a in assets:
 X=design(a);X['z_lag']=df.z.shift(1)
 for h in range(13):
  Y=100*(np.log(levels[a]).shift(-h)-np.log(levels[a]).shift(1)).reindex(df.index)
  o,b=fit(Y,X,max(3,h+1));lp.append(dict(asset=a,h=h,**o))
lp=pd.DataFrame(lp);lp.to_csv(O/'projekcje_lokalne.csv',index=False)
# expanding forecasts: at t-1 use z[t-2], return[t-2]; one-month publication buffer.
fcasts=[]
for a in assets:
 T=pd.DataFrame({'y':df['r_'+a],'z':df.z.shift(2),'r':df['r_'+a].shift(2)}).dropna()
 for i in range(85,len(T)):
  tr=T.iloc[:i-1];te=T.iloc[i];nt=len(tr);X=np.column_stack([np.ones(nt),tr[['z','r']]])
  b=np.linalg.lstsq(X,tr.y,rcond=None)[0];br=np.linalg.lstsq(np.column_stack([np.ones(nt),tr.r]),tr.y,rcond=None)[0]
  fcasts.append(dict(asset=a,date=T.index[i],actual=te.y,forecast=np.array([1,te.z,te.r])@b,baseline=tr.y.mean(),ar=np.array([1,te.r])@br))
fcasts=pd.DataFrame(fcasts);fcasts.to_csv(O/'prognozy.csv',index=False)
fs=[]
for a,t in fcasts.groupby('asset',sort=False):
 mse=np.mean((t.actual-t.forecast)**2);fs.append(dict(asset=a,n=len(t),R2_oos=1-mse/np.mean((t.actual-t.baseline)**2),R2_vs_ar=1-mse/np.mean((t.actual-t.ar)**2),RMSE=np.sqrt(mse)))
fs=pd.DataFrame(fs);fs.to_csv(O/'ocena_prognoz.csv',index=False)
# Descriptive high-GPR regime comparisons.
cut=df.GPR.quantile(.8);reg=[]
for a in assets:
 for high in [False,True]:
  s=df.loc[(df.GPR>=cut)==high,'r_'+a];reg.append(dict(asset=a,high=high,n=len(s),mean=s.mean(),sd=s.std(),meanabs=s.abs().mean()))
reg=pd.DataFrame(reg);reg.to_csv(O/'re zimy.csv'.replace(' ',''),index=False)
# plots
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,'grid.alpha':.2,'figure.dpi':150})
def save(name):plt.savefig(C/(name+'.png'),bbox_inches='tight',dpi=180);plt.close()
fig,axs=plt.subplots(2,1,figsize=(9,6),sharex=True)
for k in ['GPR','GPRT','GPRA']:axs[0].plot(df.index,df[k],label=k,lw=1)
axs[0].legend(ncol=3);axs[0].set_ylabel('Punkty indeksu');axs[1].bar(df.index,df.z,width=22,color='#22577a');axs[1].set_ylabel('Zmiana GPR [SD]');save('01_gpr')
fig,axs=plt.subplots(2,1,figsize=(9,6),sharex=True)
for i,group in enumerate([assets[:4],assets[4:]]):
 for a in group:axs[i].plot(levels.index,levels[a]/levels[a].iloc[0]*100,label=names[a])
 axs[i].legend(ncol=4);axs[i].set_ylabel('Czerwiec 2012 = 100');axs[i].set_yscale('log')
save('02_ceny')
fig,axs=plt.subplots(2,2,figsize=(9,6))
for ax,a in zip(axs.flat,assets[:4]):
 ax.scatter(df.z,df['r_'+a],s=14,alpha=.6);b=np.polyfit(df.z,df['r_'+a],1);xx=np.linspace(df.z.min(),df.z.max(),100);ax.plot(xx,np.polyval(b,xx),color='#ad4b36');ax.set_title(names[a]);ax.set_xlabel('Zmiana GPR [SD]');ax.set_ylabel('Zmiana ceny [% log]')
plt.tight_layout();save('03_scatter')
fig,ax=plt.subplots(figsize=(9,4.5));m=res[res.model=='Biezacy'].set_index('asset').loc[assets]
ax.errorbar(m.beta,np.arange(8),xerr=1.96*m.se,fmt='o',capsize=4,color='#22577a');ax.set_yticks(range(8),[names[a] for a in assets]);ax.axvline(0,color='black',lw=1);ax.set_xlabel('Współczynnik na 1 SD zmiany GPR [pkt proc. log]');ax.invert_yaxis();save('04_beta')
fig,axs=plt.subplots(2,2,figsize=(9,6),sharex=True)
for ax,a in zip(axs.flat,['REE','Lit','Kobalt','Nikiel']):
 t=lp[lp.asset==a];ax.plot(t.h,t.beta,color='#22577a');ax.fill_between(t.h,t.lo,t.hi,alpha=.18,color='#22577a');ax.axhline(0,color='black',lw=.7);ax.set_title(names[a]);ax.set_xlabel('Horyzont h [miesiące]');ax.set_ylabel('Skumulowana zmiana [% log]')
plt.tight_layout();save('05_lp')
fig,ax=plt.subplots(figsize=(9,4.5))
for a in ['REE','Lit','Kobalt','Miedz']:ax.plot(df.index,df['r_'+a].rolling(36).corr(df.z),label=names[a])
ax.legend(ncol=4);ax.axhline(0,color='black',lw=.8);ax.set_ylabel('Korelacja Pearsona w oknie 36 miesięcy');save('06_rolling')
fig,ax=plt.subplots(figsize=(9,4.5));t=rob[(rob.asset=='REE') & ~rob.variant.isin(['AsymPlus','AsymMinus','AbsReturn'])]
ax.errorbar(t.beta,np.arange(len(t)),xerr=1.96*t.se,fmt='o',capsize=4);ax.set_yticks(range(len(t)),t.variant);ax.axvline(0,color='black',lw=.8);ax.set_xlabel('Współczynnik i punktowy przedział 95%');ax.invert_yaxis();save('07_robust')
fig,ax=plt.subplots(figsize=(9,4.5));ax.bar(np.arange(8)-.18,100*fs.R2_oos,.36,label='Wobec średniej historycznej');ax.bar(np.arange(8)+.18,100*fs.R2_vs_ar,.36,label='Wobec modelu z opóźnioną stopą');ax.set_xticks(range(8),[names[a] for a in fs.asset],rotation=20);ax.set_ylabel('R² poza próbą [%]');ax.axhline(0,color='black',lw=.8);ax.legend();save('08_forecast')
manifest={'download_date':'2026-11-17','start':'2012-06','end':'2026-08','return_n':len(df),'gpr_change_sd':float(q.GPR.std()),'high_gpr_threshold':cut,'sources':{'gpr':'https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls','imf':'https://www.imf.org/-/media/files/research/commodityprices/monthly/external-data.xlsx'},'sha256':{f:hashlib.sha256((D/f).read_bytes()).hexdigest() for f in ['gpr.xls','imf.xlsx']}}
json.dump(manifest,open(O/'manifest.json','w'),indent=2)
print(desc.round(3).to_string(index=False));print(res.round(4).to_string(index=False));print(fs.round(4).to_string(index=False));print(rob[rob.asset=='REE'].round(4).to_string(index=False));print('LP REE',lp[lp.asset=='REE'].round(3).to_string(index=False))
