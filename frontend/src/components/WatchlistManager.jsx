import React, { useState, useEffect } from 'react';
import { Plus, X, Pause, Play, ChevronDown } from 'lucide-react';
import { fetchPairs, addPair, removePair, togglePair } from '../api';

export default function WatchlistManager() {
    const [pairs, setPairs]         = useState([]);
    const [suggestions, setSug]     = useState([]);
    const [input, setInput]         = useState('');
    const [showDropdown, setDrop]   = useState(false);
    const [error, setError]         = useState('');
    const [adding, setAdding]       = useState(false);

    const load = () => fetchPairs().then(r => {
        setPairs(r.data.pairs || []);
        setSug(r.data.suggestions || []);
    }).catch(() => {});

    useEffect(() => { load(); }, []);

    const handleAdd = async (sym) => {
        const symbol = (sym || input).toUpperCase().trim();
        if (!symbol) return;
        setAdding(true);
        setError('');
        try {
            await addPair(symbol);
            setInput('');
            setDrop(false);
            await load();
        } catch (e) {
            setError(e.response?.data?.error || 'Błąd dodawania pary');
        } finally {
            setAdding(false);
        }
    };

    const handleRemove = async (symbol) => {
        try { await removePair(symbol); await load(); } catch {}
    };

    const handleToggle = async (symbol) => {
        try { await togglePair(symbol); await load(); } catch {}
    };

    const activePairs  = pairs.filter(p => p.active);
    const pausedPairs  = pairs.filter(p => !p.active);
    const filtered     = input.length >= 1
        ? suggestions.filter(s => s.startsWith(input.toUpperCase()) && !pairs.find(p => p.symbol === s))
        : suggestions.filter(s => !pairs.find(p => p.symbol === s)).slice(0, 8);

    return (
        <div className="flex flex-col gap-3">
            {/* Active pairs */}
            <div className="flex flex-wrap gap-2 items-center">
                {activePairs.map(p => (
                    <div key={p.symbol}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-[#00E5FF]/10 border border-[#00E5FF]/25 rounded-full group">
                        <span className="w-1.5 h-1.5 rounded-full bg-[#10B981] animate-pulse" />
                        <span className="text-xs font-bold font-mono text-white">{p.symbol.replace('USDT', '')}</span>
                        <span className="text-[10px] text-gray-500 font-mono">USDT</span>
                        <div className="hidden group-hover:flex items-center gap-0.5 ml-1">
                            <button onClick={() => handleToggle(p.symbol)}
                                className="text-gray-500 hover:text-[#D4AF37] transition-colors p-0.5 rounded">
                                <Pause className="w-2.5 h-2.5" />
                            </button>
                            <button onClick={() => handleRemove(p.symbol)}
                                className="text-gray-500 hover:text-[#EF4444] transition-colors p-0.5 rounded">
                                <X className="w-2.5 h-2.5" />
                            </button>
                        </div>
                    </div>
                ))}

                {/* Paused pairs */}
                {pausedPairs.map(p => (
                    <div key={p.symbol}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-white/[0.03] border border-white/10 rounded-full group opacity-50">
                        <span className="w-1.5 h-1.5 rounded-full bg-gray-600" />
                        <span className="text-xs font-mono text-gray-500 line-through">{p.symbol.replace('USDT', '')}</span>
                        <div className="hidden group-hover:flex items-center gap-0.5 ml-1">
                            <button onClick={() => handleToggle(p.symbol)}
                                className="text-gray-500 hover:text-[#10B981] transition-colors p-0.5 rounded">
                                <Play className="w-2.5 h-2.5" />
                            </button>
                            <button onClick={() => handleRemove(p.symbol)}
                                className="text-gray-500 hover:text-[#EF4444] transition-colors p-0.5 rounded">
                                <X className="w-2.5 h-2.5" />
                            </button>
                        </div>
                    </div>
                ))}

                {/* Add input */}
                <div className="relative">
                    <div className="flex items-center gap-1 px-2 py-1.5 bg-white/[0.03] border border-white/10 rounded-full hover:border-[#00E5FF]/30 transition-colors">
                        <Plus className="w-3 h-3 text-gray-500" />
                        <input
                            type="text"
                            value={input}
                            onChange={e => { setInput(e.target.value); setDrop(true); setError(''); }}
                            onFocus={() => setDrop(true)}
                            onBlur={() => setTimeout(() => setDrop(false), 150)}
                            onKeyDown={e => e.key === 'Enter' && handleAdd()}
                            placeholder="SOLUSDT…"
                            className="bg-transparent text-xs font-mono text-white placeholder-gray-600 focus:outline-none w-20"
                        />
                        {input && (
                            <button onClick={() => handleAdd()} disabled={adding}
                                className="text-[#00E5FF] text-[10px] font-bold font-mono hover:text-white transition-colors ml-1">
                                {adding ? '…' : '+ ADD'}
                            </button>
                        )}
                    </div>

                    {/* Dropdown suggestions */}
                    {showDropdown && filtered.length > 0 && (
                        <div className="absolute top-full left-0 mt-1 bg-[#0a0a0b] border border-white/10 rounded-xl shadow-2xl z-50 py-1 min-w-[120px]">
                            {filtered.map(s => (
                                <button key={s}
                                    onMouseDown={() => handleAdd(s)}
                                    className="w-full text-left px-3 py-1.5 text-xs font-mono text-gray-400 hover:text-white hover:bg-white/5 transition-colors">
                                    {s}
                                </button>
                            ))}
                        </div>
                    )}
                </div>
            </div>

            {error && <p className="text-[#EF4444] text-[10px] font-mono">{error}</p>}
        </div>
    );
}
