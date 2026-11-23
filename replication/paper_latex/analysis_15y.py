"""Extend the empirical study to 2011--2026, without inventing pre-inception prices."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests

R=Path(__file__).resolve().parent;ROOT=R.parent;O=R/'results';O.mkdir(exist_ok=True)
g=pd.read_excel(ROOT/'data/gpr.xls').dropna(subset=['month']).set_index('month')[['GPR','GPRC_CHN']]
p=pd.read_csv(ROOT/'paper_en/results/daily_adjusted_prices.csv',index_col=0,parse_dates=True)
rate=pd.read_csv(ROOT/'paper_en/raw/DFF.csv',index_col=0,parse_dates=True).iloc[:,0]
rate=pd.to_numeric(rate,errors='coerce').reindex(pd.date_range(rate.index.min(),p.index.max(),freq='D')).ffill()
cash_index=(1+rate.shift(1).bfill()/36000).cumprod()
cash=cash_index.reindex(p.index).pct_change().fillna(0)
RULES=['ChinaLow','AvoidChinaHighRising','ChinaHigh','ChinaHighRising','GlobalHighRising','ChinaRising']
CAL=('2000','2009');START=pd.Timestamp('2011-01-01')
thresholds={col:float(np.log1p(g.loc[CAL[0]:CAL[1],col]).quantile(.8)) for col in g}

def signals(delay=6,q=.8,mode='fixed'):
    rows=[]
    events=p.groupby(p.index.to_period('M')).apply(lambda x:x.index[delay-1] if len(x)>=delay else x.index[-1])
    for period,date in events.items():
        month=period.to_timestamp()
        if month<START:continue
        last=month-pd.offsets.MonthBegin(1);prev=last-pd.offsets.MonthBegin(1)
        hist=g.loc[CAL[0]:CAL[1]] if mode=='fixed' else g.loc[:prev].tail(120)
        assert hist.index.max()<last
        lc=float(np.log1p(g.loc[last,'GPRC_CHN']));dc=lc-float(np.log1p(g.loc[prev,'GPRC_CHN']))
        lg=float(np.log1p(g.loc[last,'GPR']));dg=lg-float(np.log1p(g.loc[prev,'GPR']))
        qc=float(np.log1p(hist.GPRC_CHN).quantile(q));qg=float(np.log1p(hist.GPR).quantile(q));H=int(lc>qc)
        rows.append(dict(date=date,month=month,info_month=last,threshold=qc,risk_level=lc,change=dc,ChinaLow=1-H,ChinaHigh=H,ChinaHighRising=int(H and dc>0),AvoidChinaHighRising=1-int(H and dc>0),GlobalHighRising=int(lg>qg and dg>0),ChinaRising=int(dc>0)))
    return pd.DataFrame(rows).set_index('date')

def simulate(asset,t,rule,cost=10):
    dates=p.loc[t.index.min():].index
    target=pd.Series(int(rule=='BuyHold'),index=dates,dtype=float) if rule in ['BuyHold','Cash'] else t[rule].reindex(dates).ffill().fillna(0)
    target.iloc[-1]=0
    held=target.shift(1).fillna(0);turn=target.diff().abs();turn.iloc[0]=target.iloc[0]
    ar=p.loc[dates,asset].pct_change().fillna(0);cr=cash.loc[dates].copy();cr.iloc[0]=0
    net=(1+held*ar+(1-held)*cr)*(1-cost/10000*turn)-1
    wealth=10000*(1+net).cumprod();years=(dates[-1]-dates[0]).days/365.25
    dd=wealth/wealth.cummax().clip(lower=10000)-1;excess=net-cr
    path=pd.DataFrame({'return':net,'wealth':wealth,'drawdown':dd,'held':held,'turnover':turn,'cash_return':cr,'target':target})
    stats=dict(asset=asset,rule=rule,cost_bps=cost,start=str(dates[0].date()),end=str(dates[-1].date()),n_days=len(dates),years=years,final=wealth.iloc[-1],CAGR=(wealth.iloc[-1]/10000)**(1/years)-1,maxdd=dd.min(),vol=net.std()*np.sqrt(252),sharpe=excess.mean()/excess.std()*np.sqrt(252) if excess.std()>1e-12 else np.nan,exposure=held.mean(),one_way_turnover=turn.sum())
    return path,stats

summary=[];paths={}
for delay in [3,6,11]:
    t=signals(delay);t.to_csv(O/f'signals_fixed_delay{delay}.csv')
    for asset in ['REMX','LIT','COPX','SPY']:
        for rule in (RULES+['BuyHold','Cash'] if asset!='SPY' else ['BuyHold']):
            for cost in ([0,10,25,50] if delay==6 else [10]):
                path,stats=simulate(asset,t,rule,cost);stats.update(delay=delay,threshold_mode='fixed',quantile=.8);summary.append(stats)
                if delay==6 and cost==10:
                    paths[(asset,rule)]=path;path.to_csv(O/f'{asset}_{rule}_daily.csv',index_label='date')
pd.DataFrame(summary).to_csv(O/'strategy_metrics_15y.csv',index=False)

# Calibration sensitivity is retained in full, rather than selecting the best threshold.
sensitivity=[]
for mode in ['fixed','rolling120']:
    for q in [.7,.8,.9]:
        t=signals(6,q,mode);t.to_csv(O/f'signals_{mode}_q{int(q*100)}.csv')
        for asset in ['REMX','LIT','COPX']:
            for rule in RULES:
                path,stats=simulate(asset,t,rule,10);stats.update(delay=6,threshold_mode=mode,quantile=q);sensitivity.append(stats)
pd.DataFrame(sensitivity).to_csv(O/'calibration_sensitivity.csv',index=False)

annual=[];subperiod=[];tests=[]
for (asset,rule),path in paths.items():
    for year,x in path.groupby(path.index.year):
        annual.append(dict(asset=asset,rule=rule,year=year,return_pct=100*((1+x['return']).prod()-1)))
    for label,start,end in [('2011–2015','2011','2015'),('2016–2020','2016','2020'),('2021–2026','2021','2026')]:
        x=path.loc[start:end];yrs=(x.index[-1]-x.index[0]).days/365.25
        subperiod.append(dict(asset=asset,rule=rule,period=label,CAGR=np.prod(1+x['return'])**(1/yrs)-1))
    if asset=='SPY' or rule in ['Cash','BuyHold']:continue
    logret=np.log1p(path['return']).groupby(path.index.to_period('M')).sum()
    for benchmark in ['Cash','BuyHold']:
        b=paths[(asset,benchmark)];lr=np.log1p(b['return']).groupby(b.index.to_period('M')).sum();excess=logret-lr
        f=sm.OLS(excess,np.ones((len(excess),1))).fit(cov_type='HAC',cov_kwds={'maxlags':3,'use_correction':True})
        tests.append(dict(asset=asset,rule=rule,benchmark=benchmark,annual_log_difference=12*f.params.iloc[0],p=f.pvalues.iloc[0],n=len(excess)))
test=pd.DataFrame(tests)
for benchmark in ['Cash','BuyHold']:
    ix=test.benchmark==benchmark;test.loc[ix,'p_Holm_18']=multipletests(test.loc[ix,'p'],method='holm')[1]
test.to_csv(O/'strategy_tests_15y.csv',index=False)
pd.DataFrame(annual).to_csv(O/'annual_returns_15y.csv',index=False);pd.DataFrame(subperiod).to_csv(O/'subperiod_returns_15y.csv',index=False)

# Uncertainty of selected candidates, preserving six- or twelve-month return blocks.
rng=np.random.default_rng(17112615);boots=[]
for asset,rule in [('REMX','ChinaLow'),('REMX','AvoidChinaHighRising'),('COPX','AvoidChinaHighRising'),('COPX','ChinaHigh'),('LIT','AvoidChinaHighRising'),('REMX','GlobalHighRising')]:
    a=paths[(asset,rule)];la=np.log1p(a['return']).groupby(a.index.to_period('M')).sum()
    for benchmark in ['Cash','BuyHold']:
        b=paths[(asset,benchmark)];lb=np.log1p(b['return']).groupby(b.index.to_period('M')).sum();diff=(la-lb).to_numpy();n=len(diff)
        for L in [6,12]:
            vals=[]
            for _ in range(1999):
                ix=np.concatenate([(rng.integers(n)+np.arange(L))%n for j in range(int(np.ceil(n/L)))])[:n];vals.append(12*diff[ix].mean())
            boots.append(dict(asset=asset,rule=rule,benchmark=benchmark,block=L,B=1999,annual_log_difference=12*diff.mean(),lo=np.quantile(vals,.025),hi=np.quantile(vals,.975)))
pd.DataFrame(boots).to_csv(O/'strategy_bootstrap_15y.csv',index=False)

# Recover the entire IMF workbook history; the former common sample is not imposed.
x=pd.read_excel(ROOT/'data/imf.xlsx',header=None);dates=pd.to_datetime(x.iloc[4:,0].str.replace('M','-',regex=False)+'-01')
cols={'REE':92,'Lithium':90,'Cobalt':75,'Nickel':43,'Copper':29,'Platinum':79,'Palladium':78,'Silicon':93}
monthly=pd.DataFrame({key:pd.to_numeric(x.iloc[4:,col],errors='coerce').to_numpy() for key,col in cols.items()},index=dates)
other=pd.read_csv(ROOT/'extension/results/prices.csv',index_col=0,parse_dates=True)[['PrNd','neodymium','samarium','REMX','LIT','COPX','SPY','EEM']]
monthly=monthly.join(other,how='outer').loc['2009':'2026-10-01'];monthly.to_csv(O/'monthly_prices_extended.csv',index_label='month')
returns=100*np.log(monthly).diff();returns.to_csv(O/'monthly_returns_extended.csv',index_label='month')
coverage=[];meanmodels=[]
for asset in monthly:
    if asset in ['SPY','EEM']:continue
    r=returns[asset].loc['2011-01-01':].dropna();coverage.append(dict(asset=asset,first_return=str(r.index.min().date()),last_return=str(r.index.max().date()),n_returns=len(r),mean=r.mean(),std=r.std()))
    for risk in ['GPR','GPRC_CHN']:
        delta=np.log1p(g[risk]).diff();z=(delta-delta.loc['2000':'2009'].mean())/delta.loc['2000':'2009'].std()
        for lag in [0,1]:
            X=pd.DataFrame({'risk':z.shift(lag),'lag_return':returns[asset].shift()})
            if asset in ['REMX','LIT','COPX']:X=X.join(returns[['SPY','EEM']])
            t=pd.concat([r.rename('y'),X],axis=1).loc['2011':].dropna();f=sm.OLS(t.y,sm.add_constant(t.drop(columns='y'))).fit(cov_type='HAC',cov_kwds={'maxlags':3,'use_correction':True})
            meanmodels.append(dict(asset=asset,risk=risk,lag=lag,beta=f.params.risk,se=f.bse.risk,p=f.pvalues.risk,n=len(t),start=str(t.index.min().date()),end=str(t.index.max().date())))
mm=pd.DataFrame(meanmodels);mm['p_Holm_56']=multipletests(mm.p,method='holm')[1];mm.to_csv(O/'monthly_mean_models.csv',index=False)
pd.DataFrame(coverage).to_csv(O/'coverage_extended.csv',index=False)

# A genuinely earlier calibration for the already-selected PrNd interaction.
old=pd.read_csv(ROOT/'extension/results/prnd_regime_design.csv',index_col=0,parse_dates=True)
lg=np.log1p(g.GPRC_CHN);delta=lg.diff();z=(delta-delta.loc['2000':'2009'].mean())/delta.loc['2000':'2009'].std();H=(lg.shift()>thresholds['GPRC_CHN']).astype(int)
r=returns.PrNd;design=pd.concat([r.rename('y'),z.rename('z'),H.rename('H'),(z*H).rename('zH'),r.shift().rename('lag')],axis=1).dropna()
f=sm.OLS(design.y,sm.add_constant(design.drop(columns='y'))).fit(cov_type='HAC',cov_kwds={'maxlags':3,'use_correction':True});tt=f.t_test([0,1,0,1,0])
state=dict(calibration='2000–2009',threshold_original=float(np.expm1(thresholds['GPRC_CHN'])),low=f.params.z,high=float(tt.effect[0]),p_high=float(tt.pvalue),difference=f.params.zH,p_difference=f.pvalues.zH,n=len(design),high_n=int(design.H.sum()))
pd.DataFrame([state]).to_csv(O/'prnd_earlier_calibration.csv',index=False)
json.dump({'start':'2011-01','end':'2026-10','n_monthly_decisions':len(signals()),'calibration':'2000-01 through 2009-12','thresholds_log':thresholds,'thresholds_original':{k:float(np.expm1(v)) for k,v in thresholds.items()},'execution':'sixth observed US trading session close','data_vintage':'November 2026 revised GPR; archived check remains 2022–2026','cost_bps_one_way':10,'initial_USD':10000,'test_family':18},open(O/'settings_15y.json','w'),indent=2)
print(pd.DataFrame(summary).query('delay==6 and cost_bps==10')[['asset','rule','CAGR','final','sharpe','maxdd','exposure','one_way_turnover']].round(4).to_string(index=False))
print('Earlier-calibration PrNd:',state)
