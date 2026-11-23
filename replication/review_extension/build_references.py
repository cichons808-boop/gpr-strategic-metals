from pathlib import Path
import re
ROOT=Path(__file__).resolve().parent.parent;P=ROOT/'paper_revision'
source=(P/'references_base.tex').read_text()+'\n'+(P/'extra_references.tex').read_text()
source=source.replace('\\end{thebibliography}','')
matches=list(re.finditer(r'\\bibitem\[([^\]]+)\]\{([^}]+)\}',source));items=[]
for i,m in enumerate(matches):
    end=matches[i+1].start() if i+1<len(matches) else len(source);chunk=source[m.start():end].strip()
    if m.group(2)=='fred2026':chunk=chunk.replace('\\textit{Federal Funds Effective Rate [DFF]}. FRED, Federal Reserve Bank of St. Louis. \\url{https://fred.stlouisfed.org/series/DFF}.','\\textit{Federal Funds Effective Rate [DFF] and Nominal Broad U.S. Dollar Index [TWEXBGSMTH]}. FRED, Federal Reserve Bank of St. Louis. \\href{https://fred.stlouisfed.org/series/DFF}{Cash-rate documentation}; \\href{https://fred.stlouisfed.org/series/TWEXBGSMTH}{dollar-index documentation}.')
    items.append((m.group(1).lower(),chunk))
assert len(items)==32
(P/'references.tex').write_text('\\begin{thebibliography}{99}\n\\small\n'+'\n'.join(x[1] for x in sorted(items))+'\n\\end{thebibliography}\n')
print('References:',len(items))
