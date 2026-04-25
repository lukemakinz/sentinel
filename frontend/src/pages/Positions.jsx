import React, { useState, useEffect, useCallback } from 'react';
import { usePolling } from '../hooks/usePolling';
import { fetchPositions, fetchPositionLive, evaluatePosition } from '../api';
import { Network, History, MapPin, Brain, TrendingUp, TrendingDown, AlertTriangle, Clock, RefreshCw, CheckCircle, Radar } from 'lucide-react';

// ── Live Position Monitor Card ───────────────────────────────────────────────
function LiveMonitorCard({ position }) {
    const [live, setLive]         = useState(null);
    const [evalResult, setEval]   = useState(null);
    const [evaluating, setEval2]  = useState(false);

    const refresh = useCallback(async () => {
        try {
            const { data } = await fetchPositionLive(position.id);
            setLive(data);
        } catch {}
    }, [position.id]);

    useEffect(() => {
        refresh();
        const timer = setInterval(refresh, 30000);
        return () => clearInterval(timer);
    }, [refresh]);

    const handleEvaluate = async () => {
        setEval2(true);
        setEval(null);
        try {
            const { data } = await evaluatePosition(position.id);
            setEval(data);
        } catch (e) {
            setEval({ error: e.response?.data?.error || e.message });
        } finally {
            setEval2(false);
        }
    };

    const isLong = position.side === 'LONG';
    const pnlPos = live?.pnl_pct_margin >= 0;
    const progress = Math.max(0, Math.min(100, live?.sl_progress_pct || 0));

    const agentColor = v => v === 'APPROVE' ? 'text-[#10B981]' : v === 'REJECT' ? 'text-[#EF4444]' : 'text-[#D4AF37]';
    const agentIcon  = v => v === 'APPROVE' ? '✅' : v === 'REJECT' ? '❌' : '⚠️';

    return (
        <div className="glass-panel overflow-hidden">
            {/* Header */}
            <div className="p-4 border-b border-white/5 flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <span className={`px-2 py-1 rounded text-xs font-bold font-mono ${isLong ? 'bg-[#10B981]/10 text-[#10B981]' : 'bg-[#EF4444]/10 text-[#EF4444]'}`}>{position.side}</span>
                    <span className="font-bold font-mono text-white">{position.symbol}</span>
                    {position.leverage > 1 && <span className="text-xs text-gray-500 font-mono">{position.leverage}×</span>}
                    <span className="text-xs text-gray-500 font-mono">@ ${position.entry_price?.toFixed(2)}</span>
                </div>
                <div className="flex items-center gap-3">
                    {live && <span className="text-[10px] text-gray-600 font-mono flex items-center gap-1"><Clock className="w-3 h-3" /> {live.age_minutes}m</span>}
                    <button onClick={refresh} className="text-gray-600 hover:text-[#00E5FF] transition-colors"><RefreshCw className="w-4 h-4" /></button>
                </div>
            </div>

            <div className="p-5 flex flex-col gap-5">
                {/* P&L Row */}
                {live && (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <div className="flex flex-col gap-0.5">
                            <span className="text-[10px] uppercase tracking-widest text-gray-500 font-mono">Current Price</span>
                            <span className="text-xl font-black font-mono text-white">${live.current_price?.toFixed(2)}</span>
                        </div>
                        <div className="flex flex-col gap-0.5">
                            <span className="text-[10px] uppercase tracking-widest text-gray-500 font-mono">Unrealized P&L</span>
                            <span className={`text-xl font-black font-mono ${pnlPos ? 'text-[#10B981]' : 'text-[#EF4444]'}`}>
                                {pnlPos ? '+' : ''}${live.pnl_usd}
                                <span className="text-sm ml-1">({pnlPos ? '+' : ''}{live.pnl_pct_margin}%)</span>
                            </span>
                        </div>
                        <div className="flex flex-col gap-0.5">
                            <span className="text-[10px] uppercase tracking-widest text-gray-500 font-mono">Margin</span>
                            <span className="text-xl font-black font-mono text-gray-300">${live.margin_usd?.toLocaleString()}</span>
                        </div>
                        {live.liquidation_price && (
                            <div className="flex flex-col gap-0.5">
                                <span className="text-[10px] uppercase tracking-widest text-gray-500 font-mono">Liq. Price</span>
                                <span className="text-sm font-bold font-mono text-gray-400">
                                    ${live.liquidation_price?.toFixed(2)}
                                    <span className="text-xs text-gray-600 ml-1">({live.liq_distance_pct?.toFixed(1)}% away)</span>
                                </span>
                            </div>
                        )}
                    </div>
                )}

                {/* Progress Bar: SL → Entry → Current → TP1 */}
                {live?.stop_loss && live?.take_profit_1 && (
                    <div className="flex flex-col gap-2">
                        <div className="flex justify-between text-[10px] font-mono text-gray-500">
                            <span className="text-[#EF4444]">SL ${live.stop_loss?.toFixed(0)}</span>
                            <span className="text-gray-400">Entry ${live.entry_price?.toFixed(0)}</span>
                            <span className="text-[#10B981]">TP1 ${live.take_profit_1?.toFixed(0)}</span>
                        </div>
                        <div className="h-2 bg-[#0a0a0b] rounded-full overflow-hidden border border-white/5 relative">
                            <div className="h-full rounded-full transition-all duration-500"
                                style={{
                                    width: `${Math.max(2, progress)}%`,
                                    background: progress < 0 ? '#EF4444' : progress < 50 ? '#D4AF37' : '#10B981',
                                    boxShadow: `0 0 8px ${progress >= 50 ? '#10B981' : '#D4AF37'}40`,
                                }} />
                        </div>
                        <div className="text-center text-[10px] font-mono text-gray-500">
                            {progress.toFixed(0)}% toward TP1
                        </div>
                    </div>
                )}

                {/* TP Hits */}
                {(position.tp1_hit || position.tp2_hit) && (
                    <div className="flex gap-2">
                        {position.tp1_hit && <span className="text-[#10B981] text-xs font-mono flex items-center gap-1"><CheckCircle className="w-3 h-3" /> TP1 hit — SL at breakeven</span>}
                        {position.tp2_hit && <span className="text-[#10B981] text-xs font-mono flex items-center gap-1"><CheckCircle className="w-3 h-3" /> TP2 hit — runner active</span>}
                    </div>
                )}

                {/* AI Evaluate */}
                <div className="border-t border-white/5 pt-4">
                    <div className="flex items-center justify-between mb-3">
                        <span className="text-xs uppercase tracking-widest text-gray-500 font-bold flex items-center gap-2">
                            <Brain className="w-4 h-4" /> AI Assessment
                        </span>
                        <button onClick={handleEvaluate} disabled={evaluating}
                            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold font-mono transition-all border ${evaluating ? 'text-gray-500 border-white/5' : 'text-[#00E5FF] border-[#00E5FF]/30 bg-[#00E5FF]/5 hover:bg-[#00E5FF]/10'}`}>
                            {evaluating ? <><RefreshCw className="w-3 h-3 animate-spin" /> Evaluating...</> : '🔄 Evaluate Now'}
                        </button>
                    </div>

                    {!evalResult && !evaluating && (
                        <p className="text-gray-600 text-xs font-mono">Click "Evaluate Now" to get AI assessment of your current position</p>
                    )}

                    {evaluating && (
                        <div className="flex items-center gap-2 text-[#00E5FF] text-xs font-mono">
                            <div className="w-3 h-3 rounded-full border border-[#00E5FF]/30 border-t-[#00E5FF] animate-spin" />
                            Running 4 AI agents... (~10-20s)
                        </div>
                    )}

                    {evalResult?.error && (
                        <p className="text-[#EF4444] text-xs font-mono">{evalResult.error}</p>
                    )}

                    {evalResult && !evalResult.error && (
                        <div className="flex flex-col gap-3">
                            {/* Recommendation */}
                            <div className={`px-3 py-2 rounded-lg border text-sm font-bold font-mono ${evalResult.action === 'APPROVE' ? 'bg-[#10B981]/10 border-[#10B981]/30 text-[#10B981]' : 'bg-[#EF4444]/10 border-[#EF4444]/30 text-[#EF4444]'}`}>
                                {evalResult.recommendation}
                            </div>

                            {/* Agent verdicts */}
                            {evalResult.agents_summary && (
                                <div className="grid grid-cols-2 gap-2">
                                    {Object.entries(evalResult.agents_summary).map(([name, data]) => (
                                        <div key={name} className="bg-[#0a0a0b] rounded-lg p-2.5 border border-white/5">
                                            <div className="flex items-center justify-between mb-1">
                                                <span className="text-[10px] uppercase font-mono text-gray-500">{name.replace(/_/g, ' ')}</span>
                                                <span className={`text-xs font-bold font-mono ${agentColor(data.verdict)}`}>
                                                    {agentIcon(data.verdict)} {data.verdict}
                                                </span>
                                            </div>
                                            <p className="text-[10px] text-gray-500 leading-relaxed">{data.reasoning?.slice(0, 80)}{data.reasoning?.length > 80 ? '…' : ''}</p>
                                        </div>
                                    ))}
                                </div>
                            )}

                            <p className="text-[10px] text-gray-600 font-mono">
                                Evaluated at {evalResult.evaluated_at ? new Date(evalResult.evaluated_at).toLocaleTimeString() : '—'}
                            </p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

// ── Main Page ────────────────────────────────────────────────────────────────
export default function Positions() {
    const { data: openPositions }   = usePolling(() => fetchPositions('OPEN'),   30000);
    const { data: closedPositions } = usePolling(() => fetchPositions('CLOSED'), 15000);

    const open   = openPositions?.results   || openPositions   || [];
    const closed = closedPositions?.results || closedPositions || [];

    return (
        <div className="flex flex-col h-full w-full gap-8">
            {/* Header */}
            <div className="pb-6 border-b border-white/5">
                <h2 className="text-3xl font-black tracking-wider text-white">
                    Position <span className="text-[#00E5FF]">Monitor</span>
                </h2>
                <p className="text-sm text-gray-400 mt-1 font-mono flex items-center gap-2">
                    <Network className="w-4 h-4 text-[#00E5FF]" />
                    Pozycje otwarte przez sygnały — live P&L co 30s · AI re-evaluation on demand
                </p>
            </div>

            {/* Open Positions */}
            <div>
                <div className="flex items-center gap-3 mb-4">
                    <MapPin className="w-4 h-4 text-[#00E5FF]" />
                    <h3 className="text-sm uppercase tracking-widest text-[#9CA3AF] font-bold">Aktywne pozycje</h3>
                    <span className="bg-[#00E5FF]/10 text-[#00E5FF] px-2 py-0.5 rounded-full text-xs font-mono font-bold border border-[#00E5FF]/20">
                        {open.length} ACTIVE
                    </span>
                </div>

                {open.length === 0 ? (
                    <div className="glass-panel px-8 py-10 flex items-center gap-5">
                        <div className="relative shrink-0">
                            <div className="w-12 h-12 rounded-full bg-[#00E5FF]/5 border border-[#00E5FF]/10 flex items-center justify-center">
                                <Radar className="w-6 h-6 text-[#00E5FF]/30" />
                            </div>
                            <span className="absolute -top-0.5 -right-0.5 w-3 h-3 rounded-full bg-[#10B981] border-2 border-[#121214] animate-pulse" />
                        </div>
                        <div>
                            <p className="text-white font-bold">System monitoruje rynek</p>
                            <p className="text-sm text-gray-500 font-mono mt-1">
                                Pozycje pojawią się tutaj gdy skorzystasz z sygnału na dashboardzie
                                (kliknij "Wchodzę" na karcie sygnału i wpisz swoją cenę wejścia)
                            </p>
                        </div>
                    </div>
                ) : (
                    <div className="flex flex-col gap-5">
                        {open.map(pos => <LiveMonitorCard key={pos.id} position={pos} />)}
                    </div>
                )}
            </div>

            {/* Closed Trades History */}
            <div className="glass-panel overflow-hidden">
                <div className="p-4 border-b border-white/5 flex items-center gap-3">
                    <History className="w-5 h-5 text-gray-500" />
                    <h3 className="font-bold text-white">Trade History</h3>
                    <span className="ml-auto text-xs text-gray-500 font-mono">{closed.length} trades</span>
                </div>
                {closed.length > 0 ? (
                    <div className="overflow-x-auto">
                        <table className="w-full text-left">
                            <thead>
                                <tr className="bg-[#0a0a0b]/50">
                                    {['Symbol', 'Side', 'Entry', 'Exit', 'P&L', 'Reason', 'Closed'].map(h => (
                                        <th key={h} className="p-4 text-xs text-gray-500 uppercase tracking-widest border-b border-white/5">{h}</th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-white/5">
                                {closed.map(pos => (
                                    <tr key={pos.id} className="hover:bg-white/[0.02] transition-colors">
                                        <td className="p-4 font-mono font-bold text-white">{pos.symbol}</td>
                                        <td className="p-4">
                                            <span className={`px-2 py-0.5 rounded text-xs font-bold font-mono ${pos.side === 'LONG' ? 'bg-[#10B981]/10 text-[#10B981]' : 'bg-[#EF4444]/10 text-[#EF4444]'}`}>{pos.side}</span>
                                        </td>
                                        <td className="p-4 font-mono text-gray-400 text-sm">${pos.entry_price?.toFixed(2)}</td>
                                        <td className="p-4 font-mono text-gray-400 text-sm">${pos.current_price?.toFixed(2)}</td>
                                        <td className={`p-4 font-mono font-bold text-sm ${pos.realized_pnl >= 0 ? 'text-[#10B981]' : 'text-[#EF4444]'}`}>
                                            {pos.realized_pnl >= 0 ? '+' : ''}${pos.realized_pnl?.toFixed(2)}
                                        </td>
                                        <td className="p-4 text-xs text-gray-500">{pos.close_reason}</td>
                                        <td className="p-4 text-xs text-gray-600 font-mono">{pos.closed_at ? new Date(pos.closed_at).toLocaleString() : '-'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <div className="p-12 flex flex-col items-center justify-center text-gray-600">
                        <History className="w-10 h-10 mb-3 opacity-20" />
                        <p className="font-mono text-sm uppercase tracking-widest">No closed positions yet</p>
                    </div>
                )}
            </div>

        </div>
    );
}
