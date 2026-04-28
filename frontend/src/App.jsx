import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import ProtectedRoute from './components/ProtectedRoute';
import { AuthProvider } from './context/AuthContext';
import Dashboard from './pages/Dashboard';
import Positions from './pages/Positions';
import Journal from './pages/Journal';
import Analytics from './pages/Analytics';
import Risk from './pages/Risk';
import Backtest from './pages/Backtest';
import HowItWorks from './pages/HowItWorks';
import Login from './pages/Login';

function AppShell() {
    return (
        <div className="app-layout">
            <Sidebar />
            <main className="main-content">
                <Routes>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/positions" element={<Positions />} />
                    <Route path="/journal" element={<Journal />} />
                    <Route path="/analytics" element={<Analytics />} />
                    <Route path="/risk" element={<Risk />} />
                    <Route path="/backtest" element={<Backtest />} />
                    <Route path="/how-it-works" element={<HowItWorks />} />
                </Routes>
            </main>
        </div>
    );
}

export default function App() {
    return (
        <AuthProvider>
            <Router>
                <Routes>
                    <Route path="/login" element={<Login />} />
                    <Route element={<ProtectedRoute />}>
                        <Route path="/*" element={<AppShell />} />
                    </Route>
                </Routes>
            </Router>
        </AuthProvider>
    );
}
