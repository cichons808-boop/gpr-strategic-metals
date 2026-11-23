# SPY vs Caldara–Iacoviello GPR — excess returns

## Cel
Czy prosty, z góry określony sygnał ze zmiany miesięcznego indeksu GPR pozwala uzyskać dodatni **excess return netto wobec SPY buy-and-hold** (a nie tylko dodatni zysk), i czy pozostaje dodatnia alpha po uwzględnieniu ekspozycji na SPY?

Wykorzystujemy **pobrane wcześniej dzienne notowania SPY** z `output/raw/SPY_adjusted_daily.csv` i oficjalne GPR Caldary–Iacoviello, nie AI-GPR.

## Uruchomienie — konserwatywny test na historycznych wersjach

```bash
cd ~/Pobrane
unzip -o SPY_GPR_EXCESS.zip
cd REE_GPR_ETF
./run_spy_gpr.sh --source vintage --fetch-vintages --vintage-start 2010-01 --timing month_end --cash-mode tbill --fetch-tbill --cost-bps 10
```

Archiwa miesięcznych wersji GPR są pobierane z oficjalnego repozytorium autorów, T-bills (DTB3) z FRED. Następne uruchomienie może skorzystać z cache, bez `--fetch-vintages` i `--fetch-tbill`:

```bash
./run_spy_gpr.sh --source vintage --timing month_end --cash-mode tbill --cost-bps 25
```

Jeśli SPY/GPR cache nie istnieje, najpierw uruchom `./run.sh` w pierwotnym projekcie (nie trzeba powtarzać pobierania, jeśli już jest). Jeśli FRED jest chwilowo niedostępny, można wyłączyć oprocentowanie gotówki `--cash-mode zero`; taki wynik to **osobny, uproszczony scenariusz**, nie substytut głównego testu.

## Sensitivity check: szybszy wariant

```bash
./run_spy_gpr.sh --source vintage --timing day --release-day 10 --cash-mode tbill --cost-bps 10 --out output/spy_gpr_day10
```

Ten wariant przyjmuje, że odczyt został opublikowany do 10. dnia miesiąca i realizuje transakcję na pierwszym **następnym** zamknięciu sesji. **Daty publikacji nie zostały potwierdzone indywidualnie**, więc tego wariantu nie nazywaj rygorystycznie point-in-time. Test `month_end` jest bardziej konserwatywny (kosztem opóźnienia sygnału). Samo korzystanie z archiwów nie dowodzi, że były dostępne dokładnie danego dnia: przed publikacją naukową trzeba zweryfikować timestampy publikacji.

Dla porównania można uruchomić `--source final`; ale wersja z dzisiejszym szeregiem GPR jest podatna na bias rewizji i **nie jest testem point-in-time**.

## Reguły

- `spy_buy_hold`: stale long SPY (ten sam przedział dat, to samo wejściowe 10 bps).
- `gpr_up_long_cash`: wzrost **ostatniego opublikowanego** miesięcznego GPR -> 100% SPY; spadek lub brak zmiany -> gotówka.
- `gpr_up_long_short`: GPR↑ -> 100% long, inaczej 100% short, 3% p.a. opłaty borrow.
- `gpr_down_long_cash`: odwrotna reguła kontrolna.
- `ma200`: long tylko gdy SPY > MA200; sygnał z zamknięcia T wykonywany na zamknięciu T+1, pierwszy PnL T+1 -> T+2.
- `ma200_gpr_up`: MA200 AND GPR rośnie -> long, poza tym cash.
- `ma200_gpr_ls`: powyżej MA200 -> long przy GPR↑, short przy GPR↓; poniżej MA200 cash.

Na każdej sesji koszt = 10 bps × absolutna zmiana pozycji. Przejście -1 -> +1 kosztuje 20 bps. Gotówka domyślnie zarabia dzienny ekwiwalent ostatniego dostępnego wcześniej 3-miesięcznego T-bill (FRED DTB3), pozycja short **nie otrzymuje** odsetek od środków ze sprzedaży. Brak leverage powyżej |100%|. Wyniki dywidend SPY wynikają z adjusted close. Transakcje po skorygowanych cenach zamknięcia stanowią przybliżenie wykonania, nie symulację zleceń giełdowych. Bez podatków i bez dodatkowych kosztów finansowania; te ograniczenia trzeba opisać w paperze.

## Pliki wynikowe

`output/spy_gpr_excess/summary.csv`: CAGR netto, różnica CAGR vs SPY w punktach procentowych, Sharpe względem cash, MDD, t/p testu HAC dla różnicy dziennych stóp zwrotu oraz CAPM alpha (HAC) i beta.

`output/spy_gpr_excess/subperiods.csv`: testy w okresach 2016+, 2020+, 2022+, 2024+ (tylko tam, gdzie są dostępne dane).

`output/spy_gpr_excess/daily_ledger.csv`: data, pozycja, wynik netto każdej sesji, koszty.

`output/spy_gpr_excess/executed_gpr_releases.csv`: użyte historyczne odczyty i rzeczywiste sesje realizacji przy założonej dacie dostępności.

**5 automatycznie otwieranych wykresów:**
1. `01_long_cash.png` — krzywe kapitału buy-and-hold, GPR, MA200, MA200+GPR.
2. `02_long_short.png` — buy-and-hold, GPR long/short i MA200+GPR long/short.
3. `03_relative_wealth.png` — majątek strategii / majątek SPY - 1; wartość dodatnia oznacza *skumulowaną* przewagę.
4. `04_rolling_excess.png` — 252-sesyjna różnica *skumulowanych* stóp zwrotu wobec buy-and-hold.
5. `05_signals.png` — SPY, MA200, sygnał GPR.

## Interpretacja

- **Dodatni całkowity return != dodatni excess return**. Wymagamy przewagi względem identycznych okresów.
- **Dodatni excess CAGR != dodatnia alpha**. Ryzyko beta może być niższe w long/cash; uwzględniamy regresję na SPY i gotówkę.
- P-value dla testowanych wariantów są **eksploracyjne**. Wybór najlepszego wariantu po obejrzeniu wyników prowadzi do data snoopingu.
- Dodatni wynik w modelu z obecnie dostępnymi danymi GPR (`final`) może być obciążony rewizjami.
- Dane FRED DTB3 mają stopę dyskontową instrumentów 3-miesięcznych, przybliżoną jako ekwiwalent dziennej stopy depozytowej; to proxy, nie dokładna stopa realizowalna przez strategię.

Źródła: https://www.matteoiacoviello.com/gpr.htm oraz https://fred.stlouisfed.org/series/DTB3

**W środowisku tworzenia kod przetestowano na danych syntetycznych. Nie było lokalnego cache rzeczywistych notowań użytkownika, więc nie przedstawiamy wygenerowanych zmyślonych wyników SPY.**
