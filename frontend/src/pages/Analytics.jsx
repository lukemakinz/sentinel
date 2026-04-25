import React from 'react';
import { usePolling } from '../hooks/usePolling';
import { fetchPerformance } from '../api';
import PerformanceChart from '../components/PerformanceChart';
import { Loader2, TrendingUp, TrendingDown, Target, ShieldAlert, BarChart3, Wallet } from 'lucide-react';

export default function Analytics() {
    const { data: perf, loading } = usePolling(fetchPerformance, 15000);

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
            </div>

            {/* Stats Grid */}
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

            {/* Equity Curve */}
            <div className="glass-panel p-6 border border-white/5 bg-[#151518]/90">
                <div className="flex items-center justify-between mb-6">
                    <h3 className="text-lg font-bold uppercase tracking-widest text-white">Equity Performance</h3>
                </div>
                <div className="h-[400px] w-full bg-[#0a0a0b] rounded-xl border border-white/5 overflow-hidden">
                    <PerformanceChart equityCurve={perf?.equity_curve} stats={perf} />
                </div>
            </div>
        </>
    );
}
