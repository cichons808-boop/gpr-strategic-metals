from pathlib import Path
import json
import numpy as np,pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter,PercentFormatter

R=Path(__file__).resolve().parent;ROOT=R.parent;O=R/'results';F=R/'figures';T=R/'tables'
F.mkdir(exist_ok=True);T.mkdir(exist_ok=True)
plt.rcParams.update({'font.family':'serif','font.serif':['DejaVu Serif'],'font.size':9,'axes.titlesize':10,'axes.labelsize':9,'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.6,'grid.alpha':.2,'grid.linewidth':.4,'legend.frameon':False,'legend.fontsize':8,'savefig.bbox':'tight','pdf.fonttype':42,'ps.fonttype':42})
BLUE='#245B78';TEAL='#26786D';RED='#AE5444';GRAY='#7C838A';GOLD='#B68A3C'
def save(fig,name):
    fig.savefig(F/(name+'.pdf'));fig.savefig(F/(name+'.png'),dpi=180);plt.close(fig)
def path(a,r):return pd.read_csv(O/f'{a}_{r}_daily.csv',index_col=0,parse_dates=True)
def oldpath(a,r):return pd.read_csv(ROOT/'paper_en/results'/f'vintage_{a}_{r}_daily.csv',index_col=0,parse_dates=True)

prices=pd.read_csv(O/'monthly_prices_extended.csv',index_col=0,parse_dates=True);g=pd.read_excel(ROOT/'data/gpr.xls').set_index('month')
fig,ax=plt.subplots(2,1,figsize=(6.4,4.4),sharex=True,gridspec_kw={'height_ratios':[1.2,1]})
ax[0].plot(prices.PrNd/1000,color=BLUE,lw=1.2);ax[0].set_ylabel('PrNd quote\nCNY thousand per tonne');ax[0].set_title('(a) Physical material quote',loc='left')
ax[1].plot(g.loc['2010':'2026-10-01','GPRC_CHN'],color=RED,lw=1);ax[1].set_ylabel('China-related GPR\noriginal index units');ax[1].set_title('(b) News-based geopolitical risk',loc='left')
for a in ax:a.grid(axis='y');a.set_xlim(pd.Timestamp('2010-01-01'),pd.Timestamp('2026-10-31'))
fig.tight_layout();save(fig,'01_prices_and_risk')

state=pd.read_csv(ROOT/'extension/results/prnd_robustness.csv').query('variant=="all"').iloc[0];earlier=pd.read_csv(O/'prnd_earlier_calibration.csv').iloc[0]
old=pd.read_csv(ROOT/'extension/results/regimes.csv').query('asset=="PrNd" and gpr=="GPRC_CHN" and sample=="full"').iloc[0]
fig,ax=plt.subplots(figsize=(6.4,2.8));values=[old.beta_low,old.beta_high,earlier.high];errs=[0, state.se, 0]
# Standard errors for both calibrations are recalculated rather than inferred from rounded p-values.
import statsmodels.api as sm
design=pd.read_csv(ROOT/'extension/results/prnd_regime_design.csv',index_col=0);fit=sm.OLS(design.y,sm.add_constant(design.drop(columns='y'))).fit(cov_type='HAC',cov_kwds={'maxlags':3,'use_correction':True});errs[0]=fit.bse.z
from scipy.stats import norm
errs[2]=abs(earlier.high)/norm.isf(earlier.p_high/2)
for i,(v,se) in enumerate(zip(values,errs)):ax.errorbar(v,i,xerr=1.96*se,fmt='o',color=[GRAY,BLUE,TEAL][i],capsize=4,ms=5)
ax.set_yticks(range(3),['Low state: selected model','High state: selected model','High state: earlier calibration']);ax.invert_yaxis();ax.axvline(0,color=GRAY,lw=.7);ax.set_xlabel('PrNd log-return percentage points per standard deviation');ax.grid(axis='x');fig.tight_layout();save(fig,'02_state_effects')

fig,ax=plt.subplots(figsize=(6.4,3.5))
for rule,label,col in [('GlobalHighRising','High and rising global risk',BLUE),('ChinaLow','Low China-related risk',TEAL),('BuyHold','Passive REMX',RED),('Cash','Cash proxy',GRAY)]:
    x=path('REMX',rule);ax.plot(x.index,x.wealth,label=label,color=col,lw=1.2)
ax.set_yscale('log');ax.yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v:,.0f}'));ax.set_ylabel('Wealth from USD 10,000 (log scale)');ax.legend(loc='upper left',ncol=2);ax.grid(axis='y');fig.tight_layout();save(fig,'03_remx_long_history')

candidates=[('LIT','AvoidChinaHighRising','Lithium and battery equities'),('COPX','ChinaHigh','Copper-mining equities')]
fig,axes=plt.subplots(1,2,figsize=(6.4,3.15),sharey=True)
for ax,(asset,rule,title) in zip(axes,candidates):
    for name,label,col in [(rule,'GPR allocation',BLUE),('BuyHold','Passive fund',RED),('Cash','Cash proxy',GRAY)]:
        x=path(asset,name);ax.plot(x.index,x.wealth,label=label,color=col,lw=1.1)
    ax.set_title(asset+': '+title,fontsize=9);ax.set_yscale('log');ax.grid(axis='y');ax.tick_params(axis='x',labelrotation=30)
axes[0].set_ylabel('Wealth from USD 10,000 (log scale)');axes[0].yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v:,.0f}'));axes[1].legend(loc='upper left');fig.tight_layout();save(fig,'04_lit_copx_wealth')

