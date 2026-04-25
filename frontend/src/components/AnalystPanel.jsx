import React from 'react';
import { Shield, BarChart2, Activity, MessageSquare, BrainCircuit, Globe2, Loader2 } from 'lucide-react';

const ANALYST_LABELS = {
    momentum: { name: 'Momentum', icon: Activity },
    volume_flow: { name: 'Volume Flow', icon: BarChart2 },
    structure: { name: 'Structure', icon: Shield },
    sentiment: { name: 'Sentiment', icon: MessageSquare },
    llm_narrative: { name: 'LLM Narrative', icon: BrainCircuit },
    cross_asset: { name: 'Cross-Asset', icon: Globe2 },
};

export default function AnalystPanel({ data, symbol }) {
    if (!data || !data[symbol]) {
        return (
            <div className="flex flex-col items-center justify-center p-12 text-gray-500 h-full">
                <Loader2 className="w-8 h-8 mb-4 opacity-20 animate-spin text-[#00E5FF]" />
                <p className="font-mono text-xs uppercase tracking-widest text-center">Awaiting Analyst Data</p>
            </div>
        );
    }

    const analysts = data[symbol];

    return (
        <div className="flex flex-col gap-4">
            {Object.entries(ANALYST_LABELS).map(([key, meta]) => {
                const signal = analysts[key];
                const score = signal?.score || 0;
                const confidence = signal?.confidence || 0;
                const Icon = meta.icon;

                const scoreColor = score > 10 ? 'text-[#10B981]' : score < -10 ? 'text-[#EF4444]' : 'text-gray-500';
                const confidenceWidth = `${confidence * 100}%`;

                return (
                    <div key={key} className="bg-[#151518] border border-white/5 rounded-xl p-4 flex flex-col relative overflow-hidden group hover:bg-[#1a1a1e] transition-colors">
                        {/* Score glow effect */}
                        <div className="absolute right-0 top-1/2 -translate-y-1/2 w-16 h-16 blur-2xl opacity-10 group-hover:opacity-20 transition-opacity" style={{ backgroundColor: score > 10 ? '#10B981' : score < -10 ? '#EF4444' : '#6b7280' }} />

                        <div className="flex justify-between items-start mb-3">
                            <div className="flex items-center gap-2">
                                <Icon className="w-4 h-4 text-gray-400" />
                                <span className="text-xs uppercase tracking-widest font-bold text-gray-300">{meta.name}</span>
                            </div>
                            <div className={`text-2xl font-black font-mono tracking-tighter ${scoreColor}`}>
                                {score >= 0 ? '+' : ''}{score.toFixed(0)}
                            </div>
                        </div>

                        <div className="w-full bg-[#0a0a0b] h-1.5 rounded-full overflow-hidden mb-3 border border-white/5">
                            <div
                                className="h-full bg-gradient-to-r from-[#00E5FF] to-[#3b82f6] transition-all duration-500 rounded-full"
                                style={{ width: confidenceWidth }}
                            />
                        </div>

                        <p className="text-[11px] text-gray-400 font-mono leading-relaxed line-clamp-2" title={signal?.reasoning}>
                            {signal?.reasoning || 'Awaiting reasoning...'}
                        </p>
                    </div>
                );
            })}
        </div>
    );
}
