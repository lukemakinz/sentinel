"""S44C — dynamic liquidity filter.

Izolowany eksperyment na bazie S43/S20 H1.

JEDYNA istotna zmiana względem S43:
    sztywny filtr czasu 07:00-20:00 UTC

zostaje zastąpiony przez:

    1. aktualny turnover proxy >= 60 percentyla poprzednich 7 dni
    2. ATR/price <= 90 percentyla poprzednich 7 dni

Progi są liczone z .shift(1), więc nie ma look-ahead.

Pozostałe elementy pozostają takie jak w S43:
- order block 15m
- trend 4h EMA200
- ADX 1h >= 20
- OBV
- OI
- stop
- trailing
- max hold
- sizing
- koszty

UWAGA:
Dla czystego A/B zachowujemy oryginalną logikę OI S43.
Poprawka OI z S44A powinna być później testowana osobno
jako S44C+OI, jeśli S44C pokaże przewagę.
"""

from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .order_block_continuation_scalp import order_block_features
from .scalp_strategy import ScalpConfig


@dataclass(frozen=True)
class S44CLiquidityConfig:
    name: str = "S44C_dynamic_liquidity"

    # ---------------------------------------------------------
    # Parametry bazowe S43 / S20
    # ---------------------------------------------------------

    ema_period: int = 200
    ema_slope_lookback: int = 8

    adx_threshold: float = 20.0

    displacement_atr_mult: float = 1.5
    volume_mult: float = 1.2
    volume_avg_lookback: int = 20

    zone_ttl_bars: int = 32

    stop_buffer_atr_mult: float = 0.15

    obv_ema_period: int = 9

    # 8 x 15m = 2h
    oi_lookback_bars: int = 8

    # ---------------------------------------------------------
    # S44C — JEDYNA NOWA CZĘŚĆ
    # ---------------------------------------------------------

    # 7 dni * 24h * 4 świece/h
    liquidity_lookback_bars: int = 672

    # nie generujemy filtra bez minimum 2 dni historii
    liquidity_min_history: int = 192

    # aktualny turnover musi być >= 60 percentyla historii
    turnover_quantile: float = 0.60

    # unikamy top 10% najbardziej ekstremalnych warunków ATR
    atr_pct_quantile: float = 0.90

    def __post_init__(self):

        if self.liquidity_lookback_bars < 96:
            raise ValueError(
                "liquidity_lookback_bars too small"
            )

        if self.liquidity_min_history < 96:
            raise ValueError(
                "liquidity_min_history too small"
            )

        if not 0.0 < self.turnover_quantile < 1.0:
            raise ValueError(
                "invalid turnover_quantile"
            )

        if not 0.0 < self.atr_pct_quantile < 1.0:
            raise ValueError(
                "invalid atr_pct_quantile"
            )

    def execution(self) -> ScalpConfig:
        """
        Execution identyczne jak S20 H1 / S43.

        Nie zmieniamy sizingu podczas testowania edge.
        """

        return ScalpConfig(
            name=self.name,

            minutes=15,

            target_r=8.0,

            partial_r=1.5,

            partial_fraction=0.0,

            trailing=True,

            trail_atr=2.5,

            max_hold_minutes=240,

            # ---------------------------------------
            # sizing bazowy
            # ---------------------------------------

            risk_fraction=0.0020,

            max_notional_equity=0.50,

            daily_loss_fraction=0.006,

            fixed_risk_usd=0.50,

            fixed_margin_usd=25.0,

            # ---------------------------------------
            # execution / koszty
            # ---------------------------------------

            fee_bps=5.0,

            slippage_bps=2.0,

            maker_fee_bps=2.0,

            limit_penetration_bps=2.0,

            min_reward_cost_ratio=3.0,

            leverage=5.0,

            max_margin_fraction=0.10,

            margin_safety_reserve=0.01,
        )


