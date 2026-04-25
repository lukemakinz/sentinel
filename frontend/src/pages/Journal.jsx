import React from 'react';
import { usePolling } from '../hooks/usePolling';
import { fetchTrades } from '../api';
import TradeJournal from '../components/TradeJournal';
import { BookOpen, Loader2 } from 'lucide-react';

export default function Journal() {
    const { data: trades, loading } = usePolling(fetchTrades, 15000);
    const tradeList = trades?.results || trades || [];

    return (
        <div className="flex flex-col h-full w-full">
            <div className="flex items-center justify-between pb-6 border-b border-white/5 mb-8">
                <div>
                    <h2 className="text-3xl font-black tracking-wider text-white">Trade <span className="text-[#D4AF37]">Journal</span></h2>
                    <p className="text-sm text-gray-400 mt-2 font-mono flex items-center gap-2">
                        <BookOpen className="w-4 h-4 text-[#D4AF37]" />
                        Comprehensive execution and analyst rationale logs
                    </p>
                </div>
            </div>

            {loading && !trades ? (
                <div className="flex flex-col h-[50vh] w-full items-center justify-center text-gray-400">
                    <Loader2 className="w-12 h-12 animate-spin text-[#D4AF37] mb-4" />
                    <p className="font-mono uppercase tracking-widest text-sm animate-pulse text-[#D4AF37]">Retrieving Historical Archives...</p>
                </div>
            ) : (
                <TradeJournal trades={tradeList} />
            )}
        </div>
    );
}
