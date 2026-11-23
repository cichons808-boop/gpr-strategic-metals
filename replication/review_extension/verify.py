"""Independent checks of raw inputs, execution, forecast timing and model arithmetic."""
from pathlib import Path
import json,hashlib
import numpy as np,pandas as pd
from scipy.stats import norm
import market as m

R=Path(__file__).resolve().parent;ROOT=R.parent;O=R/'results';checks=[]
def passed(s):checks.append(s);print('PASS:',s,flush=True)

parts=[]
for asset in m.TRADED:
    raw=json.loads((ROOT/'paper_en/raw'/f'{asset}_daily.json').read_text())['chart']['result'][0]
    idx=pd.to_datetime(raw['timestamp'],unit='s',utc=True).tz_convert('America/New_York').tz_localize(None).normalize()
    parts.append(pd.Series(raw['indicators']['adjclose'][0]['adjclose'],index=idx,name=asset))
p=pd.concat(parts,axis=1).dropna().loc[:'2026-10-31'];assert p.index.equals(m.p.index) and np.allclose(p,m.p)
mp=p.resample('MS').last();g=pd.read_excel(ROOT/'data/gpr.xls').dropna(subset=['month']).set_index('month')
cal=pd.read_stata(ROOT/'paper_en/raw/vintages/data_gpr_export_202201.dta').dropna(subset=['month']).set_index('month')
qs={s:{c:np.log1p((g.loc['2009':'2017'] if s=='post2018' else cal.loc['2009':'2018'])[c]).quantile(.8) for c in ['GPR','GPRC_CHN']} for s in ['post2018','archived2022']}
signal={};archives={}
for sample in ['post2018','archived2022']:
    for a in m.ASSETS:
        t=pd.read_csv(O/f'{sample}_{a}_signals.csv',index_col=0,parse_dates=['date','month','info_month','forward_end']);t.index=pd.to_datetime(t.index)
        signal[(sample,a)]=t
    t=signal[(sample,'REMX')];t=t.loc[t.month>=pd.Timestamp('2018-03-01' if sample=='post2018' else '2022-03-01')]
    assert len(t)==(104 if sample=='post2018' else 56)
    for date,row in t.iterrows():
        dates=p.index[p.index.to_period('M')==date.to_period('M')];assert date==dates[10 if sample=='post2018' else 5]
        assert row.info_month==row.month-pd.offsets.MonthBegin(1)
        if sample=='post2018':risk=g
        else:
            risk=pd.read_stata(ROOT/'paper_en/raw/vintages'/f'data_gpr_export_{row.month:%Y%m}.dta').dropna(subset=['month']).set_index('month').sort_index();archives[date]=risk
        last=row.info_month;prev=last-pd.offsets.MonthBegin(1);c=np.log1p(risk.loc[last,'GPRC_CHN']);dc=c-np.log1p(risk.loc[prev,'GPRC_CHN']);H=int(c>qs[sample]['GPRC_CHN']);gg=np.log1p(risk.loc[last,'GPR']);dg=gg-np.log1p(risk.loc[prev,'GPR'])
        expected={'ChinaLow':1-H,'ChinaHigh':H,'ChinaHighRising':int(H and dc>0),'AvoidChinaHighRising':1-int(H and dc>0),'ChinaRising':int(dc>0),'GlobalHighRising':int(gg>qs[sample]['GPR'] and dg>0)}
        for rule,value in expected.items():assert row[rule]==value
passed('Raw adjusted prices, all 104 post-2018 decisions and all 56 archived decisions match their source values, fixed calibrations and execution calendars.')

rates=pd.read_csv(ROOT/'paper_en/raw/DFF.csv',index_col=0,parse_dates=True).iloc[:,0];rates=pd.to_numeric(rates,errors='coerce').reindex(pd.date_range(rates.index.min(),p.index.max(),freq='D')).ffill()
cr=pd.Series(0.,index=p.index)
for prev,day in zip(p.index[:-1],p.index[1:]):
    days=pd.date_range(prev,day-pd.Timedelta(days=1),freq='D');cr.loc[day]=np.prod(1+rates.reindex(days).to_numpy()/36000)-1
