import React, { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { usePolling } from '../hooks/usePolling';
import { fetchStatus, fetchSignals } from '../api';
import { LayoutDashboard, Monitor, BookOpen, BarChart3, ShieldAlert, Activity, Database, Briefcase, FlaskConical, HelpCircle } from 'lucide-react';

const NAV_ITEMS = [
    { path: '/', label: 'Command Center', icon: LayoutDashboard },
    { path: '/positions', label: 'Monitor', icon: Monitor },
    { path: '/journal', label: 'Trade Journal', icon: BookOpen },
    { path: '/analytics', label: 'Analytics Hub', icon: BarChart3 },
    { path: '/risk', label: 'Risk Controls', icon: ShieldAlert },
    { path: '/backtest', label: 'Backtest Lab', icon: FlaskConical },
    { path: '/how-it-works', label: 'Jak działa', icon: HelpCircle },
];

export default function Sidebar() {
    const { data: status } = usePolling(fetchStatus, 10000);
    const [signalCount, setSignalCount] = useState(0);
    useEffect(() => {
        const load = () => fetchSignals().then(r => setSignalCount(r.data?.length || 0)).catch(() => {});
        load();
        const t = setInterval(load, 30000);
        return () => clearInterval(t);
    }, []);

    return (
        <aside className="w-64 bg-[#121214] border-r border-[#27272A] flex flex-col shrink-0 relative overflow-hidden z-10 hidden md:flex">
            {/* Ambient light glow behind the sidebar */}
            <div className="absolute top-[-100px] left-[-100px] w-[200px] h-[200px] bg-[#00E5FF] rounded-full blur-[120px] opacity-10 pointer-events-none" />

            <div className="p-6 border-b border-[#27272A] flex items-center gap-3 relative z-10">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#1A1A1D] to-[#27272A] border border-white/10 flex items-center justify-center shadow-lg">
                    <Activity className="w-5 h-5 text-[#00E5FF]" />
                </div>
                <div>
                    <h1 className="text-xl font-black tracking-widest text-glow-cyan uppercase">SENTINEL</h1>
                    <span className="text-[10px] text-gray-500 font-mono tracking-widest border border-white/10 px-1.5 py-0.5 rounded bg-black/50">v1.2.0</span>
                </div>
            </div>

            <nav className="flex-1 px-3 py-6 flex flex-col gap-2 relative z-10">
                {NAV_ITEMS.map((item) => {
                    const Icon = item.icon;
                    return (
                        <NavLink
                            key={item.path}
                            to={item.path}
                            className={({ isActive }) => `
                                flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all duration-300 group relative
                                ${isActive ? 'text-[#00E5FF] bg-[#00E5FF]/10 shadow-[inset_0_0_12px_rgba(0,229,255,0.05)]' : 'text-gray-400 hover:text-white hover:bg-white/5'}
                            `}
                            end={item.path === '/'}
                        >
                            {({ isActive }) => (
                                <>
                                    {isActive && (
                                        <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-[#00E5FF] rounded-r-md shadow-[0_0_8px_rgba(0,229,255,0.8)]" />
                                    )}
                                    <Icon className={`w-5 h-5 transition-transform duration-300 ${isActive ? 'transform scale-110' : 'group-hover:scale-110'}`} />
                                    <span className="flex-1">{item.label}</span>
                                    {item.path === '/' && signalCount > 0 && (
                                        <span className="bg-[#10B981] text-black text-[10px] font-black px-1.5 py-0.5 rounded-full animate-pulse min-w-[18px] text-center">
                                            {signalCount}
                                        </span>
                                    )}
                                </>
                            )}
                        </NavLink>
                    );
                })}
            </nav>

            <div className="p-5 border-t border-[#27272A] relative z-10 bg-[#0a0a0b]/50 backdrop-blur-md">
                <div className="flex flex-col gap-3 font-mono text-xs">
                    <div className="flex items-center justify-between group">
                        <div className="flex items-center gap-2 text-gray-400 group-hover:text-white transition-colors">
                            <Database className="w-4 h-4" />
                            <span>Ingester pipeline</span>
                        </div>
                        {status?.ingester_active ? (
                            <div className="flex items-center gap-1.5 text-[#10B981]">
                                <span className="w-2 h-2 rounded-full bg-[#10B981] animate-pulse"></span>
                                <span className="uppercase tracking-wider text-[10px]">Sync</span>
                            </div>
                        ) : (
                            <div className="flex items-center gap-1.5 text-[#EF4444]">
                                <span className="w-2 h-2 rounded-full bg-[#EF4444]"></span>
                                <span className="uppercase tracking-wider text-[10px]">Halt</span>
                            </div>
                        )}
                    </div>

                    <div className="flex items-center justify-between text-gray-500 hover:text-gray-300 transition-colors">
                        <span className="flex items-center gap-2"><Activity className="w-4 h-4" /> Candles Processed</span>
                        <span className="text-[#D4AF37]">{status?.total_candles?.toLocaleString() || 0}</span>
                    </div>

                    <div className="flex items-center justify-between text-gray-500 hover:text-gray-300 transition-colors">
                        <span className="flex items-center gap-2"><Briefcase className="w-4 h-4" /> Open Positions</span>
                        <span className="text-white">{status?.open_positions || 0}</span>
                    </div>
                </div>
            </div>
        </aside>
    );
}
