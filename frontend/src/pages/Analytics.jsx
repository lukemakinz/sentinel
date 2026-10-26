import React, { useState } from 'react';
import { usePolling } from '../hooks/usePolling';
import { fetchPerformance } from '../api';
import PerformanceChart from '../components/PerformanceChart';
import { Loader2, TrendingUp, TrendingDown, Target, ShieldAlert, BarChart3, Wallet } from 'lucide-react';

export default function Analytics() {
    const [selectedStrategy, setSelectedStrategy] = useState('ALL');
    const { data: perf, loading } = usePolling(() => fetchPerformance(selectedStrategy), 15000, [selectedStrategy]);
    const strategyBreakdown = perf?.strategy_breakdown || [];

    if (loading && !perf) {
        return (
            <div className="flex flex-col h-full w-full items-center justify-center text-gray-400">
                <Loader2 className="w-12 h-12 animate-spin text-[#00E5FF] mb-4" />
                <p className="font-mono uppercase tracking-widest text-sm animate-pulse text-[#00E5FF]">Synthesizing Performance Data...</p>
            </div>
        );
    }

    const stats = perf?.account || {};

    return (
        <>
            <div className="flex items-center justify-between pb-6 border-b border-white/5 mb-8">
                <div>
                    <h2 className="text-3xl font-black tracking-wider text-white">Analytics <span className="text-[#00E5FF]">Hub</span></h2>
                    <p className="text-sm text-gray-400 mt-2 font-mono">Real-time performance metrics and capital distribution</p>
                </div>
                <div className="flex flex-wrap gap-2">
                    {['ALL', 'S1', 'S1A', 'S1B', 'S1C', 'S3', 'S4', 'S5', 'S6'].map((strategy) => (
                        <button
                            key={strategy}
                            type="button"
                            onClick={() => setSelectedStrategy(strategy)}
                            className={`rounded-xl border px-3 py-2 text-xs font-mono font-bold tracking-widest transition-all ${
                                selectedStrategy === strategy
                                    ? 'border-[#00E5FF]/40 bg-[#00E5FF]/10 text-[#00E5FF]'
                                    : 'border-white/5 bg-black/20 text-gray-500 hover:border-white/10 hover:text-white'
                            }`}
                        >
                            {strategy}
                        </button>
                    ))}
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                <div className="glass-panel p-6 relative overflow-hidden group">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-[#D4AF37]/10 rounded-full blur-3xl -mr-10 -mt-10 pointer-events-none group-hover:bg-[#D4AF37]/20 transition-all duration-500" />
                    <div className="flex items-center gap-4 mb-4">
                        <div className="p-3 rounded-xl bg-[#D4AF37]/20 text-[#D4AF37] border border-[#D4AF37]/30">
                            <Wallet className="w-6 h-6" />
                        </div>
                        <h3 className="text-xs uppercase tracking-widest text-[#9CA3AF] font-bold">Total Capital</h3>
                    </div>
                    <div className="text-3xl font-mono text-white font-black tracking-tight">
                        ${stats?.balance !== undefined ? stats.balance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '0.00'}
                    </div>
                </div>

                <div className="glass-panel p-6 relative overflow-hidden group">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-[#00E5FF]/10 rounded-full blur-3xl -mr-10 -mt-10 pointer-events-none group-hover:bg-[#00E5FF]/20 transition-all duration-500" />
                    <div className="flex items-center gap-4 mb-4">
                        <div className="p-3 rounded-xl bg-[#00E5FF]/20 text-[#00E5FF] border border-[#00E5FF]/30">
                            <Target className="w-6 h-6" />
                        </div>
                        <h3 className="text-xs uppercase tracking-widest text-[#9CA3AF] font-bold">Win Rate</h3>
                    </div>
                    <div className={`text-3xl font-mono font-black tracking-tight ${(perf?.win_rate || 0) >= 50 ? 'text-[#10B981]' : 'text-[#EF4444]'}`}>
                        {perf?.win_rate || 0}%
                    </div>
                </div>

                <div className="glass-panel p-6 relative overflow-hidden">
                    <div className="flex items-center gap-4 mb-4">
                        <div className="p-3 rounded-xl bg-gray-800 text-gray-300 border border-gray-700">
                            <BarChart3 className="w-6 h-6" />
                        </div>
                        <h3 className="text-xs uppercase tracking-widest text-[#9CA3AF] font-bold">Total Trades</h3>
                    </div>
                    <div className="text-3xl font-mono text-white font-black tracking-tight">
                        {perf?.total_trades || 0}
                    </div>
                </div>

                <div className="glass-panel p-6 relative overflow-hidden group">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-[#EF4444]/10 rounded-full blur-3xl -mr-10 -mt-10 pointer-events-none group-hover:bg-[#EF4444]/20 transition-all duration-500" />
                    <div className="flex items-center gap-4 mb-4">
                        <div className="p-3 rounded-xl bg-[#EF4444]/20 text-[#EF4444] border border-[#EF4444]/30">
                            <ShieldAlert className="w-6 h-6" />
                        </div>
                        <h3 className="text-xs uppercase tracking-widest text-[#9CA3AF] font-bold">Max Drawdown</h3>
                    </div>
                    <div className="text-3xl font-mono text-[#EF4444] font-black tracking-tight">
                        {perf?.max_drawdown?.toFixed(1) || 0}%
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <div className="glass-panel p-6 border-l-4 border-l-[#10B981]">
                    <div className="flex items-center justify-between mb-2">
                        <h3 className="text-xs uppercase tracking-widest text-[#9CA3AF] font-bold">Avg Win</h3>
                        <TrendingUp className="w-4 h-4 text-[#10B981]" />
                    </div>
                    <div className="text-2xl font-mono text-[#10B981] font-bold">+{perf?.avg_win || 0}%</div>
                </div>
                <div className="glass-panel p-6 border-l-4 border-l-[#EF4444]">
                    <div className="flex items-center justify-between mb-2">
                        <h3 className="text-xs uppercase tracking-widest text-[#9CA3AF] font-bold">Avg Loss</h3>
                        <TrendingDown className="w-4 h-4 text-[#EF4444]" />
                    </div>
                    <div className="text-2xl font-mono text-[#EF4444] font-bold">-{perf?.avg_loss || 0}%</div>
                </div>
                <div className="glass-panel p-6 border-l-4 border-l-[#D4AF37]">
                    <div className="flex justify-between items-center mb-2">
                        <h3 className="text-xs uppercase tracking-widest text-[#9CA3AF] font-bold">Profit Factor</h3>
                        <span className="text-xs font-mono bg-[#D4AF37]/20 text-[#D4AF37] px-2 py-0.5 rounded">Ratio</span>
                    </div>
                    <div className="text-2xl font-mono text-white font-bold">{perf?.profit_factor || 0}</div>
                </div>
            </div>

            <div className="glass-panel p-6 border border-white/5 bg-[#151518]/90">
                <div className="flex items-center justify-between mb-6">
                    <h3 className="text-lg font-bold uppercase tracking-widest text-white">Equity Performance</h3>
                </div>
                <div className="h-[400px] w-full bg-[#0a0a0b] rounded-xl border border-white/5 overflow-hidden">
                    <PerformanceChart equityCurve={perf?.equity_curve} stats={perf} />
                </div>
            </div>

            <div className="glass-panel p-6 border border-white/5 bg-[#151518]/90 mt-8">
                <div className="flex items-center justify-between mb-6">
                    <div>
                        <h3 className="text-lg font-bold uppercase tracking-widest text-white">Strategy Matrix</h3>
                        <p className="text-xs text-gray-400 font-mono mt-1">See which strategy carries the account and which one needs redesign</p>
                    </div>
                    <span className="text-xs font-mono bg-[#00E5FF]/10 text-[#00E5FF] border border-[#00E5FF]/20 px-3 py-1 rounded">
                        {strategyBreakdown.length} strategies
                    </span>
                </div>

                {strategyBreakdown.length === 0 ? (
                    <div className="rounded-xl border border-white/5 bg-[#0a0a0b] p-8 text-center text-sm font-mono text-gray-500">
                        No strategy-attributed trades yet.
                    </div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full min-w-[840px] text-left">
                            <thead>
                                <tr className="border-b border-white/5 text-[11px] uppercase tracking-widest text-gray-400">
                                    <th className="p-3">Strategy</th>
                                    <th className="p-3">Trades</th>
                                    <th className="p-3">Win Rate</th>
                                    <th className="p-3">Total PnL</th>
                                    <th className="p-3">Avg Win</th>
                                    <th className="p-3">Avg Loss</th>
                                    <th className="p-3">Profit Factor</th>
                                    <th className="p-3">Avg R</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-white/5">
                                {strategyBreakdown.map((row) => {
                                    const profitable = row.total_pnl >= 0;
                                    return (
                                        <tr key={row.strategy} className="hover:bg-white/[0.03]">
                                            <td className="p-3">
                                                <span className="inline-flex items-center rounded border border-[#00E5FF]/25 bg-[#00E5FF]/10 px-2 py-1 font-mono text-[10px] font-bold tracking-widest text-[#00E5FF]">
                                                    {row.strategy}
                                                </span>
                                            </td>
                                            <td className="p-3 font-mono text-white">{row.total_trades}</td>
                                            <td className={`p-3 font-mono ${row.win_rate >= 50 ? 'text-[#10B981]' : 'text-[#EF4444]'}`}>{row.win_rate}%</td>
                                            <td className={`p-3 font-mono font-bold ${profitable ? 'text-[#10B981]' : 'text-[#EF4444]'}`}>
                                                {profitable ? '+' : ''}${row.total_pnl.toFixed(2)}
                                            </td>
                                            <td className="p-3 font-mono text-[#10B981]">${row.avg_win_usd.toFixed(2)}</td>
                                            <td className="p-3 font-mono text-[#EF4444]">${row.avg_loss_usd.toFixed(2)}</td>
                                            <td className="p-3 font-mono text-white">{row.profit_factor}</td>
                                            <td className="p-3 font-mono text-[#D4AF37]">{row.avg_rr}R</td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </>
    );
}