fig,axes=plt.subplots(1,2,figsize=(6.4,2.7),sharey=True)
for ax,(asset,rule,title) in zip(axes,candidates):
    for name,label,col in [(rule,'GPR allocation',BLUE),('BuyHold','Passive fund',RED)]:
        x=path(asset,name);ax.plot(x.index,100*x.drawdown,color=col,lw=1,label=label)
    ax.set_title(asset,fontsize=10);ax.grid(axis='y');ax.tick_params(axis='x',labelrotation=30)
axes[0].set_ylabel('Decline from previous peak (%)');axes[1].legend();fig.tight_layout();save(fig,'05_drawdowns')

sens=pd.read_csv(O/'calibration_sensitivity.csv');fig,axes=plt.subplots(1,2,figsize=(6.4,2.8),sharey=True)
for ax,(asset,rule,title) in zip(axes,candidates):
    for mode,label,col in [('fixed','Fixed 2000–2009 threshold',BLUE),('rolling120','Past 120 months',GOLD)]:
        x=sens.query('asset==@asset and rule==@rule and threshold_mode==@mode').sort_values('quantile');ax.plot(x['quantile']*100,x.CAGR*100,'o-',color=col,label=label,ms=4)
    ax.axhline(0,color=GRAY,lw=.6);ax.set_title(asset);ax.set_xticks([70,80,90]);ax.set_xlabel('Risk percentile defining the high state');ax.grid(axis='y')
axes[0].set_ylabel('Annualised return after costs (%)');axes[1].legend(loc='lower left');fig.tight_layout();save(fig,'06_calibration_sensitivity')

fig,ax=plt.subplots(figsize=(6.4,3.1))
for name,label,col in [('ChinaLow','Archived monthly releases',BLUE),('Latest','Revised data, matched threshold',GOLD),('Cash','Cash proxy',GRAY)]:
    file=ROOT/'paper_en/results'/('matched_latest_REMX_ChinaLow_daily.csv' if name=='Latest' else f'vintage_REMX_{name}_daily.csv');x=pd.read_csv(file,index_col=0,parse_dates=True);ax.plot(x.index,x.wealth,color=col,label=label,lw=1.2)
