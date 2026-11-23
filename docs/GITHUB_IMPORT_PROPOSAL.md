# Propozycja jednorazowego pełnego importu GPR

Status: przygotowane do zatwierdzenia. Workflow nie jest zainstalowany ani uruchomiony.

## Zakres

Import odtworzy 951 oryginalnych plików z 21 istniejących źródeł: 11 archiwów ZIP,
3 artykułów PDF i 7 samodzielnych plików kodu lub dokumentacji. Docelowy projekt
obejmie 955 plików wraz ze spisem źródeł i raportem kontroli.

| Katalog | Zawartość |
| --- | --- |
| data/ | Surowe i przetworzone dane GPR, 57 archiwalnych wydań, ceny materiałów, ETF-y, makro i czynniki |
| models/, results/, checks/ | Zapisane modele, prognozy, strategie, wyniki i istniejące kontrole |
| replication/ | Pełna oryginalna angielska paczka replikacyjna |
| paper/, paper/latex/ | Trzy artykuły PDF i źródła LaTeX z tabelami oraz wykresami |
| legacy/ | Osiem wcześniejszych projektów i samodzielne skrypty |
| docs/ | Pochodzenie plików, rozmiary, sumy SHA-256 i opis importu |

Dane zachowają daty i wersje z zapisanych paczek badawczych. Import pobiera te
istniejące paczki; nie aktualizuje obserwacji ani nie uruchamia pełnego przeszukiwania modeli.

## Uprawnienie wymagające zgody

Jednorazowy job GitHub Actions otrzyma uprawnienie contents: write tylko do tego
repozytorium. Po odtworzeniu plików i przejściu kontroli utworzy commit oraz wykona
zwykły git push do main. Push nie jest wymuszany: konkurencyjna zmiana gałęzi
spowoduje odrzucenie zapisu.

Job pobierze wyłącznie 21 źródeł wskazanych w skrypcie. Krótkotrwałe dane dostępu
do tych plików zostaną przygotowane dopiero po zgodzie i zamaskowane w logach.
Skrypt odrzuca przekazywanie nagłówków uwierzytelniających całe konto.

Po udanym imporcie job usunie tymczasowe pliki importu i ten dokument.
Następnie usunę jednorazowy workflow z repozytorium.

## Kontrole przed zapisem

- Zgodność źródeł i oczekiwanej liczby elementów w każdym archiwum.
- Rozmiary i SHA-256 wszystkich 951 oryginalnych plików.
- Składnia 74 plików Pythona.
- Istniejący niezależny zestaw kontroli: python run.py --check.
- Zachowanie oryginalnych plików źródłowych oraz osobny raport nowej kontroli.

Skrypt odtwarzający projekt:
[.github/import/import_gpr.py](../.github/import/import_gpr.py).

Przed uruchomieniem zostaną dołączone niezmienione bieżące moduły obsługi transferów.
Obecny skrypt jest przygotowaniem do przeglądu i sam nie tworzy workflow,
nie zmienia uprawnień oraz nie wykonuje git push.

## Dokładny proponowany workflow

```yaml
name: One-time GPR source import

on:
  push:
    paths:
      - '.github/import/launch.json'

permissions:
  contents: write

jobs:
  import:
    if: github.event.head_commit.message == 'Run complete GPR source import'
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    steps:
      - name: Check out the repository
        uses: actions/checkout@v6
        with:
          fetch-depth: 0
      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: '3.12'
      - name: Restore the saved research packages
        run: python .github/import/import_gpr.py
      - name: Install the saved project dependencies
        run: python -m pip install -r requirements.txt
      - name: Verify the saved data and model results
        run: python run.py --check
      - name: Record validation and publish the complete project
        run: |
          python .github/import/import_gpr.py --finalize
          git config core.autocrlf false
          git config core.filemode true
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add -- .gitignore README.md requirements.txt run.py checks data docs legacy models paper replication results
          git rm -r -- .github/import
          git rm -- docs/GITHUB_IMPORT_PROPOSAL.md
          git commit -m "Import complete GPR research data, models and replication"
          git push origin HEAD:main
```
