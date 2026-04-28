import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { clearAuth, getAuthEventName, getUnauthorizedEventName, readAuth, writeAuth } from '../auth';
import { loginWithToken, revokeToken } from '../api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
    const [auth, setAuth] = useState(() => readAuth());

    useEffect(() => {
        const handleAuthChange = (event) => setAuth(event.detail || null);
        const handleUnauthorized = () => {
            clearAuth();
            setAuth(null);
        };

        window.addEventListener(getAuthEventName(), handleAuthChange);
        window.addEventListener(getUnauthorizedEventName(), handleUnauthorized);
        return () => {
            window.removeEventListener(getAuthEventName(), handleAuthChange);
            window.removeEventListener(getUnauthorizedEventName(), handleUnauthorized);
        };
    }, []);

    const value = useMemo(() => ({
        auth,
        isAuthenticated: Boolean(auth?.token),
        async login(username, password) {
            const response = await loginWithToken(username, password);
            const nextAuth = {
                token: response.data.token,
                username: response.data.username || username,
            };
            writeAuth(nextAuth);
            setAuth(nextAuth);
            return nextAuth;
        },
        async logout() {
            try {
                await revokeToken();
            } catch {
                // Local logout should still succeed if the API token is already invalid.
            } finally {
                clearAuth();
                setAuth(null);
            }
        },
    }), [auth]);

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used inside AuthProvider');
    }
    return context;
}
