import React from 'react';
import { usePolling } from '../hooks/usePolling';
import { fetchRisk } from '../api';
import { Loader2, ShieldAlert, AlertTriangle, AlertOctagon, ServerCrash, Activity } from 'lucide-react';

export default function Risk() {
    const { data: risk, loading } = usePolling(fetchRisk, 5000);

    if (loading && !risk) {
        return (
            <div className="flex flex-col h-full w-full items-center justify-center text-gray-400">
                <Loader2 className="w-12 h-12 animate-spin text-[#EF4444] mb-4" />
                <p className="font-mono uppercase tracking-widest text-sm animate-pulse text-[#EF4444]">Analyzing Risk Protocols...</p>
            </div>
        );
    }

    const state = risk?.state || {};
    const events = risk?.recent_events || [];

    return (
        <div className="flex flex-col h-full w-full">
            <div className="flex items-center justify-between pb-6 border-b border-white/5 mb-8">
                <div>
                    <h2 className="text-3xl font-black tracking-wider text-white">Risk <span className="text-[#EF4444]">Controls</span></h2>
                    <p className="text-sm text-gray-400 mt-2 font-mono flex items-center gap-2">
                        <ShieldAlert className="w-4 h-4 text-[#EF4444]" />
                        Automated circuit breakers and exposure limits
                    </p>
                </div>
            </div>

            {/* Kill Switch Status */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <div className="glass-panel p-6 relative overflow-hidden group border-l-4 border-l-[#10B981]">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-[#10B981]/10 rounded-full blur-3xl -mr-10 -mt-10 pointer-events-none group-hover:bg-[#10B981]/20 transition-all duration-500" />
                    <h3 className="text-xs uppercase tracking-widest text-[#9CA3AF] font-bold mb-4">Daily PnL Protocol</h3>
                    <div className={`text-4xl font-mono font-black tracking-tight ${state.daily_pnl >= 0 ? 'text-[#10B981]' : 'text-[#EF4444]'}`}>
                        {state.daily_pnl >= 0 ? '+' : ''}{state.daily_pnl?.toFixed(2) || 0}%
                    </div>
                    {state.is_daily_stopped && (
                        <div className="mt-4 flex items-center gap-2 text-[#EF4444] text-xs font-bold font-mono bg-[#EF4444]/10 p-2 rounded">
                            <AlertOctagon className="w-4 h-4 animate-pulse" /> DAILY STOP ACTIVE
                        </div>
                    )}
                </div>

                <div className="glass-panel p-6 relative overflow-hidden group border-l-4 border-l-[#D4AF37]">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-[#D4AF37]/10 rounded-full blur-3xl -mr-10 -mt-10 pointer-events-none group-hover:bg-[#D4AF37]/20 transition-all duration-500" />
                    <h3 className="text-xs uppercase tracking-widest text-[#9CA3AF] font-bold mb-4">Weekly PnL Protocol</h3>
                    <div className={`text-4xl font-mono font-black tracking-tight ${state.weekly_pnl >= 0 ? 'text-[#10B981]' : 'text-[#EF4444]'}`}>
                        {state.weekly_pnl >= 0 ? '+' : ''}{state.weekly_pnl?.toFixed(2) || 0}%
                    </div>
                    {state.is_weekly_stopped && (
                        <div className="mt-4 flex items-center gap-2 text-[#EF4444] text-xs font-bold font-mono bg-[#EF4444]/10 p-2 rounded">
                            <AlertOctagon className="w-4 h-4 animate-pulse" /> WEEKLY STOP ACTIVE
                        </div>
                    )}
                </div>

                <div className="glass-panel p-6 relative overflow-hidden group border-l-4 border-l-[#00E5FF]">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-[#00E5FF]/10 rounded-full blur-3xl -mr-10 -mt-10 pointer-events-none group-hover:bg-[#00E5FF]/20 transition-all duration-500" />
                    <h3 className="text-xs uppercase tracking-widest text-[#9CA3AF] font-bold mb-4">Position Size Factor</h3>
                    <div className="text-4xl font-mono font-black tracking-tight text-white">
                        {((state.position_size_multiplier || 1) * 100).toFixed(0)}%
                    </div>
                    <div className="mt-4 text-xs font-mono text-gray-500 flex items-center gap-2">
                        <Activity className="w-3 h-3" /> {state.consecutive_losses || 0} consecutive losses
                    </div>
                </div>
            </div>

            {/* Risk Events Log */}
            <div className="glass-panel overflow-hidden border border-white/5">
                <div className="p-4 border-b border-white/5 bg-[#151518]/50 flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-[#EF4444]/10 text-[#EF4444]">
                        <ServerCrash className="w-5 h-5" />
                    </div>
                    <h3 className="font-bold text-lg text-white">Risk Event Log</h3>
                </div>

                {events.length > 0 ? (
                    <div className="overflow-x-auto">
                        <table className="w-full text-left border-collapse">
                            <thead>
                                <tr className="bg-[#0a0a0b]/50">
                                    <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest border-b border-white/5">Time Signature</th>
                                    <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest border-b border-white/5">Event Classification</th>
                                    <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest border-b border-white/5">Symbol</th>
                                    <th className="p-4 text-xs font-semibold text-gray-400 uppercase tracking-widest border-b border-white/5">Diagnostic Message</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-white/5">
                                {events.map(evt => (
                                    <tr key={evt.id} className="hover:bg-white/[0.02] transition-colors group">
                                        <td className="p-4 text-xs font-mono text-gray-400">
                                            {new Date(evt.timestamp).toLocaleString()}
                                        </td>
                                        <td className="p-4">
                                            <span className={`px-2 py-1 rounded text-[10px] font-bold font-mono tracking-widest uppercase ${evt.event_type.includes('STOP') ? 'bg-[#EF4444]/20 text-[#EF4444] border border-[#EF4444]/30' : 'bg-[#D4AF37]/20 text-[#D4AF37] border border-[#D4AF37]/30'}`}>
                                                {evt.event_type}
                                            </span>
                                        </td>
                                        <td className="p-4 font-mono font-bold text-white group-hover:text-[#EF4444] transition-colors">{evt.symbol || 'System'}</td>
                                        <td className="p-4 text-sm text-gray-300">{evt.message}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <div className="flex flex-col items-center justify-center p-16 text-gray-500">
                        <ShieldAlert className="w-16 h-16 mb-4 opacity-20" />
                        <p className="font-mono uppercase tracking-widest text-sm">No risk events logged</p>
                        <p className="text-xs mt-2 opacity-50 font-mono">Systems nominal</p>
                    </div>
                )}
            </div>
        </div>
    );
}