metrics=pd.read_csv(O/'benchmark_metrics.csv').query('cost_bps==10');assert len(metrics)==88
for meta in metrics.itertuples():
    sample=meta.sample;asset=meta.asset;rule=meta.rule
    out=pd.read_csv(O/f'{sample}_{asset}_{rule}_daily.csv',index_col=0,parse_dates=True);dates=out.index
    target=pd.DataFrame(0.,index=dates,columns=m.TRADED)
    if rule=='BuyHold':target[asset]=1
    elif rule=='DailyMA200':
        j=p.index.get_indexer(dates)
        target[asset]=[int(p[asset].iloc[k-1]>p[asset].iloc[k-200:k].mean()) for k in j]
    elif rule=='SectorRotation':
        events=signal[(sample,'REMX')].reindex(dates).dropna(subset=['month']);w=pd.DataFrame(0.,index=events.index,columns=m.TRADED)
        for date,row in events.iterrows():
            last=row.info_month;skip=last-pd.offsets.MonthBegin(1);old=last-pd.offsets.MonthBegin(12);rank=np.log(mp.loc[skip,m.ASSETS]/mp.loc[old,m.ASSETS]);winner=rank.idxmax()
            if rank[winner]>0:w.loc[date,winner]=1
        target=w.reindex(dates).ffill().fillna(0)
    elif rule!='Cash':
        events=signal[(sample,asset)].reindex(dates).dropna(subset=['month']);w=pd.Series(index=events.index,dtype=float)
        for date,row in events.iterrows():
            if rule=='MA200':
                hist=p.loc[p.index<row.month,asset];w.loc[date]=int(hist.iloc[-1]>hist.iloc[-200:].mean())
            elif rule=='TSMOM12':w.loc[date]=int(mp.loc[row.info_month,asset]>mp.loc[row.info_month-pd.offsets.MonthBegin(12),asset])
            elif rule in m.MODELS:w.loc[date]=int(row['pred_'+rule]>row.cash_forecast)
            else:w.loc[date]=row[rule]
        target[asset]=w.reindex(dates).ffill().fillna(0)
    target.iloc[-1]=0;tar=target.to_numpy();ar=p.loc[dates,m.TRADED].to_numpy();cash=cr.reindex(dates).to_numpy();old=np.zeros(4);wealth=10000.;returns=[];wealths=[]
    for i in range(len(dates)):
        base=old@(ar[i]/ar[i-1]-1)+(1-old.sum())*cash[i] if i else 0.
        turn=np.abs(tar[i]-old).sum();net=(1+base)*(1-.001*turn)-1;wealth*=1+net;returns.append(net);wealths.append(wealth);old=tar[i]
    assert np.allclose(returns,out['return'],atol=2e-12)
    assert np.allclose(wealths,out.wealth,atol=2e-6)
    years=(dates[-1]-dates[0]).days/365.25
    assert np.isclose(meta.CAGR,(wealth/10000)**(1/years)-1)
    assert np.isclose(meta.maxdd,(np.array(wealths)/np.maximum.accumulate(np.r_[10000,wealths])[1:]-1).min())
passed('All 88 main portfolio paths match an independent loop from raw prices, derived benchmark weights, calendar cash, turnover costs, liquidation, CAGR and drawdowns.')

for asset in m.ASSETS:
    a=pd.read_csv(O/f'post2018_{asset}_forecast_audit.csv',parse_dates=['date','last_training_target_end','first_test'])
    assert (a.last_training_target_end<a.date).all() and a.iloc[0].last_training_target_end<=pd.Timestamp('2017-12-31') and a.iloc[0].train_n==73
archive_audit=pd.read_csv(O/'archive_forecast_audit.csv',parse_dates=['date','last_training_target_end','info_month'])
assert (archive_audit.last_training_target_end<archive_audit.date).all()
for sample in ['post2018','archived2022']:
    for asset in m.ASSETS:
        saved=signal[(sample,asset)];test=saved.loc[saved.month>=pd.Timestamp('2018-03-01' if sample=='post2018' else '2022-03-01')]
        for date in [test.index[0],test.index[-1]]:
            if sample=='post2018':t=saved;cutoff=pd.Timestamp('2017-12-31') if date==test.index[0] else date-pd.Timedelta(days=1)
            else:t,_=m.make_features(asset,risk=archives[date],frozen=qs['archived2022']);cutoff=date-pd.Timedelta(days=1)
            train=t.loc[t.forward_end.lt(date)&t.forward_end.le(cutoff)].dropna(subset=['forward']+list(set(sum(list(m.MODELS.values()),[]))))
            for model,cols in m.MODELS.items():
                X=np.column_stack([np.ones(len(train)),train[cols]]);b=np.linalg.solve(X.T@X,X.T@train.forward.to_numpy());pred=np.r_[1,t.loc[date,cols].to_numpy(float)]@b
                assert np.isclose(pred,saved.loc[date,'pred_'+model],atol=2e-7)
passed('Forecast training targets strictly precede execution; first and last predictions in both samples reproduce from independent normal-equation refits, using each archived risk history where required.')

