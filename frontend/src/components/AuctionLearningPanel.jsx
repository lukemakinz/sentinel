import React from 'react';
import { BrainCircuit, FlaskConical } from 'lucide-react';
import { fetchAuctionResearch } from '../api';
import { usePolling } from '../hooks/usePolling';

function valueOrDash(value, suffix = '') {
    return value == null ? '—' : `${Number(value).toFixed(3)}${suffix}`;
}

function PolicyCard({ id, name, data }) {
    const expectancy = data?.policy_expectancy_per_candidate_r;
    const color = expectancy == null
        ? 'text-gray-500'
        : expectancy >= 0 ? 'text-[#10B981]' : 'text-[#EF4444]';
    return (
        <div className="rounded-xl border border-white/5 bg-black/20 p-3">
            <div className="text-[9px] uppercase tracking-[0.24em] text-gray-600 font-mono">{id}</div>
            <div className="text-xs font-bold text-white mt-1">{name}</div>
            <div className={`text-lg font-black font-mono mt-2 ${color}`}>
                {valueOrDash(expectancy, 'R')}
            </div>
            <div className="text-[9px] text-gray-600 font-mono mt-1">
                {data?.comparison_candidates ?? data?.closed ?? 0} wspólnych rozliczonych
            </div>
        </div>
    );
}

