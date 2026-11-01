# Wniosek zespołu: audyt S1CF oraz kandydaci S11–S14

Data zamrożenia: 2026-09-10  
Kapitał odniesienia: 250 USD  
Status: badanie offline; żadna nowa strategia nie została podłączona do handlu live.

## Aktualizacja końcowa 2026-09-14: wynik po testach S15–S34

Cel 25 USD dziennie z 250 USD oznacza średnio 10% kapitału dziennie albo około
300% miesięcznie bez kapitalizacji. Żaden uczciwy test nie zbliżył się do tej
wartości. Zwiększanie dźwigni nie tworzy przewagi; tylko szybciej przenosi małą
ujemną lub niestabilną wartość oczekiwaną na rachunek.

| Kandydat | Najważniejszy wynik | Decyzja |
|---|---|---|
| S20 OB+OI patient runner | development base PF 1,066 i +2,08 USD, ale stress PF 0,764 i -7,74 USD | odrzucony |
| S26 CVD | flow: 138 filli, PF 1,039, +1,36 USD; divergence: tylko 12 filli | odrzucony |
| S30 AI adjudicator | validation: 8 decyzji AI `agree`, WR 25%, expectancy -0,375R; baseline kandydatów +0,048R | AI pogorszyło selekcję |
| XSM-28 beta-neutral | development: 14 epizodów, PF 0,687, -3,58 USD | odrzucony |
| S15 momentum 4h | development/validation mocno dodatnie, lecz 2025–VIII 2026: najlepsza wersja base PF 0,881 i -2,85 USD, stress PF 0,838 i -3,89 USD | odrzucony przez zanik przewagi |
| FCM-1M | stress wszystkich okresów +65,44 USD, ale 2 modelowane wyczerpania collateral shorta | niewykonywalny w tej alokacji |
| S31 carry z resetem miesięcznym | stress: 29 epizodów, +22,96 USD, 0 wyczerpań; jednak min. futures equity 67,53 USD z 190 USD i max 2,58x | odrzucony przez zamrożony bufor bezpieczeństwa |
| S32 cross-venue funding dispersion | development i validation: 0 epizodów; retrospective: 1 epizod, +0,09 USD stress | odrzucony przez brak powtarzalnych okazji |
| S33 fixed-expiry USD-M carry | 3/14 kwartałów zakwalifikowane, wszystkie w 2024; +1,45 USD stress, 0 epizodów w 2023 i 2025–VIII 2026 | odrzucony przez bramkę każdego okna i koncentrację ETH |
| S34 inverse COIN-M carry | 3/14 kwartałów, wszystkie ETH w 2024; +6,35 USD stress, DD 1,19%, max futures-price leverage 0,973x | bezpieczniejszy collateral, ale odrzucony przez brak okazji w dwóch oknach |
| S35 post-funding exhaustion | 2 kandydatury, 1 wykonalny trade DOGE; stress -0,50 USD, średnio -0,0014 USD/dzień w validation; 0 transakcji w development i evaluation | `EDGE_FAIL` i `INCOME_TARGET_FAIL` |

S31 jest jedynym zbadanym mechanizmem, który pozostał dodatni w każdym oknie po
kosztach stress i nie prognozuje kierunku ceny. Przewaga bardzo wyraźnie jednak
osłabła: w najnowszych 792 dniach dała tylko +0,27 USD na kapitale 250 USD,
czyli średnio 0,00034 USD dziennie. Czysto liniowa ekstrapolacja do 25 USD
dziennie wymagałaby około 18,5 mln USD i pomijałaby ograniczenia płynności;
nie jest prognozą ani sensownym planem kapitałowym.

### Co z tego wynika operacyjnie

- Nie wdrażać live S1CF, OB/ICT, Bollingera, CVD, AI, XSM, S15 ani obecnych
  wariantów carry.
- Nie zwiększać dźwigni, aby wymusić nominalny cel. Przy 250 USD najpierw trzeba
  potwierdzić dodatnią wartość oczekiwaną; kwotę celu skaluje się później
  kapitałem, nie ryzykiem ruiny.
- Cross-exchange funding-dispersion carry został już sprawdzony jako S32. Nie
  spełnił zamrożonego progu okazji w development ani validation; pojedynczy
  późniejszy epizod nie wystarcza do estymacji przewagi.
- Dated-futures cash-and-carry został sprawdzony jako S33. Mechanika była
  bezpieczna w trzech wykonanych epizodach (stress DD 0,36%, minimalne futures
  equity 163,50 USD), ale atrakcyjny basis wystąpił wyłącznie w 2024 i dał tylko
  1,45 USD. Nie jest to strumień dziennego dochodu.