ax.set_ylabel('Wealth from USD 10,000');ax.yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v:,.0f}'));ax.legend(loc='upper left');ax.grid(axis='y');fig.tight_layout();save(fig,'07_vintage_audit')

annual=pd.read_csv(O/'annual_returns_15y.csv');rows=[];labels=[]
for asset,rule,label in [('REMX','GlobalHighRising','REMX: global-risk rule'),('LIT','AvoidChinaHighRising','LIT: avoid high and rising China risk'),('COPX','ChinaHigh','COPX: high China risk'),('SPY','BuyHold','SPY: passive broad market')]:
    x=annual.query('asset==@asset and rule==@rule').set_index('year').return_pct;rows.append(x);labels.append(label)
arr=pd.DataFrame(rows).to_numpy();fig,ax=plt.subplots(figsize=(6.4,2.4));im=ax.imshow(arr,cmap='RdYlGn',vmin=-50,vmax=50,aspect='auto');ax.set_yticks(range(4),labels);ax.set_xticks(range(16),range(2011,2027),rotation=45)
for i in range(4):
    for j in range(16):ax.text(j,i,f'{arr[i,j]:.0f}',ha='center',va='center',fontsize=6.3,color='black')
fig.colorbar(im,ax=ax,label='Calendar-year return (%)',shrink=.75,pad=.02);fig.tight_layout();save(fig,'08_annual_returns')

def esc(s):return str(s).replace('&',r'\&').replace('%',r'\%').replace('_',r'\_')
def table(name,headers,rows,align=None):
    a=align or ('l'+'r'*(len(headers)-1));lines=[r'\begin{tabular}{@{}'+a+r'@{}}',r'\toprule',' & '.join(headers)+r' \\',r'\midrule']
    lines += [' & '.join(map(str,row))+r' \\' for row in rows]
    lines += [r'\bottomrule',r'\end{tabular}'];(T/(name+'.tex')).write_text('\n'.join(lines))
metric=pd.read_csv(O/'strategy_metrics_15y.csv').query('delay==6 and cost_bps==10')
names={'ChinaLow':'Low China risk','AvoidChinaHighRising':'Avoid high and rising China risk','ChinaHigh':'High China risk','ChinaHighRising':'High and rising China risk','GlobalHighRising':'High and rising global risk','ChinaRising':'China risk rising','BuyHold':'Passive fund','Cash':'Cash proxy'}
rows=[]
for a in ['REMX','LIT','COPX']:
    for row in metric.query('asset==@a and rule!="Cash"').itertuples():rows.append([a,names[row.rule],f'{100*row.CAGR:.2f}',f'{100*row.maxdd:.2f}',f'{row.sharpe:.2f}',f'{100*row.exposure:.1f}'])
for a,rule in [('REMX','Cash'),('SPY','BuyHold')]:
    row=metric.query('asset==@a and rule==@rule').iloc[0];rows.append(['Cash' if rule=='Cash' else 'SPY', 'Cash proxy' if rule=='Cash' else 'Passive broad market',f'{100*row.CAGR:.2f}',f'{100*row.maxdd:.2f}','--' if rule=='Cash' else f'{row.sharpe:.2f}',f'{100*row.exposure:.1f}'])
table('long_results',['ETF','Allocation rule','CAGR','Max. DD','Sharpe','ETF time'],rows,'llrrrr')

coverage=pd.read_csv(O/'coverage_extended.csv');rows=[]
for row in coverage.itertuples():rows.append([row.asset, row.first_return[:7],row.last_return[:7],str(row.n_returns),f'{row.std:.2f}'])
table('coverage',['Market','First return','Last return','$N$','Monthly SD'],rows,'lllr r'.replace(' ',''))

