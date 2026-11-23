from pathlib import Path
import shutil,json
import numpy as np,pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter

R=Path(__file__).resolve().parent;ROOT=R.parent;O=R/'results';P=ROOT/'paper_revision';F=P/'figures';T=P/'tables'
plt.rcParams.update({'font.family':'serif','font.serif':['DejaVu Serif'],'font.size':9,'axes.titlesize':10,'axes.labelsize':9,'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.6,'grid.alpha':.2,'grid.linewidth':.4,'legend.frameon':False,'legend.fontsize':8,'savefig.bbox':'tight','pdf.fonttype':42})
BLUE='#245B78';TEAL='#26786D';RED='#AE5444';GRAY='#78828B';GOLD='#B68A3C'
def save(fig,name):
    fig.savefig(F/(name+'.pdf'));fig.savefig(F/(name+'.png'),dpi=180);plt.close(fig)
def path(sample,asset,rule):return pd.read_csv(O/f'{sample}_{asset}_{rule}_daily.csv',index_col=0,parse_dates=True)
for suffix in ['pdf','png']:shutil.copyfile(ROOT/'paper_latex/figures'/('01_prices_and_risk.'+suffix),F/('01_prices_and_risk.'+suffix))

control=pd.read_csv(O/'price_control_models.csv')
labels={'Original_AR1':'Original model','Lagged_economic_controls':'Lagged economic controls','Current_economic_controls':'Same-month economic controls','Original_AR1_IP_matched':'Original: IP-matched dates','Lagged_IP_controls':'Lagged IP controls'}
order=['Original_AR1','Lagged_economic_controls','Current_economic_controls','Original_AR1_IP_matched','Lagged_IP_controls'];c=control.set_index('model').loc[order]
fig,ax=plt.subplots(figsize=(6.4,2.7))
for i,(name,row) in enumerate(c.iterrows()):ax.errorbar(row.high,i,xerr=1.96*row.high_se,fmt='o',capsize=3,color=BLUE if 'IP' not in name else TEAL,ms=4)
ax.set_yticks(range(len(c)),[labels[x] for x in c.index]);ax.invert_yaxis();ax.axvline(0,color=GRAY,lw=.6);ax.set_xlabel('High-state PrNd log-return response per standard deviation');ax.grid(axis='x');fig.tight_layout();save(fig,'02_price_controls')

lp=pd.read_csv(O/'local_projections.csv').query('sample=="common_h0_h12" and state=="high"');fig,ax=plt.subplots(figsize=(6.4,2.9))
ax.fill_between(lp.h.to_numpy(),lp.lo.to_numpy(),lp.hi.to_numpy(),color=BLUE,alpha=.15,label='Pointwise 95% HAC interval');ax.plot(lp.h,lp.beta,'o-',color=BLUE,ms=3,label='High prior-risk state');ax.axhline(0,color=GRAY,lw=.7);ax.set_xticks([0,1,3,6,9,12]);ax.set_xlabel('Months after the risk change');ax.set_ylabel('Cumulative PrNd log-return\npercentage points');ax.legend(loc='upper right');ax.grid(axis='y');fig.tight_layout();save(fig,'03_local_projections')

fig,axes=plt.subplots(1,2,figsize=(6.4,3.0),sharey=True)
for ax,asset in zip(axes,['LIT','COPX']):
    for rule,label,col in [('AvoidChinaHighRising','Avoid high and rising China risk',BLUE),('DailyMA200','Daily MA200',GOLD),('BuyHold','Passive fund',RED),('Cash','Cash proxy',GRAY)]:
        x=path('post2018',asset,rule);ax.plot(x.index,x.wealth,color=col,lw=1,label=label)
    ax.set_title(asset);ax.set_yscale('log');ax.grid(axis='y');ax.xaxis.set_major_locator(mdates.YearLocator(2));ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
axes[0].set_ylabel('Wealth from USD 10,000 (log scale)');axes[0].yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v:,.0f}'));axes[1].legend(loc='upper left',fontsize=7);fig.tight_layout();save(fig,'04_benchmark_wealth')

alpha_all=pd.read_csv(O/'factor_alphas.csv')
alpha=alpha_all.query('sample=="post2018" and model=="FF5_MOM"')
fig,ax=plt.subplots(figsize=(6.4,2.9));chosen={'REMX':'ChinaLow','LIT':'AvoidChinaHighRising','COPX':'AvoidChinaHighRising'}
for i,asset in enumerate(['REMX','LIT','COPX']):
    for j,(rule,label,col) in enumerate([(chosen[asset],'GPR candidate',BLUE),('DailyMA200','Daily MA200',GOLD),('TSMOM12','12-month momentum',GRAY)]):
        z=alpha.query('asset==@asset and rule==@rule').iloc[0];ax.errorbar(100*z.alpha_annual,3*i+j,xerr=196*z.alpha_se_annual,fmt='o',capsize=3,color=col,label=label if i==0 else None,ms=4)
ax.set_yticks([1,4,7],['REMX','LIT','COPX']);ax.set_ylim(9.7,-.7);ax.axvline(0,color=GRAY,lw=.7);ax.set_xlabel('Annualised factor-model alpha (percentage points)');ax.grid(axis='x');ax.legend(loc='lower right',ncol=3,fontsize=7);fig.tight_layout();save(fig,'05_factor_alpha')

annual=pd.read_csv(O/'benchmark_annual_returns.csv');rows=[];labs=[]
for a,r,label in [('REMX','ChinaLow','REMX: low China risk'),('LIT','AvoidChinaHighRising','LIT: avoid high and rising risk'),('COPX','AvoidChinaHighRising','COPX: avoid high and rising risk'),('SPY','BuyHold','SPY: passive broad market')]:
    x=annual.query('sample=="post2018" and asset==@a and rule==@r').set_index('year').return_pct.reindex(range(2018,2027));rows.append(x.to_numpy());labs.append(label)
arr=np.array(rows);fig,ax=plt.subplots(figsize=(6.4,2.25));im=ax.imshow(arr,cmap='RdYlGn',vmin=-50,vmax=50,aspect='auto');ax.set_yticks(range(4),labs);ax.set_xticks(range(9),[str(y) for y in range(2018,2027)],rotation=0)
for i in range(4):
    for j in range(9):ax.text(j,i,f'{arr[i,j]:.0f}',ha='center',va='center',fontsize=8)
fig.colorbar(im,ax=ax,label='Annual return (%)',shrink=.8,pad=.02);fig.tight_layout();save(fig,'06_annual_returns_clear')

forecast=pd.read_csv(O/'forecast_comparison.csv');fig,axes=plt.subplots(1,2,figsize=(6.4,2.6),sharey=True)
for ax,sample,title in zip(axes,['post2018','archived2022'],['2018–2026: revised risk history','2022–2026: archived risk releases']):
    for offset,model,label,col in [(-.18,'GlobalForecast','Global GPR',BLUE),(.18,'ChinaForecast','China-related GPR',GOLD)]:
        x=forecast.query('sample==@sample and model==@model').set_index('asset').loc[['REMX','LIT','COPX']];ax.bar(np.arange(3)+offset,100*x.R2_vs_market,width=.34,label=label,color=col)
    ax.set_xticks(range(3),['REMX','LIT','COPX']);ax.axhline(0,color=GRAY,lw=.7);ax.set_title(title,fontsize=8.6);ax.grid(axis='y')
axes[0].set_ylabel('Forecast R-squared relative to\nmarket-and-trend model (%)');axes[1].legend(loc='lower left',fontsize=7);fig.tight_layout();save(fig,'07_incremental_forecasts')

sens=pd.read_csv(O/'threshold_sensitivity.csv');fig,axes=plt.subplots(2,2,figsize=(6.4,4.0),sharex=True)
for i,sample in enumerate(['post2018','archived2022']):
    for j,asset in enumerate(['LIT','COPX']):
        ax=axes[i,j]
        for mode,label,col in [('fixed','Fixed earlier history',BLUE),('rolling120','Previous 120 months',GOLD)]:
            x=sens.query('sample==@sample and asset==@asset and rule=="AvoidChinaHighRising" and mode==@mode').sort_values('quantile');ax.plot(x['quantile']*100,100*x.CAGR,'o-',color=col,ms=3,label=label)
        ax.axhline(0,color=GRAY,lw=.6);ax.set_title(asset+(' | 2018–2026' if i==0 else ' | 2022–2026'),fontsize=9);ax.set_xticks([70,80,90]);ax.grid(axis='y')
        if j==0:ax.set_ylabel('Net annual return (%)')
        if i==1:ax.set_xlabel('High-risk percentile')
axes[0,0].legend(loc='lower left',fontsize=7);fig.tight_layout();save(fig,'08_threshold_stability')

fig,ax=plt.subplots(figsize=(6.4,2.8))
for file,label,col in [(O/'archived2022_REMX_ChinaLow_daily.csv','Archived monthly releases',BLUE),(O/'matched_revised_REMX_ChinaLow_daily.csv','Revised data, matched threshold',GOLD),(O/'archived2022_REMX_Cash_daily.csv','Cash proxy',GRAY)]:
    x=pd.read_csv(file,index_col=0,parse_dates=True);ax.plot(x.index,x.wealth,color=col,label=label,lw=1.1)
attribution=pd.read_csv(O/'revision_attribution.csv')
for row in attribution.itertuples():ax.axvspan(pd.Timestamp(row.execution_date),pd.Timestamp(row.next_execution),color=GRAY,alpha=.12)
ax.set_ylabel('Wealth from USD 10,000');ax.yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v:,.0f}'));ax.legend(loc='upper left');ax.grid(axis='y');fig.tight_layout();save(fig,'09_vintage_audit')