- Wariant inverse COIN-M S34 wykorzystał kupioną monetę równocześnie jako
  collateral shorta. Zwiększył stress PnL trzech okazji z 2024 do 6,35 USD i
  utrzymał dźwignię ceny futures poniżej 0,973x, ale nie stworzył ani jednego
  wejścia w development ani najnowszym evaluation. Ciągły szereg nie zawiera
  historycznego liquidation mark ani tiers, więc te metryki bezpieczeństwa są
  diagnostyczne; zerowa częstość poza 2024 i tak samodzielnie odrzuca S34.
- S35 sprawdził inną klasę hipotezy: wejście dopiero po rozliczeniu ekstremalnego
  fundingu, gdy pierwszy pełny bar potwierdza odwrócenie ruchu i kompresję
  mark–index premium. W pięciu instrumentach powstały tylko dwie kandydatury,
  obie na DOGE w validation. Jedna nie spełniła konserwatywnego minimum
  nominału 20 USD, a jedyna wykonana pozycja short trafiła stop 1R po 15
  minutach i straciła 0,50 USD w stress. Development i najnowsze evaluation
  nie miały ani jednej transakcji, więc hipoteza nie wykazała przewagi ani
  zdolności do realizacji celu dochodowego. Audyt świeca po świecy wykazał, że
  przed stopem rynek dał tylko 0,171R ruchu na korzyść, a każdy diagnostyczny
  stop 0,5–1,5R zostałby trafiony przed dowolnym targetem 0,5–2R. Problemem
  było fałszywe jednoświecowe potwierdzenie wejścia, nie zbyt wysoki target
  ani sam stop 1R.

Pełne artefakty końcowe: `docs/research/s15_tsm_4h/`,
`docs/research/fcm_1m/`, `docs/research/s31_fcm_monthly_reset/`,
`docs/research/xsm_28/`, `docs/research/s30_ai_adjudicator/`,
`docs/research/s32_xfrd/`, `docs/research/s33_dated_carry/` i
`docs/research/s34_coin_m_dated_carry/` oraz
`docs/research/s35_post_funding_exhaustion/`.

## Decyzja

Po usunięciu look-ahead i nierealnych filli **S1CF nie jest najlepszą strategią**.
Jej dawny wynik (+257,57 USD) był artefaktem symulatora, a nie powtarzalną
przewagą. S1C jest od niej trochę mniej zła, ale również nie spełnia warunku
wdrożenia.

Trzy kierunkowe propozycje zespołu (ICT/SMT, order block oraz price action)
także nie przeszły testu. Jedynym dodatnim kandydatem jest obecnie **S11 —
neutralny kierunkowo funding carry**, ale liczba niezależnych epizodów jest za
mała, aby uznać przewagę za potwierdzoną. S11 kwalifikuje się wyłącznie do
zamrożonego paper-forward.

## Dlaczego poprzedni wynik S1CF był zawyżony

Audyt wykrył pięć mechanizmów zawyżających wynik:

1. Skaner o 07:15 korzystał z całej świecy 1h otwartej o 07:00, czyli znał jej
   przyszłość do 08:00. Ten sam problem dotyczył bieżących świec 4h i 1d.
2. Symulator najpierw wykonywał cały bieżący bar, a dopiero potem tworzył sygnał
   na jego otwarciu. Pomijał w ten sposób pierwszy rzeczywisty bar ekspozycji.
3. `HYBRID` był wykonywany jako zlecenie market, ale po sztucznie korzystnej
   cenie będącej mieszanką ceny bieżącej i środka FVG.
4. Ten sam sweep/FVG/CHoCH mógł być handlowany wielokrotnie, bo nie istniał
   stabilny `setup_id` i deduplikacja.
5. Częściowe wyjścia nie ponosiły niekorzystnego slippage.

Naprawiono także błąd wyboru wcześniejszych swingów przy detekcji order block:
wcześniejszość jest teraz określana indeksem czasu, nie samą ceną.

## Wyniki po naprawie przyczynowości

Wyniki S1C/S1CF używają czterech osobnych portfeli po 1000 USD, dlatego w tabeli
porównywane są procenty, nie nominalne PnL.

| Strategia | Okres | Transakcje | WR | PF | Zwrot |
|---|---:|---:|---:|---:|---:|
| S1C | lipiec 2026 validation | 11 | 27,3% | 0,114 | -0,677% |
| S1CF | lipiec 2026 validation | 17 | 29,4% | 0,203 | -1,008% |
| S1C | sierpień 2026 holdout | 4 | 0,0% | 0,000 | -0,381% |
| S1CF | sierpień 2026 holdout | 5 | 0,0% | 0,000 | -0,396% |

Odpowiedź na pytanie „czy była lepsza odmiana S1CF?” brzmi zatem: **nie po
uczciwym przeliczeniu**. Historycznie raportowana S1CF wyglądała najlepiej tylko
przed naprawieniem błędów.

