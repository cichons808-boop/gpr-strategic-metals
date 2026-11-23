"""Factor attribution on actual holding intervals, including the opening trade cost."""
import pandas as pd,statsmodels.api as sm
from statsmodels.stats.multitest import multipletests
import market as m

def run(paths=None):
    if paths is None:
        metrics=pd.read_csv(m.O/'benchmark_metrics.csv').query('cost_bps==10')
        paths={(x['sample'],x['asset'],x['rule']):pd.read_csv(m.O/f"{x['sample']}_{x['asset']}_{x['rule']}_daily.csv",index_col=0,parse_dates=True) for _,x in metrics.iterrows()}
    ff=m.factors();rows=[];gprrules=m.RULES+['GlobalForecast','ChinaForecast']
    for (sample,asset,rule),path in paths.items():
        if rule=='Cash':continue
        # The first observation is an instantaneous opening cost, not an overnight return.
        # Attach it to the first observed holding interval and match that interval's factors.
        aligned=path[['return']].copy();aligned.iloc[1,0]=(1+aligned.iloc[0,0])*(1+aligned.iloc[1,0])-1;aligned=aligned.iloc[1:]
        q=aligned.join(ff,how='inner').dropna();y=q['return']-q.RF
        for model,cols in [('CAPM',['Mkt-RF']),('FF5_MOM',['Mkt-RF','SMB','HML','RMW','CMA','Mom'])]:
            fit=sm.OLS(y,sm.add_constant(q[cols])).fit(cov_type='HAC',cov_kwds={'maxlags':5,'use_correction':True})
            rows.append(dict(sample=sample,asset=asset,rule=rule,model=model,start=str(q.index.min().date()),end=str(q.index.max().date()),n=len(q),alpha_annual=float(252*fit.params['const']),alpha_se_annual=float(252*fit.bse['const']),p_alpha=float(fit.pvalues['const']),R2=fit.rsquared,**{c:float(fit.params[c]) for c in cols}))
    result=pd.DataFrame(rows)
    for sample in result['sample'].unique():
        for model in ['CAPM','FF5_MOM']:
            ix=(result['sample']==sample)&(result.model==model)&result.rule.isin(gprrules)&result.asset.isin(m.ASSETS)
            result.loc[ix,'p_Holm_24']=multipletests(result.loc[ix,'p_alpha'],method='holm')[1]
    result.to_csv(m.O/'factor_alphas.csv',index=False)
    return ff,result

if __name__=='__main__':
    _,r=run();print(r.query('sample=="post2018" and model=="FF5_MOM" and rule=="AvoidChinaHighRising"')[['asset','alpha_annual','p_alpha']].round(4).to_string(index=False))
