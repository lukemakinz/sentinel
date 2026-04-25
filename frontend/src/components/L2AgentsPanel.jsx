import React from 'react';
import { Brain, TrendingUp, BarChart2, Shield, Zap, Clock } from 'lucide-react';

const AGENT_META = {
    context_trader:    { label: 'Context Trader',   icon: TrendingUp, desc: 'SMC / Price Action' },
    order_flow_quant:  { label: 'Order Flow',        icon: BarChart2,  desc: 'Whale CVD / OI' },
    risk_manager:      { label: 'Risk Manager',      icon: Shield,     desc: 'DD / Heat / News' },
    devils_advocate:   { label: "Devil's Advocate",  icon: Zap,        desc: 'Contrarian check' },
};

function VerdictBadge({ verdict }) {
    const map = {
        APPROVE: 'bg-[#10B981]/15 border-[#10B981]/30 text-[#10B981]',
        REJECT:  'bg-[#EF4444]/15 border-[#EF4444]/30 text-[#EF4444]',
        NEUTRAL: 'bg-[#D4AF37]/15 border-[#D4AF37]/30 text-[#D4AF37]',
    };
    const icon = { APPROVE: '✓', REJECT: '✗', NEUTRAL: '~' };
    return (
        <span className={`text-[10px] font-bold font-mono px-1.5 py-0.5 rounded border ${map[verdict] || map.NEUTRAL}`}>
            {icon[verdict]} {verdict}
        </span>
    );
}

function AgentCard({ agentKey, data }) {
    const meta   = AGENT_META[agentKey] || { label: agentKey, icon: Brain, desc: '' };
    const Icon   = meta.icon;
    const conf   = data?.confidence ?? 0;
    const color  = data?.verdict === 'APPROVE'
        ? '#10B981' : data?.verdict === 'REJECT' ? '#EF4444' : '#D4AF37';

    return (
        <div className="bg-[#0a0a0b] rounded-xl p-3.5 border border-white/5 flex flex-col gap-2.5">
            <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                    <Icon className="w-3.5 h-3.5 text-gray-500 shrink-0" />
                    <div className="min-w-0">
                        <div className="text-[11px] font-bold text-white leading-none">{meta.label}</div>
                        <div className="text-[9px] text-gray-600 font-mono mt-0.5">{meta.desc}</div>
                    </div>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                    <span className="text-[10px] text-gray-500 font-mono">{conf}%</span>
                    <VerdictBadge verdict={data?.verdict || 'NEUTRAL'} />
                </div>
            </div>

            {/* Confidence bar */}
            <div className="h-0.5 bg-white/5 rounded-full overflow-hidden">
                <div className="h-full rounded-full" style={{ width: `${conf}%`, background: color }} />
            </div>

            {/* Reasoning */}
            <p className="text-[11px] text-gray-400 font-mono leading-relaxed">
                {data?.reasoning || '—'}
            </p>
        </div>
    );
}

export default function L2AgentsPanel({ data, symbol }) {
    if (!data || data.no_data) {
        return (
            <div className="flex flex-col items-center justify-center p-10 gap-3 text-center h-full">
                <Brain className="w-8 h-8 text-gray-700" />
                <p className="text-xs text-gray-600 font-mono">Czeka na sygnał L1...</p>
                <p className="text-[10px] text-gray-700 font-mono">AI agents uruchamiają się gdy<br/>L1 Pre-Filter wykryje setup</p>
            </div>
        );
    }

    const agents  = data.agents_summary || {};
    const action  = data.action;
    const mult    = data.size_multiplier;
    const ts      = data.timestamp ? new Date(data.timestamp) : null;

    return (
        <div className="flex flex-col gap-3">
            {/* Supervisor decision */}
            <div className={`flex items-center justify-between px-3 py-2 rounded-lg border text-sm font-bold font-mono ${action === 'APPROVE' ? 'bg-[#10B981]/10 border-[#10B981]/25 text-[#10B981]' : 'bg-[#EF4444]/10 border-[#EF4444]/25 text-[#EF4444]'}`}>
                <span>
                    {action === 'APPROVE'
                        ? `✓ APPROVE × ${(mult * 100).toFixed(0)}% size`
                        : `✗ REJECT${data.veto_reason ? ` — ${data.veto_reason}` : ''}`
                    }
                </span>
                {ts && (
                    <span className="text-[10px] font-normal text-gray-500 flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {ts.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' })}
                    </span>
                )}
            </div>

            {/* Trade params if approved */}
            {action === 'APPROVE' && data.entry_price && (
                <div className="grid grid-cols-3 gap-2 text-[10px] font-mono">
                    <div className="bg-[#0a0a0b] rounded-lg p-2 border border-white/5">
                        <div className="text-gray-600 mb-0.5">ENTRY</div>
                        <div className="font-bold text-white">${data.entry_price?.toFixed(0)}</div>
                    </div>
                    <div className="bg-[#EF4444]/5 rounded-lg p-2 border border-[#EF4444]/10">
                        <div className="text-gray-600 mb-0.5">STOP</div>
                        <div className="font-bold text-[#EF4444]">${data.stop_loss?.toFixed(0)}</div>
                    </div>
                    <div className="bg-[#10B981]/5 rounded-lg p-2 border border-[#10B981]/10">
                        <div className="text-gray-600 mb-0.5">TP1 (+1.5R)</div>
                        <div className="font-bold text-[#10B981]">${data.take_profit_1?.toFixed(0)}</div>
                    </div>
                </div>
            )}

            {/* All 4 agents */}
            {Object.keys(AGENT_META).map(key => (
                <AgentCard key={key} agentKey={key} data={agents[key]} />
            ))}
        </div>
    );
}
