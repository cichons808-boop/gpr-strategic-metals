"""Shared price-only accounting and dated signal construction for the revision."""
from pathlib import Path
import json,re,zipfile,io
import numpy as np,pandas as pd

R=Path(__file__).resolve().parent;ROOT=R.parent;O=R/'results';O.mkdir(exist_ok=True)
ASSETS=['REMX','LIT','COPX'];TRADED=ASSETS+['SPY']
g=pd.read_excel(ROOT/'data/gpr.xls').dropna(subset=['month']).set_index('month')[['GPR','GPRC_CHN']].loc['2009':'2026-10-01']
p=pd.read_csv(ROOT/'paper_en/results/daily_adjusted_prices.csv',index_col=0,parse_dates=True)
ej=json.loads((R/'raw/EEM_daily.json').read_text())['chart']['result'][0]
ei=pd.to_datetime(ej['timestamp'],unit='s',utc=True).tz_convert('America/New_York').tz_localize(None).normalize()
eem=pd.Series(ej['indicators']['adjclose'][0]['adjclose'],index=ei,name='EEM')
allprices=p.join(eem);monthly=allprices.resample('MS').last();monthly_return=100*np.log(monthly).diff()
ma=allprices.rolling(200,min_periods=200).mean()
rf=pd.read_csv(ROOT/'paper_en/raw/DFF.csv',index_col=0,parse_dates=True).iloc[:,0]
rf=pd.to_numeric(rf,errors='coerce').reindex(pd.date_range(rf.index.min(),p.index.max(),freq='D')).ffill()
cashindex=(1+rf.shift(1).bfill()/36000).cumprod();cash=cashindex.reindex(p.index).pct_change().fillna(0)

def factors():
    def parse(name):
        with zipfile.ZipFile(R/'raw'/name) as z:s=z.read(z.namelist()[0]).decode('utf-8-sig')
        lines=s.splitlines();header=next(x for x in lines if x.startswith(','));rows=[x for x in lines if re.match(r'^\d{8},',x)]
        x=pd.read_csv(io.StringIO(header+'\n'+'\n'.join(rows)),index_col=0);x.columns=x.columns.str.strip();x.index=pd.to_datetime(x.index.astype(str),format='%Y%m%d');return x/100
    ff=parse('FF5_daily.zip').join(parse('MOM_daily.zip'));ff.to_csv(O/'factor_daily.csv',index_label='date');return ff

def events(delay=6):
    x=p.groupby(p.index.to_period('M')).apply(lambda x:x.index[min(delay-1,len(x)-1)]);x.index=x.index.to_timestamp();return x

def make_features(asset,delay=6,risk=None,cal_end='2017-12-01',frozen=None):
    risk=g if risk is None else risk;rows=[]
    thresholds=frozen or {c:float(np.log1p(risk.loc['2009':cal_end,c]).quantile(.8)) for c in ['GPR','GPRC_CHN']}
    for month,date in events(delay).items():
        last=month-pd.offsets.MonthBegin(1);prev=last-pd.offsets.MonthBegin(1)
        if last not in risk.index or prev not in risk.index:continue
        if last not in monthly.index or not np.isfinite(monthly_return.loc[last,asset]):continue
        close=allprices.loc[:last+pd.offsets.MonthEnd(0)].iloc[-1]
        avg=ma.loc[:last+pd.offsets.MonthEnd(0)].iloc[-1]
        if not np.isfinite(avg[asset]):continue
        old=last-pd.offsets.MonthBegin(12);skip=last-pd.offsets.MonthBegin(1)
        if old not in monthly.index or not np.isfinite(monthly.loc[old,asset]):continue
        row=dict(month=month,date=date,info_month=last,lagret=monthly_return.loc[last,asset],mom12=100*np.log(monthly.loc[last,asset]/monthly.loc[old,asset]),mom12_1=100*np.log(monthly.loc[skip,asset]/monthly.loc[old,asset]),spyret=monthly_return.loc[last,'SPY'],eemret=monthly_return.loc[last,'EEM'],maGap=100*np.log(close[asset]/avg[asset]),cash_forecast=float(rf.shift(1).loc[date]/100*30/360))
        for c,tag in [('GPR','global'),('GPRC_CHN','china')]:
            level=float(np.log1p(risk.loc[last,c]));delta=level-float(np.log1p(risk.loc[prev,c]));H=int(level>thresholds[c]);row.update({tag+'_level':level,tag+'_change':delta,tag+'_high':H,tag+'_interaction':delta*H})
        H=row['china_high'];d=row['china_change'];row.update(ChinaLow=1-H,ChinaHigh=H,ChinaHighRising=int(H and d>0),AvoidChinaHighRising=1-int(H and d>0),GlobalHighRising=int(row['global_high'] and row['global_change']>0),ChinaRising=int(d>0),MA200=int(row['maGap']>0),TSMOM12=int(row['mom12']>0))
        rows.append(row)
    t=pd.DataFrame(rows).set_index('date');t['forward_end']=pd.Series(t.index,index=t.index).shift(-1)
    t['forward']=p[asset].reindex(t.index).shift(-1)/p[asset].reindex(t.index)-1
    return t,thresholds

