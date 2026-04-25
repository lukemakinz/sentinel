import React, { useState } from 'react';
import { BookOpen, GitBranch, Brain, TrendingUp, Shield, Clock, Zap, ChevronDown, ChevronUp, AlertTriangle, CheckCircle } from 'lucide-react';

function Section({ title, icon: Icon, children, defaultOpen = false }) {
    const [open, setOpen] = useState(defaultOpen);
    return (
        <div className="glass-panel overflow-hidden">
            <button
                className="w-full p-5 flex items-center justify-between hover:bg-white/[0.02] transition-colors"
                onClick={() => setOpen(o => !o)}
            >
                <div className="flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-[#00E5FF]/10">
                        <Icon className="w-4 h-4 text-[#00E5FF]" />
                    </div>
                    <span className="font-bold text-white">{title}</span>
                </div>
                {open ? <ChevronUp className="w-4 h-4 text-gray-500" /> : <ChevronDown className="w-4 h-4 text-gray-500" />}
            </button>
            {open && <div className="px-5 pb-5 border-t border-white/5 pt-5">{children}</div>}
        </div>
    );
}

function Tag({ color = 'cyan', children }) {
    const colors = {
        cyan:   'bg-[#00E5FF]/10 text-[#00E5FF] border-[#00E5FF]/25',
        green:  'bg-[#10B981]/10 text-[#10B981] border-[#10B981]/25',
        yellow: 'bg-[#D4AF37]/10 text-[#D4AF37] border-[#D4AF37]/25',
        red:    'bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/25',
        gray:   'bg-white/5 text-gray-400 border-white/10',
    };
    return (
        <span className={`text-[10px] font-bold font-mono px-2 py-0.5 rounded border ${colors[color]}`}>
            {children}
        </span>
    );
}

function Gate({ id, desc, mandatory }) {
    return (
        <div className="flex items-start gap-2 py-1.5 border-b border-white/[0.03] last:border-0">
            <div className="flex items-center gap-1.5 min-w-[48px]">
                <span className="text-[11px] font-bold font-mono text-gray-400">{id}</span>
                {mandatory && <span className="text-[8px] text-[#EF4444] font-mono">REQ</span>}
            </div>
            <span className="text-[11px] text-gray-400 font-mono">{desc}</span>
        </div>
    );
}

