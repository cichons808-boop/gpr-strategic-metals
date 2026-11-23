# Poprawka do SPY + GPR (DTB3/FRED)

## Przyczyna błędu
W poprzedniej wersji `load_tbill` przesuwał o jedną sesję **gotowy, dopasowany do SPY** szereg. Pierwszy element szeregu był zatem zawsze `NaN`, nawet jeżeli DTB3 miał pełną historię. W przypadku częściowych plików pobranych z FRED dodatkowo mogło brakować początku szeregu. Nowa wersja najpierw opóźnia stopy procentowe **wewnątrz oryginalnego szeregu FRED**, a dopiero potem dopasowuje je do dat sesji SPY. Dodatkowo automatycznie ponawia pobieranie pełnej historii przy `--fetch-tbill`.

## Instalacja

```bash
cd ~/Pobrane
unzip -o SPY_GPR_EXCESS_FIX.zip
cd REE_GPR_ETF
./run_spy_gpr.sh --source vintage --timing month_end --cash-mode tbill --fetch-tbill --cost-bps 10
```

Pobrane wcześniej archiwa GPR są zachowane (bez potrzeby `--fetch-vintages`). Wykresy otwierają się automatycznie. Pole `excess_cagr_vs_SPY_pp` w tabeli to różnica CAGR względem buy-and-hold SPY za te same daty.

Wariant wstępny bez rentowności gotówki (bez FRED):

```bash
./run_spy_gpr.sh --source vintage --timing month_end --cash-mode zero --cost-bps 10
```

Wciąż pozostają ograniczenia związane z datami publikacji archiwów GPR, realizacją na adjusted close i aproximacją stopy gotówki na podstawie DTB3; nie należy ich nazywać idealnie wykonalnym backtestem.
