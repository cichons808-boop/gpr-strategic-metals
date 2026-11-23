from pathlib import Path
import json,numpy as np,pandas as pd,statsmodels.api as sm
from scipy.optimize import brentq
from statsmodels.stats.multitest import multipletests
R=Path(__file__).resolve().parent;O=R/'results';D=R/'raw'
(O/'forecast_metrics.jsonl').unlink(missing_ok=True)
g=pd.read_excel(R.parent/'data/gpr.xls').set_index('month')[['GPR','GPRC_CHN']].loc['2009-01-01':'2026-10-01']
prices=[]
for a in ['REMX','LIT','COPX','SPY']:
 d=json.load(open(D/(a+'_daily.json')))['chart']['result'][0]
 idx=pd.to_datetime(d['timestamp'],unit='s',utc=True).tz_convert('America/New_York').tz_localize(None).normalize()
 s=pd.Series(d['indicators']['adjclose'][0]['adjclose'],index=idx,name=a).dropna();assert s.index.is_unique;prices.append(s)
p=pd.concat(prices,axis=1).dropna().loc[:'2026-10-31'];assert (p>0).all().all();p.to_csv(O/'daily_adjusted_prices.csv',index_label='date')
ff=pd.read_csv(D/'DFF.csv',index_col=0,parse_dates=True).iloc[:,0];ff=pd.to_numeric(ff,errors='coerce');cal=pd.date_range(ff.index.min(),p.index.max(),freq='D');ff=ff.reindex(cal).ffill();cashfactor=1+ff.shift(1).bfill()/100/360
cashwealth=cashfactor.cumprod();cashdaily=cashwealth.reindex(p.index).pct_change().fillna(0)
monthly=p.resample('MS').last();lagret=100*np.log(monthly).diff();calibration=g.loc['2009':'2018'];thresholds={c:float(calibration[c].quantile(.8)) for c in g};thresholds_log={c:float(np.log1p(calibration[c]).quantile(.8)) for c in g};rules=['ChinaLow','AvoidChinaHighRising','ChinaHigh','ChinaHighRising','GlobalHighRising','ChinaRising','ARForecast','GPRForecast']

def events_for(delay):
 ev=p.groupby(p.index.to_period('M')).apply(lambda x:x.index[min(delay-1,len(x)-1)]);ev.index=ev.index.to_timestamp();return ev

def positions(asset,delay):
 ev=events_for(delay);rows=[]
 for month,date in ev.items():
  last=month-pd.offsets.MonthBegin(1);prev=last-pd.offsets.MonthBegin(1)
  if last not in g.index or prev not in g.index or last not in lagret.index or not np.isfinite(lagret.loc[last,asset]):continue
  level=float(np.log1p(g.loc[last,'GPRC_CHN']));delta=level-float(np.log1p(g.loc[prev,'GPRC_CHN']));H=int(level>thresholds_log['GPRC_CHN']);dg=float(np.log1p(g.loc[last,'GPR'])-np.log1p(g.loc[prev,'GPR']))
  # All prices used as predictors are from the completed calendar month.
  row=dict(month=month,date=date,info_month=last,level=level,delta=delta,H=H,interaction=delta*H,lagret=float(lagret.loc[last,asset]),cash_forecast=float(ff.shift(1).loc[date]/100*30/360))
  row.update(ChinaLow=1-H,AvoidChinaHighRising=1-int(H and delta>0),ChinaHigh=H,ChinaHighRising=int(H and delta>0),GlobalHighRising=int(np.log1p(g.loc[last,'GPR'])>thresholds_log['GPR'] and dg>0),ChinaRising=int(delta>0));rows.append(row)
 t=pd.DataFrame(rows).set_index('date');t['forward']=p[asset].reindex(t.index).shift(-1)/p[asset].reindex(t.index)-1;t['ARForecast']=np.nan;t['GPRForecast']=np.nan;t['pred_ar']=np.nan;t['pred_gpr']=np.nan;t['pred_mean']=np.nan;t['train_n']=0
 for i in range(len(t)):
  # Exclude label i-1: its endpoint is today's close and cannot be used before execution.
  train=t.iloc[:max(0,i-1)].dropna(subset=['forward','lagret','level','delta','H','interaction']);test=t.iloc[i]
  if len(train)<84:continue
  for mode,cols,outcol in [('AR',['lagret'],'ARForecast'),('GPR',['lagret','level','delta','H','interaction'],'GPRForecast')]:
   X=np.column_stack([np.ones(len(train)),train[cols]]);b=np.linalg.lstsq(X,train.forward,rcond=None)[0];forecast=np.r_[1,test[cols].to_numpy(float)]@b;t.loc[t.index[i],'pred_'+mode.lower()]=forecast;t.loc[t.index[i],outcol]=int(forecast>test.cash_forecast)
  t.loc[t.index[i],'pred_mean']=train.forward.mean();t.loc[t.index[i],'train_n']=len(train)
 return t