def liquidity_features(
    minutes: pd.DataFrame,
    metrics: pd.DataFrame,
    config: S44CLiquidityConfig,
) -> pd.DataFrame:

    """
    S43 features + kauzalny filtr aktywności.

    Kluczowa rzecz:

        shift(1)

    powoduje, że próg dla bieżącej świecy powstaje WYŁĄCZNIE
    z wcześniejszych świec.

    Czyli backtest nie zna przyszłości.
    """

    bars = order_block_features(
        minutes,
        config,
    )

    # ---------------------------------------------------------
    # Open Interest
    # ---------------------------------------------------------

    aligned = metrics.reindex(
        bars.index,
        method="ffill",
    )

    bars = bars.join(aligned)

    bars["oi_change"] = (
        bars.open_interest
        - bars.open_interest.shift(
            config.oi_lookback_bars
        )
    )

    # ---------------------------------------------------------
    # Proxy realnej aktywności rynku
    # ---------------------------------------------------------

    # Nie próbujemy udawać prawdziwego order-book spreadu.
    #
    # close * volume daje prosty proxy obrotu nominalnego,
    # który można porównywać względnie w czasie dla danej pary.

    bars["turnover_proxy"] = (
        bars["close"]
        * bars["volume"]
    )

    # ---------------------------------------------------------
    # Zmienność znormalizowana ceną
    # ---------------------------------------------------------

    bars["atr_pct"] = (
        bars["atr"]
        / bars["close"]
    )

    # ---------------------------------------------------------
    # WYŁĄCZNIE PRZESZŁE DANE
    # ---------------------------------------------------------

    historical_turnover = (
        bars["turnover_proxy"]
        .shift(1)
    )

    historical_atr_pct = (
        bars["atr_pct"]
        .shift(1)
    )

    # ---------------------------------------------------------
    # Minimalna wymagana aktywność
    # ---------------------------------------------------------

    bars["turnover_floor"] = (
        historical_turnover
        .rolling(
            config.liquidity_lookback_bars,
            min_periods=config.liquidity_min_history,
        )
        .quantile(
            config.turnover_quantile
        )
    )

    # ---------------------------------------------------------
    # Maksymalny dopuszczalny volatility shock
    # ---------------------------------------------------------

    bars["atr_pct_ceiling"] = (
        historical_atr_pct
        .rolling(
            config.liquidity_lookback_bars,
            min_periods=config.liquidity_min_history,
        )
        .quantile(
            config.atr_pct_quantile
        )
    )

    # ---------------------------------------------------------
    # Finalny filtr S44C
    # ---------------------------------------------------------

    bars["liquidity_ok"] = (

        (
            bars["turnover_proxy"]
            >= bars["turnover_floor"]
        )

        &

        (
            bars["atr_pct"]
            <= bars["atr_pct_ceiling"]
        )

        & bars["turnover_floor"].notna()

        & bars["atr_pct_ceiling"].notna()
    )

    return bars


