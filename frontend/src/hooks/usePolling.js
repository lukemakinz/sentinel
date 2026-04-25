import { useState, useEffect, useRef, useCallback } from 'react';

export function usePolling(fetchFn, interval = 5000) {
    const [data, setData]       = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError]     = useState(null);
    const fetchRef   = useRef(fetchFn);
    const intervalRef = useRef(null);

    // Keep ref current without re-running effect on every render
    useEffect(() => { fetchRef.current = fetchFn; });

    useEffect(() => {
        let mounted = true;

        const load = async () => {
            try {
                const res = await fetchRef.current();
                if (mounted) {
                    setData(res.data);
                    setLoading(false);
                    setError(null);
                }
            } catch (err) {
                if (mounted) {
                    setError(err.message);
                    setLoading(false);
                }
            }
        };

        load();
        intervalRef.current = setInterval(load, interval);

        return () => {
            mounted = false;
            clearInterval(intervalRef.current);
        };
    }, [interval]); // interval is the only stable dependency

    return { data, loading, error };
}
