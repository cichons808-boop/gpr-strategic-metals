# REMX · MA200 + Caldara–Iacoviello GPR / VAR

Badamy dwa **oddzielne warunki** wejścia oraz wersję łączoną. Skrypt pracuje na Twoich istniejących danych z `REE_GPR_ETF/output/`, pobranych wcześniej. Nie pobiera nowych cen.

## Uruchomienie na Linux Mint

Rozpakuj `REE_GPR_MA200.zip` w folderze `~/Pobrane`, a potem:

```bash
cd ~/Pobrane/REE_GPR_ETF
./run_ma200.sh --source final --release-day 10 --cost-bps 10
```

Automatycznie otwierane są cztery wykresy PNG; wykresy zostaną też zapisane w `output/ma200_gpr_var/figures/`. Jeśli sesja graficzna nie pozwala otwierać okien, wykonaj `xdg-open output/ma200_gpr_var/figures/01_long_cash.png` lub `xdg-open output/ma200_gpr_var/figures/02_long_short.png`.

Jeżeli chcesz bardziej restrykcyjnej kontroli rewizji GPR i masz archiwa historyczne z poprzedniego modułu:

```bash
./run_ma200.sh --source vintage --release-day 10
```

Jeśli archiwów jeszcze nie ma, można je pobrać opcją `--source vintage --fetch-vintages --vintage-start 2018-01`; zajmie to więcej czasu. Można zmienić dzień publikacji na 5, 15 lub 20 i sprawdzić odporność wyników na założenia o czasie dostępności danych.

## Zasady handlu

1. **MA200** to średnia z *ostatnich 200 sesji handlowych* skorygowanej ceny REMX. Gdy zamknięcie REMX znajduje się powyżej MA200, filtr dopuszcza handel. Na danych tylko z cenami zamknięcia decyzja z sesji D może zostać wykonana najwcześniej na następnym zamknięciu D+1, a zyski liczą się od D+1 do D+2; to dodatkowa ostrożność przeciwko transakcji po właśnie zaobserwowanej cenie zamknięcia.
2. **GPR up**: ostatni *opublikowany* miesięczny GPR zwiększył się wobec poprzedniego miesiąca. Domyślne założenie: odczyt za miesiąc M pojawia się 10. dnia miesiąca M+1, a jego wykorzystanie następuje od pierwszego zamknięcia sesji *ściśle po* tej dacie, z pierwszym PnL na kolejnej sesji.
3. **VAR positive**: rosnący zbiór danych do zakończonego miesiąca M, znanego po publikacji GPR, służy do ponownej estymacji `VAR(1)` ze zmiennymi `[Δlog(1+GPR), miesięczny log-return SPY, XME, REMX]`. Prognoza jest *jednokrokowa* (następny miesiąc). Prognoza na miesiąc M+1 powstaje dopiero po założonej publikacji GPR za M, a więc wpływa jedynie na część następnego miesiąca po publikacji. To kierunkowy sygnał handlowy, a nie dokładnie dopasowany horyzont prognozy pozostałych sesji miesiąca.
4. **Kapitał**: 1x ekspozycja, gotówka bez oprocentowania, koszty 10 bp na jednostkę zmiany ekspozycji (np. long→short = 20 bp), short borrow 3% p.a. domyślnie. Wartości uwzględniają koszty, ale nie poślizg ponad przyjęte bps, ograniczenia shortowania, podatki czy finansowanie depozytu.

### Testowane warianty

| Id | Strategia |
| --- | --- |
| `buy_hold` | REMX cały czas long |
| `ma200_only` | **Cena REMX powyżej MA200** → long, inaczej cash |
| `gpr_unfiltered` | Wzrost ostatniego GPR → long, inaczej cash |
| `var_unfiltered` | Dodatnia prognoza VAR → long, inaczej cash |
| `ma200_gpr` | **Cena > MA200 i ΔGPR>0 → long, inaczej cash** |
| `ma200_var` | **Cena > MA200 i prognoza VAR>0 → long, inaczej cash** |
| `ma200_both` | **Cena > MA200 i ΔGPR>0 i VAR>0 → long, inaczej cash** |
| `ma200_gpr_ls` | Gdy cena > MA200: GPR↑ long, GPR↓ short; poniżej MA200 cash |
| `ma200_var_ls` | Gdy cena > MA200: VAR>0 long, VAR≤0 short; poniżej MA200 cash |

Wszystkie serie porównywane są w **tym samym okresie** po pierwszej dostępnej prognozie VAR. Jeśli w danym miesiącu nie uda się oszacować VAR, jego warianty pozostają w gotówce, nie usuwając tego miesiąca z próby. `--min-train 72` miesięcy domyślnie, można sprawdzić `--min-train 48` jako wariant wrażliwości.

## Wyniki

- Terminal: total return, CAGR, Sharpe, max drawdown, dni long/short, turnover.
- `output/ma200_gpr_var/summary.csv` — porównywalne metryki wszystkich strategii.
- `output/ma200_gpr_var/daily_trades.csv` — PnL z każdej sesji, pozycja i koszt.
- `output/ma200_gpr_var/daily_signals.csv` — MA200, przyjęta data sygnału i prognoza VAR.
- `output/ma200_gpr_var/signal_publications_and_VAR.csv` — wartości GPR, daty publikacji i prognozy.
- `output/ma200_gpr_var/figures/01_long_cash.png` — krzywe long/cash.
- `output/ma200_gpr_var/figures/02_long_short.png` — krzywe long/short.
- `output/ma200_gpr_var/figures/03_price_MA200_positions.png` — REMX i MA200 + sygnały/pozycje.
- `output/ma200_gpr_var/figures/04_drawdowns.png` — obsunięcia.

## Uwaga do wykorzystania naukowego

Dane `--source final` mają historyczne rewizje GPR. Żaden wybór opóźnienia publikacji tego nie usuwa. Archiwalne pliki `--source vintage` są znacznie bliższe backtestowi point-in-time, ale ich nazwy miesięczne **nie potwierdzają dokładnego dnia publikacji**. `--release-day 10` to ZAŁOŻENIE. Dodatkowo adjusted close jest przybliżeniem egzekucji z uwzględnieniem korekt dywidend/splitów. Nie nazywaj wyniku w pełni wolnym od lookahead bez historycznie potwierdzonych dat publikacji GPR.

Do oceny strategii wykonaj test odporności na datę publikacji, koszt 10/25/50 bps, różne podokresy i pierwotne, a nie zrewidowane odczyty GPR. Test wielokrotnych wariantów jest eksploracyjny. Nie wykorzystuj wyników syntetycznych z testów jednostkowych jako wyników REMX.
