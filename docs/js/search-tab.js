/**
 * Full-text search over linked publications.
 *
 * There is no backend, so search runs in the browser against a sharded inverted
 * index. Postings live in one file per two-character term prefix, so a query
 * fetches only the shards for the words typed - a few kilobytes - rather than
 * the whole index. Shards and the document store are cached for the session.
 *
 * Two posting sets per term: `meta` (title, MeSH, author keywords) and `abst`
 * (abstract text). A hit in the title or MeSH scores higher than a passing
 * mention in an abstract. Abstracts matter: for queries like "pragmatic trial"
 * they more than double the number of papers found.
 */

class SearchTab {
    constructor(app) {
        this.app = app;
        this.manifest = null;
        this.docs = null;
        this.shardCache = { meta: {}, abst: {} };
        this.results = [];
    }

    async setup() {
        const base = this.app.loader.baseUrl;
        this.base = `${base}/search`;
        try {
            this.manifest = await this.app.loader._fetch(`${this.base}/manifest.json`);
        } catch (e) {
            document.getElementById('se-controls').innerHTML =
                '<p class="data-note">Search index not available. Run build_search_index.py.</p>';
            console.error('search manifest', e);
            return;
        }

        document.getElementById('se-controls').innerHTML = `
            <div class="controls-row">
                <input type="text" id="se-q" placeholder="Search titles, abstracts, MeSH terms, keywords — or paste PMIDs"
                       autocomplete="off" spellcheck="false">
                <button class="download-btn" id="se-go">Search</button>
            </div>
            <div class="controls-row">
                <label>Fields:
                    <select id="se-fields">
                        <option value="all" selected>Title, MeSH, keywords + abstract</option>
                        <option value="meta">Title, MeSH and keywords only</option>
                    </select>
                </label>
                <label>Site:
                    <select id="se-site">
                        <option value="">All sites</option>
                        ${this.app.index.sites.map(s =>
                            `<option value="${s.slug}">${s.hub_name}</option>`).join('')}
                    </select>
                </label>
                <label>Sort:
                    <select id="se-sort">
                        <option value="relevance" selected>Relevance</option>
                        <option value="cites">Citations</option>
                        <option value="rcr">RCR</option>
                        <option value="year">Newest</option>
                    </select>
                </label>
                <label>From: <select id="se-from"></select></label>
                <label>To: <select id="se-to"></select></label>
                <label><input type="checkbox" id="se-clinical"> Clinical articles only</label>
            </div>
            <p class="data-note" id="se-status">
                ${(+this.manifest.n_docs).toLocaleString()} publications indexed
                (${(+this.manifest.abst_terms).toLocaleString()} abstract terms,
                ${(+this.manifest.meta_terms).toLocaleString()} title/MeSH/keyword terms).
                The index loads on your first search.
            </p>`;

        const years = this.app.allYears;
        const opts = (sel) => years.map(y =>
            `<option value="${y}"${y === sel ? ' selected' : ''}>${y}</option>`).join('');
        document.getElementById('se-from').innerHTML = opts(years[0]);
        document.getElementById('se-to').innerHTML = opts(years[years.length - 1]);

        const run = () => this.search();
        const box = document.getElementById('se-q');
        document.getElementById('se-go').addEventListener('click', run);
        box.addEventListener('keydown', e => {
            if (e.key === 'Enter') run();
        });
        // A single-line input silently strips newlines, so a column of PMIDs
        // pasted from a spreadsheet would arrive as one long concatenated
        // number. Normalise whitespace as it is pasted instead.
        box.addEventListener('paste', e => {
            const text = (e.clipboardData || window.clipboardData).getData('text');
            if (!/[\r\n\t]/.test(text)) return;
            e.preventDefault();
            const cleaned = text.replace(/\s+/g, ' ').trim();
            const start = box.selectionStart, end = box.selectionEnd;
            box.value = box.value.slice(0, start) + cleaned + box.value.slice(end);
            box.selectionStart = box.selectionEnd = start + cleaned.length;
        });
        // Filters only re-rank what is already found, so they are cheap to apply.
        ['se-site', 'se-sort', 'se-from', 'se-to', 'se-clinical'].forEach(id =>
            document.getElementById(id).addEventListener('input', () => this.render()));
        document.getElementById('se-fields').addEventListener('input', run);

        this.app._attachDownloadBar('se-downloads',
            null,   // a table, not a chart: only CSV applies
            () => this.csvRows(),
            () => 'ncats-search-results');
    }

    /** The document store is large, so it is fetched only when first needed. */
    async ensureDocs() {
        if (this.docs) return;
        const status = document.getElementById('se-status');
        status.textContent = 'Loading index…';
        this.docs = await this.app.loader._fetch(`${this.base}/docs.json`);
        // Lookup table for PMID queries; built once, reused for every search.
        this.pmidIndex = new Map();
        this.docs.pmid.forEach((p, i) => this.pmidIndex.set(p, i));
        status.textContent = '';
    }

