import React from 'react';
import {
    LineChart, Line, XAxis, YAxis, CartesianGrid,
    Tooltip, ResponsiveContainer, Area, AreaChart
} from 'recharts';
import { LineChart as LineChartIcon } from 'lucide-react';

export default function PerformanceChart({ equityCurve, stats }) {
    if (!equityCurve || equityCurve.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center h-full w-full opacity-50 p-12">
                <LineChartIcon className="w-12 h-12 mb-4 text-[#00E5FF] opacity-50" />
                <p className="font-mono text-sm uppercase tracking-widest text-[#00E5FF]">System initialization pending</p>
                <p className="text-xs mt-2 text-gray-500 font-mono">Performance vectors will render post-execution</p>
            </div>
        );
    }

    return (
        <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={equityCurve} margin={{ top: 20, right: 30, left: 10, bottom: 0 }}>
                <defs>
                    <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#00E5FF" stopOpacity={0.4} />
                        <stop offset="95%" stopColor="#00E5FF" stopOpacity={0} />
                    </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272A" />
                <XAxis
                    dataKey="updated_at"
                    tick={{ fontSize: 11, fill: '#9CA3AF', fontFamily: 'monospace' }}
                    tickFormatter={(v) => new Date(v).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                    axisLine={{ stroke: '#27272A' }}
                    tickLine={{ stroke: '#27272A' }}
                />
                <YAxis
                    tick={{ fontSize: 11, fill: '#9CA3AF', fontFamily: 'monospace' }}
                    tickFormatter={(v) => `$${v.toLocaleString()}`}
                    axisLine={{ stroke: '#27272A' }}
                    tickLine={{ stroke: '#27272A' }}
                    domain={['auto', 'auto']}
                />
                <Tooltip
                    contentStyle={{
                        background: 'rgba(21, 21, 24, 0.95)',
                        border: '1px solid rgba(0, 229, 255, 0.3)',
                        borderRadius: '12px',
                        fontSize: '13px',
                        fontFamily: 'monospace',
                        color: '#fff',
                        boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
                        backdropFilter: 'blur(10px)'
                    }}
                    itemStyle={{ color: '#00E5FF', fontWeight: 'bold' }}
                    formatter={(v) => [`$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, 'Equity']}
                    labelFormatter={(v) => new Date(v).toLocaleString()}
                />
                <Area
                    type="monotone"
                    dataKey="equity"
                    stroke="#00E5FF"
                    strokeWidth={3}
                    fill="url(#equityGradient)"
                    animationDuration={1500}
                />
            </AreaChart>
        </ResponsiveContainer>
    );
}
