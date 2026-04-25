import React from 'react';
import { History, Target, ArrowRight } from 'lucide-react';

export default function TradeJournal({ trades }) {
    if (!trades || trades.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center p-16 text-gray-500 w-full glass-panel border border-white/5">
                <History className="w-16 h-16 mb-4 opacity-20" />
                <p className="font-mono text-sm uppercase tracking-widest text-[#D4AF37]">Execution Matrix Empty</p>
                <p className="text-xs mt-2 opacity-50 font-mono">Simulated or live paper trades will populate the archive</p>
            </div>
        );
    }

    return (
        <div className="glass-panel overflow-hidden border border-white/5 shadow-2xl">
            <div className="p-5 border-b border-white/5 bg-[#151518]/80 flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-[#D4AF37]/10 text-[#D4AF37]">
                        <Target className="w-5 h-5" />
                    </div>
                    <h3 className="font-bold text-lg text-white">Execution Log</h3>
                </div>
                <span className="text-xs text-[#D4AF37] font-mono tracking-widest uppercase border border-[#D4AF37]/30 bg-[#D4AF37]/10 px-3 py-1 rounded">
                    {trades.length} Archives
                </span>
            </div>

            <div className="overflow-x-auto w-full">
                <table className="w-full text-left border-collapse min-w-[1000px]">
                    <thead>
                        <tr className="bg-[#0a0a0b]/80 border-b border-white/5 backdrop-blur-md">
                            <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest">Temporal Sig</th>
                            <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest">Protocol</th>
                            <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest">Vector</th>
                            <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest">Execution</th>
                            <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest border-r border-white/5">Resolution</th>
                            <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest">Net PnL</th>
                            <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest">Yield</th>
                            <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest">R:R</th>
                            <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest">Dur.</th>
                            <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest max-w-[200px]">Catalyst</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5 bg-[#121214]/50">
                        {trades.map(trade => {
                            const isProfit = trade.pnl >= 0;
                            return (
                                <tr key={trade.id} className="hover:bg-white/[0.03] transition-colors group">
                                    <td className="p-4">
                                        <div className="font-mono text-xs text-gray-300 group-hover:text-[#D4AF37] transition-colors">
                                            {new Date(trade.exit_time).toLocaleDateString()}
                                        </div>
                                        <div className="font-mono text-[10px] text-gray-500 mt-1">
                                            {new Date(trade.exit_time).toLocaleTimeString()}
                                        </div>
                                    </td>
                                    <td className="p-4 font-mono font-bold text-white tracking-wider">{trade.symbol}</td>
                                    <td className="p-4">
                                        <span className={`px-2 py-1 rounded text-[10px] font-bold font-mono tracking-widest border ${trade.side === 'LONG' ? 'bg-[#10B981]/10 text-[#10B981] border-[#10B981]/30' : 'bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30'}`}>
                                            {trade.side}
                                        </span>
                                    </td>
                                    <td className="p-4 font-mono text-gray-400">
                                        ${trade.entry_price?.toFixed(2)}
                                    </td>
                                    <td className="p-4 font-mono text-white border-r border-white/5 relative">
                                        <div className="absolute left-0 top-1/2 -translate-y-1/2 -ml-2 text-gray-600">
                                            <ArrowRight className="w-3 h-3" />
                                        </div>
                                        <span className="pl-2">${trade.exit_price?.toFixed(2)}</span>
                                    </td>
                                    <td className={`p-4 font-mono font-bold ${isProfit ? 'text-[#10B981]' : 'text-[#EF4444]'}`}>
                                        {isProfit ? '+' : ''}${trade.pnl?.toFixed(2)}
                                    </td>
                                    <td className={`p-4 font-mono font-bold bg-white/5 px-2 rounded mx-2 ${isProfit ? 'text-[#10B981]' : 'text-[#EF4444]'}`}>
                                        {isProfit ? '+' : ''}{trade.pnl_percent?.toFixed(2)}%
                                    </td>
                                    <td className="p-4 font-mono text-gray-300">
                                        {trade.risk_reward?.toFixed(1)}<span className="text-[#D4AF37]">R</span>
                                    </td>
                                    <td className="p-4 font-mono text-gray-500">
                                        {trade.duration_minutes}m
                                    </td>
                                    <td className="p-4 text-[11px] text-gray-400 max-w-[200px] truncate" title={trade.close_reason}>
                                        {trade.close_reason}
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
