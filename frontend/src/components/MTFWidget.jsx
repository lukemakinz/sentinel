import React from 'react';
import { usePolling } from '../hooks/usePolling';
import { fetchMTF } from '../api';
import { AlertTriangle, TrendingUp, TrendingDown, Minus } from 'lucide-react';

const TF_LABELS = { '5m': '5M', '15m': '15M', '1h': '1H', '4h': '4H', '1d': '1D' };
const TF_ORDER  = ['1d', '4h', '1h', '15m', '5m'];

const RISK_COLORS = {
    LOW:    { bg: 'bg-[#10B981]/10', border: 'border-[#10B981]/25', text: 'text-[#10B981]' },
    MEDIUM: { bg: 'bg-[#D4AF37]/10', border: 'border-[#D4AF37]/25', text: 'text-[#D4AF37]' },
    HIGH:   { bg: 'bg-[#EF4444]/10', border: 'border-[#EF4444]/25', text: 'text-[#EF4444]' },
};

const TRADE_TYPE_LABELS = {
    TREND_FOLLOW:  { label: 'Trend Follow',   color: 'text-[#10B981]' },
    SWING:         { label: 'Swing',           color: 'text-[#10B981]' },
    INTRADAY:      { label: 'Intraday',        color: 'text-[#D4AF37]' },
    SCALP:         { label: 'Scalp',           color: 'text-[#D4AF37]' },
    COUNTER_TREND: { label: 'Counter-Trend',   color: 'text-[#EF4444]' },
    AVOID:         { label: 'Avoid',           color: 'text-gray-500' },
};

function TFBox({ tf, data }) {
    const dir = data?.direction || 'NEUTRAL';
    const str = data?.strength  || 0;
    const colors = {
        BULLISH: 'bg-[#10B981]/15 border-[#10B981]/30 text-[#10B981]',
        BEARISH: 'bg-[#EF4444]/15 border-[#EF4444]/30 text-[#EF4444]',
        NEUTRAL: 'bg-white/5 border-white/10 text-gray-500',
    };
    const Icon = dir === 'BULLISH' ? TrendingUp : dir === 'BEARISH' ? TrendingDown : Minus;

    return (
        <div className={`flex flex-col items-center gap-1 px-3 py-2 rounded-xl border ${colors[dir]} min-w-[52px]`}
             title={`${data?.reason || ''} | EMA20: ${data?.ema20} EMA50: ${data?.ema50}`}>
            <span className="text-[9px] font-bold font-mono tracking-widest">{TF_LABELS[tf]}</span>
            <Icon className="w-3.5 h-3.5" />
            {str > 0 && <span className="text-[8px] font-mono opacity-60">{str}</span>}
        </div>
    );
}

export default function MTFWidget({ symbol }) {
    const { data, loading } = usePolling(() => fetchMTF(symbol), 120000); // 2 min

    if (loading || !data || data.error) return null;

    const tfs  = data.timeframes || {};
    const risk = RISK_COLORS[data.risk_level] || RISK_COLORS.MEDIUM;
    const type = TRADE_TYPE_LABELS[data.trade_type] || TRADE_TYPE_LABELS.AVOID;

    return (
        <div className="flex flex-col gap-3">
            {/* TF boxes */}
            <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[9px] uppercase tracking-widest text-gray-600 font-mono w-full">
                    Multi-Timeframe
                </span>
                {TF_ORDER.map(tf => (
                    <TFBox key={tf} tf={tf} data={tfs[tf]} />
                ))}
            </div>

            {/* Trade type + risk */}
            <div className={`flex items-start gap-2 px-3 py-2 rounded-lg border text-[10px] font-mono ${risk.bg} ${risk.border}`}>
                {data.risk_level === 'HIGH' && <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5 text-[#EF4444]" />}
                <div>
                    <span className={`font-bold ${type.color}`}>{type.label}</span>
                    {' — '}
                    <span className="text-gray-400">{data.note}</span>
                </div>
            </div>
        </div>
    );
}
