const AUTH_STORAGE_KEY = 'sentinel.auth';
const AUTH_EVENT = 'sentinel:auth-changed';
const UNAUTHORIZED_EVENT = 'sentinel:unauthorized';

export function readAuth() {
    try {
        const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch {
        return null;
    }
}

export function writeAuth(auth) {
    if (!auth) {
        window.localStorage.removeItem(AUTH_STORAGE_KEY);
    } else {
        window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(auth));
    }
    window.dispatchEvent(new CustomEvent(AUTH_EVENT, { detail: auth || null }));
}

export function clearAuth() {
    writeAuth(null);
}

export function getAuthToken() {
    return readAuth()?.token || '';
}

export function getAuthUsername() {
    return readAuth()?.username || '';
}

export function getAuthEventName() {
    return AUTH_EVENT;
}

export function getUnauthorizedEventName() {
    return UNAUTHORIZED_EVENT;
}

export function notifyUnauthorized() {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
}
