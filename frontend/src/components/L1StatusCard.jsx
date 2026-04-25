import React, { useState } from 'react';
import { CheckCircle, XCircle, Clock, ChevronDown, ChevronUp, Minus } from 'lucide-react';
import MTFWidget from './MTFWidget';

const GATE_LABELS = {
    A1: 'Killzone (London/NY)',
    A2: 'HTF Trend (EMA50/200)',
    A3: 'BTC Correlation',
    A4: 'Funding Rate',
    A5: 'ADX > 20 (trending)',
    B1: 'Liquidity Sweep',
    B2: 'FVG / Order Block',
    B3: 'Premium / Discount zone',
    B4: 'Klasyczny pattern',
    B5: 'ATR Squeeze',
    C1: 'ChoCH (struktura)',
    C2: 'RSI Divergence',
    C3: 'EMA 9/21 alignment',
    C4: 'Volume Spike',
    C5: 'Cena vs VWAP',
};

function Gate({ id, passed, required }) {
    const color = passed
        ? 'text-[#10B981]'
        : required
            ? 'text-[#EF4444]'
            : 'text-gray-600';

    return (
        <div className={`flex items-center gap-2 py-1 ${color}`}>
            {passed
                ? <CheckCircle className="w-3.5 h-3.5 shrink-0" />
                : required
                    ? <XCircle className="w-3.5 h-3.5 shrink-0" />
                    : <Minus className="w-3.5 h-3.5 shrink-0" />
            }
            <span className="text-[11px] font-mono">
                <span className="font-bold">{id}</span> {GATE_LABELS[id]}
            </span>
        </div>
    );
}

function GatesGroup({ label, gates, obj, required_all, required_count }) {
    const keys = Object.keys(obj || {});
    const passed = keys.filter(k => obj[k]);
    const req = required_count
        ? `${passed.length}/${keys.length} — potrzeba ${required_count}`
        : 'wszystkie wymagane';
    const ok = required_all
        ? passed.length === keys.length
        : passed.length >= (required_count || 0);

    return (
        <div className="flex flex-col gap-0.5">
            <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] uppercase tracking-widest text-gray-500 font-bold">{label}</span>
                <span className={`text-[10px] font-mono font-bold ${ok ? 'text-[#10B981]' : 'text-[#EF4444]'}`}>{req}</span>
            </div>
            {gates.map(id => (
                <Gate key={id} id={id} passed={!!obj?.[id]} required={required_all || false} />
            ))}
        </div>
    );
}

