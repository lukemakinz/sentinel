import React from 'react';
import { usePolling } from '../hooks/usePolling';
import { fetchSystemStats } from '../api';
import { Wifi, WifiOff, Activity, Brain, Zap, Clock } from 'lucide-react';

function timeAgo(ts) {
    if (!ts) return '—';
    const sec = Math.floor((Date.now() - new Date(ts)) / 1000);
    if (sec < 5)   return 'przed chwilą';
    if (sec < 60)  return `${sec}s temu`;
    if (sec < 3600) return `${Math.floor(sec / 60)}m temu`;
    return `${Math.floor(sec / 3600)}h temu`;
}

function Metric({ label, value, sub, color = 'text-white' }) {
    return (
        <div className="flex flex-col gap-0.5">
            <span className="text-[9px] uppercase tracking-widest text-gray-600 font-mono">{label}</span>
            <span className={`text-lg font-black font-mono leading-none ${color}`}>{value ?? '—'}</span>
            {sub && <span className="text-[9px] text-gray-600 font-mono">{sub}</span>}
        </div>
    );
}

export default function SystemStats() {
    const { data } = usePolling(fetchSystemStats, 60000);

    if (!data) return null;

    const fresh     = data.data?.data_fresh;
    const ageSec    = data.data?.data_age_seconds;
    const ageStr    = ageSec != null
        ? ageSec < 60 ? `${ageSec}s` : `${Math.floor(ageSec / 60)}m`
        : '—';

    const lastScan  = timeAgo(data.l1?.last_scan);
    const lastAI    = timeAgo(data.l2?.last_analysis);

    return (
        <div className="glass-panel px-5 py-4">
            <div className="flex items-center justify-between gap-6 flex-wrap">

                {/* Data freshness */}
                <div className="flex items-center gap-2.5">
                    {fresh
                        ? <div className="flex items-center gap-1.5 text-[#10B981]">
                            <Wifi className="w-3.5 h-3.5" />
                            <span className="text-[10px] font-mono font-bold">Dane live</span>
                          </div>
                        : <div className="flex items-center gap-1.5 text-[#EF4444]">
                            <WifiOff className="w-3.5 h-3.5" />
                            <span className="text-[10px] font-mono font-bold">Dane nieaktualne</span>
                          </div>
                    }
                    <span className="text-[10px] text-gray-600 font-mono">
                        {fresh ? `świeże (${ageStr})` : `ostatnie ${ageStr} temu`}
                    </span>
                </div>

                <div className="h-8 w-px bg-white/5 hidden sm:block" />

                {/* L1 scans */}
                <div className="flex items-center gap-3">
                    <Activity className="w-3.5 h-3.5 text-[#00E5FF] shrink-0" />
                    <Metric
                        label="Skany L1 / 1h"
                        value={data.l1?.scans_last_1h}
                        sub={`ostatni: ${lastScan}`}
                        color="text-[#00E5FF]"
                    />
                    <div className="flex flex-col gap-0.5 ml-2">
                        <span className="text-[9px] text-gray-600 font-mono">24h</span>
                        <span className="text-[10px] font-mono">
                            <span className="text-[#10B981] font-bold">{data.l1?.pass_last_24h ?? 0} pass</span>
                            {' / '}
                            <span className="text-gray-500">{data.l1?.fail_last_24h ?? 0} fail</span>
                        </span>
                    </div>
                </div>

                <div className="h-8 w-px bg-white/5 hidden sm:block" />

                {/* AI analyses */}
                <div className="flex items-center gap-3">
                    <Brain className="w-3.5 h-3.5 text-[#D4AF37] shrink-0" />
                    <Metric
                        label="AI Analyses / 24h"
                        value={data.l2?.ai_analyses_24h}
                        sub={`ostatnia: ${lastAI}`}
                        color="text-[#D4AF37]"
                    />
                    <div className="flex flex-col gap-0.5 ml-2">
                        <span className="text-[9px] text-gray-600 font-mono">wyniki</span>
                        <span className="text-[10px] font-mono">
                            <span className="text-[#10B981] font-bold">{data.l2?.approved_24h ?? 0}✓</span>
                            {' '}
                            <span className="text-[#EF4444]">{data.l2?.rejected_24h ?? 0}✗</span>
                        </span>
                    </div>
                </div>

                <div className="h-8 w-px bg-white/5 hidden sm:block" />

                {/* Signals */}
                <div className="flex items-center gap-3">
                    <Zap className={`w-3.5 h-3.5 shrink-0 ${data.signals?.active_now > 0 ? 'text-[#10B981] animate-pulse' : 'text-gray-600'}`} />
                    <Metric
                        label="Sygnały aktywne"
                        value={data.signals?.active_now ?? 0}
                        sub={`${data.signals?.generated_24h ?? 0} wygenerowanych dziś`}
                        color={data.signals?.active_now > 0 ? 'text-[#10B981]' : 'text-gray-400'}
                    />
                </div>

            </div>
        </div>
    );
}
