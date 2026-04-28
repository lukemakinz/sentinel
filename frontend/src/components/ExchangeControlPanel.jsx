import React, { useMemo, useState } from 'react';
import { ArrowRightLeft, CircleAlert, CircleCheckBig, Coins, LoaderCircle, RefreshCw, Shield, Wallet } from 'lucide-react';
import { fetchExchangeIntegration, fetchExchangeState, transferExchangeProfit, triggerExchangeSync } from '../api';
import { usePolling } from '../hooks/usePolling';

function StatChip({ label, value, tone = 'text-white' }) {
    return (
        <div className="rounded-xl border border-white/5 bg-black/20 px-3 py-2">
            <p className="text-[9px] uppercase tracking-[0.28em] text-gray-600 font-mono">{label}</p>
            <p className={`mt-1 text-sm font-black font-mono ${tone}`}>{value}</p>
        </div>
    );
}

export default function ExchangeControlPanel() {
    const { data: integration, loading: integrationLoading } = usePolling(fetchExchangeIntegration, 30000);
    const { data: exchangeState, loading: exchangeStateLoading } = usePolling(fetchExchangeState, 30000);
    const [syncing, setSyncing] = useState(false);
    const [transferring, setTransferring] = useState(false);
    const [feedback, setFeedback] = useState(null);
    const [manualAmount, setManualAmount] = useState('');

    const account = exchangeState?.account;
    const positions = exchangeState?.positions || [];
    const openOrders = exchangeState?.open_orders || [];
    const activeSymbols = integration?.active_symbols || [];
    const liveEnabled = Boolean(integration?.live_trading_enabled);
    const credentialsConfigured = Boolean(integration?.credentials_configured);
    const spotRatioPct = Math.round((Number(integration?.profit_to_spot_ratio || 0) * 100) * 10) / 10;
    const isLoading = integrationLoading || exchangeStateLoading;

    const readiness = useMemo(() => {
        if (liveEnabled && credentialsConfigured) {
            return {
                label: 'Live Ready',
                tone: 'text-[#10B981]',
                border: 'border-[#10B981]/20 bg-[#10B981]/10',
                icon: CircleCheckBig,
            };
        }
        return {
            label: 'Setup Pending',
            tone: 'text-[#D4AF37]',
            border: 'border-[#D4AF37]/20 bg-[#D4AF37]/10',
            icon: CircleAlert,
        };
    }, [credentialsConfigured, liveEnabled]);

    const handleSync = async () => {
        setSyncing(true);
        setFeedback(null);
        try {
            const response = await triggerExchangeSync();
            setFeedback({
                ok: true,
                message: `Sync completed • positions ${response.data.payload?.normalized_positions?.length ?? 0}, orders ${response.data.payload?.normalized_open_orders?.length ?? 0}`,
            });
        } catch (error) {
            setFeedback({
                ok: false,
                message: error.response?.data?.reason || error.response?.data?.error || 'Sync failed',
            });
        } finally {
            setSyncing(false);
        }
    };

    const handleTransfer = async () => {
        setTransferring(true);
        setFeedback(null);
        try {
            const normalizedAmount = String(manualAmount).trim() === '' ? null : Number(manualAmount);
            const response = await transferExchangeProfit(normalizedAmount);
            setFeedback({
                ok: true,
                message: `Transferred reserve slice • $${Number(response.data.amount_usd || 0).toFixed(2)}`,
            });
            setManualAmount('');
        } catch (error) {
            setFeedback({
                ok: false,
                message: error.response?.data?.reason || error.response?.data?.error || 'Transfer failed',
            });
        } finally {
            setTransferring(false);
        }
    };

    const ReadinessIcon = readiness.icon;

    return (
        <div className="glass-panel p-5 flex flex-col gap-5">
            <div className="flex items-start justify-between gap-4 flex-wrap">
                <div>
                    <p className="text-xs uppercase tracking-[0.32em] text-gray-500 font-mono mb-2">Exchange Ops</p>
                    <h3 className="text-lg font-black tracking-wider text-white">KuCoin Live Control</h3>
                    <p className="text-sm text-gray-500 mt-2 max-w-2xl">
                        Ręczny nadzór nad integracją live: status gotowości, snapshot giełdy i operacje bezpieczeństwa.
                    </p>
                </div>

                <div className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 ${readiness.border}`}>
                    <ReadinessIcon className={`w-4 h-4 ${readiness.tone}`} />
                    <span className={`text-[11px] uppercase tracking-[0.28em] font-mono ${readiness.tone}`}>{readiness.label}</span>
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
                <StatChip label="Live Trading" value={liveEnabled ? 'Enabled' : 'Disabled'} tone={liveEnabled ? 'text-[#10B981]' : 'text-[#EF4444]'} />
                <StatChip label="Credentials" value={credentialsConfigured ? 'Configured' : 'Missing'} tone={credentialsConfigured ? 'text-[#10B981]' : 'text-[#D4AF37]'} />
                <StatChip label="Profit to Spot" value={`${spotRatioPct}%`} tone="text-[#D4AF37]" />
                <StatChip label="Active Symbols" value={activeSymbols.length || '0'} tone="text-[#00E5FF]" />
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-[1.2fr_0.8fr] gap-4">
                <div className="rounded-2xl border border-white/5 bg-black/20 p-4">
                    <div className="flex items-center justify-between gap-3 mb-3">
                        <div className="flex items-center gap-2">
                            <Wallet className="w-4 h-4 text-[#00E5FF]" />
                            <p className="text-sm font-semibold text-white">Exchange Snapshot</p>
                        </div>
                        {isLoading && <LoaderCircle className="w-4 h-4 text-gray-500 animate-spin" />}
                    </div>

                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <StatChip label="Balance" value={`$${Number(account?.balance || 0).toFixed(2)}`} />
                        <StatChip label="Equity" value={`$${Number(account?.equity || 0).toFixed(2)}`} tone="text-[#10B981]" />
                        <StatChip label="Open Positions" value={exchangeState?.positions_count ?? 0} tone="text-[#00E5FF]" />
                        <StatChip label="Open Orders" value={exchangeState?.open_orders_count ?? 0} tone="text-[#D4AF37]" />
                    </div>

                    <div className="mt-4 flex flex-wrap gap-2">
                        {activeSymbols.length > 0 ? activeSymbols.map((symbol) => (
                            <span
                                key={symbol}
                                className="inline-flex items-center gap-2 rounded-full border border-[#00E5FF]/20 bg-[#00E5FF]/10 px-3 py-1 text-[11px] font-mono text-[#00E5FF]"
                            >
                                <span className="w-1.5 h-1.5 rounded-full bg-[#10B981]" />
                                {symbol}
                            </span>
                        )) : (
                            <span className="text-xs font-mono text-gray-600">No active symbols configured.</span>
                        )}
                    </div>
                </div>

                <div className="rounded-2xl border border-white/5 bg-black/20 p-4 flex flex-col gap-3">
                    <div className="flex items-center gap-2">
                        <Shield className="w-4 h-4 text-[#D4AF37]" />
                        <p className="text-sm font-semibold text-white">Manual Operations</p>
                    </div>

                    <button
                        type="button"
                        onClick={handleSync}
                        disabled={syncing}
                        className="w-full inline-flex items-center justify-center gap-2 rounded-xl border border-[#00E5FF]/20 bg-[#00E5FF]/10 px-4 py-3 text-sm font-semibold text-[#00E5FF] transition-all hover:bg-[#00E5FF]/15 disabled:opacity-60"
                    >
                        {syncing ? <LoaderCircle className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                        Sync Exchange Now
                    </button>

                    <button
                        type="button"
                        onClick={handleTransfer}
                        disabled={transferring}
                        className="w-full inline-flex items-center justify-center gap-2 rounded-xl border border-[#D4AF37]/20 bg-[#D4AF37]/10 px-4 py-3 text-sm font-semibold text-[#D4AF37] transition-all hover:bg-[#D4AF37]/15 disabled:opacity-60"
                    >
                        {transferring ? <LoaderCircle className="w-4 h-4 animate-spin" /> : <ArrowRightLeft className="w-4 h-4" />}
                        Transfer {spotRatioPct}% Reserve to Spot
                    </button>

                    <label className="flex flex-col gap-2">
                        <span className="text-[10px] uppercase tracking-[0.28em] text-gray-600 font-mono">Optional Manual Amount</span>
                        <input
                            type="number"
                            min="0"
                            step="0.01"
                            value={manualAmount}
                            onChange={(event) => setManualAmount(event.target.value)}
                            placeholder="auto ratio"
                            className="w-full rounded-xl border border-white/10 bg-[#0d0d10]/80 px-3 py-2.5 text-sm text-white outline-none transition-all focus:border-[#D4AF37]/35 focus:shadow-[0_0_0_4px_rgba(212,175,55,0.08)]"
                        />
                    </label>

                    <div className="rounded-xl border border-white/5 bg-[#0f0f12] px-3 py-3">
                        <div className="flex items-start gap-2">
                            <Coins className="w-4 h-4 text-gray-500 mt-0.5 shrink-0" />
                            <p className="text-xs text-gray-500 leading-6">
                                Transfer używa aktualnego `profit_to_spot_ratio`, jeśli nie podamy ręcznej kwoty.
                            </p>
                        </div>
                    </div>

                    {feedback && (
                        <div className={`rounded-xl border px-3 py-3 text-xs font-mono ${feedback.ok ? 'border-[#10B981]/20 bg-[#10B981]/10 text-[#86efac]' : 'border-[#EF4444]/20 bg-[#EF4444]/10 text-[#fca5a5]'}`}>
                            {feedback.message}
                        </div>
                    )}
                </div>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <div className="rounded-2xl border border-white/5 bg-black/20 p-4">
                    <div className="flex items-center justify-between gap-3 mb-3">
                        <p className="text-sm font-semibold text-white">Live Positions</p>
                        <span className="text-[10px] uppercase tracking-[0.28em] text-gray-600 font-mono">{positions.length} tracked</span>
                    </div>

                    {positions.length === 0 ? (
                        <p className="text-sm text-gray-600 font-mono">No open exchange positions in the latest snapshot.</p>
                    ) : (
                        <div className="overflow-hidden rounded-xl border border-white/5">
                            <div className="grid grid-cols-[1.1fr_0.7fr_0.8fr_0.9fr] gap-3 bg-white/[0.03] px-3 py-2 text-[10px] uppercase tracking-[0.25em] text-gray-600 font-mono">
                                <span>Symbol</span>
                                <span>Side</span>
                                <span>Size</span>
                                <span>PnL</span>
                            </div>
                            <div className="divide-y divide-white/5">
                                {positions.slice(0, 6).map((position) => (
                                    <div key={`${position.symbol}-${position.side}-${position.id}`} className="grid grid-cols-[1.1fr_0.7fr_0.8fr_0.9fr] gap-3 px-3 py-3 text-sm">
                                        <div>
                                            <p className="font-semibold text-white">{position.symbol}</p>
                                            <p className="text-[11px] font-mono text-gray-600">@ {Number(position.entry_price || 0).toFixed(2)}</p>
                                        </div>
                                        <span className={position.side === 'LONG' ? 'text-[#10B981] font-mono' : 'text-[#EF4444] font-mono'}>
                                            {position.side}
                                        </span>
                                        <div>
                                            <p className="text-white font-mono">{Number(position.quantity || 0).toFixed(4)}</p>
                                            <p className="text-[11px] text-gray-600 font-mono">${Number(position.position_size_usd || 0).toFixed(2)}</p>
                                        </div>
                                        <span className={`${Number(position.unrealized_pnl || 0) >= 0 ? 'text-[#10B981]' : 'text-[#EF4444]'} font-mono`}>
                                            {Number(position.unrealized_pnl || 0) >= 0 ? '+' : ''}{Number(position.unrealized_pnl || 0).toFixed(2)}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>

                <div className="rounded-2xl border border-white/5 bg-black/20 p-4">
                    <div className="flex items-center justify-between gap-3 mb-3">
                        <p className="text-sm font-semibold text-white">Open Orders</p>
                        <span className="text-[10px] uppercase tracking-[0.28em] text-gray-600 font-mono">{openOrders.filter((order) => order.status === 'active').length} active</span>
                    </div>

                    {openOrders.length === 0 ? (
                        <p className="text-sm text-gray-600 font-mono">No exchange orders resting on the book.</p>
                    ) : (
                        <div className="overflow-hidden rounded-xl border border-white/5">
                            <div className="grid grid-cols-[1.1fr_0.7fr_0.7fr_0.8fr_0.7fr] gap-3 bg-white/[0.03] px-3 py-2 text-[10px] uppercase tracking-[0.25em] text-gray-600 font-mono">
                                <span>Symbol</span>
                                <span>Side</span>
                                <span>Type</span>
                                <span>Price</span>
                                <span>Status</span>
                            </div>
                            <div className="divide-y divide-white/5">
                                {openOrders.slice(0, 6).map((order) => (
                                    <div key={order.order_id} className="grid grid-cols-[1.1fr_0.7fr_0.7fr_0.8fr_0.7fr] gap-3 px-3 py-3 text-sm">
                                        <div>
                                            <p className="font-semibold text-white">{order.symbol}</p>
                                            <p className="text-[11px] font-mono text-gray-600">size {Number(order.size || 0).toFixed(3)}</p>
                                        </div>
                                        <span className={order.side === 'LONG' ? 'text-[#10B981] font-mono' : 'text-[#EF4444] font-mono'}>
                                            {order.side}
                                        </span>
                                        <span className="text-white font-mono">{order.order_type || '—'}</span>
                                        <span className="text-white font-mono">{Number(order.price || 0).toFixed(2)}</span>
                                        <span className={order.status === 'active' ? 'text-[#D4AF37] font-mono' : 'text-gray-500 font-mono'}>
                                            {order.status}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
