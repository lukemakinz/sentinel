import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createChart } from 'lightweight-charts';
import { CandlestickChart, LoaderCircle } from 'lucide-react';
import { fetchExchangeChart } from '../api';

const INTERVALS = ['5m', '15m', '1h', '4h'];

function markerForTrade(trade, type) {
    const isLong = trade.side === 'LONG';
    const entry = type === 'entry';
    return {
        time: Math.floor(new Date(entry ? trade.entry_time : trade.exit_time).getTime() / 1000),
        position: entry ? (isLong ? 'belowBar' : 'aboveBar') : (isLong ? 'aboveBar' : 'belowBar'),
        color: entry ? (isLong ? '#10B981' : '#EF4444') : '#D4AF37',
        shape: entry ? (isLong ? 'arrowUp' : 'arrowDown') : 'circle',
        text: entry ? `${trade.side} entry` : `${trade.close_reason || 'exit'} ${Number(trade.pnl || 0) >= 0 ? '+' : ''}${Number(trade.pnl || 0).toFixed(2)}`,
    };
}

function markerForFill(fill) {
    const isLong = fill.side === 'LONG';
    return {
        time: Math.floor(new Date(fill.filled_at).getTime() / 1000),
        position: isLong ? 'belowBar' : 'aboveBar',
        color: isLong ? '#00E5FF' : '#D4AF37',
        shape: isLong ? 'arrowUp' : 'arrowDown',
        text: `${fill.side} fill ${Number(fill.size || 0).toFixed(4)}`,
    };
}

function markerForClosedOrder(order) {
    const isLong = order.side === 'LONG';
    const canceled = Boolean(order.cancel_reason);
    return {
        time: Math.floor(new Date(order.closed_at).getTime() / 1000),
        position: isLong ? 'aboveBar' : 'belowBar',
        color: canceled ? '#EF4444' : '#D4AF37',
        shape: 'square',
        text: canceled ? `cancel ${order.cancel_reason}` : `${order.side} done`,
    };
}

