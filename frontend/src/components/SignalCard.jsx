import React, { useState, useEffect } from 'react';
import { enterSignal, dismissSignal } from '../api';
import { TrendingUp, TrendingDown, Clock, X, CheckCircle, AlertTriangle, Zap } from 'lucide-react';
import MTFWidget from './MTFWidget';

function AgentDot({ verdict }) {
    const c = verdict === 'APPROVE' ? '#10B981' : verdict === 'REJECT' ? '#EF4444' : '#D4AF37';
    return <span style={{ color: c, fontSize: 10 }}>{verdict === 'APPROVE' ? '✓' : verdict === 'REJECT' ? '✗' : '~'}</span>;
}

function Timer({ ageSeconds }) {
    const [elapsed, setElapsed] = useState(ageSeconds);
    useEffect(() => {
        const t = setInterval(() => setElapsed(s => s + 1), 1000);
        return () => clearInterval(t);
    }, []);

    const remaining = Math.max(0, 1800 - elapsed); // 30 min validity
    const m = Math.floor(remaining / 60);
    const s = remaining % 60;
    const pct = (remaining / 1800) * 100;
    const urgent = remaining < 300;

    return (
        <div className="flex items-center gap-2">
            <div className="flex-1 h-1 bg-white/5 rounded-full overflow-hidden">
                <div className="h-full rounded-full transition-all duration-1000"
                    style={{
                        width: `${pct}%`,
                        background: urgent ? '#EF4444' : pct > 60 ? '#10B981' : '#D4AF37',
                    }} />
            </div>
            <span className={`text-[10px] font-mono font-bold tabular-nums ${urgent ? 'text-[#EF4444]' : 'text-gray-400'}`}>
                {m}:{s.toString().padStart(2, '0')}
            </span>
        </div>
    );
}