export default function AuctionLearningPanel({ symbol }) {
    const { data, loading } = usePolling(
        () => fetchAuctionResearch(symbol), 120000, [symbol],
    );
    if (loading || !data) return null;

    const paired = data.paired_comparison || {};
    const learning = data.learning_postmortems || {};
    const globalComparison = data.global_context_comparison || {};
    const globalContext = data.latest_global_context || {};
    const globalComponents = globalContext.components || {};
    const breadth = globalComponents.alt_breadth_1h || {};
    const external = globalContext.external_indicators || {};
    const reasonCodes = globalComparison.reason_codes || {};
    const contextTimestamp = globalContext.snapshot_as_of
        || globalContext.as_of || globalContext.snapshot_timestamp;
    const contextTimestampMs = contextTimestamp ? Date.parse(contextTimestamp) : NaN;
    const contextAgeMinutes = Number.isFinite(contextTimestampMs)
        ? Math.max(0, (Date.now() - contextTimestampMs) / 60000) : null;
    const contextStale = contextAgeMinutes == null || contextAgeMinutes > 20;
    const counterfactuals = learning.counterfactual_mean_net_r || {};
    const counterfactualTp1 = learning.counterfactual_tp1_hit_rate || {};
    const diagnoses = Object.entries(learning.diagnoses || {});

    return (
        <div className="glass-panel p-5">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <p className="text-[10px] uppercase tracking-[0.28em] text-gray-600 font-mono">Auction Learning</p>
                    <h3 className="text-sm font-bold text-white mt-1 flex items-center gap-2">
                        <BrainCircuit className="w-4 h-4 text-[#A855F7]" />
                        M0 / M1 / M2 / M3 + post-mortem
                    </h3>
                </div>
                <span className="text-[9px] uppercase tracking-widest text-[#D4AF37] border border-[#D4AF37]/20 bg-[#D4AF37]/10 rounded-full px-2 py-1 font-mono">
                    shadow only
                </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-4">
                <PolicyCard id="M0" name="Mechanical baseline" data={paired.m0_mechanical_baseline} />
                <PolicyCard id="M1" name="Baseline + trend" data={paired.m1_trend_filter} />
                <PolicyCard id="M2" name="AI reviewer" data={paired.m2_ai} />
                <PolicyCard id="M3" name="Global context" data={globalComparison.m3_global_context} />
            </div>

            <div className="mt-4 rounded-xl border border-[#00E5FF]/10 bg-[#00E5FF]/[0.03] p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                        <div className="text-[10px] uppercase tracking-widest text-gray-500 font-mono">
                            Global Context v1 — {globalContext.symbol || symbol}
                        </div>
                        <div className="text-sm font-black text-white mt-1">
                            {globalContext.state || 'Brak nowego snapshotu'}
                        </div>
                    </div>
                    <div className="text-right font-mono">
                        <div className={`text-[9px] uppercase ${contextStale ? 'text-[#EF4444]' : 'text-[#10B981]'}`}>
                            {contextAgeMinutes == null
                                ? 'brak timestampu'
                                : `${contextStale ? 'stale' : 'fresh'} · ${contextAgeMinutes.toFixed(0)}m`}
                        </div>
                        <div className="text-[9px] text-gray-600 uppercase mt-1">target bias</div>
                        <div className="text-lg font-black text-[#00E5FF]">
                            {globalContext.target_bias_score_minus100_100 == null
                                ? '—'
                                : Number(globalContext.target_bias_score_minus100_100).toFixed(1)}
                        </div>
                    </div>
                </div>

                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-3 text-[9px] font-mono">
                    <div className="text-gray-600">BTC trend <span className="block text-white mt-1">{valueOrDash(globalComponents.btc_trend_score_minus1_1)}</span></div>
                    <div className="text-gray-600">ETH trend <span className="block text-white mt-1">{valueOrDash(globalComponents.eth_trend_score_minus1_1)}</span></div>
                    <div className="text-gray-600">Alt breadth UP <span className="block text-white mt-1">{breadth.up_share == null ? '—' : `${(Number(breadth.up_share) * 100).toFixed(0)}%`}</span></div>
                    <div className="text-gray-600">Internal coverage <span className="block text-white mt-1">{globalContext.target_data_coverage_0_1 == null ? '—' : `${(Number(globalContext.target_data_coverage_0_1) * 100).toFixed(0)}%`}</span></div>
                </div>

                <div className="flex flex-wrap gap-2 mt-3">
                    {Object.entries(reasonCodes).map(([name, count]) => (
                        <span key={name} className="rounded-full border border-[#00E5FF]/10 px-2 py-1 text-[9px] font-mono text-gray-500">
                            {name} <span className="text-white">{count}</span>
                        </span>
                    ))}
                </div>

                <div className="flex flex-wrap gap-2 mt-3">
                    {['TOTAL2', 'TOTAL3', 'TOTAL3ES', 'BTC.D'].map((name) => (
                        <span key={name} className="rounded-full border border-white/10 px-2 py-1 text-[9px] font-mono text-gray-500">
                            {name} {external[name]?.available ? 'ready' : 'provider pending'}
                        </span>
                    ))}
                </div>
            </div>

            <div className="mt-4 rounded-xl border border-white/5 bg-black/20 p-4">
                <div className="flex items-center justify-between gap-3">
                    <span className="text-[10px] uppercase tracking-widest text-gray-500 font-mono flex items-center gap-2">
                        <FlaskConical className="w-3.5 h-3.5" /> Post-mortems
                    </span>
                    <span className="text-xs font-bold font-mono text-white">{learning.records || 0}</span>
                </div>

                {diagnoses.length > 0 ? (
                    <div className="flex flex-wrap gap-2 mt-3">
                        {diagnoses.map(([name, count]) => (
                            <span key={name} className="rounded-full border border-white/10 px-2 py-1 text-[9px] font-mono text-gray-400">
                                {name} <span className="text-white font-bold">{count}</span>
                            </span>
                        ))}
                    </div>
                ) : (
                    <p className="text-[10px] text-gray-600 font-mono mt-3">
                        Zbieramy pierwsze pełne okna po zamknięciu epizodów.
                    </p>
                )}

                <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 mt-4 text-[9px] font-mono">
                    <div className="text-gray-600">Actual <span className="block text-white mt-1">{valueOrDash(learning.actual_mean_net_r, 'R')}</span></div>
                    <div className="text-gray-600">Target 1R <span className="block text-white mt-1">{valueOrDash(counterfactuals['market_target_1.0r'], 'R')}</span></div>
                    <div className="text-gray-600">Target 1.5R <span className="block text-white mt-1">{valueOrDash(counterfactuals['market_target_1.5r'], 'R')}</span></div>
                    <div className="text-gray-600">Target 2R <span className="block text-white mt-1">{valueOrDash(counterfactuals['market_target_2.0r'], 'R')}</span></div>
                    <div className="text-gray-600">P1 scale + BE <span className="block text-white mt-1">{valueOrDash(counterfactuals.intraday_p1_structural, 'R')}</span></div>
                    <div className="text-gray-600">P1 TP1 hit <span className="block text-white mt-1">{counterfactualTp1.intraday_p1_structural == null ? '—' : `${(Number(counterfactualTp1.intraday_p1_structural) * 100).toFixed(0)}%`}</span></div>
                    <div className="text-gray-600">P2 trail runner <span className="block text-white mt-1">{valueOrDash(counterfactuals.intraday_p2_hybrid, 'R')}</span></div>
                    <div className="text-gray-600">P2 TP1 hit <span className="block text-white mt-1">{counterfactualTp1.intraday_p2_hybrid == null ? '—' : `${(Number(counterfactualTp1.intraday_p2_hybrid) * 100).toFixed(0)}%`}</span></div>
                    <div className="text-gray-600">Limit 5m <span className="block text-white mt-1">{valueOrDash(counterfactuals.post_confirmation_limit_5m, 'R')}</span></div>
                </div>
            </div>

            <p className="text-[9px] text-gray-600 font-mono mt-3">
                Dane opisowe. P1/P2 są kontrfaktycznymi politykami day tradingu; nie autoryzują live ani automatycznej zmiany strategii.
            </p>
        </div>
    );
}