export default function ExchangeChartPanel({ symbols = [] }) {
    const resolvedSymbols = useMemo(() => (symbols.length ? symbols : ['BTCUSDT']), [symbols]);
    const [selectedSymbol, setSelectedSymbol] = useState(resolvedSymbols[0] || 'BTCUSDT');
    const [interval, setInterval] = useState('15m');
    const [layers, setLayers] = useState({
        fills: true,
        trades: true,
        orders: true,
        positions: true,
        closedOrders: true,
    });
    const [payload, setPayload] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const containerRef = useRef(null);
    const chartRef = useRef(null);

    useEffect(() => {
        if (!resolvedSymbols.includes(selectedSymbol)) {
            setSelectedSymbol(resolvedSymbols[0] || 'BTCUSDT');
        }
    }, [resolvedSymbols, selectedSymbol]);

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        setError('');

        fetchExchangeChart(selectedSymbol, interval, 220)
            .then(({ data }) => {
                if (!cancelled) {
                    setPayload(data);
                    setLoading(false);
                }
            })
            .catch((err) => {
                if (!cancelled) {
                    setError(err.response?.data?.error || 'Nie udało się pobrać danych wykresu');
                    setLoading(false);
                }
            });

        return () => {
            cancelled = true;
        };
    }, [selectedSymbol, interval]);

    useEffect(() => {
        if (!containerRef.current || !payload?.candles?.length) {
            return undefined;
        }

        const chart = createChart(containerRef.current, {
            autoSize: true,
            layout: {
                background: { color: '#0d0d10' },
                textColor: '#9CA3AF',
            },
            grid: {
                vertLines: { color: 'rgba(255,255,255,0.05)' },
                horzLines: { color: 'rgba(255,255,255,0.05)' },
            },
            rightPriceScale: {
                borderColor: 'rgba(255,255,255,0.08)',
            },
            timeScale: {
                borderColor: 'rgba(255,255,255,0.08)',
                timeVisible: true,
                secondsVisible: false,
            },
            crosshair: {
                vertLine: { color: 'rgba(0,229,255,0.25)' },
                horzLine: { color: 'rgba(0,229,255,0.25)' },
            },
        });
        chartRef.current = chart;

        const series = chart.addCandlestickSeries({
            upColor: '#10B981',
            downColor: '#EF4444',
            borderVisible: false,
            wickUpColor: '#10B981',
            wickDownColor: '#EF4444',
        });
        series.setData(payload.candles.map((candle) => ({
            time: candle.time,
            open: candle.open,
            high: candle.high,
            low: candle.low,
            close: candle.close,
        })));

        const markers = [];
        if (layers.fills) {
            for (const fill of payload.fills || []) {
                if (fill.filled_at) markers.push(markerForFill(fill));
            }
        }
        if (layers.trades) {
            for (const trade of payload.trades || []) {
                if (trade.entry_time) markers.push(markerForTrade(trade, 'entry'));
                if (trade.exit_time) markers.push(markerForTrade(trade, 'exit'));
            }
        }
        if (layers.closedOrders) {
            for (const order of payload.closed_orders || []) {
                if (order.closed_at) markers.push(markerForClosedOrder(order));
            }
        }
        if (markers.length) {
            series.setMarkers(markers);
        }

        if (layers.positions) {
            for (const position of payload.positions || []) {
                series.createPriceLine({
                    price: Number(position.entry_price || 0),
                    color: position.side === 'LONG' ? '#10B981' : '#EF4444',
                    lineWidth: 2,
                    lineStyle: 2,
                    axisLabelVisible: true,
                    title: `${position.side} entry`,
                });
                if (position.stop_loss) {
                    series.createPriceLine({
                        price: Number(position.stop_loss),
                        color: '#EF4444',
                        lineWidth: 1,
                        lineStyle: 3,
                        axisLabelVisible: true,
                        title: 'SL',
                    });
                }
                if (position.liquidation_price) {
                    series.createPriceLine({
                        price: Number(position.liquidation_price),
                        color: '#D4AF37',
                        lineWidth: 1,
                        lineStyle: 4,
                        axisLabelVisible: true,
                        title: 'Liq',
                    });
                }
            }
        }

        if (layers.orders) {
            for (const order of payload.open_orders || []) {
                series.createPriceLine({
                    price: Number(order.price || 0),
                    color: '#00E5FF',
                    lineWidth: 1,
                    lineStyle: 1,
                    axisLabelVisible: true,
                    title: `${order.side} ${order.order_type || 'order'}`,
                });
            }
        }

        chart.timeScale().fitContent();

        return () => {
            chart.remove();
            chartRef.current = null;
        };
    }, [payload, layers]);

    const toggleLayer = (key) => {
        setLayers((current) => ({ ...current, [key]: !current[key] }));
    };

    return (
        <div className="rounded-2xl border border-white/5 bg-black/20 p-4 flex flex-col gap-4">
            <div className="flex items-start justify-between gap-3 flex-wrap">
                <div>
                    <div className="flex items-center gap-2 mb-2">
                        <CandlestickChart className="w-4 h-4 text-[#00E5FF]" />
                        <p className="text-sm font-semibold text-white">Exchange Chart</p>
                    </div>
                    <p className="text-xs text-gray-500 font-mono">
                        Nasz wykres ze świecami, poziomami pozycji, otwartymi zleceniami i markerami trade’ów.
                    </p>
                </div>

                <div className="flex items-center gap-2 flex-wrap">
                    <select
                        value={selectedSymbol}
                        onChange={(event) => setSelectedSymbol(event.target.value)}
                        className="rounded-xl border border-white/10 bg-[#0d0d10]/80 px-3 py-2 text-xs font-mono text-white outline-none"
                    >
                        {resolvedSymbols.map((symbol) => (
                            <option key={symbol} value={symbol}>{symbol}</option>
                        ))}
                    </select>

                    <select
                        value={interval}
                        onChange={(event) => setInterval(event.target.value)}
                        className="rounded-xl border border-white/10 bg-[#0d0d10]/80 px-3 py-2 text-xs font-mono text-white outline-none"
                    >
                        {INTERVALS.map((value) => (
                            <option key={value} value={value}>{value}</option>
                        ))}
                    </select>
                </div>
            </div>

            <div className="flex items-center justify-between gap-4 flex-wrap">
                <div className="flex flex-wrap gap-2">
                        {[
                        { key: 'fills', label: `Fills ${payload?.fills?.length ?? 0}`, tone: 'border-[#00E5FF]/20 text-[#00E5FF] bg-[#00E5FF]/10' },
                        { key: 'trades', label: `Trades ${payload?.trades?.length ?? 0}`, tone: 'border-[#D4AF37]/20 text-[#D4AF37] bg-[#D4AF37]/10' },
                        { key: 'orders', label: `Orders ${payload?.open_orders?.length ?? 0}`, tone: 'border-white/10 text-gray-300 bg-white/5' },
                        { key: 'positions', label: `Positions ${payload?.positions?.length ?? 0}`, tone: 'border-[#10B981]/20 text-[#10B981] bg-[#10B981]/10' },
                        { key: 'closedOrders', label: `Done ${payload?.closed_orders?.length ?? 0}`, tone: 'border-[#EF4444]/20 text-[#fca5a5] bg-[#EF4444]/10' },
                    ].map((layer) => (
                        <button
                            key={layer.key}
                            type="button"
                            onClick={() => toggleLayer(layer.key)}
                            className={`rounded-full border px-3 py-1.5 text-[11px] font-mono uppercase tracking-[0.22em] transition-all ${layers[layer.key] ? layer.tone : 'border-white/5 text-gray-600 bg-black/20'}`}
                        >
                            {layer.label}
                        </button>
                    ))}
                </div>

                <p className="text-[10px] font-mono uppercase tracking-[0.26em] text-gray-600">
                    Symbol {selectedSymbol} • {interval}
                </p>
            </div>

            <div className="h-[420px] rounded-2xl border border-white/5 bg-[#0b0b0d] overflow-hidden relative">
                {loading && (
                    <div className="absolute inset-0 flex items-center justify-center gap-2 text-gray-500 font-mono text-sm">
                        <LoaderCircle className="w-4 h-4 animate-spin" />
                        Loading chart...
                    </div>
                )}
                {!loading && error && (
                    <div className="absolute inset-0 flex items-center justify-center px-6 text-center text-sm text-[#fca5a5] font-mono">
                        {error}
                    </div>
                )}
                {!loading && !error && (!payload?.candles || payload.candles.length === 0) && (
                    <div className="absolute inset-0 flex items-center justify-center px-6 text-center text-sm text-gray-600 font-mono">
                        Brak świec dla wybranego symbolu i interwału.
                    </div>
                )}
                <div ref={containerRef} className="w-full h-full" />
            </div>
        </div>
    );
}
