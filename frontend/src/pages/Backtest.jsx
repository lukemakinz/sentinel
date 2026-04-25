import React, { useState, useEffect, useRef } from 'react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { FlaskConical, Play, TrendingUp, TrendingDown, AlertTriangle, CheckCircle, Clock, BarChart2, Zap } from 'lucide-react';
import { runBacktest, fetchBacktestStatus, fetchBacktestList } from '../api';

const PAIRS      = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT'];
const STRATEGIES = [
    { id: 'S1', label: 'S1 — SMC Sweep',    desc: 'Liquidity sweep → ChoCH → FVG entry' },
    { id: 'S2', label: 'S2 — Order Flow',   desc: 'Whale CVD + OI + funding divergence' },
    { id: 'S3', label: 'S3 — Classic TA',   desc: 'EMA crossover + RSI + S/R level' },
];

function MetricCard({ label, value, unit = '', positive = true, highlight = false }) {
    return (
        <div className={`glass-panel p-4 flex flex-col gap-1 ${highlight ? 'border-[#00E5FF]/30' : ''}`}>
            <span className="text-[10px] uppercase tracking-widest text-gray-500 font-mono">{label}</span>
            <span className={`text-2xl font-black font-mono ${positive ? 'text-[#10B981]' : 'text-[#EF4444]'}`}>
                {value}<span className="text-sm text-gray-400 ml-1">{unit}</span>
            </span>
        </div>
    );
}

function StatusBadge({ status }) {
    const map = {
        pending: { color: 'text-[#D4AF37] border-[#D4AF37]/30 bg-[#D4AF37]/10', label: 'Queued' },
        running: { color: 'text-[#00E5FF] border-[#00E5FF]/30 bg-[#00E5FF]/10', label: 'Running...' },
        done:    { color: 'text-[#10B981] border-[#10B981]/30 bg-[#10B981]/10', label: 'Done' },
        error:   { color: 'text-[#EF4444] border-[#EF4444]/30 bg-[#EF4444]/10', label: 'Error' },
    };
    const s = map[status] || map.pending;
    return (
        <span className={`text-xs font-bold font-mono px-2 py-0.5 rounded-full border ${s.color}`}>
            {status === 'running' && <span className="animate-pulse">●</span>} {s.label}
        </span>
    );
}

