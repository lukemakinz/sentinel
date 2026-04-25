import React, { useState, useEffect } from 'react';
import { Clock } from 'lucide-react';

const SESSIONS = [
    { name: 'London', start: 7, end: 10 },
    { name: 'New York', start: 13, end: 16 },
];

function getSessionStatus() {
    const now = new Date();
    const utcHour = now.getUTCHours();
    const utcMin  = now.getUTCMinutes();
    const utcSec  = now.getUTCSeconds();
    const totalSeconds = utcHour * 3600 + utcMin * 60 + utcSec;

    for (const s of SESSIONS) {
        const startSec = s.start * 3600;
        const endSec   = s.end * 3600;
        if (totalSeconds >= startSec && totalSeconds < endSec) {
            return { active: true, name: s.name, secondsLeft: endSec - totalSeconds };
        }
    }

    // Find next session
    const next = SESSIONS.find(s => s.start * 3600 > totalSeconds)
              || { ...SESSIONS[0], start: SESSIONS[0].start + 24 }; // wrap to tomorrow
    const nextStart = next.start * 3600;
    const secsUntil = nextStart > totalSeconds
        ? nextStart - totalSeconds
        : 86400 - totalSeconds + SESSIONS[0].start * 3600;

    return { active: false, name: next.name, secondsUntil: secsUntil };
}

function fmt(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return h > 0
        ? `${h}h ${m.toString().padStart(2, '0')}m`
        : `${m}:${s.toString().padStart(2, '0')}`;
}

export default function SessionCountdown() {
    const [state, setState] = useState(getSessionStatus);
    useEffect(() => {
        const t = setInterval(() => setState(getSessionStatus()), 1000);
        return () => clearInterval(t);
    }, []);

    if (state.active) {
        return (
            <div className="flex items-center gap-2 px-3 py-1.5 bg-[#10B981]/10 border border-[#10B981]/20 rounded-lg">
                <span className="w-2 h-2 rounded-full bg-[#10B981] animate-pulse" />
                <span className="text-xs font-mono font-bold text-[#10B981]">{state.name} Session</span>
                <span className="text-xs text-gray-500 font-mono">jeszcze {fmt(state.secondsLeft)}</span>
            </div>
        );
    }

    return (
        <div className="flex items-center gap-2 px-3 py-1.5 bg-white/[0.03] border border-white/5 rounded-lg">
            <Clock className="w-3 h-3 text-gray-500" />
            <span className="text-xs font-mono text-gray-500">{state.name} za</span>
            <span className="text-xs font-mono font-bold text-[#D4AF37]">{fmt(state.secondsUntil)}</span>
        </div>
    );
}