export default function L1StatusCard({ data, symbol }) {
    const [expanded, setExpanded] = useState(false);

    if (!data || data.no_data) {
        return (
            <div className="glass-panel p-5 flex flex-col items-center justify-center min-h-[120px] gap-2">
                <Clock className="w-6 h-6 text-gray-600" />
                <span className="text-[10px] uppercase tracking-widest text-gray-600 font-mono">{symbol}</span>
                <span className="text-[10px] text-gray-600 font-mono">Czeka na scan L1...</span>
            </div>
        );
    }

    const isLong  = data.direction === 'LONG';
    const passed  = data.passed;
    const ts      = data.timestamp ? new Date(data.timestamp) : null;
    const timeStr = ts ? ts.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' }) : '';

    return (
        <div className={`glass-panel overflow-hidden border transition-all ${passed ? 'border-[#10B981]/20' : 'border-white/5'}`}>
            {/* Header — klikalne */}
            <button
                className="w-full p-4 flex items-center justify-between hover:bg-white/[0.02] transition-colors"
                onClick={() => setExpanded(e => !e)}
            >
                <div className="flex items-center gap-3">
                    <div className={`w-2 h-2 rounded-full ${passed ? 'bg-[#10B981] shadow-[0_0_6px_#10B981]' : 'bg-gray-700'}`} />
                    <span className="font-black font-mono text-white">{symbol.replace('USDT', '')}<span className="text-gray-600 font-normal text-xs">USDT</span></span>
                    {data.direction && (
                        <span className={`text-xs font-bold font-mono px-2 py-0.5 rounded-full ${isLong ? 'bg-[#10B981]/10 text-[#10B981]' : 'bg-[#EF4444]/10 text-[#EF4444]'}`}>
                            {data.direction}
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-2">
                    {data.passing_strategies?.length > 0
                        ? data.passing_strategies.map(s => (
                            <span key={s.id} className="text-[10px] font-bold font-mono px-1.5 py-0.5 bg-[#00E5FF]/15 text-[#00E5FF] rounded">
                                {s.id}
                            </span>
                          ))
                        : passed
                            ? <span className="text-[10px] font-mono text-[#D4AF37]">pass / no strategy</span>
                            : <span className="text-[10px] font-mono text-gray-600">
                                A:{Object.values(data.gates_a || {}).filter(Boolean).length}/5 &nbsp;
                                B:{data.gates_b_count || 0}/5 &nbsp;
                                C:{data.gates_c_count || 0}/5
                              </span>
                    }
                    {expanded ? <ChevronUp className="w-4 h-4 text-gray-500" /> : <ChevronDown className="w-4 h-4 text-gray-500" />}
                </div>
            </button>

            {/* Expanded gate detail */}
            {expanded && (
                <div className="px-4 pb-4 border-t border-white/5 pt-4 flex flex-col gap-4">

                    {/* Active strategies */}
                    {data.passing_strategies?.length > 0 && (
                        <div className="flex flex-wrap gap-2 pb-3 border-b border-white/5">
                            <span className="text-[10px] text-gray-500 font-mono self-center">Strategie aktywne:</span>
                            {data.passing_strategies.map(s => (
                                <div key={s.id} className="flex items-center gap-1.5 px-2.5 py-1 bg-[#00E5FF]/10 border border-[#00E5FF]/25 rounded-full">
                                    <span className="text-[10px] font-bold font-mono text-[#00E5FF]">{s.id}</span>
                                    <span className="text-[10px] text-gray-300 font-mono">{s.name}</span>
                                </div>
                            ))}
                        </div>
                    )}
                    {!data.has_whale_cvd && (
                        <div className="text-[10px] text-gray-600 font-mono -mt-2 mb-1">
                            ⚠️ S2 nieaktywna — brak danych WhaleCVD (aggTrade stream potrzebny)
                        </div>
                    )}

                    {/* Market context */}
                    {(data.adx_value || data.funding_rate !== undefined) && (
                        <div className="flex flex-wrap gap-3 text-[10px] font-mono text-gray-500 pb-3 border-b border-white/5">
                            {data.adx_value   && <span>ADX <span className="text-white">{data.adx_value?.toFixed(1)}</span></span>}
                            {data.funding_rate !== undefined && <span>Funding <span className="text-white">{(data.funding_rate * 100).toFixed(3)}%</span></span>}
                            {data.regime      && <span>Regime <span className="text-white">{data.regime}</span></span>}
                            {data.btc_trend   && <span>BTC <span className="text-white">{data.btc_trend}</span></span>}
                            {timeStr          && <span className="ml-auto">Scan {timeStr}</span>}
                        </div>
                    )}

                    <GatesGroup
                        label="Gate A — Bias & Context (WSZYSTKIE wymagane)"
                        gates={['A1','A2','A3','A4','A5']}
                        obj={data.gates_a}
                        required_all
                    />
                    <GatesGroup
                        label="Gate B — Setup Structure (min 3/5)"
                        gates={['B1','B2','B3','B4','B5']}
                        obj={data.gates_b}
                        required_count={3}
                    />
                    <GatesGroup
                        label="Gate C — Trigger Confirmation (min 2/5)"
                        gates={['C1','C2','C3','C4','C5']}
                        obj={data.gates_c}
                        required_count={2}
                    />

                    {data.swept_level && (
                        <div className="flex flex-wrap gap-3 text-[10px] font-mono text-gray-500 pt-2 border-t border-white/5">
                            <span>Sweep <span className="text-white">${data.swept_level?.toFixed(0)}</span></span>
                            {data.fvg_zone && <span>FVG <span className="text-white">${data.fvg_zone[0]?.toFixed(0)}–${data.fvg_zone[1]?.toFixed(0)}</span></span>}
                            {data.daily_vwap && <span>VWAP <span className="text-white">${data.daily_vwap?.toFixed(0)}</span></span>}
                        </div>
                    )}
                    {/* MTF Analysis */}
                    <div className="border-t border-white/5 pt-4">
                        <MTFWidget symbol={symbol} />
                    </div>
                </div>
            )}
        </div>
    );
}
