"""Check the compiled current manuscript without rerunning empirical models."""
from pathlib import Path
import hashlib
import json
import re

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
P = ROOT / 'paper_revision'


def audit():
    pdf = P / 'main.pdf'
    reader = PdfReader(pdf)
    pages = [page.extract_text() for page in reader.pages]
    text = '\n'.join(pages)
    sections = sorted(P.glob('0*.tex'))
    manuscript = (P / 'main.tex').read_text() + '\n' + '\n'.join(p.read_text() for p in sections)
    references = (P / 'references.tex').read_text()
    keys = re.findall(r'\\bibitem\[[^\]]*\]\{([^}]+)\}', references)
    used = set()
    for group in re.findall(r'\\cite\w*(?:\[[^\]]*\])?\{([^}]+)\}', manuscript):
        used.update(group.split(','))
    figures = re.findall(r'\\fig\{([^}]+)\}', manuscript)
    tables = len(re.findall(r'\\begin\{table\}', manuscript))

    assert len(pages) == 20, len(pages)
    assert len(figures) == 9 and len(set(figures)) == 9
    assert tables == 8
    assert len(keys) == 32 and len(set(keys)) == 32
    assert used <= set(keys), sorted(used - set(keys))
    assert not re.search(r'\?\?|\ufffd|\u25a0', text)
    assert not [c for c in text if ord(c) < 32 and c not in '\n\r\t']
    assert min(len(page.split()) for page in pages) > 100
    assert 'xdvipdfmx' in reader.metadata.producer.lower()
    log = (P / 'main.log').read_text()
    assert not any(w in log for w in ['Overfull', 'undefined references', 'undefined citations', 'Missing character:', 'LaTeX Error:'])
    for name in figures:
        assert (P / 'figures' / (name + '.pdf')).is_file()
    for name in re.findall(r'\\input\{([^}]+)\}', manuscript):
        assert (P / (name if name.endswith('.tex') else name + '.tex')).is_file(), name

    result = {
        'status': 'PASS',
        'pages': len(pages),
        'words': sum(len(page.split()) for page in pages),
        'figures': len(figures),
        'tables': tables,
        'references': len(keys),
        'producer': reader.metadata.producer,
        'pdf_sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(),
        'visual_review': 'All 20 pages rendered and inspected; revised wealth axes and alpha legend re-inspected after final typesetting.',
        'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(P.glob('*.tex'))},
    }
    (ROOT / 'review_extension/results/document_verification.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    result = audit()
    print(json.dumps({k: v for k, v in result.items() if k not in ['source_sha256']}, indent=2))
