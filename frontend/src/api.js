import axios from 'axios';
import { getAuthToken, notifyUnauthorized } from './auth';

// Empty VITE_API_URL = relative URLs (works behind nginx on Pi/prod)
// Set VITE_API_URL=http://localhost:8000 only for local dev without nginx
const API_BASE = import.meta.env.VITE_API_URL || '';
const api = axios.create({ baseURL: `${API_BASE}/api` });

api.interceptors.request.use((config) => {
    const token = getAuthToken();
    if (token) {
        config.headers.Authorization = `Token ${token}`;
    }
    return config;
});

api.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error?.response?.status === 401 && !String(error.config?.url || '').includes('/auth/token/')) {
            notifyUnauthorized();
        }
        return Promise.reject(error);
    },
);

export const loginWithToken = (username, password) => api.post('/auth/token/', { username, password });
export const rotateToken = () => api.post('/auth/token/rotate/');
export const revokeToken = () => api.post('/auth/token/revoke/');

export const fetchStatus = () => api.get('/status/');
export const fetchExchangeState = () => api.get('/exchange/state/');
export const fetchExchangeIntegration = () => api.get('/exchange/integration/');
export const triggerExchangeSync = () => api.post('/exchange/sync/');
export const transferExchangeProfit = (amountUsd) => api.post('/exchange/transfer-profit/', amountUsd == null ? {} : { amount_usd: amountUsd });
export const fetchConviction = () => api.get('/conviction/');
export const fetchAnalysts = (symbol) => api.get('/analysts/', { params: { symbol } });
export const fetchPositions = (status) => api.get('/positions/', { params: { status } });
export const fetchTrades = () => api.get('/trades/');
export const fetchPerformance = () => api.get('/performance/');
export const fetchRisk = () => api.get('/risk/');
export const fetchConsensusHistory = (symbol, hours = 24) =>
    api.get('/consensus/history/', { params: { symbol, hours } });

export const fetchSystemStats    = ()        => api.get(`/system/stats/`);
export const fetchMTF            = (symbol)  => api.get(`/mtf/${symbol}/`);
export const fetchLatestScan     = (symbol) => api.get(`/scan/${symbol}/`);
export const fetchLatestAnalysis = (symbol) => api.get(`/analysis/${symbol}/`);

export const fetchPairs     = ()              => api.get('/pairs/');
export const addPair        = (symbol)        => api.post('/pairs/', { symbol });
export const removePair     = (symbol)        => api.delete(`/pairs/${symbol}/`);
export const togglePair     = (symbol)        => api.patch(`/pairs/${symbol}/`);

export const fetchSignals   = ()          => api.get('/signals/');
export const enterSignal   = (id, price) => api.post(`/signals/${id}/enter/`, { entry_price: price });
export const dismissSignal = (id)        => api.post(`/signals/${id}/dismiss/`);

export const openManualPosition = (params) => api.post('/positions/manual/', params);
export const fetchPositionLive  = (id)     => api.get(`/positions/${id}/live/`);
export const evaluatePosition   = (id)     => api.post(`/positions/${id}/evaluate/`);

export const runBacktest = (params) => api.post('/backtest/run/', params);
export const fetchBacktestStatus = (id) => api.get(`/backtest/${id}/`);
export const fetchBacktestList = () => api.get('/backtest/');

export default api;