def generate_s44c_signals(
    bars: pd.DataFrame,
    config: S44CLiquidityConfig,
    symbol: str,
) -> list[dict]:

    n = len(bars)

    atr = bars.atr.to_numpy()

    low = bars.low.to_numpy()
    high = bars.high.to_numpy()
    close = bars.close.to_numpy()

    htf_trend_up = (
        bars.htf_trend_up.to_numpy()
    )

    htf_trend_down = (
        bars.htf_trend_down.to_numpy()
    )

    htf_adx = (
        bars.htf_adx.to_numpy()
    )

    obv = bars.obv.to_numpy()

    obv_ema = (
        bars.obv_ema.to_numpy()
    )

    oi_change = (
        bars.oi_change.to_numpy()
    )

    liquidity_ok = (
        bars.liquidity_ok.to_numpy(
            dtype=bool
        )
    )

    ob_bull_confirmed = (
        bars.ob_bull_confirmed.to_numpy()
    )

    ob_bull_top = (
        bars.ob_bull_top.to_numpy()
    )

    ob_bull_bottom = (
        bars.ob_bull_bottom.to_numpy()
    )

    ob_bear_confirmed = (
        bars.ob_bear_confirmed.to_numpy()
    )

    ob_bear_top = (
        bars.ob_bear_top.to_numpy()
    )

    ob_bear_bottom = (
        bars.ob_bear_bottom.to_numpy()
    )

    active = {
        1: [],
        -1: [],
    }

    records = []

    # =========================================================
    # GŁÓWNA PĘTLA
    # =========================================================

    for i in range(n):

        # ------------------------------------------------------
        # wygasające order blocki
        # ------------------------------------------------------

        active[1] = [
            z
            for z in active[1]
            if z["expires"] > i
        ]

        active[-1] = [
            z
            for z in active[-1]
            if z["expires"] > i
        ]

        # ------------------------------------------------------
        # nowy bullish OB
        # ------------------------------------------------------

        if (
            ob_bull_confirmed[i]
            and np.isfinite(
                ob_bull_top[i]
            )
            and np.isfinite(
                ob_bull_bottom[i]
            )
        ):

            active[1].append({
                "top":
                    float(
                        ob_bull_top[i]
                    ),

                "bottom":
                    float(
                        ob_bull_bottom[i]
                    ),

                "expires":
                    i
                    + config.zone_ttl_bars,
            })

        # ------------------------------------------------------
        # nowy bearish OB
        # ------------------------------------------------------

        if (
            ob_bear_confirmed[i]
            and np.isfinite(
                ob_bear_top[i]
            )
            and np.isfinite(
                ob_bear_bottom[i]
            )
        ):

            active[-1].append({
                "top":
                    float(
                        ob_bear_top[i]
                    ),

                "bottom":
                    float(
                        ob_bear_bottom[i]
                    ),

                "expires":
                    i
                    + config.zone_ttl_bars,
            })

        if not np.isfinite(
            atr[i]
        ):
            continue

        # =====================================================
        # LONG / SHORT
        # =====================================================

        for side in (
            1,
            -1,
        ):

            # --------------------------------------------------
            # retest
            # --------------------------------------------------

            if side == 1:

                touched = [
                    z
                    for z in active[1]
                    if (
                        low[i]
                        <= z["top"]
                    )
                    and (
                        close[i]
                        >= z["bottom"]
                    )
                ]

            else:

                touched = [
                    z
                    for z in active[-1]
                    if (
                        high[i]
                        >= z["bottom"]
                    )
                    and (
                        close[i]
                        <= z["top"]
                    )
                ]

            if not touched:
                continue

            # pierwsze dotknięcie konsumuje strefę

            for z in touched:
                active[side].remove(z)

            # --------------------------------------------------
            # 1. TREND / REGIME
            # --------------------------------------------------

            regime_ok = (

                htf_trend_up[i]

                if side == 1

                else htf_trend_down[i]
            )

            if not (
                regime_ok
                and np.isfinite(
                    htf_adx[i]
                )
                and htf_adx[i]
                >= config.adx_threshold
            ):
                continue

            # --------------------------------------------------
            # 2. OBV
            # --------------------------------------------------

            flow_ok = (

                obv[i]
                > obv_ema[i]

                if side == 1

                else

                obv[i]
                < obv_ema[i]
            )

            if not flow_ok:
                continue

            # --------------------------------------------------
            # 3. OPEN INTEREST
            #
            # CELOWO pozostawiamy S43 bez zmian.
            #
            # To eksperyment tylko filtra płynności.
            # --------------------------------------------------

            if not np.isfinite(
                oi_change[i]
            ):
                continue

            oi_ok = (

                oi_change[i] >= 0

                if side == 1

                else

                oi_change[i] <= 0
            )

            if not oi_ok:
                continue

            # ==================================================
            # 4. S44C
            #
            # ZAMIAST:
            #
            # 07 <= hour < 20
            #
            # MAMY REALNY FILTR AKTYWNOŚCI
            # ==================================================

            if not liquidity_ok[i]:
                continue

            # --------------------------------------------------
            # STOP
            # --------------------------------------------------

            zone = touched[0]

            if side == 1:

                stop = (
                    zone["bottom"]
                    - config.stop_buffer_atr_mult
                    * atr[i]
                )

            else:

                stop = (
                    zone["top"]
                    + config.stop_buffer_atr_mult
                    * atr[i]
                )

            risk = (
                side
                * (
                    close[i]
                    - stop
                )
            )

            if risk <= 0:
                continue

            direction = (
                "long"
                if side == 1
                else "short"
            )

            # --------------------------------------------------
            # SYGNAŁ
            # --------------------------------------------------

            records.append({

                "timestamp":
                    bars.index[i],

                "side":
                    side,

                "reference":
                    float(
                        close[i]
                    ),

                "stop":
                    float(
                        stop
                    ),

                "min_stop_atr":
                    0.5,

                "max_stop_atr":
                    3.0,

                "atr":
                    float(
                        atr[i]
                    ),

                "score":
                    6,

                "setup":
                    (
                        "s44c_dynamic_liquidity_"
                        f"{symbol}"
                    ),

                "setup_id":
                    (
                        f"S44C:v1:"
                        f"{symbol}:"
                        f"{direction}:"
                        f"{bars.index[i].isoformat()}"
                    ),

                # ----------------------------------------------
                # diagnostyka filtra
                # ----------------------------------------------

                "turnover_proxy":
                    float(
                        bars.turnover_proxy.iloc[i]
                    ),

                "turnover_floor":
                    float(
                        bars.turnover_floor.iloc[i]
                    ),

                "atr_pct":
                    float(
                        bars.atr_pct.iloc[i]
                    ),

                "atr_pct_ceiling":
                    float(
                        bars.atr_pct_ceiling.iloc[i]
                    ),
            })

    # ---------------------------------------------------------
    # sortowanie i konflikt long/short
    # ---------------------------------------------------------

    records.sort(
        key=lambda x: x["timestamp"]
    )

    counts = Counter(
        x["timestamp"]
        for x in records
    )

    return [
        x
        for x in records
        if counts[x["timestamp"]] == 1
    ]


def central_variants():
    """
    Celowo dokładnie jeden wariant.

    Nie robimy:
        q=0.50
        q=0.55
        q=0.60
        q=0.65
        ...

    bo wtedy bardzo szybko zaczynamy optymalizować historię,
    zamiast testować hipotezę.
    """

    return [
        S44CLiquidityConfig()
    ]
