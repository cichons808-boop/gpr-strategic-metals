"""Build the current PDF, editable LaTeX ZIP and complete frozen replication ZIP."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

from document_audit import audit

ROOT = Path(__file__).resolve().parent.parent
P = ROOT / 'paper_revision'
R = ROOT / 'review_extension'
OUT = ROOT / 'output'

document = audit()
assert json.loads((R / 'results/verification.json').read_text())['status'] == 'PASS'
OUT.mkdir(exist_ok=True)
article = OUT / 'GPR_Rare_Earths_Research_Article_EN.pdf'
shutil.copyfile(P / 'main.pdf', article)
assert hashlib.sha256(article.read_bytes()).hexdigest() == document['pdf_sha256']

source = [P / n for n in ['main.tex', 'preamble.tex', 'numbers.tex', 'references.tex', 'compile.py', 'README_LATEX.md']]
source += sorted(P.glob('0*.tex'))
source += sorted((P / 'figures').glob('*.pdf'))
source += sorted((P / 'tables').glob('*.tex'))
assert len(source) == len(set(source)) == 26
sourcezip = OUT / 'GPR_Rare_Earths_LaTeX_Source.zip'
with zipfile.ZipFile(sourcezip, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for f in sorted(source):
        z.write(f, str(f.relative_to(P)))

files = [ROOT / n for n in ['README_EN.md', 'README.md', 'requirements.txt', 'analysis.py', 'supplemental.py']]
files += [article]
files += [p for p in (ROOT / 'data').iterdir() if p.suffix in ['.xls', '.xlsx', '.html']]
files += [p for p in OUT.iterdir() if p.suffix == '.csv' or p.name in ['slownik_danych.json', 'manifest.json']]
files += [ROOT / 'extension' / n for n in ['prepare.py', 'explore.py', 'nonlinear.py', 'validate_candidates.py']]
files += [p for p in (ROOT / 'extension/raw').iterdir() if p.is_file() and p.suffix in ['.json', '.csv', '.xls', '.html']]
files += [p for p in (ROOT / 'extension/results').iterdir() if p.suffix in ['.csv', '.json'] and p.name != 'manifest_extended.json']
files += [ROOT / 'paper_en' / n for n in ['engine.py', 'backtest.py', 'vintage_backtest.py', 'vintage_download.py', 'download_market_data.py']]
files += [p for p in (ROOT / 'paper_en/raw').rglob('*') if p.is_file()]
files += [p for p in (ROOT / 'paper_en/results').iterdir() if p.suffix in ['.csv', '.json', '.jsonl'] and p.name not in ['verification.json', 'article_layout.json']]
files += [ROOT / 'paper_latex' / n for n in ['analysis_15y.py', 'make_exhibits.py', 'README_SUPPLEMENT.md']]
files += [p for p in (ROOT / 'paper_latex/results').iterdir() if p.suffix in ['.csv', '.json']]
files += [ROOT / 'paper_latex/figures' / ('01_prices_and_risk.' + suffix) for suffix in ['pdf', 'png']]
files += source
files += [P / n for n in ['references_base.tex', 'extra_references.tex']]
files += list((P / 'figures').glob('*.png'))
files += list(R.glob('*.py')) + list(R.glob('*.md'))
files += [p for p in (R / 'raw').iterdir() if p.is_file()]
files += [p for p in (R / 'results').iterdir() if p.suffix in ['.csv', '.json', '.jsonl']]
files = sorted(set(files))
assert all(p.is_file() and p.is_relative_to(ROOT) for p in files)
assert not any('__pycache__' in p.parts or '.venv' in str(p) or 'library_helper' in str(p) for p in files)

manifest = {
    'article': str(article.relative_to(ROOT)),
    'active_manuscript': 'paper_revision/main.tex',
    'language': 'English',
    'pages': 20,
    'figures': 9,
    'tables': 8,
    'references': 32,
    'typesetting': 'XeLaTeX',
    'source_snapshot_date': '2026-11-17',
    'chronological_investment_sample': ['2018-03-15', '2026-10-30'],
    'archived_investment_sample': ['2022-03-08', '2026-10-30'],
    'selection_status': 'Exploratory retrospective chronological evaluation; not independent untouched strategy validation',
    'verification': 'review_extension/results/verification.json',
    'document_verification': 'review_extension/results/document_verification.json',
    'sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
}
archive = OUT / 'GPR_Rare_Earths_Replication_EN.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for f in files:
        z.write(f, str(f.relative_to(ROOT)))
    z.writestr('MANIFEST_EN.json', json.dumps(manifest, indent=2))

for file in [sourcezip, archive]:
    with zipfile.ZipFile(file) as z:
        assert z.testzip() is None
        assert len(z.namelist()) == len(set(z.namelist()))
with zipfile.ZipFile(archive) as z:
    assert sum(n.endswith('.dta') for n in z.namelist()) == 57
    assert 'paper_revision/main.tex' in z.namelist()
    assert 'review_extension/results/benchmark_metrics.csv' in z.namelist()
    assert 'review_extension/results/verification.json' in z.namelist()
    assert 'review_extension/results/document_verification.json' in z.namelist()
    assert sum(n.startswith('review_extension/results/') and n.endswith('_daily.csv') and n != 'review_extension/results/factor_daily.csv' and 'matched_revised' not in n for n in z.namelist()) == 88

for file in [article, sourcezip, archive]:
    print(json.dumps({'path': str(file), 'bytes': file.stat().st_size, 'status': 'PASS'}))