## Co wniósł zespół kierunkowy

- ICT: BTC jako rynek referencyjny, raid płynności sesyjnej, SMT
  non-confirmation na alcie, późniejszy MSS/displacement i pierwsza mitigacja.
- Order block: wyłącznie przyczynowy OB powodujący BOS, zgodność 4h/1h, pierwszy
  powrót do bloku i jeden handel na setup.
- Price action: kompresja 15m, wybicie zamrożonego zakresu i pierwszy
  zaakceptowany retest w sesji London/NY.
- Analityka i ryzyko: zamknięte bary, stabilny identyfikator setupu, kosztowe
  fill assumptions, maksymalnie jedna skorelowana pozycja i stałe ryzyko.

Syntetyczna S10 (BTC SMT → displacement → pierwszy event-OB) dała w pełnym
retrospektywnym oknie 9 transakcji, PF 0,549, **-0,659%** i DD 0,804%. W stresie
kosztowym wynik spadł do **-1,354%**. Centralna odmiana price action przegrała w
evaluation kwiecień–sierpień 2026 (-3,316 USD), a ścisły first-mitigation OB nie
wygenerował żadnego wykonywalnego setupu. Żadnej z tych wersji nie należy
wdrażać.

## S11 — miesięczny funding carry

S11 nie prognozuje kierunku ceny. Utrzymuje taką samą ilość aktywa w dwóch
przeciwnych nogach:

- long spot;
- short USD-M perpetual;
- dodatni funding płacony przez longi trafia do nogi short;
- zysk/strata kierunkowa obu nóg znosi się przy równej ilości.

Reguła jest zamrożona i przyczynowa:

1. O 00:01 UTC pierwszego dnia miesiąca sumowany jest funding wyłącznie z
   zakończonego poprzedniego miesiąca.
2. Wybierany jest lider spośród ETH, SOL i BNB. BTC nie jest handlowany.
3. Wejście następuje tylko przy wyniku co najmniej 10 bps.
4. Trzymany instrument jest zamykany, gdy jego poprzedni miesiąc ma wynik
   niedodatni.
5. Zmiana dodatniego instrumentu następuje dopiero, gdy przewaga lidera pokrywa
   pełny koszt round-trip.
6. Jednocześnie utrzymywana jest maksymalnie jedna para spot/perpetual.

Alokacja 250 USD:

- 100 USD long spot;
- 100 USD collateral dla short perpetual o nominale 100 USD (1×);
- 50 USD rezerwy;
- brak skalowania strat, brak 20×, brak dokładania do pozycji.

Koszty bazowe obejmują 10 bps prowizji spot, 2 bps futures oraz po 1 bps
slippage na każdej nodze i w każdym kierunku. Stres podnosi całkowity round-trip
z 28 do 50 bps.

| Okno | Wynik bazowy | Wynik stress | Maks. DD bazowy |
|---|---:|---:|---:|
| Development VIII–XII 2025 | +0,689% | +0,609% | 0,056% |
| Validation I–III 2026 | -0,007% | -0,081% | 0,127% |
| Evaluation IV–VIII 2026 | +0,454% | +0,360% | 0,063% |
| Forward combined I–VIII 2026 | +0,446% | +0,280% | 0,183% |
| Całe dostępne VIII 2025–VIII 2026 | +1,230% | +1,069% | 0,157% |

W forward-combined system najpierw utrzymywał ETH (styczeń–luty), w marcu
przeszedł do gotówki, pozostał poza rynkiem w kwietniu i utrzymywał BNB od maja
do końca sierpnia. Maksymalny historyczny wzrost ceny przeciw nodze short wyniósł
21,29% w forward i 34,22% w całym oknie; przy nominale równym collateral nie
doszło do testu granicy likwidacji.

## Ograniczenia, których wynik nie rozwiązuje

- Brak archiwum spot: cena perpetual jest użyta jako proxy ceny spot i mark.
- Model nie mierzy basis risk, rozjazdu filli obu nóg, transferów collateral,
  awarii giełdy ani podatków.
- Dwa epizody w forward to za mało do estymacji stabilnego PF lub istotności.
- Validation była lekko ujemna po kosztach, więc przewaga nie jest równomierna.
- Zwrot jest niski; wartością kandydata jest mała ekspozycja kierunkowa i małe
  obsunięcie, nie szybki wzrost kapitału.

## Protokół następnego kroku

Nie zmieniać progów po obejrzeniu nowych danych. Uruchomić S11 na koncie paper z
rzeczywistymi kwotowaniami spot i futures na co najmniej 12 miesięcy lub 12
niezależnych epizodów. Rejestrować osobno oba fille, basis, prowizje, slippage,
funding i zmianę margin ratio.