control=pd.read_csv(O/'price_control_models.csv')
for model in ['Original_AR1','Lagged_economic_controls','Lagged_IP_controls']:
    t=pd.read_csv(O/f'price_design_{model}.csv',index_col=0,parse_dates=True);X=np.column_stack([np.ones(len(t)),t.drop(columns='y')]);y=t.y.to_numpy();names=['constant']+list(t.drop(columns='y').columns);n,k=X.shape;b=np.linalg.solve(X.T@X,X.T@y);s=X*(y-X@b)[:,None];S=np.zeros((k,k));mi=t.index.to_period('M').asi8
    for i in range(n):
        for j in range(n):
            gap=abs(mi[i]-mi[j])
            if gap<=3:S+=(1-gap/4)*np.outer(s[i],s[j])
    bread=np.linalg.inv(X.T@X);cov=bread@S@bread*n/(n-k);v=np.array([int(c in ['z','zH']) for c in names]);high=v@b;se=np.sqrt(v@cov@v);z=control.query('model==@model').iloc[0]
    assert np.isclose(high,z.high) and np.isclose(se,z.high_se)
    if model=='Lagged_IP_controls':assert len(t)==152 and len(pd.date_range(t.index.min(),t.index.max(),freq='MS'))>len(t)
price=pd.read_csv(ROOT/'extension/results/prices.csv',index_col=0,parse_dates=True).PrNd
lp=pd.read_csv(O/'local_projections.csv')
for h in range(13):
    t=pd.read_csv(O/f'lp_design_h{h}.csv',index_col=0,parse_dates=True);expected=100*(np.log(price.shift(-h))-np.log(price.shift())).reindex(t.index);assert len(t)==177 and np.allclose(t.y,expected)
    X=np.column_stack([np.ones(len(t)),t.drop(columns='y')]);b=np.linalg.lstsq(X,t.y,rcond=None)[0];names=['constant']+list(t.drop(columns='y').columns);high=b[names.index('z')]+b[names.index('zH')];ref=lp.query('sample=="common_h0_h12" and state=="high" and h==@h').iloc[0];assert np.isclose(high,ref.beta)
passed('Price slopes and calendar-aware HAC errors reproduce independently, including actual IP gaps; every local-projection target matches the raw cumulative quote change on 177 common dates.')

ff=pd.read_csv(O/'factor_daily.csv',index_col=0,parse_dates=True);alpha=pd.read_csv(O/'factor_alphas.csv')
for asset,rule in [('REMX','ChinaLow'),('LIT','AvoidChinaHighRising'),('COPX','AvoidChinaHighRising')]:
    x=pd.read_csv(O/f'post2018_{asset}_{rule}_daily.csv',index_col=0,parse_dates=True)[['return']];x.iloc[1,0]=(1+x.iloc[0,0])*(1+x.iloc[1,0])-1;x=x.iloc[1:].join(ff,how='inner').dropna();cols=['Mkt-RF','SMB','HML','RMW','CMA','Mom'];X=np.column_stack([np.ones(len(x)),x[cols]]);y=(x['return']-x.RF).to_numpy();b=np.linalg.solve(X.T@X,X.T@y);ref=alpha.query('sample=="post2018" and asset==@asset and rule==@rule and model=="FF5_MOM"').iloc[0];assert np.isclose(252*b[0],ref.alpha_annual)
fc=pd.read_csv(O/'forecast_comparison.csv')
for row in fc.itertuples():
    t=signal[(row.sample,row.asset)];t=t.loc[t.month>=pd.Timestamp('2018-03-01' if row.sample=='post2018' else '2022-03-01')].dropna(subset=['forward','pred_MarketForecast','pred_'+row.model]);a=np.mean((t.forward-t['pred_'+row.model])**2);b=np.mean((t.forward-t.pred_MarketForecast)**2);assert len(t)==row.n and np.isclose(1-a/b,row.R2_vs_market)
at=pd.read_csv(O/'revision_attribution.csv');cf=pd.read_csv(O/'revision_counterfactuals.csv');diff=cf.query('change_first==1 and change_second==1').final.iloc[0]-cf.query('change_first==0 and change_second==0').final.iloc[0];assert np.isclose(at.wealth_attribution_USD.sum(),diff) and (at.ETF_gross_holding_return<0).all()
passed('Six-factor intercepts, nested forecast error ratios and the exact two-decision wealth attribution reconcile; factor attribution includes the opening cost on its first holding interval.')

manifest={'status':'PASS','checks':checks,'runtime':{'numpy':np.__version__,'pandas':pd.__version__},'sha256':{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted((R/'raw').iterdir()) if f.is_file()}}
(O/'verification.json').write_text(json.dumps(manifest,indent=2))
