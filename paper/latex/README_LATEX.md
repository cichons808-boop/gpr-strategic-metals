# LaTeX manuscript

`main.tex` is the current English working paper: 20 pages, nine vector figures,
eight tables and 32 references. It uses XeLaTeX, Latin Modern Roman and Latin
Modern Math. The equations and financial measures are explained in the text.

In Overleaf, upload the contents of this source directory, choose **XeLaTeX**,
and select `main.tex` as the main document. Compile three times to resolve all
cross-references. Bibliographical entries are included in `references.tex` and
use `natbib`; no BibTeX step is required.

With a recent local TeX Live installation, run:

```bash
xelatex -interaction=nonstopmode -halt-on-error main.tex
xelatex -interaction=nonstopmode -halt-on-error main.tex
xelatex -interaction=nonstopmode -halt-on-error main.tex
```

Alternatively, `python compile.py` runs the same three passes and supports a
Linux TeX installation that has not yet built its format files. This optional
wrapper is not needed on Overleaf.

Keep `preamble.tex`, `numbers.tex`, the five numbered section files,
`references.tex`, `figures/` and `tables/` alongside `main.tex`. The figures are
vector PDF files. The tables and number macros are generated from the actual
calculations; they should not be edited to imply a new empirical result.

This source archive reproduces the document from its computed exhibits. The
separate full replication archive contains the frozen raw inputs and Python
scripts needed to reproduce the estimates, strategies, exhibits and checks.

The physical-price panel covers 2010–2026. The investment analysis distinguishes
a revised-data chronological forecast exercise starting in March 2018 from a
reconstruction using actual archived GPR releases starting in March 2022. The
2018 exercise is not claimed to be an untouched, real-time holdout.