Warunek promocji do minimalnej stawki realnej:

- dodatni wynik netto również przy kosztach stress;
- brak zdarzenia likwidacyjnego i brak niedopasowania ilości obu nóg;
- rzeczywisty basis i koszty mieszczą się w budżecie stress;
- maksymalne obsunięcie portfela poniżej 1%;
- co najmniej 12 niezależnych epizodów, bez ponownego strojenia parametrów.

Do tego czasu obecny system live powinien pozostać wyłączony dla S1C, S1CF,
S10, S11, S12AI, S13 oraz S14.

## Uzupełnienie: S12AI jako selektor, nie samodzielna przewaga

Zaproponowany później przepływ „X z Y kryteriów → ocena AI” został dodany jako
osobny tryb shadow. Quorum 7/9 z minimum 2/3 dowodów strukturalnych jedynie
nominuje setup. Werdykt wymaga zgodnego APPROVE od agentów context, order-flow i
risk-manager, a mocne veto devil's advocate odrzuca przypadek. Każdy setup ma
fingerprint i jest analizowany tylko raz.

Surowa kolejka approve-all na development maj–czerwiec 2026 pozostała ujemna:
125 filli, WR 20,8%, PF 0,166 i -6,273%. Oznacza to, że samo quorum nie jest
strategią. Wartość AI zostanie uznana dopiero po co najmniej 100 prospektywnie
rozstrzygniętych kandydaturach, gdy kohorta APPROVE osiągnie PF > 1,20 po
kosztach i wyraźnie pokona identycznie mierzoną kohortę REJECT. S12AI jest
domyślnie wyłączony i technicznie zablokowany przed wykonaniem transakcji.

## Uzupełnienie: Bollinger Bands — S13 i S14

Bollinger Bands zostały potraktowane jako jedna rodzina informacji o reżimie
zmienności i położeniu ceny, a nie jako kilka skorelowanych głosów (`%B`, touch,
bandwidth i squeeze). Zespół zamroził reguły przed odczytem wyników. BB(20, 2σ)
używa odchylenia populacyjnego, poziom zewnętrznego pasma pochodzi z poprzedniej
zamkniętej świecy, a percentyle bandwidth wykluczają klasyfikowany bar.

S13 przetestował dwie prostsze trasy na development VIII 2025–I 2026:

| Trasa S13 | Kandydaci | Fille base | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---:|---:|---:|---:|---:|---:|---:|
| squeeze → expansion, wejście market | 58 | 37 | 27,0% | 0,434 | -7,04 USD | -2,815% | 3,355% |
| sweep sesji i BB → reclaim + SMT | 35 | 14 | 14,3% | 0,120 | -4,85 USD | -1,941% | 1,941% |

Po audycie powstał wspólny minutowy symulator portfela: jeden cash, jeden
pending i jedna pozycja dla ETH/SOL/BNB, 250 USD kapitału, 0,50 USD ryzyka,
notional do 125 USD i dźwignia do 5×. Naprawiono też semantykę SMT: BTC nie może
potwierdzić sweepu ani na bieżącej, ani na wcześniejszej świecy tej samej sesji.

S14 sprawdził pełniejszy przepływ `twardy event → X z Y → kandydat shadow AI`:

| Trasa S14 | Quorum | Kandydaci | Fille base | PF | PnL |
|---|---:|---:|---:|---:|---:|
| squeeze → wybicie box/BB → dokładny event-OB | 4/6 | 90 | 5 | 0,877 | -0,15 USD |
| sweep box/BB → sesyjne SMT → późniejszy MSS | 3/6 | 2 | 0 | — | 0,00 USD |

Wersja market po ekspansji ma wyraźnie ujemną wartość. Wersja z mitygacją OB
nominuje dużo przypadków, ale realistyczny resting limit prawie się nie
wypełnia; przy kosztach stress nie było żadnego fillu. Pełna sekwencja
sweep–SMT–MSS jest natomiast zbyt rzadka, aby utworzyć uczącą kolejkę dla AI.

Obie strategie przegrały zamrożoną bramkę development, dlatego validation i
retrospective evaluation nie zostały otwarte. Nie oznacza to, że każdy możliwy
system Bollingera musi przegrywać; oznacza, że cztery dokładnie opisane warianty
nie wykazały przewagi i nie wolno ich wdrażać ani ratować strojeniem tych samych
danych. Agent AI nie może stworzyć przewagi z kolejki o PF 0,12–0,43 bez
prospektywnego dowodu bardzo silnej selekcji.

Szczegóły i hashe protokołów znajdują się w `docs/research/s13_bollinger/` oraz
`docs/research/s14_bollinger_event/`.
