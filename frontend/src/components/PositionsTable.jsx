import React from 'react';
import { Layers } from 'lucide-react';

export default function PositionsTable({ positions }) {
    if (!positions || positions.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center p-12 text-gray-500 w-full min-h-[300px]">
                <Layers className="w-12 h-12 mb-4 opacity-20" />
                <p className="font-mono text-sm uppercase tracking-widest">No active open positions</p>
                <p className="text-xs mt-2 opacity-50 font-mono">Awaiting high conviction signals</p>
            </div>
        );
    }

    return (
        <div className="overflow-x-auto w-full">
            <table className="w-full text-left border-collapse">
                <thead>
                    <tr className="bg-[#0a0a0b]/50 border-b border-white/5">
                        <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest border-b border-transparent">Protocol</th>
                        <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest border-b border-transparent">Vector</th>
                        <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest border-b border-transparent">Entry Base</th>
                        <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest border-b border-transparent">Mark Price</th>
                        <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest border-b border-transparent">Size (USD)</th>
                        <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest border-b border-transparent text-right">Net PnL</th>
                        <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest border-b border-transparent text-right">Yield</th>
                        <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest border-b border-transparent text-right">SL Limit</th>
                        <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest border-b border-transparent text-right">TP Target</th>
                        <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest border-b border-transparent text-center">Class</th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                    {positions.map(pos => {
                        const pnl = pos.unrealized_pnl || 0;
                        const pnlPct = pos.pnl_percent || 0;
                        const isProfit = pnl >= 0;

                        return (
                            <tr key={pos.id} className="hover:bg-white/[0.02] transition-colors group">
                                <td className="p-4 font-mono font-bold text-white group-hover:text-[#00E5FF] transition-colors">{pos.symbol}</td>
                                <td className="p-4">
                                    <span className={`px-2 py-1 rounded text-[10px] font-bold font-mono tracking-widest border ${pos.side === 'LONG' ? 'bg-[#10B981]/10 text-[#10B981] border-[#10B981]/30' : 'bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30'}`}>
                                        {pos.side}
                                    </span>
                                </td>
                                <td className="p-4 font-mono text-gray-300 group-hover:text-white transition-colors">${pos.entry_price?.toFixed(2)}</td>
                                <td className="p-4 font-mono text-[#D4AF37]">${pos.current_price?.toFixed(2)}</td>
                                <td className="p-4 font-mono text-gray-300 group-hover:text-white transition-colors">${pos.position_size_usd?.toFixed(0)}</td>
                                <td className={`p-4 font-mono font-bold text-right ${isProfit ? 'text-[#10B981]' : 'text-[#EF4444]'}`}>
                                    {isProfit ? '+' : ''}${pnl.toFixed(2)}
                                </td>
                                <td className={`p-4 font-mono font-bold text-right ${isProfit ? 'text-[#10B981]' : 'text-[#EF4444]'}`}>
                                    {isProfit ? '+' : ''}{pnlPct.toFixed(2)}%
                                </td>
                                <td className="p-4 font-mono text-gray-400 text-right">${pos.stop_loss?.toFixed(2)}</td>
                                <td className="p-4 font-mono text-gray-400 text-right">${pos.take_profit_1?.toFixed(2)}</td>
                                <td className="p-4 text-center">
                                    <span className={`px-2 py-1 flex justify-center items-center rounded text-[10px] font-bold font-mono uppercase tracking-widest border ${pos.tier === 'HIGH_CONVICTION' ? 'bg-[#10B981]/10 text-[#10B981] border-[#10B981]/30' :
                                            pos.tier === 'SIGNAL' ? 'bg-[#00E5FF]/10 text-[#00E5FF] border-[#00E5FF]/30' :
                                                'bg-white/5 text-gray-400 border-white/10'
                                        }`}>
                                        {pos.tier?.replace('_', ' ') || 'NONE'}
                                    </span>
                                </td>
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
}
