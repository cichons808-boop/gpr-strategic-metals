from pathlib import Path
import pandas as pd,numpy as np,statsmodels.api as sm,warnings,json
from scipy.optimize import linprog
warnings.filterwarnings('ignore');R=Path(__file__).resolve().parent;O=R/'results';rng=np.random.default_rng(112026)
r=pd.read_csv(O/'returns.csv',index_col=0,parse_dates=True);g=pd.read_csv(O/'gpr.csv',index_col=0,parse_dates=True)
lg=np.log1p(g.GPRC_CHN);dg=lg.diff();sd=dg.loc[:'2022'].std();z=(dg-dg.loc[:'2022'].mean())/sd;threshold=lg.loc[:'2022'].quantile(.8);H=(lg.shift()>threshold).astype(int)
X=pd.DataFrame({'z':z,'H':H,'zH':z*H,'lag':r.PrNd.shift()});t=pd.concat([r.PrNd.rename('y'),X],axis=1).dropna();t.to_csv(O/'prnd_regime_design.csv')
def ols(t,L=3):
 f=sm.OLS(t.y,sm.add_constant(t.drop(columns='y'))).fit(cov_type='HAC',cov_kwds={'maxlags':L,'use_correction':True});s=f.t_test(np.array([0,1,0,1,0]));return {'low':f.params.z,'high':float(s.effect[0]),'se':float(s.sd[0,0]),'p':float(s.pvalue),'diff':f.params.zH,'p_diff':f.pvalues.zH,'n':len(t),'nhigh':int(t.H.sum())}
res=[]
for label,sub in [('all',t),('discovery',t.loc[:'2022']),('test',t.loc['2023':]),('without2010_11',t.loc['2012':]),('without2022',t[t.index.year!=2022]),('without2020_22',t[~t.index.year.isin([2020,2021,2022])])]:res.append({'variant':label,**ols(sub)})
for year in sorted(t.index.year.unique()):res.append({'variant':'leave_'+str(year),**ols(t[t.index.year!=year])})
for q in [.7,.8,.9]:
 h=(lg.shift()>lg.loc[:'2022'].quantile(q)).astype(int);u=t.copy();u.H=h.reindex(u.index);u.zH=u.z*u.H;res.append({'variant':'threshold_'+str(q),**ols(u)})
for L in [6,12]:res.append({'variant':'HAC_'+str(L),**ols(t,L)})
pd.DataFrame(res).to_csv(O/'prnd_robustness.csv',index=False)
def indices(n,L):return np.concatenate([(rng.integers(n)+np.arange(L))%n for _ in range(int(np.ceil(n/L)))])[:n]
boots=[]
for L in [6,12]:
 arr=t.to_numpy();n=len(arr);est=[]
 for b in range(1999):
  u=arr[indices(n,L)];coef=np.linalg.lstsq(np.column_stack([np.ones(n),u[:,1:]]),u[:,0],rcond=None)[0];est.append([coef[1]+coef[3],coef[3]])
 for j,label in enumerate(['high','difference']):
  vals=np.array(est)[:,j];boots.append({'model':'PrNd_state','parameter':label,'block':L,'B':1999,'lo':np.quantile(vals,.025),'median':np.median(vals),'hi':np.quantile(vals,.975),'fraction_nonpositive':np.mean(vals<=0)})
def qr(y,x,tau):
 n,k=x.shape;c=np.r_[np.zeros(k),np.full(n,tau),np.full(n,1-tau)];A=np.column_stack([x,np.eye(n),-np.eye(n)]);ans=linprog(c,A_eq=A,b_eq=y,bounds=[(None,None)]*k+[(0,None)]*(2*n),method='highs');assert ans.success;return ans.x[:k]
x=(lg-lg.loc[:'2022'].mean())/lg.loc[:'2022'].std();u=pd.concat([r.REE.rename('y'),x.rename('x'),r.REE.shift().rename('lag')],axis=1).dropna();u.to_csv(O/'ree_quantile_design.csv');y=u.y.to_numpy();xx=sm.add_constant(u[['x','lag']]).to_numpy();exact=qr(y,xx,.9)
for L in [6,12]:
 est=[]
 for b in range(499):
  ix=indices(len(u),L);est.append(qr(y[ix],xx[ix],.9)[1])
 vals=np.array(est);boots.append({'model':'REE_q90','parameter':'beta','block':L,'B':499,'lo':np.quantile(vals,.025),'median':np.median(vals),'hi':np.quantile(vals,.975),'fraction_nonpositive':np.mean(vals<=0)})
pd.DataFrame(boots).to_csv(O/'candidate_bootstrap.csv',index=False)
json.dump({'prnd_SD_change_log1p_GPR_CHN':sd,'threshold_GPR_CHN':float(np.expm1(threshold)),'state_calibration':'2009-01 through 2022-12','seed':112026,'exact_qr90_beta':exact.tolist()},open(O/'candidate_settings.json','w'),indent=2)
print(pd.DataFrame(res).round(4).to_string(index=False));print(pd.DataFrame(boots).round(4).to_string(index=False))