def tab(name,head,rows,align):
    text=['\\begin{tabular}{@{}'+align+'@{}}','\\toprule',' & '.join(head)+r' \\','\\midrule']+[' & '.join(map(str,x))+r' \\' for x in rows]+['\\bottomrule','\\end{tabular}'];(T/f'{name}.tex').write_text('\n'.join(text))
def pf(x):return f'{x:.3f}'
names={'ChinaLow':'Low China risk','ChinaHigh':'High China risk','ChinaHighRising':'High and rising China risk','AvoidChinaHighRising':'Avoid high and rising China risk','GlobalHighRising':'High and rising global risk','ChinaRising':'China risk rising','MA200':'MA200: monthly decisions','DailyMA200':'MA200: daily decisions','TSMOM12':'12-month momentum','MarketForecast':'Market-and-trend forecast','GlobalForecast':'Market model + global GPR','ChinaForecast':'Market model + China GPR','BuyHold':'Passive fund','Cash':'Cash proxy'}
metric=pd.read_csv(O/'benchmark_metrics.csv');main=metric.query('sample=="post2018" and cost_bps==10');archive=metric.query('sample=="archived2022" and cost_bps==10')
for label,df,include in [('benchmark_returns',main,list(names)[:10]+['BuyHold','Cash']),('archive_returns',archive,list(names))]:
    rr=[]
    for rule in include:
        rr.append([names[rule]]+[f'{100*df.query("asset==@a and rule==@rule").CAGR.iloc[0]:.2f}' for a in ['REMX','LIT','COPX']])
    tab(label,['Rule','REMX','LIT','COPX'],rr,'lrrr')
