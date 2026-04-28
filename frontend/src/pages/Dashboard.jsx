import React, { useState } from 'react';
import { usePolling } from '../hooks/usePolling';
import { fetchPositions, fetchStatus, fetchSignals, fetchLatestScan, fetchLatestAnalysis } from '../api';
import L1StatusCard from '../components/L1StatusCard';
import L2AgentsPanel from '../components/L2AgentsPanel';
import PositionsTable from '../components/PositionsTable';
import SignalCard from '../components/SignalCard';
import SessionCountdown from '../components/SessionCountdown';
import WatchlistManager from '../components/WatchlistManager';
import SystemStats from '../components/SystemStats';
import ExchangeControlPanel from '../components/ExchangeControlPanel';
import { Activity, Radio, Cpu, Bell, Radar } from 'lucide-react';

const PAIRS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT'];

export default function Dashboard() {
    const [selectedSymbol, setSelectedSymbol] = useState('BTCUSDT');
    const [signals, setSignals] = useState([]);
    const { data: positions } = usePolling(() => fetchPositions('OPEN'), 30000);
    const { data: status }    = usePolling(fetchStatus, 10000);
    const { data: scan }      = usePolling(() => fetchLatestScan(selectedSymbol), 60000);
    const { data: analysis }  = usePolling(() => fetchLatestAnalysis(selectedSymbol), 60000);
    usePolling(() => fetchSignals().then(r => { setSignals(r.data); return r; }), 30000);

    const openPositions = positions?.results || positions || [];

    const handleSignalEnter   = () => fetchSignals().then(r => setSignals(r.data)).catch(() => {});
    const handleSignalDismiss = (id) => setSignals(s => s.filter(x => x.id !== id));

    return (
        <div className="flex flex-col min-h-full">
            {/* Header */}
            <div className="flex items-center justify-between pb-6 border-b border-white/5 mb-8">
                <div>
                    <h2 className="text-3xl font-black tracking-wider text-white">Command <span className="text-[#00E5FF]">Center</span></h2>
                    <p className="text-sm text-gray-400 mt-2 font-mono flex items-center gap-2">
                        <Activity className="w-4 h-4 text-[#00E5FF]" />
                        Monitoring real-time trading nodes
                    </p>
                </div>

                <div className="flex flex-col items-end gap-2">
                    <div className={`px-4 py-1.5 rounded-full text-xs font-bold uppercase tracking-widest border font-mono ${status?.trading_mode === 'paper' ? 'bg-[#D4AF37]/10 text-[#D4AF37] border-[#D4AF37]/30' : 'bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30'}`}>
                        <div className="flex items-center gap-2">
                            <Radio className={`w-3 h-3 ${status?.trading_mode === 'live' ? 'animate-pulse text-[#EF4444]' : ''}`} />
                            {status?.trading_mode || 'PAPER'} MODE
                        </div>
                    </div>
                    <div className="bg-[#151518] px-4 py-2 rounded-lg border border-white/5 font-mono text-sm shadow-inner flex items-center gap-3">
                        <span className="text-gray-500 uppercase tracking-widest text-xs">Daily PnL</span>
                        <span className={`font-black ${status?.daily_pnl >= 0 ? 'text-[#10B981]' : 'text-[#EF4444]'}`}>
                            {status?.daily_pnl >= 0 ? '+' : ''}{status?.daily_pnl?.toFixed(2) || '0.00'}%
                        </span>
                    </div>
                </div>
            </div>

            {/* ── SYSTEM STATS BAR ── */}
            <SystemStats />

            <div className="mt-6 mb-8">
                <ExchangeControlPanel />
            </div>

            {/* ── SIGNAL FEED ── */}
            <div className="flex flex-col gap-3 mb-2">
                <div className="flex items-center justify-between">
                    <h3 className="text-sm uppercase tracking-widest text-[#9CA3AF] font-bold flex items-center gap-2">
                        {signals.length > 0
                            ? <><Bell className="w-4 h-4 text-[#00E5FF] animate-pulse" /> Aktywne Sygnały</>
                            : <><Radar className="w-4 h-4 text-gray-600" /> Monitoring</>
                        }
                        {signals.length > 0 && (
                            <span className="bg-[#00E5FF]/15 text-[#00E5FF] border border-[#00E5FF]/30 px-2 py-0.5 rounded-full text-[10px] font-mono font-bold">
                                {signals.length}
                            </span>
                        )}
                    </h3>
                    <SessionCountdown />
                </div>

                {signals.length > 0 ? (
                    <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
                        {signals.map(sig => (
                            <SignalCard
                                key={sig.id}
                                signal={sig}
                                onDismiss={handleSignalDismiss}
                                onEnter={handleSignalEnter}
                            />
                        ))}
                    </div>
                ) : (
                    <div className="glass-panel px-6 py-5 flex items-center gap-4">
                        <div className="relative shrink-0">
                            <div className="w-10 h-10 rounded-full bg-[#00E5FF]/5 border border-[#00E5FF]/10 flex items-center justify-center">
                                <Radar className="w-5 h-5 text-[#00E5FF]/40" />
                            </div>
                            <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-[#10B981] animate-pulse border-2 border-[#121214]" />
                        </div>
                        <div>
                            <p className="text-sm font-medium text-gray-300">System aktywny — skanowanie rynku co minutę</p>
                            <p className="text-xs text-gray-600 font-mono mt-0.5">
                                Sygnały pojawiają się tutaj gdy L1 Pre-Filter + AI Agents zatwierdzą setup
                            </p>
                        </div>
                    </div>
                )}
            </div>

            {/* Watchlist + Symbol selector */}
            <div className="flex flex-col gap-3 mb-8">
                <WatchlistManager />
                <div className="flex gap-2 flex-wrap">
                    {PAIRS.map(pair => (
                        <button
                            key={pair}
                            className={`px-5 py-2 rounded-xl text-sm font-bold font-mono transition-all duration-300 border backdrop-blur-sm ${selectedSymbol === pair ? 'bg-gradient-to-r from-[#00E5FF]/20 to-transparent border-[#00E5FF]/50 text-[#00E5FF] shadow-[0_0_15px_rgba(0,229,255,0.2)]' : 'bg-[#151518] border-white/5 text-gray-400 hover:text-white hover:border-white/20 hover:bg-[#1a1a1f]'}`}
                            onClick={() => setSelectedSymbol(pair)}
                        >
                            {pair.replace('USDT', '')}
                        </button>
                    ))}
                </div>
            </div>

            {/* L1 Gate Status per para — kliknij żeby zobaczyć które kryteria przeszły */}
            <h3 className="text-sm uppercase tracking-widest text-[#9CA3AF] font-bold mb-3 flex items-center gap-2">
                <Cpu className="w-4 h-4" /> L1 Pre-Filter — Status skanowania
            </h3>
            <div className="flex flex-col gap-2 mb-8">
                {PAIRS.map(pair => (
                    <L1StatusCard
                        key={pair}
                        symbol={pair}
                        data={pair === selectedSymbol ? scan : undefined}
                    />
                ))}
            </div>

            {/* L2 Agents + Active Positions */}
            <div className="flex flex-col xl:flex-row gap-8">
                <div className="xl:w-[40%] flex flex-col gap-4">
                    <h3 className="text-sm uppercase tracking-widest text-[#9CA3AF] font-bold">
                        AI Agents — {selectedSymbol}
                    </h3>
                    <div className="glass-panel p-4 flex-1 overflow-y-auto max-h-[600px]">
                        <L2AgentsPanel data={analysis} symbol={selectedSymbol} />
                    </div>
                </div>

                <div className="xl:w-[60%] flex flex-col gap-4">
                    <h3 className="text-sm uppercase tracking-widest text-[#9CA3AF] font-bold">Aktywne pozycje</h3>
                    <div className="glass-panel overflow-hidden">
                        <PositionsTable positions={openPositions} />
                    </div>
                </div>
            </div>
        </div>
    );
}