export default function SignalCard({ signal, onDismiss, onEnter }) {
    const [showEntry, setShowEntry] = useState(false);
    const [entryPrice, setEntryPrice] = useState(signal.entry_price?.toFixed(2) || '');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const isLong = signal.direction === 'LONG';
    const conviction = Math.round((signal.size_multiplier || 0) * 100);
    const agents = signal.agents_summary || {};
    const agentKeys = ['context_trader', 'order_flow_quant', 'risk_manager', 'devils_advocate'];

    const handleEnter = async () => {
        const price = parseFloat(entryPrice);
        if (!price || price <= 0) { setError('Podaj cenę wejścia'); return; }
        setLoading(true);
        setError('');
        try {
            const { data } = await enterSignal(signal.id, price);
            setShowEntry(false);
            onEnter(data);
        } catch (e) {
            setError(e.response?.data?.error || 'Błąd — spróbuj ponownie');
            setLoading(false);
        }
    };

    const handleDismiss = async () => {
        try {
            await dismissSignal(signal.id);
            onDismiss(signal.id);
        } catch {}
    };

    return (
        <div className={`relative rounded-2xl border overflow-hidden transition-all duration-300 ${isLong ? 'border-[#10B981]/30 bg-gradient-to-br from-[#10B981]/5 to-transparent' : 'border-[#EF4444]/30 bg-gradient-to-br from-[#EF4444]/5 to-transparent'}`}
            style={{ boxShadow: isLong ? '0 0 30px rgba(16,185,129,0.08)' : '0 0 30px rgba(239,68,68,0.08)' }}>

            {/* Pulsing indicator — new signal */}
            <div className={`absolute top-3 right-3 w-2 h-2 rounded-full animate-pulse ${isLong ? 'bg-[#10B981]' : 'bg-[#EF4444]'}`} />

            <div className="p-5 flex flex-col gap-4">
                {/* Header */}
                <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-3">
                        <div className={`p-2 rounded-xl ${isLong ? 'bg-[#10B981]/15' : 'bg-[#EF4444]/15'}`}>
                            {isLong
                                ? <TrendingUp className="w-5 h-5 text-[#10B981]" />
                                : <TrendingDown className="w-5 h-5 text-[#EF4444]" />}
                        </div>
                        <div>
                            <div className="flex items-center gap-2">
                                <span className="font-black font-mono text-white text-lg tracking-wider">{signal.symbol}</span>
                                <span className={`text-xs font-bold font-mono px-2 py-0.5 rounded-full ${isLong ? 'bg-[#10B981]/15 text-[#10B981]' : 'bg-[#EF4444]/15 text-[#EF4444]'}`}>
                                    {signal.direction}
                                </span>
                                <span className="text-[10px] text-gray-600 font-mono">{signal.strategy}</span>
                            </div>
                            <div className="text-[10px] text-gray-500 font-mono mt-0.5 flex items-center gap-1">
                                <Clock className="w-3 h-3" />
                                {new Date(signal.timestamp).toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' })}
                            </div>
                        </div>
                    </div>

                    {/* Conviction */}
                    <div className="flex flex-col items-end gap-1">
                        <span className="text-[10px] uppercase tracking-widest text-gray-500 font-mono">Conviction</span>
                        <div className="flex items-center gap-1.5">
                            <div className="w-20 h-1.5 bg-white/5 rounded-full overflow-hidden">
                                <div className="h-full rounded-full" style={{
                                    width: `${conviction}%`,
                                    background: conviction > 70 ? '#10B981' : conviction > 50 ? '#D4AF37' : '#EF4444',
                                }} />
                            </div>
                            <span className="text-sm font-black font-mono text-white">{conviction}%</span>
                        </div>
                    </div>
                </div>

                {/* Trade params */}
                <div className="grid grid-cols-2 gap-2">
                    <div className="bg-white/[0.03] rounded-xl p-3 border border-white/5">
                        <div className="text-[10px] text-gray-500 uppercase tracking-widest font-mono mb-1">Wejście (sugerowane)</div>
                        <div className="text-lg font-black font-mono text-white">
                            ${signal.entry_price ? Number(signal.entry_price).toLocaleString('pl-PL', { minimumFractionDigits: 0 }) : '—'}
                        </div>
                    </div>
                    <div className="bg-[#EF4444]/5 rounded-xl p-3 border border-[#EF4444]/10">
                        <div className="text-[10px] text-gray-500 uppercase tracking-widest font-mono mb-1">Stop Loss</div>
                        <div className="text-lg font-black font-mono text-[#EF4444]">
                            ${signal.stop_loss ? Number(signal.stop_loss).toLocaleString('pl-PL', { minimumFractionDigits: 0 }) : '—'}
                        </div>
                        {signal.r_value && (
                            <div className="text-[10px] text-gray-600 font-mono">R = ${Number(signal.r_value).toFixed(0)}</div>
                        )}
                    </div>
                    <div className="bg-[#D4AF37]/5 rounded-xl p-3 border border-[#D4AF37]/10">
                        <div className="text-[10px] text-gray-500 uppercase tracking-widest font-mono mb-1">TP1 (+1.5R)</div>
                        <div className="text-base font-bold font-mono text-[#D4AF37]">
                            ${signal.take_profit_1 ? Number(signal.take_profit_1).toLocaleString('pl-PL', { minimumFractionDigits: 0 }) : '—'}
                        </div>
                    </div>
                    <div className="bg-[#10B981]/5 rounded-xl p-3 border border-[#10B981]/10">
                        <div className="text-[10px] text-gray-500 uppercase tracking-widest font-mono mb-1">TP2 (+3.0R)</div>
                        <div className="text-base font-bold font-mono text-[#10B981]">
                            ${signal.take_profit_2 ? Number(signal.take_profit_2).toLocaleString('pl-PL', { minimumFractionDigits: 0 }) : '—'}
                        </div>
                    </div>
                </div>

                {/* MTF Analysis */}
                <div className="border-t border-white/5 pt-3">
                    <MTFWidget symbol={signal.symbol} />
                </div>

                {/* Agents row */}
                {Object.keys(agents).length > 0 && (
                    <div className="flex items-center gap-3 py-2 border-t border-white/5">
                        {agentKeys.map(key => {
                            const a = agents[key];
                            if (!a) return null;
                            const short = { context_trader: 'CT', order_flow_quant: 'OFQ', risk_manager: 'RM', devils_advocate: 'DA' };
                            return (
                                <div key={key} className="flex items-center gap-1">
                                    <span className="text-[10px] text-gray-500 font-mono">{short[key]}</span>
                                    <AgentDot verdict={a.verdict} />
                                </div>
                            );
                        })}
                        <div className="ml-auto text-[10px] text-gray-600 font-mono flex items-center gap-1">
                            <Zap className="w-3 h-3" />
                            Ważny przez:
                        </div>
                        <div className="w-24">
                            <Timer ageSeconds={signal.age_seconds || 0} />
                        </div>
                    </div>
                )}

                {/* Entry form */}
                {!showEntry ? (
                    <div className="flex gap-2 mt-1">
                        <button onClick={() => setShowEntry(true)}
                            className={`flex-1 py-3 rounded-xl font-bold font-mono text-sm flex items-center justify-center gap-2 transition-all border ${isLong ? 'bg-[#10B981]/15 border-[#10B981]/40 text-[#10B981] hover:bg-[#10B981]/25 hover:shadow-[0_0_20px_rgba(16,185,129,0.2)]' : 'bg-[#EF4444]/15 border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/25'}`}>
                            <CheckCircle className="w-4 h-4" />
                            Wchodzę
                        </button>
                        <button onClick={handleDismiss}
                            className="px-4 py-3 rounded-xl font-bold font-mono text-sm text-gray-500 border border-white/5 bg-white/[0.02] hover:text-gray-300 hover:border-white/10 transition-all">
                            <X className="w-4 h-4" />
                        </button>
                    </div>
                ) : (
                    <div className="flex flex-col gap-3 mt-1 p-4 bg-white/[0.02] rounded-xl border border-white/5">
                        <div>
                            <label className="text-[10px] uppercase tracking-widest text-gray-500 font-mono block mb-1.5">
                                Twoja faktyczna cena wejścia
                            </label>
                            <div className="flex items-center gap-2">
                                <span className="text-gray-500 font-mono text-sm">$</span>
                                <input
                                    type="number"
                                    value={entryPrice}
                                    onChange={e => setEntryPrice(e.target.value)}
                                    onKeyDown={e => e.key === 'Enter' && handleEnter()}
                                    autoFocus
                                    step="0.01"
                                    className="flex-1 bg-[#0a0a0b] border border-white/15 rounded-lg px-3 py-2.5 text-white font-mono text-base focus:border-[#00E5FF]/50 focus:outline-none font-bold"
                                    placeholder={signal.entry_price?.toFixed(2) || '0'}
                                />
                            </div>
                            {signal.entry_price && entryPrice && (
                                <p className="text-[10px] text-gray-600 font-mono mt-1.5">
                                    Sugerowane: ${Number(signal.entry_price).toFixed(2)}
                                    {Math.abs(parseFloat(entryPrice) - signal.entry_price) > 0.01 &&
                                        ` · Różnica: ${parseFloat(entryPrice) > signal.entry_price ? '+' : ''}${(parseFloat(entryPrice) - signal.entry_price).toFixed(2)}`
                                    }
                                </p>
                            )}
                        </div>
                        {error && (
                            <div className="flex items-center gap-2 text-[#EF4444] text-xs font-mono">
                                <AlertTriangle className="w-3 h-3" /> {error}
                            </div>
                        )}
                        <div className="flex gap-2">
                            <button onClick={handleEnter} disabled={loading}
                                className={`flex-1 py-2.5 rounded-xl font-bold font-mono text-sm transition-all ${loading ? 'bg-white/5 text-gray-500' : 'bg-[#00E5FF]/15 border border-[#00E5FF]/40 text-[#00E5FF] hover:bg-[#00E5FF]/25'}`}>
                                {loading ? 'Otwieranie...' : 'Potwierdź wejście'}
                            </button>
                            <button onClick={() => { setShowEntry(false); setError(''); }}
                                className="px-3 py-2.5 rounded-xl text-gray-500 border border-white/5 hover:text-gray-300 transition-all font-mono text-sm">
                                Cofnij
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