export default function Backtest() {
    const [symbol,   setSymbol]   = useState('BTCUSDT');
    const [strategy, setStrategy] = useState('S1');
    const [startDate, setStart]   = useState('2024-01-01');
    const [endDate,   setEnd]     = useState('2025-01-01');
    const [capital,  setCapital]  = useState(10000);
    const [risk,     setRisk]     = useState(0.005);
    const [loading,  setLoading]  = useState(false);
    const [runId,    setRunId]    = useState(null);
    const [result,   setResult]   = useState(null);
    const [history,  setHistory]  = useState([]);
    const pollRef = useRef(null);

    useEffect(() => {
        fetchBacktestList().then(r => setHistory(r.data)).catch(() => {});
    }, []);

    useEffect(() => {
        if (!runId) return;
        pollRef.current = setInterval(async () => {
            try {
                const { data } = await fetchBacktestStatus(runId);
                setResult(data);
                if (data.status === 'done' || data.status === 'error') {
                    clearInterval(pollRef.current);
                    setLoading(false);
                    fetchBacktestList().then(r => setHistory(r.data)).catch(() => {});
                }
            } catch {}
        }, 2000);
        return () => clearInterval(pollRef.current);
    }, [runId]);

    const handleRun = async () => {
        setLoading(true);
        setResult(null);
        try {
            const { data } = await runBacktest({ symbol, strategy, start_date: startDate, end_date: endDate, initial_capital: capital, risk_per_trade: risk });
            setRunId(data.id);
            setResult({ status: 'pending' });
        } catch (e) {
            setLoading(false);
            setResult({ status: 'error', error_message: e.message });
        }
    };

    const equityData = result?.equity_curve?.map((v, i) => ({ i, equity: v })) || [];

    return (
        <div className="flex flex-col min-h-full gap-8">
            {/* Header */}
            <div className="flex items-center justify-between pb-6 border-b border-white/5">
                <div>
                    <h2 className="text-3xl font-black tracking-wider text-white flex items-center gap-3">
                        <FlaskConical className="w-8 h-8 text-[#00E5FF]" />
                        Back<span className="text-[#00E5FF]">test</span>
                    </h2>
                    <p className="text-sm text-gray-400 mt-1 font-mono">Validate strategies on historical data before going live</p>
                </div>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-3 gap-8">
                {/* Config Panel */}
                <div className="xl:col-span-1 flex flex-col gap-5">
                    <div className="glass-panel p-5 flex flex-col gap-5">
                        <h3 className="text-xs uppercase tracking-widest text-[#9CA3AF] font-bold">Configuration</h3>

                        {/* Pair */}
                        <div className="flex flex-col gap-2">
                            <label className="text-xs text-gray-500 font-mono uppercase tracking-widest">Pair</label>
                            <div className="grid grid-cols-2 gap-2">
                                {PAIRS.map(p => (
                                    <button key={p} onClick={() => setSymbol(p)}
                                        className={`py-2 rounded-lg text-xs font-bold font-mono transition-all border ${symbol === p ? 'bg-[#00E5FF]/15 border-[#00E5FF]/40 text-[#00E5FF]' : 'bg-[#151518] border-white/5 text-gray-400 hover:text-white'}`}>
                                        {p}
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* Strategy */}
                        <div className="flex flex-col gap-2">
                            <label className="text-xs text-gray-500 font-mono uppercase tracking-widest">Strategy</label>
                            {STRATEGIES.map(s => (
                                <button key={s.id} onClick={() => setStrategy(s.id)}
                                    className={`p-3 rounded-lg text-left transition-all border ${strategy === s.id ? 'bg-[#00E5FF]/10 border-[#00E5FF]/40' : 'bg-[#151518] border-white/5 hover:border-white/20'}`}>
                                    <div className={`text-sm font-bold font-mono ${strategy === s.id ? 'text-[#00E5FF]' : 'text-white'}`}>{s.label}</div>
                                    <div className="text-xs text-gray-500 mt-0.5">{s.desc}</div>
                                </button>
                            ))}
                        </div>

                        {/* Dates */}
                        <div className="grid grid-cols-2 gap-3">
                            <div className="flex flex-col gap-1">
                                <label className="text-xs text-gray-500 font-mono">Start</label>
                                <input type="date" value={startDate} onChange={e => setStart(e.target.value)}
                                    className="bg-[#151518] border border-white/10 rounded-lg px-3 py-2 text-sm text-white font-mono focus:border-[#00E5FF]/50 focus:outline-none" />
                            </div>
                            <div className="flex flex-col gap-1">
                                <label className="text-xs text-gray-500 font-mono">End</label>
                                <input type="date" value={endDate} onChange={e => setEnd(e.target.value)}
                                    className="bg-[#151518] border border-white/10 rounded-lg px-3 py-2 text-sm text-white font-mono focus:border-[#00E5FF]/50 focus:outline-none" />
                            </div>
                        </div>

                        {/* Capital + Risk */}
                        <div className="grid grid-cols-2 gap-3">
                            <div className="flex flex-col gap-1">
                                <label className="text-xs text-gray-500 font-mono">Capital ($)</label>
                                <input type="number" value={capital} onChange={e => setCapital(+e.target.value)} min="1000"
                                    className="bg-[#151518] border border-white/10 rounded-lg px-3 py-2 text-sm text-white font-mono focus:border-[#00E5FF]/50 focus:outline-none" />
                            </div>
                            <div className="flex flex-col gap-1">
                                <label className="text-xs text-gray-500 font-mono">Risk/Trade</label>
                                <select value={risk} onChange={e => setRisk(+e.target.value)}
                                    className="bg-[#151518] border border-white/10 rounded-lg px-3 py-2 text-sm text-white font-mono focus:border-[#00E5FF]/50 focus:outline-none">
                                    <option value={0.005}>0.5%</option>
                                    <option value={0.01}>1.0%</option>
                                    <option value={0.015}>1.5%</option>
                                    <option value={0.02}>2.0%</option>
                                </select>
                            </div>
                        </div>

                        <button onClick={handleRun} disabled={loading}
                            className={`w-full py-3 rounded-xl font-bold font-mono text-sm flex items-center justify-center gap-2 transition-all ${loading ? 'bg-[#00E5FF]/10 text-[#00E5FF]/50 cursor-not-allowed border border-[#00E5FF]/20' : 'bg-gradient-to-r from-[#00E5FF]/20 to-[#00E5FF]/10 border border-[#00E5FF]/40 text-[#00E5FF] hover:from-[#00E5FF]/30 hover:shadow-[0_0_20px_rgba(0,229,255,0.2)]'}`}>
                            {loading ? <><Clock className="w-4 h-4 animate-spin" /> Running...</> : <><Play className="w-4 h-4" /> Run Backtest</>}
                        </button>
                    </div>

                    {/* History */}
                    {history.length > 0 && (
                        <div className="glass-panel p-4 flex flex-col gap-3">
                            <h3 className="text-xs uppercase tracking-widest text-[#9CA3AF] font-bold">Recent Runs</h3>
                            {history.slice(0, 6).map(run => (
                                <div key={run.id} onClick={() => { setRunId(run.id); fetchBacktestStatus(run.id).then(r => setResult(r.data)); }}
                                    className="flex items-center justify-between cursor-pointer hover:bg-white/5 p-2 rounded-lg transition-colors">
                                    <div>
                                        <div className="text-xs font-mono text-white">{run.symbol} / {run.strategy}</div>
                                        <div className="text-[10px] text-gray-500">{new Date(run.created_at).toLocaleDateString()}</div>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        {run.status === 'done' && <span className="text-xs font-mono text-[#10B981]">S:{run.sharpe_ratio?.toFixed(2)}</span>}
                                        <StatusBadge status={run.status} />
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* Results Panel */}
                <div className="xl:col-span-2 flex flex-col gap-5">
                    {!result && (
                        <div className="glass-panel p-12 flex flex-col items-center justify-center gap-4 text-center h-64">
                            <BarChart2 className="w-12 h-12 text-gray-600" />
                            <p className="text-gray-500 font-mono text-sm">Configure and run a backtest to see results</p>
                            <p className="text-gray-600 text-xs">Results include Sharpe, MaxDD, win rate, equity curve, and Monte Carlo analysis</p>
                        </div>
                    )}

                    {result?.status === 'pending' || result?.status === 'running' ? (
                        <div className="glass-panel p-12 flex flex-col items-center justify-center gap-4">
                            <div className="w-16 h-16 rounded-full border-2 border-[#00E5FF]/30 border-t-[#00E5FF] animate-spin" />
                            <p className="text-[#00E5FF] font-mono font-bold">Backtesting {symbol} / {strategy}...</p>
                            <p className="text-gray-500 text-xs font-mono">Replaying {startDate} → {endDate}</p>
                        </div>
                    ) : null}

                    {result?.status === 'error' && (
                        <div className="glass-panel p-6 border-[#EF4444]/30 flex items-start gap-3">
                            <AlertTriangle className="w-5 h-5 text-[#EF4444] shrink-0 mt-0.5" />
                            <div>
                                <p className="text-[#EF4444] font-bold text-sm">Backtest Error</p>
                                <p className="text-gray-400 text-xs mt-1 font-mono">{result.error_message}</p>
                            </div>
                        </div>
                    )}

                    {result?.status === 'done' && (
                        <>
                            {/* Live Threshold Badge */}
                            <div className={`glass-panel p-4 flex items-center gap-3 border ${result.passes_live ? 'border-[#10B981]/30' : 'border-[#EF4444]/20'}`}>
                                {result.passes_live
                                    ? <><CheckCircle className="w-5 h-5 text-[#10B981]" /><span className="text-[#10B981] font-bold font-mono text-sm">PASSES LIVE THRESHOLD — Sharpe &gt; 1.5 | MaxDD &lt; 20% | Trades &gt; 300 | Calmar &gt; 0.5</span></>
                                    : <><AlertTriangle className="w-5 h-5 text-[#D4AF37]" /><span className="text-[#D4AF37] font-bold font-mono text-sm">NOT READY FOR LIVE — One or more thresholds not met</span></>
                                }
                            </div>

                            {/* Key Metrics */}
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                                <MetricCard label="Sharpe Ratio" value={result.sharpe_ratio?.toFixed(2)} positive={result.sharpe_ratio > 0} />
                                <MetricCard label="Max Drawdown" value={result.max_drawdown?.toFixed(1)} unit="%" positive={result.max_drawdown < 20} />
                                <MetricCard label="Win Rate" value={result.win_rate?.toFixed(1)} unit="%" positive={result.win_rate > 50} />
                                <MetricCard label="Calmar" value={result.calmar_ratio?.toFixed(2)} positive={result.calmar_ratio > 0.5} />
                                <MetricCard label="Total Trades" value={result.total_trades} positive={result.total_trades >= 300} />
                                <MetricCard label="Total PnL" value={result.total_pnl?.toFixed(0)} unit="$" positive={result.total_pnl > 0} />
                                <MetricCard label="PnL %" value={result.total_pnl_pct?.toFixed(1)} unit="%" positive={result.total_pnl_pct > 0} />
                                <MetricCard label="Final Capital" value={result.final_capital?.toFixed(0)} unit="$" positive={result.final_capital > result.initial_capital} />
                            </div>

                            {/* Equity Curve */}
                            {equityData.length > 1 && (
                                <div className="glass-panel p-5">
                                    <h3 className="text-xs uppercase tracking-widest text-[#9CA3AF] font-bold mb-4 flex items-center gap-2">
                                        <TrendingUp className="w-4 h-4" /> Equity Curve
                                    </h3>
                                    <ResponsiveContainer width="100%" height={200}>
                                        <AreaChart data={equityData}>
                                            <defs>
                                                <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                                                    <stop offset="5%" stopColor="#00E5FF" stopOpacity={0.3} />
                                                    <stop offset="95%" stopColor="#00E5FF" stopOpacity={0} />
                                                </linearGradient>
                                            </defs>
                                            <XAxis dataKey="i" hide />
                                            <YAxis domain={['auto', 'auto']} tick={{ fill: '#6B7280', fontSize: 10 }} tickFormatter={v => `$${(v/1000).toFixed(0)}k`} />
                                            <Tooltip
                                                contentStyle={{ background: '#151518', border: '1px solid #27272A', borderRadius: 8 }}
                                                formatter={v => [`$${v?.toFixed(0)}`, 'Equity']}
                                                labelFormatter={() => ''}
                                            />
                                            <ReferenceLine y={result.initial_capital} stroke="#27272A" strokeDasharray="3 3" />
                                            <Area type="monotone" dataKey="equity" stroke="#00E5FF" strokeWidth={2} fill="url(#eqGrad)" dot={false} />
                                        </AreaChart>
                                    </ResponsiveContainer>
                                </div>
                            )}

                            {/* Monte Carlo */}
                            {result.mc_ruin_probability !== null && (
                                <div className="glass-panel p-5">
                                    <h3 className="text-xs uppercase tracking-widest text-[#9CA3AF] font-bold mb-4 flex items-center gap-2">
                                        <Zap className="w-4 h-4" /> Monte Carlo (5,000 permutations)
                                    </h3>
                                    <div className="grid grid-cols-3 gap-4">
                                        <div className="flex flex-col gap-1">
                                            <span className="text-[10px] text-gray-500 uppercase tracking-widest font-mono">Ruin Probability</span>
                                            <span className={`text-2xl font-black font-mono ${result.mc_ruin_probability < 0.01 ? 'text-[#10B981]' : result.mc_ruin_probability < 0.05 ? 'text-[#D4AF37]' : 'text-[#EF4444]'}`}>
                                                {(result.mc_ruin_probability * 100).toFixed(2)}%
                                            </span>
                                            <span className="text-[10px] text-gray-600">Target: &lt; 1%</span>
                                        </div>
                                        <div className="flex flex-col gap-1">
                                            <span className="text-[10px] text-gray-500 uppercase tracking-widest font-mono">Worst 5% DD</span>
                                            <span className={`text-2xl font-black font-mono ${result.mc_worst_5pct_dd < 20 ? 'text-[#10B981]' : 'text-[#EF4444]'}`}>
                                                {result.mc_worst_5pct_dd?.toFixed(1)}%
                                            </span>
                                            <span className="text-[10px] text-gray-600">Target: &lt; 20%</span>
                                        </div>
                                        <div className="flex flex-col gap-1">
                                            <span className="text-[10px] text-gray-500 uppercase tracking-widest font-mono">Median Sharpe</span>
                                            <span className={`text-2xl font-black font-mono ${result.mc_median_sharpe > 1.5 ? 'text-[#10B981]' : 'text-[#D4AF37]'}`}>
                                                {result.mc_median_sharpe?.toFixed(2)}
                                            </span>
                                            <span className="text-[10px] text-gray-600">Target: &gt; 1.5</span>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}