state=pd.read_csv(ROOT/'extension/results/regimes.csv').query('asset=="PrNd" and gpr=="GPRC_CHN"');rows=[]
for row in state.itertuples():rows.append([{'discovery':'2010–2022','test':'2023–2026','full':'2010–2026'}[row.sample],str(row.n),str(row.high_n),f'{row.beta_low:.3f}',f'{row.beta_high:.3f}',f'{row.p_high:.3f}',f'{row.p_difference:.3f}'])
rows.append(['Earlier calibration',str(int(earlier.n)),str(int(earlier.high_n)),f'{earlier.low:.3f}',f'{earlier.high:.3f}',f'{earlier.p_high:.3f}',f'{earlier.p_difference:.3f}'])
table('prnd_state',['Sample / check','$N$','High $N$','Low slope','High slope','$p$ high','$p$ difference'],rows,'lrrrrrr')

models=pd.read_csv(O/'monthly_mean_models.csv');rows=[]
for a in ['PrNd','neodymium','samarium','Cobalt','Nickel','Copper','Platinum','Palladium','REMX','LIT','COPX']:
    cur=models.query('asset==@a and risk=="GPRC_CHN" and lag==0').iloc[0];lag=models.query('asset==@a and risk=="GPRC_CHN" and lag==1').iloc[0]
    rows.append([a,str(int(cur.n)),f'{cur.beta:.3f}',f'{cur.p:.3f}',f'{lag.beta:.3f}',f'{lag.p:.3f}'])
table('linear_models',['Market','$N$','Same-month slope','$p$','Lagged slope','$p$'],rows,'lrrrrr')

sub=pd.read_csv(O/'subperiod_returns_15y.csv');rows=[]
for asset,rule,label in [('LIT','AvoidChinaHighRising','LIT: GPR allocation'),('LIT','BuyHold','LIT: passive'),('COPX','ChinaHigh','COPX: GPR allocation'),('COPX','BuyHold','COPX: passive')]:
    x=sub.query('asset==@asset and rule==@rule');rows.append([label]+[f'{100*v:.2f}' for v in x.CAGR])
table('subperiods',['Investment','2011–2015','2016–2020','2021–2026'],rows,'lrrr')

v=pd.read_csv(ROOT/'paper_en/results/vintage_strategy_metrics.csv').query('delay==6 and cost_bps==10');rows=[]
for asset,rule in [('REMX','ChinaLow'),('REMX','LatestMatchedLow'),('REMX','BuyHold'),('REMX','Cash'),('COPX','AvoidChinaHighRising'),('COPX','BuyHold')]:
    z=v.query('asset==@asset and rule==@rule').iloc[0];label='REMX: revised-data match' if rule=='LatestMatchedLow' else ('Cash proxy' if rule=='Cash' else asset+': '+names[rule]);rows.append([label,f'{z.final:,.0f}',f'{100*z.CAGR:.2f}',f'{100*z.maxdd:.2f}'])
table('vintage_results',['Investment / data version','Final USD','CAGR','Max. DD'],rows,'lrrr')

macro=[]
for asset,rule,prefix in [('REMX','ChinaLow','RemxLow'),('REMX','GlobalHighRising','RemxGlobal'),('REMX','BuyHold','RemxPassive'),('LIT','AvoidChinaHighRising','LitAvoid'),('LIT','BuyHold','LitPassive'),('COPX','ChinaHigh','CopxHigh'),('COPX','BuyHold','CopxPassive'),('REMX','Cash','Cash'),('SPY','BuyHold','Spy')]:
    z=metric.query('asset==@asset and rule==@rule').iloc[0]
    for suffix,value in [('Cagr',f'{z.CAGR*100:.2f}'),('Drawdown',f'{abs(z.maxdd)*100:.2f}'),('Final',f'{z.final:,.0f}'),('Time',f'{z.exposure*100:.1f}')]:macro.append('\\newcommand{\\'+prefix+suffix+'}{'+value+'}')
(R/'numbers.tex').write_text('\n'.join(macro))
print('Saved eight vector figures, six tables and computed-number macros.')
