import React, { useState } from 'react';
import { Activity, AlertCircle, KeyRound, ShieldCheck } from 'lucide-react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function Login() {
    const { login, isAuthenticated } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();
    const [form, setForm] = useState({ username: '', password: '' });
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState('');

    const destination = location.state?.from?.pathname || '/';

    if (isAuthenticated) {
        return <Navigate to={destination} replace />;
    }

    const handleChange = (event) => {
        const { name, value } = event.target;
        setForm((current) => ({ ...current, [name]: value }));
    };

    const handleSubmit = async (event) => {
        event.preventDefault();
        setIsSubmitting(true);
        setError('');

        try {
            await login(form.username, form.password);
            navigate(destination, { replace: true });
        } catch (err) {
            const nextError = err?.response?.data?.error === 'invalid_credentials'
                ? 'Nieprawidłowy login lub hasło.'
                : 'Nie udało się zalogować. Sprawdź połączenie z API.';
            setError(nextError);
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="auth-shell">
            <div className="auth-ambient auth-ambient-cyan" />
            <div className="auth-ambient auth-ambient-gold" />

            <div className="auth-layout">
                <section className="auth-brand-panel glass-panel">
                    <div className="auth-brand-badge">
                        <Activity className="w-5 h-5 text-[#00E5FF]" />
                        <span className="font-mono text-[11px] tracking-[0.28em] text-gray-400 uppercase">Secure Operator Console</span>
                    </div>

                    <div className="space-y-5">
                        <div>
                            <p className="text-sm font-mono uppercase tracking-[0.35em] text-gray-500 mb-3">Sentinel Access</p>
                            <h1 className="text-4xl md:text-5xl font-black tracking-[0.18em] text-white uppercase">
                                <span className="text-glow-cyan">SENTINEL</span>
                            </h1>
                            <p className="mt-4 max-w-xl text-sm md:text-base text-gray-400 leading-7">
                                Zaloguj się do konsoli tradingowej, żeby monitorować sygnały, pozycje, ryzyko i zsynchronizowany stan giełdy.
                            </p>
                        </div>

                        <div className="auth-feature-grid">
                            <div className="auth-feature-card">
                                <ShieldCheck className="w-5 h-5 text-[#D4AF37]" />
                                <div>
                                    <p className="text-sm font-semibold text-white">Protected API</p>
                                    <p className="text-xs text-gray-500 font-mono">Session + token access for dashboard workflows.</p>
                                </div>
                            </div>
                            <div className="auth-feature-card">
                                <KeyRound className="w-5 h-5 text-[#00E5FF]" />
                                <div>
                                    <p className="text-sm font-semibold text-white">Live Exchange Sync</p>
                                    <p className="text-xs text-gray-500 font-mono">Positions, orders and account state in one control plane.</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </section>

                <section className="auth-form-panel glass-panel">
                    <div className="space-y-2">
                        <p className="text-xs font-mono uppercase tracking-[0.35em] text-[#D4AF37]">Operator Login</p>
                        <h2 className="text-2xl font-black tracking-wider text-white">Access Node</h2>
                        <p className="text-sm text-gray-500">
                            Użyj danych operatora Django, aby wejść do panelu.
                        </p>
                    </div>

                    <form className="space-y-5" onSubmit={handleSubmit}>
                        <label className="auth-field">
                            <span className="auth-field-label">Username</span>
                            <input
                                name="username"
                                type="text"
                                autoComplete="username"
                                value={form.username}
                                onChange={handleChange}
                                className="auth-input"
                                placeholder="operator"
                                required
                            />
                        </label>

                        <label className="auth-field">
                            <span className="auth-field-label">Password</span>
                            <input
                                name="password"
                                type="password"
                                autoComplete="current-password"
                                value={form.password}
                                onChange={handleChange}
                                className="auth-input"
                                placeholder="••••••••"
                                required
                            />
                        </label>

                        {error && (
                            <div className="auth-error">
                                <AlertCircle className="w-4 h-4 shrink-0" />
                                <span>{error}</span>
                            </div>
                        )}

                        <button type="submit" className="btn-primary auth-submit" disabled={isSubmitting}>
                            {isSubmitting ? 'Authorizing...' : 'Enter Command Center'}
                        </button>
                    </form>
                </section>
            </div>
        </div>
    );
}
