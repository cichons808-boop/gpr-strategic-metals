# ETF Cross-Section × Caldara–Iacoviello GPR

## Cel

Przetestować, **dla których ETF-ów GPR wnosi informację prognostyczną poza próbą** w stosunku do porównywalnego modelu, który zna historię ETF-u i SPY, ale nie zna GPR. Następnie osobno ocenić, czy sygnał poprawia realnie wykonywalną strategię.

Fundusze w próbie to **ustalona z góry reprezentatywna lista 26 ETF-ów**, a nie ranking AUM na konkretny dzień:

| Grupa | ETF-y |
|---|---|
| Amerykańskie akcje | SPY, QQQ, DIA, IWM |
| Akcje zagraniczne | EEM, EFA |
| Obligacje | TLT, IEF, LQD, HYG |
| Złoto i energia | GLD, SLV, USO, XLE |
| Metale i minerały strategiczne | REMX, XME, GDX, COPX, URA |
| Sektory USA | XLK, XLF, XLI, XLU, XBI |
| Technologia i obronność | SMH, ITA |

REMX to spółki z sektora REE i metali strategicznych, **nie indeks cen fizycznych metali ziem rzadkich**. Różne ETF-y mają różną długość historii; rankingi porównuje się z zachowaniem tej informacji.

## Uruchomienie na Linux Mint

Rozpakuj ZIP **do folderu `~/Pobrane`**, gdzie masz już `REE_GPR_ETF`:

```bash
cd ~/Pobrane
unzip -o ETF_GPR_FORECAST.zip
cd REE_GPR_ETF
./run_etf_screen.sh --gpr-mode final --open
```

Skrypt wykorzystuje istniejące cache z poprzedniego projektu `output/raw/{TICKER}_adjusted_daily.csv` i `output/raw/data_gpr_export.xls`. Automatycznie pobiera **brakujące** historyczne notowania ETF-ów w paczkach z Yahoo (yfinance). `--refresh-prices` wymusza odświeżenie wszystkich instrumentów.

### Bardziej rygorystyczny tryb na historycznych wersjach GPR

Jeśli masz już archiwa z poprzedniego testu SPY:

```bash
./run_etf_screen.sh --gpr-mode vintage --vintage-start 2019-01 --open
```

Jeśli ich nie ma:

```bash
./run_etf_screen.sh --gpr-mode vintage --fetch-vintages \
  --vintage-start 2019-01 --open
```

Opcja `--fetch-vintages` może pobierać **dużo danych**. Dane do tego badania pochodziły z oficjalnego archiwum autora indeksu na GitHub. Skrypt wykorzystuje w każdym miesiącu tylko odpowiadający mu plik vintage `data_gpr_export_YYYYMM.*`; nie wypełnia brakujących vintage przyszłymi danymi. Data w nazwie pliku identyfikuje miesiąc wydania, ale **nie weryfikuje co do dnia godziny publikacji**. Wynik w trybie `final` nie jest ścisłym point-in-time ze względu na rewizje GPR.

### Krótsze / wspólne próby

```bash
./run_etf_screen.sh --tickers SPY QQQ TLT GLD XLE REMX XME GDX COPX URA \
  --min-train 72 --min-oos 24 --cost-bps 10 --open
```

`--min-train` domyślnie 72 obserwacje miesięczne dla final-vintage i 24 dla vintage. Poniżej 24 miesięcy OOS test jest wyłącznie wstępny. `--min-oos 24` zwiększa rygor. `--offline` ogranicza program do już zapisanych notowań.

## Konstrukcja informacji i transakcji

Na końcu miesiąca `t` znane są miesięczne zwroty ETF-ów do `t`, a **GPR maksymalnie do `t−1`**, publikowany w miesiącu `t`. Model prognozuje stopę zwrotu z miesiąca `t+1`. W historycznych vintage pobieramy `GPR(t−1)` i `GPR(t−2)` *z pliku vintage oznaczonego miesiącem `t`*, a nie z bieżącej edycji indeksu.

- **Baseline:** Ridge (stałe λ=10), opóźniony zwrot ETF-u, 3-miesięczne momentum, 6-miesięczna zmienność, zwrot SPY w `t` (z wyjątkiem regresji samego SPY).
- **Model GPR:** to samo + `Δlog(1+GPR(t−1))`.
- **Uczenie:** expanding-window OOS, bez dobierania λ na okresie testowym, skalowanie predyktorów wyłącznie na próbie uczącej.
- **Dokładność:** wynik `R²_OOS = 1 − MSE_GPR / MSE_baseline`; test średniej różnicy strat z odchyleniami Newey–West HAC.
- **Warianty tradingowe:** `Buy & Hold`, long/cash i long/short dla obu modeli. **Sygnał powstaje po zamknięciu miesiąca t. Zlecenie zakładamy na zamknięciu pierwszej sesji miesiąca t+1; zamknięcie pozycji/rebalancing na zamknięciu pierwszej sesji t+2.** Stopa zwrotu transakcji jest obliczona dokładnie z tych dziennych cen, a nie z niedostępnej ceny na końcu miesiąca t. Model nadal uczony jest na standardowych miesięcznych close-to-close, a PnL jest osobną realizowalną stopą zwrotu.
- **Koszty:** 10 pb za każdą jednostkę zmiany ekspozycji (z +1 do −1: 20 pb) i 3% rocznie za pożyczkę do shortowania. Koszt gotówki = 0% (bez odsetek). Nie modelujemy podatku, realnej dostępności akcji do short, ślizgu zależnego od płynności i odchyleń ceny zamknięcia od wykonania.
- **Wielokrotne testowanie:** BH-FDR osobno dla testów przewagi forecast MSE, long/cash i long/short. Nie traktuj wybranego ex-post zwycięzcy jako osobno zweryfikowanej strategii.

## Wyniki

```
output/etf_gpr_forecast/
  leaderboard.csv          # n OOS, R², p, q, directional accuracy, CAGR/Sharpe/DD
  forecasts_oos.csv        # każdy forecast, as-of, miesiąc, wynik ETF
  trades_monthly.csv       # waga, realizowalna stopa zwrotu, koszty, equity
  gpr_asof_features.csv    # jaki GPR był użyty w danym miesiącu i z jakiego pliku
  metadata.json            # wszystkie przyjęte założenia
  figures/
    01_oos_r2_all.png
    02_gpr_excess_long_cash.png
    03_gpr_excess_long_short.png
    04_equity_REMX.png, ...
```

Wykresy otworzą się automatycznie przy `--open` i zawsze zapiszą do PNG.

## Interpretacja

**Dodatni `R²_OOS`** jest ważniejszy dla pytania prognostycznego niż istotna regresja in-sample. Dodatni trading excess return nie musi oznaczać poprawy MSE. Ranking 26 instrumentów jest eksploracyjny, wymaga stabilności podokresowej i powtórnego testu w całkowicie nowym okresie. Pojedynczy GPR nie rozdziela źródeł wydarzeń: dla drugiego papera sensownie byłoby porównać zagrożenia `GPRT` i akty `GPRA`, lecz dopiero po ocenie głównego testu.

**Źródła:** D. Caldara & M. Iacoviello (2022), *Measuring Geopolitical Risk*, AER; https://www.matteoiacoviello.com/gpr.htm. Ceny ETF: Yahoo Finance `auto_adjust=True` przez yfinance. Ze względu na brak zewnętrznego połączenia w środowisku generowania paczki, **nie dołączono autentycznych współczynników ani historycznych kursów**; testy kodu przeprowadzono na danych syntetycznych.
