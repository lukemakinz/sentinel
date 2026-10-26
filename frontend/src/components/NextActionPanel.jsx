import React, { useMemo } from 'react';
import { AlertTriangle, ArrowRightLeft, BellRing, CheckCircle2, RadioTower, ShieldAlert } from 'lucide-react';
import { fetchExchangeIntegration, fetchExchangeState } from '../api';
import { usePolling } from '../hooks/usePolling';

function ActionBadge({ tone, children }) {
    const styles = {
        urgent: 'border-[#EF4444]/25 bg-[#EF4444]/10 text-[#fca5a5]',
        active: 'border-[#00E5FF]/25 bg-[#00E5FF]/10 text-[#67e8f9]',
        safe: 'border-[#10B981]/25 bg-[#10B981]/10 text-[#86efac]',
        warn: 'border-[#D4AF37]/25 bg-[#D4AF37]/10 text-[#fcd34d]',
    };
    return (
        <span className={`rounded-full border px-3 py-1 text-[11px] font-mono uppercase tracking-[0.22em] ${styles[tone] || styles.safe}`}>
            {children}
        </span>
    );
}

function ActionRow({ icon: Icon, title, detail, tone = 'safe' }) {
    const colorMap = {
        urgent: 'text-[#EF4444]',
        active: 'text-[#00E5FF]',
        safe: 'text-[#10B981]',
        warn: 'text-[#D4AF37]',
    };

    return (
        <div className="rounded-2xl border border-white/5 bg-black/20 px-4 py-4 flex items-start gap-3">
            <div className="mt-0.5">
                <Icon className={`w-4 h-4 ${colorMap[tone] || colorMap.safe}`} />
            </div>
            <div className="min-w-0">
                <p className="text-sm font-semibold text-white">{title}</p>
                <p className="text-xs font-mono text-gray-500 mt-1 leading-6">{detail}</p>
            </div>
        </div>
    );
}

export default function NextActionPanel({
    status,
    signals = [],
    positions = [],
}) {
    const { data: exchangeState } = usePolling(fetchExchangeState, 30000);
    const { data: exchangeIntegration } = usePolling(fetchExchangeIntegration, 30000);

    const summary = useMemo(() => {
        const activeSignals = signals.length;
        const openPositions = positions.length;
        const openExchangeOrders = exchangeState?.open_orders_count || 0;
        const liveEnabled = Boolean(exchangeIntegration?.live_trading_enabled);
        const credentialsConfigured = Boolean(exchangeIntegration?.credentials_configured);
        const dataFresh = Boolean(status?.ingester_active);

        if (!dataFresh) {
            return {
                badge: { tone: 'urgent', label: 'Action Required' },
                rows: [
                    {
                        icon: RadioTower,
                        title: 'Sprawdź dopływ danych',
                        detail: 'Ingester wygląda na nieświeży. Najpierw upewnij się, że świeczki i feed market data są aktualne.',
                        tone: 'urgent',
                    },
                ],
            };
        }

        if (activeSignals > 0) {
            return {
                badge: { tone: 'active', label: `${activeSignals} Signal${activeSignals > 1 ? 's' : ''} Waiting` },
                rows: [
                    {
                        icon: BellRing,
                        title: 'Przejrzyj aktywne sygnały',
                        detail: `Masz ${activeSignals} aktywn${activeSignals === 1 ? 'y' : 'e'} sygnał${activeSignals === 1 ? '' : 'y'}. To jest teraz najwyższy priorytet użytkownika.`,
                        tone: 'active',
                    },
                    {
                        icon: ShieldAlert,
                        title: 'Zweryfikuj risk przed wejściem',
                        detail: 'Przed kliknięciem wejścia sprawdź aktualny drawdown, ekspozycję i czy profil strategii pasuje do bieżącej sesji.',
                        tone: 'warn',
                    },
                ],
            };
        }

        if (openPositions > 0) {
            return {
                badge: { tone: 'warn', label: `${openPositions} Position${openPositions > 1 ? 's' : ''} Live` },
                rows: [
                    {
                        icon: ShieldAlert,
                        title: 'Monitoruj otwarte pozycje',
                        detail: `Masz ${openPositions} otwart${openPositions === 1 ? 'ą pozycję' : 'e pozycje'}. Głównym zadaniem jest teraz kontrola ryzyka i egzekucji.`,
                        tone: 'warn',
                    },
                    {
                        icon: ArrowRightLeft,
                        title: 'Sprawdź exchange ops',
                        detail: `Exchange pokazuje ${openExchangeOrders} aktywn${openExchangeOrders === 1 ? 'e zlecenie' : 'ych zleceń'}. Zweryfikuj, czy wszystko zgadza się z planem pozycji.`,
                        tone: 'active',
                    },
                ],
            };
        }

        if (liveEnabled && !credentialsConfigured) {
            return {
                badge: { tone: 'warn', label: 'Setup Pending' },
                rows: [
                    {
                        icon: AlertTriangle,
                        title: 'Dokończ konfigurację live exchange',
                        detail: 'Live trading jest włączony, ale credentials nie wyglądają na kompletne. To trzeba wyprostować przed realnym startem.',
                        tone: 'warn',
                    },
                ],
            };
        }

        return {
            badge: { tone: 'safe', label: 'System Ready' },
            rows: [
                {
                    icon: CheckCircle2,
                    title: 'System jest gotowy do pracy',
                    detail: 'Brak pilnych akcji. Możesz obserwować rynek, utrzymywać watchlistę i czekać na kolejny jakościowy sygnał.',
                    tone: 'safe',
                },
                {
                    icon: ArrowRightLeft,
                    title: 'Pilnuj exchange sync',
                    detail: 'Jeśli chcesz mieć pełny audit trail, odśwież od czasu do czasu snapshot exchange albo sprawdź wykres z fillami i orderami.',
                    tone: 'active',
                },
            ],
        };
    }, [exchangeIntegration, exchangeState, positions.length, signals.length, status?.ingester_active]);

    return (
        <div className="glass-panel p-5 flex flex-col gap-4">
            <div className="flex items-start justify-between gap-3 flex-wrap">
                <div>
                    <p className="text-xs uppercase tracking-[0.32em] text-gray-500 font-mono mb-2">Next Action</p>
                    <h3 className="text-lg font-black tracking-wider text-white">What Needs Attention Now</h3>
                    <p className="text-sm text-gray-500 mt-2">
                        Zamiast wielu paneli naraz, ten blok mówi wprost jaki jest teraz najważniejszy krok użytkownika.
                    </p>
                </div>
                <ActionBadge tone={summary.badge.tone}>{summary.badge.label}</ActionBadge>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                {summary.rows.map((row) => (
                    <ActionRow
                        key={row.title}
                        icon={row.icon}
                        title={row.title}
                        detail={row.detail}
                        tone={row.tone}
                    />
                ))}
            </div>
        </div>
    );
}