function StrategyCard({ id, name, desc, color, gates_a, gates_b, gates_c, note }) {
    const colors = {
        S1: 'border-[#00E5FF]/20 bg-[#00E5FF]/3',
        S2: 'border-[#10B981]/20 bg-[#10B981]/3',
        S3: 'border-[#D4AF37]/20 bg-[#D4AF37]/3',
    };
    const tagColor = { S1: 'cyan', S2: 'green', S3: 'yellow' };

    return (
        <div className={`rounded-xl border p-4 flex flex-col gap-3 ${colors[id]}`}>
            <div className="flex items-center gap-2">
                <Tag color={tagColor[id]}>{id}</Tag>
                <span className="font-bold text-white">{name}</span>
                <span className="text-xs text-gray-500 font-mono">— {desc}</span>
            </div>

            {note && (
                <div className="flex items-start gap-2 bg-[#D4AF37]/5 border border-[#D4AF37]/15 rounded-lg p-2.5">
                    <AlertTriangle className="w-3.5 h-3.5 text-[#D4AF37] shrink-0 mt-0.5" />
                    <span className="text-[11px] text-[#D4AF37] font-mono">{note}</span>
                </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-[11px]">
                <div>
                    <div className="text-[9px] uppercase tracking-widest text-gray-600 font-bold mb-1.5">Gate A</div>
                    {gates_a.map((g, i) => <div key={i} className="font-mono text-gray-400 py-0.5">{g}</div>)}
                </div>
                <div>
                    <div className="text-[9px] uppercase tracking-widest text-gray-600 font-bold mb-1.5">Gate B</div>
                    {gates_b.map((g, i) => <div key={i} className="font-mono text-gray-400 py-0.5">{g}</div>)}
                </div>
                <div>
                    <div className="text-[9px] uppercase tracking-widest text-gray-600 font-bold mb-1.5">Gate C</div>
                    {gates_c.map((g, i) => <div key={i} className="font-mono text-gray-400 py-0.5">{g}</div>)}
                </div>
            </div>
        </div>
    );
}

function RiskRule({ icon: Icon, title, desc }) {
    return (
        <div className="flex items-start gap-3 py-3 border-b border-white/5 last:border-0">
            <div className="p-1.5 rounded-lg bg-white/5 shrink-0 mt-0.5">
                <Icon className="w-3.5 h-3.5 text-gray-400" />
            </div>
            <div>
                <div className="text-sm font-bold text-white">{title}</div>
                <div className="text-xs text-gray-500 font-mono mt-0.5">{desc}</div>
            </div>
        </div>
    );
}

export default function HowItWorks() {
    return (
        <div className="flex flex-col gap-6">
            {/* Header */}
            <div className="pb-6 border-b border-white/5">
                <h2 className="text-3xl font-black tracking-wider text-white flex items-center gap-3">
                    <BookOpen className="w-7 h-7 text-[#00E5FF]" />
                    Jak działa <span className="text-[#00E5FF]">Sentinel</span>
                </h2>
                <p className="text-sm text-gray-400 mt-2 font-mono">
                    Opis systemu, strategii i reguł risk management
                </p>
            </div>

            {/* Pipeline overview */}
            <Section title="Pipeline sygnału — od danych do trade'u" icon={GitBranch} defaultOpen>
                <div className="flex flex-col gap-3">
                    {[
                        { step: '1', color: '#00E5FF', label: 'Dane w czasie rzeczywistym', desc: 'Binance WebSocket: ceny (1m/5m/15m/1h/4h), funding rate, liquidacje, aggTrade (Whale CVD). REST co 5-15 min: Open Interest, L/S ratio.' },
                        { step: '2', color: '#10B981', label: 'L1 Pre-Filter (co 1 minutę)', desc: '15 deterministycznych bram w 3 grupach (A/B/C). Zero LLM — czysta matematyka. Sprawdza jednocześnie wszystkie 3 strategie (S1/S2/S3).' },
                        { step: '3', color: '#D4AF37', label: 'L2 AI Agents (~10-15s)', desc: '4 wyspecjalizowani agenci AI oceniają setup w równoległych wywołaniach. Supervisor (deterministyczny) decyduje APPROVE/REJECT i rozmiar pozycji (0-100%).' },
                        { step: '4', color: '#EF4444', label: 'L3 Calculator', desc: 'Deterministyczne obliczenie entry (25% głębokości FVG), SL (sweep - 0.2×ATR, max 3% od entry), TP1 (+1.5R / 40%), TP2 (+3.0R / 40%), runner (20% chandelier).' },
                        { step: '5', color: '#A855F7', label: 'Karta sygnału na dashboardzie', desc: 'Widzisz: parę, kierunek, strategię, entry/SL/TP, reasoning wszystkich 4 agentów, timer ważności (30 min). Wpisujesz swoją faktyczną cenę wejścia.' },
                        { step: '6', color: '#6B7280', label: 'Monitoring pozycji (co 30s)', desc: 'Live P&L, SL/TP progress bar, cena likwidacji. Po TP1: SL przesuwa się na breakeven. Po TP2: chandelier trailing stop. Po 8h bez 1R: time-kill.' },
                    ].map(({ step, color, label, desc }) => (
                        <div key={step} className="flex items-start gap-4">
                            <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 font-black text-sm font-mono border-2"
                                style={{ borderColor: color, color }}>
                                {step}
                            </div>
                            <div>
                                <div className="font-bold text-white text-sm">{label}</div>
                                <div className="text-[11px] text-gray-400 font-mono mt-0.5 leading-relaxed">{desc}</div>
                            </div>
                        </div>
                    ))}
                </div>
            </Section>

            {/* Strategies */}
            <Section title="3 aktywne strategie — sprawdzane jednocześnie" icon={TrendingUp} defaultOpen>
                <div className="flex flex-col gap-4">
                    <StrategyCard
                        id="S1" name="SMC Sweep" desc="Smart Money Concepts / ICT"
                        gates_a={['✅ A1 Killzone (London/NY)', '✅ A2 HTF Trend (EMA50/200)', '✅ A3 BTC Correlation', '✅ A4 Funding Rate normalny', '✅ A5 ADX > 20 (wszystkie wymagane)']}
                        gates_b={['✅ B1 Liquidity Sweep (obow.)', '✅ B2 FVG/Order Block (obow.)', '○ B3 Premium/Discount zone', '○ B4 Classical pattern', '○ B5 ATR Squeeze', 'min 3/5 wymagane']}
                        gates_c={['✅ C1 ChoCH (obowiązkowy)', '○ C2 RSI Divergence', '○ C3 EMA 9/21 alignment', '○ C4 Volume Spike', '○ C5 Cena vs VWAP', 'min 2/5 wymagane']}
                    />
                    <StrategyCard
                        id="S2" name="Order Flow" desc="Quantitative CVD + OI"
                        note="Wymaga danych WhaleCVD — aktywna po 4h od startu (aggTrade stream)"
                        gates_a={['✅ A1 Killzone', '○ A2 (opcjonalne)', '○ A3 (opcjonalne)', '✅ A4 Funding Rate', '✅ A5 ADX > 20']}
                        gates_b={['○ dowolne 2/5 B gates', 'B1/B2 preferowane']}
                        gates_c={['○ dowolna 1/5 C gate']}
                    />
                    <StrategyCard
                        id="S3" name="Classic TA" desc="EMA crossover + RSI + S/R"
                        gates_a={['✅ A1 Killzone', '✅ A2 HTF Trend (EMA50/200)', '○ A3-A5 (opcjonalne)']}
                        gates_b={['✅ B3 Premium/Discount (obow.)', '○ + 1 dowolny B gate', 'min 2/5 wymagane']}
                        gates_c={['✅ C2 RSI Divergence (obow.)', '✅ C3 EMA alignment (obow.)', 'min 2/5 wymagane']}
                    />
                    <div className="bg-[#0a0a0b] rounded-xl p-4 border border-white/5 text-[11px] font-mono text-gray-500">
                        <div className="font-bold text-gray-300 mb-2">Entry / SL / TP (wspólne dla wszystkich strategii)</div>
                        <div className="grid grid-cols-2 gap-x-8 gap-y-1">
                            <div>Entry: <span className="text-white">FVG bottom + 25% głębokości</span></div>
                            <div>SL S1/S2: <span className="text-white">swept_level − 0.2×ATR</span></div>
                            <div>SL cap: <span className="text-white">max 3% od entry</span></div>
                            <div>SL S3: <span className="text-white">swing − 0.15×ATR</span></div>
                            <div>TP1: <span className="text-white">+1.5R → 40% pozycji</span></div>
                            <div>TP2: <span className="text-white">+3.0R → 40% pozycji</span></div>
                            <div>Runner: <span className="text-white">20% → chandelier trailing</span></div>
                            <div>Time-kill: <span className="text-white">8h bez 1R → zamknij</span></div>
                        </div>
                    </div>
                </div>
            </Section>

            {/* AI Agents */}
            <Section title="4 Agenci AI — co oceniają" icon={Brain}>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {[
                        { name: 'Context Trader', color: '#10B981', desc: 'SMC/ICT narrativa — sweep, FVG, ChoCH, premium/discount, HTF alignment. Nie generuje liczb — tylko ocenia jakość setupu.' },
                        { name: 'Order Flow Quant', color: '#00E5FF', desc: 'Whale CVD vs Retail CVD, Open Interest trend, absorpcja. Quantitative — patrzy na dane order flow, nie price action.' },
                        { name: 'Risk Manager', color: '#D4AF37', desc: 'Drawdown, portfolio heat (BTC-beta), news calendar, szerokość SL. REJECT = twarde weto — blokuje niezależnie od innych agentów.' },
                        { name: "Devil's Advocate", color: '#EF4444', desc: 'Kontrariański red-team — szuka powodów dlaczego setup może nie zadziałać. Jego REJECT z confidence > 70% → size multiplier ×0.5.' },
                    ].map(a => (
                        <div key={a.name} className="bg-[#0a0a0b] rounded-xl p-4 border border-white/5">
                            <div className="font-bold text-sm mb-1.5" style={{ color: a.color }}>{a.name}</div>
                            <p className="text-[11px] text-gray-400 font-mono leading-relaxed">{a.desc}</p>
                        </div>
                    ))}
                </div>
                <div className="mt-4 bg-[#0a0a0b] rounded-xl p-4 border border-white/5">
                    <div className="text-xs font-bold text-white mb-2">Reguły Supervisora (deterministyczne, bez LLM)</div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5 text-[11px] font-mono text-gray-400">
                        <div><span className="text-[#EF4444]">Risk Manager REJECT</span> → całe REJECT (twarde weto)</div>
                        <div><span className="text-white">3+ APPROVE</span> → pełny size (1.0×)</div>
                        <div><span className="text-[#D4AF37]">DA REJECT confidence {'>'} 70%</span> → size ×0.5</div>
                        <div><span className="text-white">2 APPROVE</span> → size 0.75×</div>
                        <div><span className="text-gray-600">{'≤'} 1 APPROVE</span> → REJECT</div>
                    </div>
                </div>
            </Section>

            {/* Risk Management */}
            <Section title="Risk Management — automatyczne zabezpieczenia" icon={Shield}>
                <RiskRule icon={TrendingUp} title="DD-based size scaling" desc="0% DD → 100% size | -5% → 75% | -10% → 50% | -15% → 25% | -20% → HALT" />
                <RiskRule icon={AlertTriangle} title="Daily / Weekly HALT" desc="Dzienny drawdown -3% lub tygodniowy -7% → wszystkie nowe pozycje zablokowane" />
                <RiskRule icon={Clock} title="News Calendar" desc="Blokada 2h przed i 1h po: FOMC, CPI, NFP — 2026 hardcoded, future: CoinGecko API" />
                <RiskRule icon={Zap} title="Portfolio Heat" desc="Efektywna ekspozycja BTC-beta max 2× equity. ETHUSDT=0.9×, SOLUSDT=0.85×, BNBUSDT=0.75×" />
                <RiskRule icon={Brain} title="Strategy Monitor" desc="Rolling 20-trade Sharpe < 0 → auto-halt. Ochrona przed degradacją strategii w czasie." />
                <RiskRule icon={CheckCircle} title="Chandelier Trailing Stop" desc="Po TP2: runner (20%) → highest_high(22) − 3×ATR, update co 1h candle close" />
            </Section>

            {/* Sessions */}
            <Section title="Sesje tradingowe i timing" icon={Clock}>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="bg-[#0a0a0b] rounded-xl p-4 border border-[#10B981]/15">
                        <div className="text-[#10B981] font-bold text-sm mb-2">🇬🇧 London Session</div>
                        <div className="text-2xl font-black font-mono text-white mb-1">07:00 – 10:00 UTC</div>
                        <div className="text-[11px] text-gray-500 font-mono">Gate A1 aktywny tylko w tym oknie</div>
                    </div>
                    <div className="bg-[#0a0a0b] rounded-xl p-4 border border-[#00E5FF]/15">
                        <div className="text-[#00E5FF] font-bold text-sm mb-2">🇺🇸 New York Session</div>
                        <div className="text-2xl font-black font-mono text-white mb-1">13:00 – 16:00 UTC</div>
                        <div className="text-[11px] text-gray-500 font-mono">Druga aktywna sesja dla Gate A1</div>
                    </div>
                </div>
                <div className="mt-4 bg-[#0a0a0b] rounded-xl p-4 border border-white/5 text-[11px] font-mono text-gray-400">
                    <div className="font-bold text-white mb-2">Częstotliwość odświeżania</div>
                    <div className="grid grid-cols-2 gap-x-8 gap-y-1">
                        <div>Ceny / Funding / CVD → <span className="text-white">real-time WebSocket</span></div>
                        <div>L1 scan (15 gates) → <span className="text-white">co 1 minutę</span></div>
                        <div>Open Interest / L/S → <span className="text-white">co 5-15 min</span></div>
                        <div>Whale threshold → <span className="text-white">co 1 godzinę</span></div>
                        <div>Dashboard → <span className="text-white">co 30-60 sekund</span></div>
                        <div>L2 AI Agents → <span className="text-white">po każdym L1 PASS</span></div>
                    </div>
                </div>
            </Section>

            {/* Before going live */}
            <Section title="Checklist przed live tradingiem" icon={CheckCircle}>
                <div className="flex flex-col gap-2 text-[11px] font-mono">
                    {[
                        { done: true,  text: 'MAX_RISK_PER_TRADE = 0.5% (ustawione)' },
                        { done: false, text: 'Backtest S1/S2/S3: Sharpe > 1.5, MaxDD < 20%, min 300 trade\'ów (potrzeba 3 lata danych historycznych)' },
                        { done: false, text: 'Paper trading ≥ 3 miesiące — rozbieżność vs backtest < 20%' },
                        { done: false, text: 'WhaleCVD zbierany ≥ 4 tygodnie (potrzeba historii dla S2)' },
                        { done: false, text: 'Binance Testnet — przetestowany faktyczny timing wejść i latencja' },
                        { done: false, text: 'Monte Carlo ruin probability < 1% przy 0.5% risk' },
                    ].map((item, i) => (
                        <div key={i} className={`flex items-start gap-2 py-2 border-b border-white/5 last:border-0 ${item.done ? 'text-[#10B981]' : 'text-gray-500'}`}>
                            {item.done
                                ? <CheckCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                                : <div className="w-3.5 h-3.5 rounded-full border border-gray-700 shrink-0 mt-0.5" />
                            }
                            {item.text}
                        </div>
                    ))}
                </div>
            </Section>
        </div>
    );
}