start_period='2019-01';end=p.index[-1];allsummary=[];paths={};audits=[]
def simulate(asset,t,rule,cost=10,start=None):
 t=t.loc[t.month>=pd.Timestamp(start_period)];t=t.dropna(subset=[rule]) if rule in rules else t
 if start is None:start=t.index[0]
 dates=p.loc[start:end].index;ev=t[rule].to_dict() if rule in rules else {};w=0.;wealth=10000.;ret=[];turn=[];held=[]
 for i,date in enumerate(dates):
  if i==0:base=0.;q=0.
  else:
   q=w;base=q*(p.loc[date,asset]/p.loc[dates[i-1],asset]-1)+(1-q)*cashdaily.loc[date]
  new=float(ev[date]) if date in ev else w
  if rule=='BuyHold':new=1.
  if rule=='Cash':new=0.
  if date==dates[-1]:new=0.
  turnover=abs(new-w);net=(1+base)*(1-cost/10000*turnover)-1;wealth*=1+net;ret.append(net);turn.append(turnover);held.append(q);w=new
 result=pd.DataFrame({'return':ret,'wealth':10000*np.cumprod(1+np.array(ret)),'turnover':turn,'held':held,'cash_return':cashdaily.reindex(dates).to_numpy()},index=dates)
 years=(dates[-1]-dates[0]).days/365.25;excess=result['return']-result.cash_return;excess.iloc[0]=result['return'].iloc[0];dd=result.wealth/np.maximum.accumulate(np.r_[10000,result.wealth])[1:]-1
 stats=dict(asset=asset,rule=rule,cost_bps=cost,n_days=len(dates),start=str(dates[0].date()),end=str(dates[-1].date()),final=result.wealth.iloc[-1],profit=result.wealth.iloc[-1]-10000,CAGR=(result.wealth.iloc[-1]/10000)**(1/years)-1,vol=result['return'].std(ddof=1)*np.sqrt(252),sharpe=excess.mean()/excess.std(ddof=1)*np.sqrt(252) if excess.std(ddof=1)>1e-12 else np.nan,maxdd=float(dd.min()),exposure=np.mean(held),one_way_turnover=sum(turn),years=years)
 return result,stats

for delay in [3,6,11]:
 for asset in ['REMX','LIT','COPX']:
  t=positions(asset,delay);t.to_csv(O/(asset+'_signals_delay'+str(delay)+'.csv'));audits.append(dict(asset=asset,delay=delay,first_date=str(t.index.min()),min_training=int(t.query('month>="2019-01-01"').train_n.min())))
  assert t.loc[t.month>=pd.Timestamp(start_period),rules].notna().all().all()
  for rule in rules+['BuyHold','Cash']:
   for cost in ([0,10,25,50] if delay==6 else [10]):
    path,ss=simulate(asset,t,rule,cost);ss['delay']=delay;allsummary.append(ss)
    if delay==6 and cost==10:
     path.to_csv(O/(asset+'_'+rule+'_daily.csv'),index_label='date');paths[(asset,rule)]=path
  # Forecast accuracy compares the same completed holding periods; final partial period excluded.
  q=t.loc[(t.month>=pd.Timestamp(start_period)) & t.forward.notna()].dropna(subset=['pred_gpr','pred_ar','pred_mean'])
  pred=dict(asset=asset,delay=delay,n=len(q),R2_mean=1-np.mean((q.forward-q.pred_gpr)**2)/np.mean((q.forward-q.pred_mean)**2),R2_AR=1-np.mean((q.forward-q.pred_gpr)**2)/np.mean((q.forward-q.pred_ar)**2),directional_hit=np.mean((q.pred_gpr>q.cash_forecast)==(q.forward>q.cash_forecast)))
  with open(O/'forecast_metrics.jsonl','a') as f:f.write(json.dumps(pred)+'\n')