FEATURES=['lagret','mom12_1','spyret','eemret','maGap']
MODELS={'MarketForecast':FEATURES,'GlobalForecast':FEATURES+['global_level','global_change','global_high','global_interaction'],'ChinaForecast':FEATURES+['china_level','china_change','china_high','china_interaction']}
RULES=['ChinaLow','ChinaHigh','ChinaHighRising','AvoidChinaHighRising','GlobalHighRising','ChinaRising']

def fit_forecasts(t,sample_start='2018-03-01',expanding=True):
    t=t.copy();audit=[]
    for model in MODELS:t[model]=np.nan;t['pred_'+model]=np.nan
    t['pred_Mean']=np.nan
    first_test=t.index[t.month>=pd.Timestamp(sample_start)][0]
    for date,row in t.loc[t.month>=pd.Timestamp(sample_start)].iterrows():
        cutoff=pd.Timestamp('2017-12-31') if date==first_test or not expanding else date-pd.Timedelta(days=1)
        train=t.loc[t.forward_end.le(cutoff)&t.forward_end.lt(date)].dropna(subset=['forward']+list(set(sum(list(MODELS.values()),[]))))
        if len(train)<60:continue
        assert train.forward_end.max()<date
        for model,cols in MODELS.items():
            X=np.column_stack([np.ones(len(train)),train[cols]]);b=np.linalg.lstsq(X,train.forward,rcond=None)[0]
            pred=np.r_[1,row[cols].to_numpy(float)]@b;t.loc[date,'pred_'+model]=pred;t.loc[date,model]=int(pred>row.cash_forecast)
        t.loc[date,'pred_Mean']=train.forward.mean();audit.append(dict(date=date,train_n=len(train),last_training_target_end=train.forward_end.max(),first_test=first_test,calibration_cutoff=cutoff))
    return t,pd.DataFrame(audit)

def simulate(weights,start=None,end=None,cost=10):
    start=weights.index.min() if start is None else pd.Timestamp(start);end=p.index.max() if end is None else pd.Timestamp(end)
    dates=p.loc[start:end].index;target=weights.reindex(columns=TRADED,fill_value=0).reindex(dates).ffill().fillna(0).astype(float);target.iloc[-1]=0
    assert (target>=0).all().all() and (target.sum(axis=1)<=1+1e-10).all()
    held=target.shift(1).fillna(0);turn=target.diff().abs().sum(axis=1);turn.iloc[0]=target.iloc[0].abs().sum()
    ret=p.loc[dates,TRADED].pct_change().fillna(0);cr=cash.loc[dates].copy();cr.iloc[0]=0
    gross=(held*ret).sum(axis=1)+(1-held.sum(axis=1))*cr;net=(1+gross)*(1-cost/10000*turn)-1;wealth=10000*(1+net).cumprod();dd=wealth/wealth.cummax().clip(lower=10000)-1
    path=pd.DataFrame({'return':net,'wealth':wealth,'drawdown':dd,'turnover':turn,'cash_return':cr,'exposure':held.sum(axis=1)}).join(held.add_prefix('held_')).join(target.add_prefix('target_'))
    years=(dates[-1]-dates[0]).days/365.25;ex=net-cr
    metrics=dict(start=str(dates[0].date()),end=str(dates[-1].date()),n_days=len(dates),years=years,final=float(wealth.iloc[-1]),CAGR=float((wealth.iloc[-1]/10000)**(1/years)-1),maxdd=float(dd.min()),sharpe=float(ex.mean()/ex.std()*np.sqrt(252)) if ex.std()>1e-12 else np.nan,vol=float(net.std()*np.sqrt(252)),exposure=float(held.sum(axis=1).mean()),one_way_turnover=float(turn.sum()),cost_bps=cost)
    return path,metrics

def asset_weights(t,asset,rule):
    x=pd.DataFrame(0.,index=t.index,columns=TRADED);x[asset]=1. if rule=='BuyHold' else 0. if rule=='Cash' else t[rule];return x

def sector_weights(index):
    w=pd.DataFrame(0.,index=index,columns=TRADED)
    for date in index:
        last=date.to_period('M').to_timestamp()-pd.offsets.MonthBegin(1);skip=last-pd.offsets.MonthBegin(1);old=last-pd.offsets.MonthBegin(12)
        ranks=np.log(monthly.loc[skip,ASSETS]/monthly.loc[old,ASSETS]);winner=ranks.idxmax()
        if ranks[winner]>0:w.loc[date,winner]=1
    return w
