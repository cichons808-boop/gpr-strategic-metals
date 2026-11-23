"""Compile the manuscript with XeLaTeX; uses the standard TeX installation."""
from pathlib import Path
import os,subprocess,sys
R=Path(__file__).resolve().parent
env=os.environ.copy()
# This workspace has a complete TeX tree but no pre-generated file database/formats.
# Explicit recursive paths also make the source usable without rebuilding system files.
texroot=Path('/usr/share/texlive/texmf-dist')
if texroot.exists():
    for key,relative in [('TEXINPUTS','tex'),('TFMFONTS','fonts/tfm'),('VFFONTS','fonts/vf'),('T1FONTS','fonts/type1'),('ENCFONTS','fonts/enc'),('TEXFONTMAPS','fonts/map'),('OPENTYPEFONTS','fonts/opentype'),('TTFONTS','fonts/truetype')]:
        env[key]=str(texroot/relative)+'//:/usr/share/texmf/'+relative+'//:'+env.get(key,'')
    runtime=R.parent/'tmp/tex-runtime'
    runtime.mkdir(parents=True,exist_ok=True)
    env['TEXFORMATS']=str(runtime)+'//:'+env.get('TEXFORMATS','')
    env['TEXMFCNF']='/etc/texmf/web2c:/usr/share/texlive/texmf-dist/web2c:'+env.get('TEXMFCNF','')
    if not (runtime/'xelatex.fmt').exists():
        subprocess.run(['xetex','-ini','-etex','-interaction=nonstopmode','-halt-on-error','-output-directory='+str(runtime),'-jobname=xelatex',str(texroot/'tex/latex/tex-ini-files/xelatex.ini')],env=env,cwd=R,check=True,stdout=subprocess.DEVNULL)
name=sys.argv[1] if len(sys.argv)>1 else 'main.tex'
for i in range(3):
    logfile=R/(Path(name).stem+'.build-output.txt')
    with logfile.open('w') as f:
        result=subprocess.run(['xelatex','-interaction=nonstopmode','-halt-on-error','-file-line-error',name],env=env,cwd=R,stdout=f,stderr=subprocess.STDOUT)
    if result.returncode:
        print(logfile.read_text()[-7000:]);raise SystemExit(result.returncode)
print('Compiled:',R/Path(name).with_suffix('.pdf'))