for delay in [3,6,11]:
 t=positions('REMX',delay)
 for cost in ([0,10,25,50] if delay==6 else [10]):
  path,ss=simulate('SPY',t,'BuyHold',cost);ss['delay']=delay;allsummary.append(ss)
  if delay==6 and cost==10:path.to_csv(O/'SPY_BuyHold_daily.csv',index_label='date')
summ=pd.DataFrame(allsummary);summ.to_csv(O/'strategy_metrics.csv',index=False)
# Paired monthly log outperformance versus cash; 24 rules tested and adjusted together.
rows=[]
for (asset,rule),path in paths.items():
 if rule in ['Cash','BuyHold']:continue
 month=(path['return'].add(1).groupby(path.index.to_period('M')).prod()-1);cash=paths[(asset,'Cash')]['return'].add(1).groupby(path.index.to_period('M')).prod()-1;excess=np.log1p(month)-np.log1p(cash);fit=sm.OLS(excess.to_numpy(),np.ones((len(excess),1))).fit(cov_type='HAC',cov_kwds={'maxlags':3,'use_correction':True});rows.append(dict(asset=asset,rule=rule,mean_monthly_log_excess=fit.params[0],p_cash=fit.pvalues[0],n=len(excess)))
tr=pd.DataFrame(rows);tr['p_cash_Holm']=multipletests(tr.p_cash,method='holm')[1];tr.to_csv(O/'strategy_tests.csv',index=False)
# Six-month block bootstrap for paired monthly log performance of the primary REMX rule.
rng=np.random.default_rng(17112026);boot=[]
monthlylog=lambda t:np.log1p(t['return']).groupby(t.index.to_period('M')).sum()
for candidate in ['ChinaHighRising','ChinaLow','AvoidChinaHighRising']:
 a=monthlylog(paths[('REMX',candidate)]);b=monthlylog(paths[('REMX','BuyHold')]);cash=monthlylog(paths[('REMX','Cash')])
 for L in [6,12]:
  vals=[]
  for k in range(1999):
   ix=np.concatenate([(rng.integers(len(a))+np.arange(L))%len(a) for _ in range(int(np.ceil(len(a)/L)))])[:len(a)];vals.append([12*(a.values-b.values)[ix].mean(),12*(a.values-cash.values)[ix].mean()])
  v=np.array(vals)
  for j,bench in enumerate(['BuyHold','Cash']):boot.append(dict(rule=candidate,asset='REMX',benchmark=bench,block=L,B=1999,annual_log_point=12*(a-(b if bench=='BuyHold' else cash)).mean(),lo=np.quantile(v[:,j],.025),hi=np.quantile(v[:,j],.975)))
pd.DataFrame(boot).to_csv(O/'trading_bootstrap.csv',index=False)
# Required fee per one-way portfolio turnover to match passive REMX under primary implementation.
t=positions('REMX',6);target=paths[('REMX','BuyHold')].wealth.iloc[-1]
fun=lambda c:simulate('REMX',t,'ChinaHighRising',c)[1]['final']-target
breakeven=float(brentq(fun,0,2000)) if fun(0)*fun(2000)<0 else None
json.dump({'sample_start':summ.query('delay==6').start.iloc[0],'sample_end':str(end.date()),'initial_capital_USD':10000,'cash_proxy':'lagged DFF daily, ACT/360','execution':'close of sixth observed US trading session of each month','calibration':'2009-01 through 2018-12','level_thresholds':thresholds,'log_level_thresholds':thresholds_log,'primary_rule':'ChinaHighRising','primary_cost_bps':10,'break_even_cost_bps_vs_passive':breakeven,'time_robustness':[3,6,11]},open(O/'trading_settings.json','w'),indent=2)
print(summ.query('asset=="REMX" and delay==6 and cost_bps==10')[['rule','final','CAGR','sharpe','maxdd','exposure','one_way_turnover']].round(4).to_string(index=False));print('Break even vs passive',breakeven);print(pd.DataFrame(boot).round(4).to_string(index=False))
