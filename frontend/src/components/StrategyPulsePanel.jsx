import React from 'react';
import { BarChart3, TrendingUp, TrendingDown } from 'lucide-react';

export default function StrategyPulsePanel({ strategies = [] }) {
    const ranked = [...strategies].sort((a, b) => b.total_pnl - a.total_pnl).slice(0, 4);

    return (
        <div className="glass-panel p-5 border border-white/5">
            <div className="flex items-center justify-between mb-4">
                <div>
                    <p className="text-[10px] uppercase tracking-[0.28em] text-gray-600 font-mono mb-1">Strategy Pulse</p>
                    <h3 className="text-sm font-bold text-white flex items-center gap-2">
                        <BarChart3 className="w-4 h-4 text-[#00E5FF]" />
                        Live ranking of what is working
                    </h3>
                </div>
                <span className="text-[10px] font-mono uppercase tracking-[0.22em] text-gray-600">{ranked.length} tracked</span>
            </div>

            {ranked.length === 0 ? (
                <div className="rounded-xl border border-white/5 bg-[#0a0a0b] p-5 text-sm font-mono text-gray-500">
                    No strategy history yet.
                </div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
                    {ranked.map((row) => {
                        const profitable = row.total_pnl >= 0;
                        return (
                            <div key={row.strategy} className="rounded-xl border border-white/5 bg-[#0f1013] p-4">
                                <div className="flex items-center justify-between mb-3">
                                    <span className="inline-flex items-center rounded border border-[#00E5FF]/25 bg-[#00E5FF]/10 px-2 py-1 font-mono text-[10px] font-bold tracking-widest text-[#00E5FF]">
                                        {row.strategy}
                                    </span>
                                    {profitable ? <TrendingUp className="w-4 h-4 text-[#10B981]" /> : <TrendingDown className="w-4 h-4 text-[#EF4444]" />}
                                </div>
                                <div className={`text-xl font-mono font-black ${profitable ? 'text-[#10B981]' : 'text-[#EF4444]'}`}>
                                    {profitable ? '+' : ''}${row.total_pnl.toFixed(2)}
                                </div>
                                <div className="mt-3 flex items-center justify-between text-[11px] font-mono text-gray-500">
                                    <span>{row.total_trades} trades</span>
                                    <span>{row.win_rate}% WR</span>
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