rr=[]
for name,row in c.iterrows():rr.append([labels[name],str(int(row.n)),f'{row.high:.3f}',f'{row.high_se:.3f}',pf(row.p_high),pf(row.p_difference)])
tab('controlled_prices',['Model','$N$','High slope','SE','$p$ high','$p$ difference'],rr,'lrrrrr')
rr=[]
for sample,code in [('post2018','2018–2026'),('archived2022','2022–2026')]:
    for a in ['REMX','LIT','COPX']:
        for model,label in [('GlobalForecast','Global'),('ChinaForecast','China')]:
            z=forecast.query('sample==@sample and asset==@a and model==@model').iloc[0];me=metric.query('sample==@sample and asset==@a and rule==@model and cost_bps==10').iloc[0];rr.append([code,a,label,str(int(z.n)),f'{100*z.R2_vs_market:.2f}',f'{100*me.CAGR:.2f}',pf(z.ClarkWest_p),pf(z.ClarkWest_p_Holm6)])
tab('forecast_comparison',['Sample','ETF','Added GPR','$N$','$R^2$','CAGR','$p_{CW}$','$p_{Holm}$'],rr,'lllrrrrr')
rr=[]
for a in ['REMX','LIT','COPX']:
    for r in [chosen[a],'DailyMA200','TSMOM12']:
        z=alpha.query('asset==@a and rule==@r').iloc[0];me=main.query('asset==@a and rule==@r').iloc[0];rr.append([a,'GPR candidate' if r==chosen[a] else names[r],f'{100*me.CAGR:.2f}',f'{100*me.maxdd:.2f}',f'{100*z.alpha_annual:.2f}',pf(z.p_alpha)])
tab('alpha_comparison',['ETF','Rule','CAGR','Max. DD','Alpha',r'$p_{\alpha}$'],rr,'llrrrr')
tab('revision_attribution',['Decision','Risk: archive','Risk: revised','ETF return','Wealth effect'],[[x.execution_date,f'{x.archived_risk:.3f}',f'{x.revised_risk:.3f}',f'{100*x.ETF_gross_holding_return:.2f}',f'{x.wealth_attribution_USD:,.0f}'] for x in attribution.itertuples()],'lrrrr')

mac=[]
for sample,code in [('post2018','Oos'),('archived2022','Arc')]:
    for a,short in [('REMX','Remx'),('LIT','Lit'),('COPX','Copx'),('SPY','Spy')]:
        rules=['BuyHold'] if a=='SPY' else ['ChinaLow','ChinaHigh','AvoidChinaHighRising','MA200','DailyMA200','TSMOM12','MarketForecast','GlobalForecast','ChinaForecast','BuyHold','Cash']
        for rule in rules:
            z=metric.query('sample==@sample and asset==@a and rule==@rule and cost_bps==10').iloc[0]
            stem=code+short+{'ChinaLow':'Low','ChinaHigh':'High','AvoidChinaHighRising':'Avoid','MA200':'MonthlyMA','DailyMA200':'DailyMA','TSMOM12':'Momentum','MarketForecast':'Market','GlobalForecast':'GlobalForecast','ChinaForecast':'ChinaForecast','BuyHold':'Passive','Cash':'Cash'}[rule]
            values=[('Cagr',f'{100*z.CAGR:.2f}'),('Drawdown',f'{abs(100*z.maxdd):.2f}'),('Final',f'{z.final:,.0f}'),('Time',f'{100*z.exposure:.1f}')]
            if rule!='Cash':
                az=alpha_all.query('sample==@sample and asset==@a and rule==@rule and model=="FF5_MOM"').iloc[0]
                values += [('Alpha',f'{100*az.alpha_annual:.2f}'),('AlphaP',f'{az.p_alpha:.3f}')]
            for suffix,val in values:mac.append('\\newcommand{\\'+stem+suffix+'}{'+val+'}')
(P/'numbers.tex').write_text('\n'.join(mac));print('Nine figures, six computed tables and manuscript number macros saved.')
