/* services/service_c/app/static/js/app.js */
/* Graph-RAG — Frontend API Client */

const API = {
    token: localStorage.getItem('graphrag_token'),
    user: JSON.parse(localStorage.getItem('graphrag_user') || 'null'),

    async request(method, url, body = null) {
        const headers = { 'Content-Type': 'application/json' };
        if (this.token) headers['Authorization'] = `Bearer ${this.token}`;
        const opts = { method, headers };
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(url, opts);
        if (res.status === 401) { this.logout(); return null; }
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: 'Error' }));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        return res.json();
    },

    async register(email, name, password) {
        const data = await this.request('POST', '/auth/register', { email, name, password });
        this.setSession(data);
        return data;
    },

    async login(email, password) {
        const data = await this.request('POST', '/auth/login', { email, password });
        this.setSession(data);
        return data;
    },

    setSession(data) {
        this.token = data.access_token;
        this.user = data.user;
        localStorage.setItem('graphrag_token', data.access_token);
        localStorage.setItem('graphrag_user', JSON.stringify(data.user));
    },

    logout() {
        this.token = null;
        this.user = null;
        localStorage.removeItem('graphrag_token');
        localStorage.removeItem('graphrag_user');
        window.location.href = '/';
    },

    isAuthenticated() { return !!this.token; },

    // Projects
    getProjects()        { return this.request('GET', '/projects/'); },
    getProject(id)       { return this.request('GET', `/projects/${id}`); },
    createProject(data)  { return this.request('POST', '/projects/', data); },
    updateProject(id, d) { return this.request('PUT', `/projects/${id}`, d); },
    deleteProject(id)    { return this.request('DELETE', `/projects/${id}`); },

    // Profile
    getProfile()         { return this.request('GET', '/auth/me'); },
    generateApiKey()     { return this.request('POST', '/auth/generate-api-key'); },
};

// ── UI Helpers ──

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

function showError(el, msg) {
    el.textContent = msg;
    el.style.display = 'block';
    setTimeout(() => el.style.display = 'none', 5000);
}

function showSuccess(el, msg) {
    el.textContent = msg;
    el.style.display = 'block';
    setTimeout(() => el.style.display = 'none', 3000);
}

function requireAuth() {
    if (!API.isAuthenticated()) {
        window.location.href = '/';
        return false;
    }
    return true;
}

function initials(name) {
    return name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
}
