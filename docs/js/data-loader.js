/**
 * IMPACT-NCATS Data Loader
 * Fetches JSON from Cloudflare R2 (production) or local data/ (dev).
 *
 * Detection: if the page is served from localhost/file://, uses local data/.
 * Otherwise uses R2_BASE_URL, which points at the ncats/ prefix in the
 * shared IMPACT bucket.
 */

const R2_BASE_URL = 'https://pub-4368cf00a45748488f64d2b648550d4d.r2.dev/ncats';

/**
 * Cache-busting token for DATA files.
 *
 * The JS and CSS carry ?v=N in index.html, but data URLs did not, and R2 serves
 * them with max-age=3600. A data refresh was therefore invisible to anyone with
 * a warm cache for up to an hour: the page loaded new code against a stale
 * themes.json and showed the previous run's theme labels.
 *
 * Bump this whenever exported data changes.
 */
const DATA_VERSION = '2026-08-28a';

class DataLoader {
    constructor() {
        const isLocal = location.hostname === 'localhost' ||
                        location.hostname === '127.0.0.1' ||
                        location.protocol === 'file:';
        this.baseUrl = isLocal ? 'data' : R2_BASE_URL;
        this.cache = {};
    }

    async loadIndex() {
        return this._fetch(`${this.baseUrl}/index.json`);
    }

    async loadPublications() {
        return this._fetch(`${this.baseUrl}/publications.json`);
    }

    async loadThemes() {
        return this._fetch(`${this.baseUrl}/themes.json`);
    }

    async loadSite(slug) {
        return this._fetch(`${this.baseUrl}/sites/${slug}.json`);
    }

    async loadInvestigator(profileId) {
        return this._fetch(`${this.baseUrl}/investigators/${profileId}.json`);
    }

    async _fetch(url) {
        if (this.cache[url]) return this.cache[url];
        const versioned = url + (url.includes('?') ? '&' : '?') + 'v=' + DATA_VERSION;
        const resp = await fetch(versioned);
        if (!resp.ok) throw new Error(`Failed to load ${url}: ${resp.status}`);
        const data = await resp.json();
        this.cache[url] = data;
        return data;
    }
}