    async fetchShard(kind, prefix) {
        const cache = this.shardCache[kind];
        if (prefix in cache) return cache[prefix];
        const list = kind === 'meta' ? this.manifest.meta_shards : this.manifest.abst_shards;
        if (!list.includes(prefix)) { cache[prefix] = {}; return cache[prefix]; }
        try {
            cache[prefix] = await this.app.loader._fetch(`${this.base}/${kind}/${prefix}.json`);
        } catch (e) {
            cache[prefix] = {};
        }
        return cache[prefix];
    }

    /** Undo the delta+hex encoding used to keep postings small. */
    decode(str) {
        if (!str) return [];
        const out = [];
        let prev = 0;
        for (const part of str.split(',')) {
            prev += parseInt(part, 16);
            out.push(prev);
        }
        return out;
    }

    /**
     * PMIDs found in the query, if it is a PMID lookup rather than a text search.
     *
     * Returns null when the query contains any word characters beyond PMID
     * scaffolding, so "covid 2020" stays a text search rather than hunting for a
     * paper numbered 2020. PMIDs are 1-8 digits; anything longer is not one.
     */
    parsePmids(q) {
        const cleaned = (q || '').replace(/\bpmids?\b|[:,;]/gi, ' ').trim();
        if (!cleaned) return null;
        const parts = cleaned.split(/\s+/);
        const ids = [];
        for (const part of parts) {
            if (!/^\d{1,8}$/.test(part)) return null;   // any non-numeric token -> text search
            ids.push(parseInt(part, 10));
        }
        return ids.length ? [...new Set(ids)] : null;
    }

    tokenize(q) {
        const stop = new Set(this.manifest.stopwords || []);
        return [...new Set((q || '').toLowerCase().match(/[a-z][a-z0-9]{2,}/g) || [])]
            .filter(t => !stop.has(t));
    }

    async search() {
        const q = document.getElementById('se-q').value.trim();
        const status = document.getElementById('se-status');
        if (!q) { status.textContent = 'Type something to search for.'; return; }

        const pmids = this.parsePmids(q);
        if (pmids) {
            status.textContent = 'Looking up…';
            await this.ensureDocs();
            const found = [], missing = [];
            for (const p of pmids) {
                const id = this.pmidIndex.get(p);
                if (id === undefined) missing.push(p);
                // Score descends with input order so a pasted list keeps its order.
                else found.push({ id, score: pmids.length - found.length });
            }
            this.results = found;
            this.query = { pmidLookup: true, requested: pmids.length,
                           missing, terms: [], partial: false };
            this.render();
            return;
        }

        const terms = this.tokenize(q);
        if (!terms.length) {
            status.textContent = 'That query is all stop-words — try a more specific term.';
            return;
        }

        status.textContent = 'Searching…';
        await this.ensureDocs();

        const useAbstract = document.getElementById('se-fields').value === 'all';
        const w = this.manifest.weights || { meta: 3, abst: 1 };
        const n = this.manifest.n_docs;

        // score[doc] accumulates weighted idf; hits[doc] counts distinct query
        // terms matched, so an AND-style requirement can be applied after.
        const score = new Map();
        const hits = new Map();
        const missing = [];

        for (const term of terms) {
            const prefix = term.slice(0, this.manifest.shard_chars);
            const [metaShard, abstShard] = await Promise.all([
                this.fetchShard('meta', prefix),
                useAbstract ? this.fetchShard('abst', prefix) : Promise.resolve({}),
            ]);
            const metaIds = this.decode(metaShard[term]);
            const abstIds = useAbstract ? this.decode(abstShard[term]) : [];
            const df = new Set([...metaIds, ...abstIds]).size;
            if (!df) { missing.push(term); continue; }

            const idf = Math.log(1 + n / df);
            const seen = new Set();
            for (const id of metaIds) {
                score.set(id, (score.get(id) || 0) + idf * w.meta);
                seen.add(id);
            }
            for (const id of abstIds) {
                score.set(id, (score.get(id) || 0) + idf * w.abst);
                seen.add(id);
            }
            for (const id of seen) hits.set(id, (hits.get(id) || 0) + 1);
        }

        const wanted = terms.length - missing.length;
        // Require every findable term, which is what people expect from a search
        // box; fall back to partial matches only if that returns nothing.
        let ids = [...hits.entries()].filter(([, c]) => c === wanted).map(([id]) => id);
        let partial = false;
        if (!ids.length && wanted > 1) {
            ids = [...hits.keys()];
            partial = true;
        }

        this.results = ids.map(id => ({ id, score: score.get(id) || 0 }));
        this.query = { terms, missing, partial, wanted };
        this.render();
    }

