import React from 'react';
import { Target } from 'lucide-react';

export default function ConvictionMeter({ data, symbol }) {
    if (!data) {
        return (
            <div className="flex flex-col items-center justify-center p-8 text-gray-500 min-h-[160px]">
                <Target className="w-8 h-8 mb-2 opacity-20" />
                <p className="font-mono text-xs uppercase tracking-widest text-center">Awaiting<br />Signal</p>
            </div>
        );
    }

    const score = data.conviction_score || 0;
    const absScore = Math.abs(score);
    const tier = data.tier || 'NONE';
    const bias = data.bias || 'NEUTRAL';
    const displaySymbol = symbol || data.symbol || '';

    const scoreColor = score > 0 ? 'text-[#10B981]' : score < 0 ? 'text-[#EF4444]' : 'text-gray-500';
    const fillWidth = Math.min(absScore, 100) / 2; // 0-50% of bar width

    const getTierBadgeClass = (t) => {
        switch (t) {
            case 'HIGH_CONVICTION': return 'bg-[#10B981]/10 text-[#10B981] border-[#10B981]/30';
            case 'SIGNAL': return 'bg-[#00E5FF]/10 text-[#00E5FF] border-[#00E5FF]/30';
            case 'WATCH': return 'bg-[#D4AF37]/10 text-[#D4AF37] border-[#D4AF37]/30';
            default: return 'bg-white/5 text-gray-500 border-white/10';
        }
    };

    return (
        <div className="flex flex-col items-center p-6 h-full justify-between">
            <div className="text-xs uppercase tracking-widest font-bold text-gray-400 mb-2">
                {displaySymbol} CONVICTION
            </div>

            <div className={`text-5xl font-black font-mono tracking-tighter ${scoreColor} drop-shadow-[0_2px_10px_rgba(0,0,0,0.5)] my-4`}>
                {score >= 0 ? '+' : ''}{score.toFixed(0)}
            </div>

            <div className="text-xs text-gray-400 font-mono mb-6 bg-black/30 px-3 py-1 rounded-full border border-white/5">
                <span className={bias === 'BULLISH' ? 'text-[#10B981]' : bias === 'BEARISH' ? 'text-[#EF4444]' : ''}>{bias}</span> • {data.agreeing_analysts || 0}/{data.total_analysts || 6} agree
            </div>

            <div className="w-full relative px-4">
                <div className="w-full h-2 bg-[#0a0a0b] rounded-full relative overflow-hidden border border-white/5 shadow-inner">
                    <div
                        className={`absolute top-0 h-full rounded-full transition-all duration-1000 ease-out shadow-[0_0_10px_currentColor]`}
                        style={{
                            width: `${fillWidth}%`,
                            ...(score < 0
                                ? { right: '50%', background: 'linear-gradient(90deg, #EF4444, #F59E0B)' }
                                : { left: '50%', background: 'linear-gradient(90deg, #10B981, #00E5FF)' }),
                        }}
                    />
                    <div className="absolute left-1/2 top-0 w-px h-full bg-white/20 -translate-x-1/2" />
                </div>

                <div className="flex justify-between w-full mt-2 text-[10px] font-mono text-gray-600">
                    <span>-100</span>
                    <span>0</span>
                    <span>+100</span>
                </div>
            </div>

            <div className={`mt-6 px-4 py-1.5 rounded text-[10px] font-bold font-mono tracking-widest uppercase border ${getTierBadgeClass(tier)}`}>
                {tier.replace('_', ' ')}
            </div>
        </div>
    );
}