    _filtered() {
        const d = this.docs;
        const slug = document.getElementById('se-site').value;
        const siteIdx = slug ? d.slugs.indexOf(slug) : -1;
        const from = +document.getElementById('se-from').value;
        const to = +document.getElementById('se-to').value;
        const [lo, hi] = from <= to ? [from, to] : [to, from];
        const clinicalOnly = document.getElementById('se-clinical').checked;

        let rows = this.results.filter(r => {
            const y = d.year[r.id];
            if (y != null && (y < lo || y > hi)) return false;
            if (clinicalOnly && !d.clinical[r.id]) return false;
            if (siteIdx >= 0 && !(d.sites[r.id] || []).includes(siteIdx)) return false;
            return true;
        });

        const sort = document.getElementById('se-sort').value;
        const key = { cites: 'cites', rcr: 'rcr', year: 'year' }[sort];
        rows.sort((a, b) => key
            ? ((d[key][b.id] ?? -Infinity) - (d[key][a.id] ?? -Infinity))
            : b.score - a.score);
        return rows;
    }

    render() {
        if (!this.docs || !this.query) return;
        const d = this.docs;
        const rows = this._filtered();
        this.shown = rows.slice(0, 200);

        const q = this.query;
        if (q.pmidLookup) {
            const parts = [`${rows.length.toLocaleString()} of ${q.requested.toLocaleString()} PMID${q.requested === 1 ? '' : 's'} found`];
            if (q.missing.length) {
                const shown = q.missing.slice(0, 8).join(', ');
                parts.push(`<strong>Not in this corpus:</strong> ${shown}` +
                    (q.missing.length > 8 ? ` and ${q.missing.length - 8} more` : '') +
                    ' — either not linked to an NCATS award, or not indexed in IMPACT.');
            }
            if (rows.length !== this.results.length) {
                parts.push(`${this.results.length - rows.length} hidden by the filters above.`);
            }
            document.getElementById('se-status').innerHTML = parts.join(' ');
            this.renderTable();
            return;
        }
        const notes = [];
        if (q.missing.length) {
            notes.push(`No matches for ${q.missing.map(t => `“${t}”`).join(', ')}.`);
        }
        if (q.partial) {
            notes.push('<strong>No paper contained every term, so these match at least one.</strong>');
        }
        document.getElementById('se-status').innerHTML =
            `${rows.length.toLocaleString()} matching publications` +
            (rows.length > 200 ? ', showing the first 200' : '') +
            (notes.length ? ` — ${notes.join(' ')}` : '');

        this.renderTable();
    }

    renderTable() {
        const d = this.docs;
        const tri = this.manifest.tri_labels || [];
        document.getElementById('se-results').innerHTML = `
            <div class="table-scroll tall">
            <table class="data-table compact">
                <thead><tr><th>#</th><th>PMID</th><th>Title</th><th>Journal</th><th>Year</th>
                    <th>Citations</th><th>RCR</th><th>Translational</th><th>Site(s)</th></tr></thead>
                <tbody>${this.shown.map((r, i) => {
                    const id = r.id;
                    const sites = (d.sites[id] || []).map(s => d.slugs[s]);
                    const names = sites.map(slug => {
                        const s = this.app.index.sites.find(x => x.slug === slug);
                        return s ? s.hub_name : slug;
                    });
                    const t = d.tri[id];
                    return `<tr>
                        <td>${i + 1}</td>
                        <td class="mono">${d.pmid[id]}</td>
                        <td><a href="https://pubmed.ncbi.nlm.nih.gov/${d.pmid[id]}/"
                               target="_blank" rel="noopener">${d.title[id] || '(untitled)'}</a></td>
                        <td>${d.journals[d.journal[id]] || '—'}</td>
                        <td>${d.year[id] ?? '—'}</td>
                        <td>${(d.cites[id] || 0).toLocaleString()}</td>
                        <td>${d.rcr[id] == null ? '—' : d.rcr[id].toFixed(2)}</td>
                        <td>${t == null ? '—' : (tri[t] || '').replace('_', '/')}</td>
                        <td>${names.length ? names.join(', ') : '—'}</td>
                    </tr>`;
                }).join('')}</tbody>
            </table></div>`;
    }

    csvRows() {
        if (!this.docs || !this.shown) return [['no results']];
        const d = this.docs;
        const tri = this.manifest.tri_labels || [];
        return [['pmid', 'title', 'journal', 'year', 'citations', 'rcr', 'apt',
                 'clinical', 'translational_class', 'sites'],
                ...this._filtered().map(r => {
                    const id = r.id;
                    return [d.pmid[id], d.title[id], d.journals[d.journal[id]],
                            d.year[id], d.cites[id], d.rcr[id] ?? '', d.apt[id] ?? '',
                            d.clinical[id] ? 'yes' : 'no',
                            d.tri[id] == null ? '' : tri[d.tri[id]],
                            (d.sites[id] || []).map(s => d.slugs[s]).join('; ')];
                })];
    }
}
