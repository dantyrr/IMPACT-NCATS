/**
 * Collaboration tab: a US map of CTSA hubs, the links between them, and
 * optionally the partner and other non-hub institutions they publish with.
 *
 * collaboration.json holds one record per paper (year, the hubs of its core
 * authors, partner-only authors and cited CTSA awards, and the hub whose grants
 * are its only NCATS link). The network is recomputed in the browser for
 * whatever the controls describe, so hiding a hub or leaving out consortium
 * papers changes every number consistently: the map, the panel and the table.
 *
 * Nearly every pair of hubs shares some papers, and large hubs share many with
 * everyone, so raw counts mostly measure hub size. The default link measure is
 * therefore relative: shared papers over the number expected from how much
 * each hub collaborates overall (association strength; 1 = as expected).
 *
 * collaboration_institutions.json (partner and non-hub institutions with map
 * points) is loaded only when one of those layers is switched on.
 * Kept in its own file rather than added to app.js, which is already large.
 */

const COLLAB_COLORS = { hub: '#2e86c1', partner: '#D55E00', other: '#009E73' };
const COLLAB_SELECT = '#0e2f44';     // ring on the selected hub
const COLLAB_RAMP = d3.interpolateRgb('#a9cce3', '#0e2f44');   // weak -> strong links
const COLLAB_OUTLIERS = ['Yale University', 'Baylor College of Medicine'];
const MIN_SHARED_FOR_RELATIVE = 10;  // fewer shared papers makes the ratio noise
const RELATIVE_MAX = 8;              // links at 8x expected or more are drawn at full strength
const NETWORKS = {
    core:  { label: 'Co-authorship (hub institutions)', coauthor: true },
    broad: { label: 'Co-authorship incl. partner hospitals', coauthor: true },
    fund:  { label: 'Co-funding (shared CTSA award citations)', coauthor: false },
};
const INST_TYPES = ['university', 'hospital', 'government', 'industry', 'other'];

function escHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

const fmt1 = v => v.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const fmtX = v => `×${v >= 10 ? Math.round(v) : v.toFixed(1)}`;

class CollabTab {
    constructor(app) {
        this.app = app;
        this.loading = null;
        this.selected = null;          // hub index
        this.hidden = new Set();       // hub indices
        this.state = null;
        this.inst = null;              // institution layer data, once loaded
        window.addEventListener('resize', () => {
            clearTimeout(this._resizeTimer);
            this._resizeTimer = setTimeout(() => this._isVisible() && this.render(), 150);
        });
    }

    /** Called whenever the tab is shown. Loads data the first time. */
    show() {
        if (!this.loading) this.loading = this._load();
        else if (this.data) this.render();
        return this.loading;
    }

    _isVisible() {
        return document.getElementById('collaboration')?.classList.contains('active');
    }

    async _load() {
        const status = document.getElementById('co-status');
        status.textContent = 'Loading collaboration data…';
        try {
            const [data, geo] = await Promise.all([
                this.app.loader.loadCollaboration(), this.app.loader.loadStates()]);
            this.data = data;
            this.geo = geo;
            this._prepare();
            this._renderControls();
            status.textContent = '';
            this.render();
        } catch (e) {
            status.textContent = 'Collaboration data is not available yet. ' +
                'Run scripts/export_collaboration_json.py.';
            console.error('Failed to load collaboration data', e);
        }
    }

    async _loadInstitutions() {
        if (this.inst || this._instLoading) return this._instLoading;
        const note = document.getElementById('co-inst-note');
        note.textContent = 'Loading institutions…';
        this._instLoading = this.app.loader.loadCollaborationInstitutions().then(d => {
            if (d.build !== this.data.build) {
                console.warn('collaboration_institutions.json is from a different export', d.build, this.data.build);
            }
            this.inst = d;
            note.textContent = '';
        }).catch(e => {
            note.textContent = 'Institution data is not available.';
            console.error('Failed to load collaboration_institutions.json', e);
        });
        return this._instLoading;
    }

    _prepare() {
        const P = this.data.papers;
        this.hubs = this.data.hubs;
        this.n = this.hubs.length;
        // Hub sets per paper for each network. Broad = core plus partner-only.
        this.sets = {
            core: P.c,
            broad: P.c.map((c, i) => P.p[i].length ? c.concat(P.p[i]) : c),
            fund: P.f,
        };
        this.years = [];
        // Not Math.max(...P.y): spreading ~140k arguments overflows the call stack.
        const maxYear = P.y.reduce((m, y) => (y > m ? y : m), this.data.from_year);
        for (let y = this.data.from_year; y <= maxYear; y++) this.years.push(y);
        this.state = {
            network: 'core', counting: 'fractional', measure: 'relative',
            from: this.data.coauthor_reliable_from, to: maxYear,
            noConsortium: true, dropSole: true, topN: 60, partnersShown: 10,
            showPartner: false, showOther: false, instType: 'all', instMin: 5, instTop: 250,
        };
    }

    // ---------------------------------------------------------------- controls

    _renderControls() {
        const st = this.state;
        const opts = (pairs, sel) => pairs.map(([v, l]) =>
            `<option value="${v}"${String(v) === String(sel) ? ' selected' : ''}>${escHtml(l)}</option>`).join('');
        const years = this.years.map(y => [y, y]);
        document.getElementById('co-controls').innerHTML = `
            <div class="controls-row">
                <label>Network: <select id="co-network">${opts(Object.entries(NETWORKS).map(([k, v]) => [k, v.label]), st.network)}</select></label>
                <label>From: <select id="co-from">${opts(years, st.from)}</select></label>
                <label>To: <select id="co-to">${opts(years, st.to)}</select></label>
            </div>
            <div class="controls-row">
                <label>Link strength: <select id="co-measure">${opts([
                    ['relative', 'Relative to expected'], ['papers', 'Shared papers']], st.measure)}</select></label>
                <label>Count: <select id="co-counting">${opts([
                    ['fractional', 'Fractional (each paper counts once)'], ['full', 'Full (1 per shared paper)']], st.counting)}</select></label>
                <label>Links shown: <select id="co-topn">${opts([[30, 'Top 30'], [60, 'Top 60'], [120, 'Top 120'], [250, 'Top 250'], [0, 'All']], st.topN)}</select></label>
                <label>Selected hub's partners: <select id="co-partners">${opts([[5, 'Top 5'], [10, 'Top 10'], [20, 'Top 20'], [0, 'All']], st.partnersShown)}</select></label>
            </div>
            <div class="controls-row">
                <label class="co-check"><input type="checkbox" id="co-noconsortium"${st.noConsortium ? ' checked' : ''}>
                    Leave out papers naming ${this.data.consortium_hubs}+ hubs</label>
                <label>Hide a hub: <select id="co-hide">
                    <option value="">Choose…</option>${opts(this.hubs.map((h, i) => [i, h.label]))}
                </select></label>
                <span class="co-quick">Common outliers:
                    ${COLLAB_OUTLIERS.map(l => `<button class="co-link-btn" data-outlier="${escHtml(l)}">${escHtml(l)}</button>`).join(' · ')}
                </span>
            </div>
            <div class="controls-row" id="co-hidden-row" style="display:none;">
                <span>Hidden:</span><span id="co-hidden-chips" class="picker-chips"></span>
                <label class="co-check"><input type="checkbox" id="co-dropsole"${st.dropSole ? ' checked' : ''}>
                    Also drop papers that are in the data only through a hidden hub's grants</label>
            </div>
            <div class="controls-row co-layers">
                <span class="co-layers-title">Also show:</span>
                <label class="co-check"><input type="checkbox" id="co-show-partner">
                    <span class="co-swatch" style="background:${COLLAB_COLORS.partner}"></span> Partner institutions</label>
                <label class="co-check"><input type="checkbox" id="co-show-other">
                    <span class="co-swatch" style="background:${COLLAB_COLORS.other}"></span> Other non-hub institutions</label>
                <span id="co-other-filters" style="display:none;">
                    <label>Type: <select id="co-inst-type">${opts([['all', 'All types'], ...INST_TYPES.map(t => [t, t[0].toUpperCase() + t.slice(1)])], st.instType)}</select></label>
                    <label>At least <select id="co-inst-min">${opts([[3, '3'], [5, '5'], [10, '10'], [25, '25'], [50, '50']], st.instMin)}</select> papers</label>
                    <label>Show <select id="co-inst-top">${opts([[100, 'top 100'], [250, 'top 250'], [500, 'top 500'], [0, 'all']], st.instTop)}</select></label>
                </span>
                <span class="data-note" id="co-inst-note"></span>
            </div>
            <p class="data-note co-warning" id="co-warning"></p>`;

        const on = (id, ev, fn) => document.getElementById(id).addEventListener(ev, fn);
        const set = (key, conv = v => v) => e => { st[key] = conv(e.target.value); this.render(); };
        on('co-network', 'change', e => {
            st.network = e.target.value;
            // Co-funding needs no affiliations, so it can start in the first year.
            if (!NETWORKS[st.network].coauthor && st.from === this.data.coauthor_reliable_from) {
                st.from = this.data.from_year;
                document.getElementById('co-from').value = st.from;
            }
            this.render();
        });
        on('co-measure', 'change', set('measure'));
        on('co-counting', 'change', set('counting'));
        on('co-from', 'change', set('from', Number));
        on('co-to', 'change', set('to', Number));
        on('co-topn', 'change', set('topN', Number));
        on('co-partners', 'change', set('partnersShown', Number));
        on('co-inst-type', 'change', set('instType'));
        on('co-inst-min', 'change', set('instMin', Number));
        on('co-inst-top', 'change', set('instTop', Number));
        on('co-noconsortium', 'change', e => { st.noConsortium = e.target.checked; this.render(); });
        on('co-dropsole', 'change', e => { st.dropSole = e.target.checked; this.render(); });
        const layer = key => async e => {
            st[key] = e.target.checked;
            document.getElementById('co-other-filters').style.display = st.showOther ? '' : 'none';
            if (e.target.checked) await this._loadInstitutions();
            this.render();
        };
        on('co-show-partner', 'change', layer('showPartner'));
        on('co-show-other', 'change', layer('showOther'));
        on('co-hide', 'change', e => {
            if (e.target.value !== '') this.hideHub(+e.target.value);
            e.target.value = '';
        });
        document.querySelectorAll('[data-outlier]').forEach(btn => btn.addEventListener('click', () => {
            const i = this.hubs.findIndex(h => h.label === btn.dataset.outlier);
            if (i >= 0) this.hideHub(i);
        }));
    }

    hideHub(i) {
        this.hidden.add(i);
        if (this.selected === i) this.selected = null;
        this.render();
    }

    _renderHiddenChips() {
        const row = document.getElementById('co-hidden-row');
        row.style.display = this.hidden.size ? '' : 'none';
        const chips = document.getElementById('co-hidden-chips');
        chips.innerHTML = [...this.hidden].map(i =>
            `<span class="picker-chip" style="background:var(--text-light)">${escHtml(this.hubs[i].label)}
                <button class="chip-remove" data-hub="${i}" aria-label="Show ${escHtml(this.hubs[i].label)} again">×</button></span>`).join('');
        chips.querySelectorAll('.chip-remove').forEach(b => b.addEventListener('click', () => {
            this.hidden.delete(+b.dataset.hub);
            this.render();
        }));
    }

    // ---------------------------------------------------------------- compute

    /** The hubs a paper counts for under the current controls, or null to skip it. */
    _paperHubs(i) {
        const st = this.state, P = this.data.papers;
        const y = P.y[i];
        if (y < st.from || y > st.to) return null;
        const raw = this.sets[st.network][i];
        if (!raw.length) return null;
        if (st.noConsortium && raw.length >= this.data.consortium_hubs) return null;
        if (st.dropSole && P.s[i] >= 0 && this.hidden.has(P.s[i])) return null;
        const hs = this.hidden.size ? raw.filter(h => !this.hidden.has(h)) : raw;
        return hs.length ? hs : null;
    }

    /** The hub network for the current controls. */
    compute() {
        const st = this.state, n = this.n, N = this.data.papers.y.length;
        const W = new Float64Array(n * n), F = new Uint32Array(n * n);
        const papers = new Uint32Array(n), cross = new Uint32Array(n);
        let nPapers = 0, nMulti = 0;
        for (let i = 0; i < N; i++) {
            const hs = this._paperHubs(i);
            if (!hs) continue;
            const k = hs.length;
            nPapers++;
            for (const h of hs) papers[h]++;
            if (k < 2) continue;
            nMulti++;
            const w = st.counting === 'fractional' ? 1 / (k - 1) : 1;
            for (let a = 0; a < k; a++) {
                cross[hs[a]]++;
                for (let b = a + 1; b < k; b++) {
                    const lo = Math.min(hs[a], hs[b]), hi = Math.max(hs[a], hs[b]);
                    W[lo * n + hi] += w;
                    F[lo * n + hi]++;
                }
            }
        }
        const links = [];
        const strength = new Float64Array(n);
        let total = 0;
        for (let a = 0; a < n; a++) for (let b = a + 1; b < n; b++) {
            const f = F[a * n + b];
            if (!f) continue;
            const w = W[a * n + b];
            links.push({ a, b, w, f });
            strength[a] += w;
            strength[b] += w;
            total += w;
        }
        // Association strength: observed over expected, where expected is what the
        // pair would share if each hub spread its links in proportion to the others'.
        for (const l of links) {
            l.rel = total ? (l.w * 2 * total) / (strength[l.a] * strength[l.b]) : 0;
        }
        const relative = st.measure === 'relative';
        const value = l => (relative ? l.rel : l.w);
        const ranked = links.filter(l => !relative || l.f >= MIN_SHARED_FOR_RELATIVE)
            .sort((x, y) => value(y) - value(x));
        return { papers, cross, strength, links, ranked, value, nPapers, nMulti };
    }

    /** Papers per institution under the current controls (and with the selected hub). */
    computeInstitutions() {
        if (!this.inst) return null;
        const m = this.inst.institutions.length, sel = this.selected;
        const count = new Uint32Array(m), withSel = new Uint32Array(m);
        const { rows, inst } = this.inst;
        for (let r = 0; r < rows.length; r++) {
            const hs = this._paperHubs(rows[r]);
            if (!hs) continue;
            const has = sel != null && hs.includes(sel);
            for (const id of inst[r]) {
                count[id]++;
                if (has) withSel[id]++;
            }
        }
        return { count, withSel };
    }

    // ---------------------------------------------------------------- render

    render() {
        if (!this.data) return;
        this._renderHiddenChips();
        const st = this.state;
        const warn = document.getElementById('co-warning');
        warn.textContent = NETWORKS[st.network].coauthor && st.from < this.data.coauthor_reliable_from
            ? `Before ${this.data.coauthor_reliable_from}, PubMed recorded only the first author's ` +
              'affiliation, so co-authorship links in earlier years are undercounted.'
            : '';
        this.net = this.compute();
        this.instNet = (st.showPartner || st.showOther) ? this.computeInstitutions() : null;
        const { nPapers, nMulti, links } = this.net;
        const pairs = this.n - this.hidden.size;
        document.getElementById('co-summary').textContent =
            `${nPapers.toLocaleString()} papers with a hub · ` +
            `${nMulti.toLocaleString()} with 2 or more hubs ` +
            `(${nPapers ? (100 * nMulti / nPapers).toFixed(1) : 0}%) · ` +
            `${links.length.toLocaleString()} of ${(pairs * (pairs - 1) / 2).toLocaleString()} hub pairs share a paper`;
        this._drawMap();
        this._renderPanel();
        this._renderPairs();
        this._renderDownloads();
    }

    /** 0..1 strength of a link for width and color. With a hub selected, the
     *  scale runs up to that hub's strongest tie, so its partners' ranking reads
     *  at a glance even when all its ties are modest. */
    _linkT(l) {
        const top = this._linkTop;
        if (this.state.measure === 'relative') {
            return Math.max(0, Math.min(1, Math.log(Math.max(l.rel, 1)) / Math.log(Math.max(top, 1.05))));
        }
        return Math.min(1, l.w / top);
    }

    _positions(projection) {
        // Hubs in the same city share a Gazetteer point; spread them on a small
        // circle so each stays visible and clickable.
        const pts = this.hubs.map(h => (h.lat == null ? null : projection([h.lon, h.lat])));
        const groups = new Map();
        pts.forEach((p, i) => {
            if (!p || this.hidden.has(i)) return;
            const key = `${Math.round(p[0] / 8)},${Math.round(p[1] / 8)}`;
            if (!groups.has(key)) groups.set(key, []);
            groups.get(key).push(i);
        });
        const out = pts.map(p => (p ? [...p] : null));
        for (const members of groups.values()) {
            if (members.length < 2) continue;
            const [cx, cy] = members.reduce(([x, y], i) => [x + pts[i][0], y + pts[i][1]], [0, 0])
                .map(v => v / members.length);
            const r = 6 + 2.5 * members.length;
            members.forEach((i, j) => {
                const t = -Math.PI / 2 + 2 * Math.PI * j / members.length;
                out[i] = [cx + r * Math.cos(t), cy + r * Math.sin(t)];
            });
        }
        return out;
    }

    /** Institutions to draw, with their projected positions and sizes. */
    _institutionMarks(projection) {
        if (!this.instNet) return [];
        const st = this.state, sel = this.selected;
        const { count, withSel } = this.instNet;
        const val = sel == null ? count : withSel;
        const list = this.inst.institutions;
        const pick = kind => list.map((d, id) => id).filter(id => {
            const d = list[id];
            if (d.kind !== kind || !val[id]) return false;
            if (kind === 'other') return (st.instType === 'all' || d.type === st.instType) && val[id] >= st.instMin;
            return true;
        }).sort((a, b) => val[b] - val[a]);
        let ids = [];
        if (st.showPartner) ids = ids.concat(pick('partner'));
        if (st.showOther) {
            const others = pick('other');
            ids = ids.concat(st.instTop ? others.slice(0, st.instTop) : others);
        }
        // Spread institutions that share a city center on a sunflower spiral.
        const byPoint = new Map();
        const marks = [];
        for (const id of ids) {
            const d = list[id];
            const p = projection([d.lon, d.lat]);
            if (!p) continue;
            const key = `${d.lat},${d.lon}`;
            const j = byPoint.get(key) || 0;
            byPoint.set(key, j + 1);
            const r = 3.2 * Math.sqrt(j), t = j * 2.39996;
            marks.push({ id, d, v: val[id], x: p[0] + r * Math.cos(t), y: p[1] + r * Math.sin(t) });
        }
        const maxV = Math.max(1, ...marks.map(m => m.v));
        for (const m of marks) m.r = 1.8 + 6 * Math.sqrt(m.v / maxV);
        // Big first so small dots draw on top and stay hoverable.
        return marks.sort((a, b) => b.r - a.r);
    }

    _drawMap() {
        const wrap = document.getElementById('co-map-wrap');
        const width = Math.max(320, wrap.clientWidth - 16);
        const height = Math.round(width * 0.6);
        const svg = d3.select('#co-map').attr('viewBox', `0 0 ${width} ${height}`)
            .attr('width', width).attr('height', height);
        svg.selectAll('*').remove();
        const root = svg.append('g');

        const projection = d3.geoAlbersUsa().fitSize([width, height], this.geo);
        const path = d3.geoPath(projection);
        root.append('g').attr('class', 'co-states').selectAll('path')
            .data(this.geo.features).join('path').attr('d', path);

        const pos = this._positions(projection);
        this.pos = pos;
        const { papers, ranked } = this.net;
        const sel = this.selected;
        const drawable = l => pos[l.a] && pos[l.b];
        let shown;
        if (sel == null) {
            shown = (this.state.topN ? ranked.slice(0, this.state.topN) : ranked).filter(drawable);
        } else {
            const mine = ranked.filter(l => (l.a === sel || l.b === sel) && drawable(l));
            shown = this.state.partnersShown ? mine.slice(0, this.state.partnersShown) : mine;
        }
        this.shownLinks = shown;
        const relative = this.state.measure === 'relative';
        this._linkTop = sel == null
            ? (relative ? RELATIVE_MAX : (ranked[0]?.w || 1))
            : (shown.length ? (relative ? shown[0].rel : shown[0].w) : 1);
        const partners = new Set(shown.map(l => (l.a === sel ? l.b : l.a)));

        // Link strokes keep their screen width when zoomed (vector-effect in CSS).
        const gl = root.append('g').attr('class', 'co-links');
        gl.selectAll(null).data([...shown].reverse()).join('line')
            .attr('x1', l => pos[l.a][0]).attr('y1', l => pos[l.a][1])
            .attr('x2', l => pos[l.b][0]).attr('y2', l => pos[l.b][1])
            .attr('stroke', l => COLLAB_RAMP(this._linkT(l))).attr('stroke-linecap', 'round')
            .attr('stroke-width', l => 0.8 + 6.2 * this._linkT(l))
            .attr('stroke-opacity', l => 0.35 + 0.6 * this._linkT(l));
        // Wide transparent strokes so a thin link is still easy to hover.
        gl.selectAll(null).data(shown).join('line').attr('class', 'co-link-hit')
            .attr('x1', l => pos[l.a][0]).attr('y1', l => pos[l.a][1])
            .attr('x2', l => pos[l.b][0]).attr('y2', l => pos[l.b][1])
            .attr('stroke', 'transparent').attr('stroke-width', 9)
            .on('pointermove', (e, l) => this._tip(e, this._linkTip(l)))
            .on('pointerleave', () => this._tip(null));

        // Partner and non-hub institutions, under the hubs.
        const marks = this._institutionMarks(projection);
        const gi = root.append('g').attr('class', 'co-insts');
        const instDots = gi.selectAll('circle').data(marks).join('circle')
            .attr('cx', m => m.x).attr('cy', m => m.y)
            .attr('fill', m => COLLAB_COLORS[m.d.kind]).attr('fill-opacity', 0.85)
            .attr('stroke', '#fff')
            .on('pointermove', (e, m) => this._tip(e, this._instTip(m)))
            .on('pointerleave', () => this._tip(null));

        const visible = this.hubs.map((_, i) => i).filter(i => pos[i] && !this.hidden.has(i) && papers[i]);
        const maxP = Math.max(1, ...visible.map(i => papers[i]));
        const radius = i => 3 + 16 * Math.sqrt(papers[i] / maxP);
        const dim = i => sel != null && i !== sel && !partners.has(i);
        const gn = root.append('g').attr('class', 'co-nodes');
        const dots = gn.selectAll('circle').data(visible).join('circle')
            .attr('cx', i => pos[i][0]).attr('cy', i => pos[i][1])
            .attr('fill', COLLAB_COLORS.hub)
            .attr('fill-opacity', i => (dim(i) ? 0.25 : 0.95))
            .attr('stroke', i => (i === sel ? COLLAB_SELECT : '#fff'));
        // 24px hit areas, focusable, with the same tooltip on hover and focus.
        const hits = gn.selectAll(null).data(visible).join('circle')
            .attr('class', 'co-hit').attr('cx', i => pos[i][0]).attr('cy', i => pos[i][1])
            .attr('fill', 'transparent').attr('tabindex', 0).attr('role', 'button')
            .attr('aria-label', i => `${this.hubs[i].label}: ${papers[i]} papers`)
            .on('pointermove', (e, i) => this._tip(e, this._hubTip(i)))
            .on('pointerleave', () => this._tip(null))
            .on('focus', (e, i) => this._tip({ target: e.target, focus: true }, this._hubTip(i)))
            .on('blur', () => this._tip(null))
            .on('click', (e, i) => this.select(i === this.selected ? null : i))
            .on('keydown', (e, i) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.select(i === this.selected ? null : i); }
            });

        const order = sel != null
            ? [sel, ...shown.slice(0, 10).map(l => (l.a === sel ? l.b : l.a))]
            : [...visible].sort((a, b) => papers[b] - papers[a]).slice(0, width < 560 ? 7 : 14);
        const labels = this._labelLayout(order, sel, radius, width, height);
        const texts = root.append('g').attr('class', 'co-labels').selectAll('text').data(labels).join('text')
            .attr('text-anchor', d => d.anchor).attr('class', d => d.cls).text(d => d.text);

        // Zoom and pan. Dots, hit areas and labels are rescaled by 1/k so they
        // keep their screen size while the map grows around them.
        const fit = t => {
            const k = t.k;
            root.attr('transform', t);
            dots.attr('r', i => radius(i) / k).attr('stroke-width', i => (i === sel ? 3.5 : 2) / k);
            hits.attr('r', i => Math.max(12, radius(i) + 4) / k);
            instDots.attr('r', m => m.r / k).attr('stroke-width', 0.8 / k);
            texts.attr('x', d => d.x + d.dx / k).attr('y', d => d.y + d.dy / k)
                .style('font-size', `${11 / k}px`).style('stroke-width', `${3 / k}px`);
            document.getElementById('co-reset').style.display = k > 1.01 ? '' : 'none';
        };
        const zoom = d3.zoom().scaleExtent([1, 12])
            .extent([[0, 0], [width, height]]).translateExtent([[0, 0], [width, height]])
            // A plain scroll wheel keeps scrolling the page; Ctrl/Cmd+scroll or a
            // trackpad pinch (sent as ctrl+wheel) zooms. One finger on a touch
            // screen scrolls the page unless the map is already zoomed in.
            .filter(e => {
                if (e.type === 'wheel') return e.ctrlKey || e.metaKey;
                if (e.type === 'touchstart') return e.touches.length > 1 || (this.zoomT?.k ?? 1) > 1;
                return !e.button;
            })
            .on('zoom', e => { this.zoomT = e.transform; fit(e.transform); this._tip(null); });
        svg.call(zoom).style('touch-action', 'pan-y');
        if (this.zoomWidth !== width) this.zoomT = d3.zoomIdentity;   // reset after a resize
        this.zoomWidth = width;
        svg.call(zoom.transform, this.zoomT || d3.zoomIdentity);
        document.getElementById('co-reset').onclick = () =>
            svg.transition().duration(300).call(zoom.transform, d3.zoomIdentity);
        document.getElementById('co-zoom-in').onclick = () => svg.transition().duration(250).call(zoom.scaleBy, 1.8);
        document.getElementById('co-zoom-out').onclick = () => svg.transition().duration(250).call(zoom.scaleBy, 1 / 1.8);

        this._drawLegend(maxP, marks);
    }

    _labelLayout(order, sel, radius, width, height) {
        // Placed greedily: a label that would overlap another or leave the map is skipped.
        const pos = this.pos;
        const placed = [], out = [];
        for (const i of order) {
            if (!pos[i]) continue;
            const text = this.hubs[i].label.replace(' (Harvard Catalyst)', '');
            const w = text.length * 6.3, h = 13, r = radius(i);
            const candidates = [[r + 4, 4, 'start'], [-r - 4, 4, 'end'], [0, -r - 5, 'middle'], [0, r + 13, 'middle']];
            for (const [dx, dy, anchor] of candidates) {
                const x0 = pos[i][0] + dx - (anchor === 'end' ? w : anchor === 'middle' ? w / 2 : 0);
                const y0 = pos[i][1] + dy - 10;
                const box = [x0, y0, x0 + w, y0 + h];
                if (box[0] < 2 || box[2] > width - 2 || box[1] < 2 || box[3] > height - 2) continue;
                if (placed.some(b => !(box[2] < b[0] || box[0] > b[2] || box[3] < b[1] || box[1] > b[3]))) continue;
                placed.push(box);
                out.push({ x: pos[i][0], y: pos[i][1], dx, dy, anchor, text,
                           cls: i === sel ? 'co-label co-label-sel' : 'co-label' });
                break;
            }
        }
        return out;
    }

    _drawLegend(maxP, marks) {
        // HTML, not SVG, so the keys wrap onto separate lines on a phone.
        const st = this.state, relative = st.measure === 'relative';
        const r = v => 3 + 16 * Math.sqrt(v / maxP);
        const dot = (radius, color) => `<svg width="${2 * radius + 4}" height="${Math.max(16, 2 * radius + 4)}" aria-hidden="true">
            <circle cx="${radius + 2}" cy="${Math.max(8, radius + 2)}" r="${radius}" fill="${color}" stroke="#fff" stroke-width="1.5"/></svg>`;
        const line = t => `<svg width="30" height="16" aria-hidden="true">
            <line x1="2" x2="28" y1="8" y2="8" stroke="${COLLAB_RAMP(t)}" stroke-linecap="round"
                  stroke-opacity="${0.35 + 0.6 * t}" stroke-width="${0.8 + 6.2 * t}"/></svg>`;
        const item = (mark, text) => `<span class="co-legend-item">${mark}${escHtml(text)}</span>`;
        const top = this._linkTop;
        const fake = v => this._linkT(relative ? { rel: v } : { w: v });
        const samples = relative ? [Math.sqrt(top), Math.pow(top, 0.75), top].filter((v, k, a) => k === 0 || v > a[k - 1] + 0.05)
                                 : [top / 4, top / 2, top];
        const linkItems = samples.map(v => item(line(fake(v)), relative
            ? `${fmtX(v)}${this.selected == null && v === RELATIVE_MAX ? '+' : ''}`
            : Math.round(v).toLocaleString()));
        const kinds = [item(dot(5, COLLAB_COLORS.hub), 'CTSA hub')];
        if (st.showPartner) kinds.push(item(dot(4, COLLAB_COLORS.partner), 'Partner institution'));
        if (st.showOther) kinds.push(item(dot(4, COLLAB_COLORS.other), 'Other non-hub institution'));
        document.getElementById('co-legend').innerHTML = `
            <div class="co-legend-group">${kinds.join('')}</div>
            <div class="co-legend-group"><span class="co-legend-title">Hub size: papers</span>
                ${[maxP, maxP / 4, maxP / 16].map(v => item(dot(r(v), COLLAB_COLORS.hub), Math.round(v).toLocaleString())).join('')}</div>
            <div class="co-legend-group"><span class="co-legend-title">Link: ${relative ? 'times the expected rate' :
                (st.counting === 'fractional' ? 'fractional papers' : 'shared papers')}${this.selected != null
                ? ` (scaled to ${escHtml(this.hubs[this.selected].label)}'s strongest tie)` : ''}</span>${linkItems.join('')}</div>
            ${marks.length ? `<div class="co-legend-group"><span class="co-legend-title">Institution size: papers ${this.selected == null ? 'with hubs' : 'with the selected hub'}</span>
                ${item('', `${marks.length.toLocaleString()} shown, from ${this.inst.from_year}`)}</div>` : ''}`;
    }

    // ---------------------------------------------------------------- tooltip

    _hubTip(i) {
        const { papers, cross } = this.net;
        const h = this.hubs[i];
        return [[`${papers[i].toLocaleString()} papers`, 'strong'],
                [`${cross[i].toLocaleString()} with another hub (${papers[i] ? Math.round(100 * cross[i] / papers[i]) : 0}%)`, ''],
                [h.label, 'muted'], [`${h.city}, ${h.state}`, 'muted']];
    }

    _linkTip(l) {
        const frac = this.state.counting === 'fractional';
        const rel = `${fmtX(l.rel)} the expected rate`;
        const papers = `${l.f.toLocaleString()} shared papers${frac ? ` (${fmt1(l.w)} fractional)` : ''}`;
        return [this.state.measure === 'relative' ? [rel, 'strong'] : [papers, 'strong'],
                this.state.measure === 'relative' ? [papers, ''] : [rel, ''],
                [`${this.hubs[l.a].label} – ${this.hubs[l.b].label}`, 'muted']];
    }

    _instTip(m) {
        const d = m.d, sel = this.selected;
        const lines = [[sel == null ? `${m.v.toLocaleString()} papers with hubs`
                                    : `${m.v.toLocaleString()} papers with ${this.hubs[sel].label}`, 'strong'],
                       [d.name, ''],
                       [`${d.kind === 'partner' ? `Partner of ${this.hubs[d.hub]?.label ?? 'a hub'}` : 'Non-hub'} · ${d.type}`, 'muted']];
        if (d.city) lines.push([`${d.city}, ${d.state}`, 'muted']);
        return lines;
    }

    _tip(e, lines) {
        const tip = document.getElementById('co-tooltip');
        if (!e) { tip.style.display = 'none'; return; }
        tip.replaceChildren(...lines.map(([text, cls]) => {
            const d = document.createElement('div');
            d.textContent = text;
            if (cls) d.className = `co-tip-${cls}`;
            return d;
        }));
        const box = document.getElementById('co-map-wrap').getBoundingClientRect();
        let x, y;
        if (e.focus) {
            const r = e.target.getBoundingClientRect();
            x = r.right - box.left + 8; y = r.top - box.top;
        } else {
            x = e.clientX - box.left + 14; y = e.clientY - box.top + 14;
        }
        tip.style.display = 'block';
        tip.style.left = `${Math.max(4, Math.min(x, box.width - tip.offsetWidth - 4))}px`;
        tip.style.top = `${Math.max(4, Math.min(y, box.height - tip.offsetHeight - 4))}px`;
    }

    // ---------------------------------------------------------------- panel & table

    select(i) {
        this.selected = i;
        this.render();
    }

    _partnerCell(l) {
        const relative = this.state.measure === 'relative';
        const papers = l.f.toLocaleString();
        return relative ? `${fmtX(l.rel)} <span class="co-sub">(${papers})</span>`
                        : `${papers} <span class="co-sub">(${fmtX(l.rel)})</span>`;
    }

    _renderPanel() {
        const el = document.getElementById('co-panel');
        const { papers, cross, strength, links, ranked } = this.net;
        const st = this.state, relative = st.measure === 'relative';
        const i = this.selected;
        if (i == null) {
            const top = ranked.slice(0, 10);
            el.innerHTML = `
                <h3>${relative ? 'Strongest ties' : 'Most shared papers'}</h3>
                <p class="data-note">${relative
                    ? `Pairs that share the most papers relative to what their overall collaboration predicts (at least ${MIN_SHARED_FOR_RELATIVE} shared papers).`
                    : 'Pairs with the most shared papers.'} Click a hub, on the map or here, to see its partners.</p>
                <ol class="co-list">${top.map(l => `
                    <li><span><button class="co-link-btn" data-select="${l.a}">${escHtml(this.hubs[l.a].label)}</button> –
                        <button class="co-link-btn" data-select="${l.b}">${escHtml(this.hubs[l.b].label)}</button></span>
                        <span class="co-num">${this._partnerCell(l)}</span></li>`).join('')}</ol>`;
        } else {
            const h = this.hubs[i];
            const mine = ranked.filter(l => l.a === i || l.b === i);
            const nPartners = links.filter(l => l.a === i || l.b === i).length;
            const o = h.outreach;
            const pct = v => (v == null || v === '' ? '–' : `${(+v).toFixed(1)}%`);
            let instHtml = '';
            if (this.instNet) {
                const { withSel } = this.instNet;
                const list = this.inst.institutions;
                const topOf = kind => list.map((_, id) => id).filter(id => list[id].kind === kind && withSel[id])
                    .sort((a, b) => withSel[b] - withSel[a]).slice(0, 6);
                const block = (title, ids) => ids.length ? `<h4>${title}</h4><ol class="co-list">${ids.map(id =>
                    `<li><span>${escHtml(list[id].name)}</span><span class="co-num">${withSel[id].toLocaleString()}</span></li>`).join('')}</ol>` : '';
                if (st.showPartner) instHtml += block('Top partner institutions', topOf('partner'));
                if (st.showOther) instHtml += block('Top other non-hub institutions', topOf('other'));
            }
            el.innerHTML = `
                <h3>${escHtml(h.label)}</h3>
                <p class="data-note">${escHtml(h.city)}, ${escHtml(h.state)}
                    ${h.award_first ? `· CTSA award ${h.award_first}–${h.award_last}` : ''}</p>
                <dl class="co-stats">
                    <dt>Papers</dt><dd>${papers[i].toLocaleString()}</dd>
                    <dt>With another hub</dt><dd>${cross[i].toLocaleString()} (${papers[i] ? (100 * cross[i] / papers[i]).toFixed(1) : 0}%)</dd>
                    <dt>Hubs it shares papers with</dt><dd>${nPartners}</dd>
                </dl>
                <h4>${relative ? 'Strongest ties' : 'Most shared papers'}</h4>
                ${relative ? `<p class="data-note">Times the expected rate (shared papers). At least ${MIN_SHARED_FOR_RELATIVE} shared papers.</p>` : ''}
                <ol class="co-list">${mine.slice(0, 10).map(l => {
                    const k = l.a === i ? l.b : l.a;
                    return `<li><button class="co-link-btn" data-select="${k}">${escHtml(this.hubs[k].label)}</button>
                            <span class="co-num">${this._partnerCell(l)}</span></li>`;
                }).join('') || '<li class="data-note">No links with these settings.</li>'}</ol>
                ${instHtml}
                ${o ? `<h4>Outside the hubs</h4>
                <p class="data-note">Papers from 2014 on; not affected by the controls. International and in-state shares are of papers with a located non-hub co-author.</p>
                <dl class="co-stats">
                    <dt>With a non-hub co-author</dt><dd>${pct(o.pct_with_nonhub_coauthor)}</dd>
                    <dt>International co-author</dt><dd>${pct(o.pct_international_of_located)}</dd>
                    <dt>US co-author in own state</dt><dd>${pct(o.pct_in_state_of_us)}</dd>
                    <dt>States / countries</dt><dd>${o.nonhub_states ?? '–'} / ${o.nonhub_countries ?? '–'}</dd>
                    <dt>Top non-hub partner</dt><dd>${escHtml(o.top_nonhub_institution || '–')}</dd>
                </dl>` : ''}
                <div class="co-actions">
                    ${h.slug ? `<button class="download-btn" data-open="${escHtml(h.slug)}">Open in Site Detail</button>` : ''}
                    <button class="download-btn" data-hide="${i}">Hide this hub</button>
                    <button class="download-btn" data-select="">Clear selection</button>
                </div>`;
        }
        el.querySelectorAll('[data-select]').forEach(b => b.addEventListener('click', () =>
            this.select(b.dataset.select === '' ? null : +b.dataset.select)));
        el.querySelectorAll('[data-hide]').forEach(b => b.addEventListener('click', () => this.hideHub(+b.dataset.hide)));
        el.querySelectorAll('[data-open]').forEach(b => b.addEventListener('click', () => this.app.openSite(b.dataset.open)));
    }

    _renderPairs() {
        const frac = this.state.counting === 'fractional';
        const rows = this.net.ranked.slice(0, 25);
        document.getElementById('co-pairs').innerHTML = `
            <p class="data-note">Ranked by the link strength chosen above.</p>
            <div class="table-scroll"><table class="data-table">
                <thead><tr><th>#</th><th>Hub</th><th>Hub</th><th>× expected</th>
                    <th>Shared papers</th>${frac ? '<th>Fractional papers</th>' : ''}</tr></thead>
                <tbody>${rows.map((l, r) => `<tr>
                    <td>${r + 1}</td>
                    <td><button class="co-link-btn" data-select="${l.a}">${escHtml(this.hubs[l.a].label)}</button></td>
                    <td><button class="co-link-btn" data-select="${l.b}">${escHtml(this.hubs[l.b].label)}</button></td>
                    <td>${fmtX(l.rel)}</td><td>${l.f.toLocaleString()}</td>
                    ${frac ? `<td>${fmt1(l.w)}</td>` : ''}</tr>`).join('')}
                </tbody></table></div>`;
        document.querySelectorAll('#co-pairs [data-select]').forEach(b => b.addEventListener('click', () => {
            this.select(+b.dataset.select);
            document.getElementById('collaboration').scrollIntoView({ behavior: 'smooth' });
        }));
    }

    _renderDownloads() {
        const el = document.getElementById('co-downloads');
        if (el.dataset.ready) return;
        el.dataset.ready = '1';
        el.innerHTML = `<div class="download-bar"><span>Download:</span>
            <button class="download-btn" data-dl="links">Links CSV</button>
            <button class="download-btn" data-dl="hubs">Hubs CSV</button>
            <button class="download-btn" data-dl="insts">Institutions CSV</button>
            <button class="download-btn" data-dl="svg">Map SVG</button></div>`;
        el.querySelectorAll('[data-dl]').forEach(b => b.addEventListener('click', () => this._download(b.dataset.dl)));
    }

    _filename() {
        const st = this.state;
        return `hub_${st.network}_${st.measure}_${st.counting}_${st.from}-${st.to}` +
               (st.noConsortium ? '_no-consortium' : '') + (this.hidden.size ? '_some-hidden' : '');
    }

    async _download(kind) {
        const { papers, cross, strength, links } = this.net;
        if (kind === 'links') {
            ChartManager.downloadCSV([
                ['hub_a', 'hub_b', 'state_a', 'state_b', 'times_expected', 'shared_papers', 'weight'],
                ...links.map(l => [this.hubs[l.a].label, this.hubs[l.b].label, this.hubs[l.a].state,
                                   this.hubs[l.b].state, l.rel.toFixed(4), l.f, l.w.toFixed(4)])], `${this._filename()}_links`);
        } else if (kind === 'hubs') {
            ChartManager.downloadCSV([
                ['hub', 'city', 'state', 'lat', 'lon', 'papers', 'cross_hub_papers', 'link_strength', 'hidden'],
                ...this.hubs.map((h, i) => [h.label, h.city, h.state, h.lat, h.lon, papers[i], cross[i],
                                            strength[i].toFixed(4), this.hidden.has(i) ? 1 : 0])], `${this._filename()}_hubs`);
        } else if (kind === 'insts') {
            await this._loadInstitutions();
            if (!this.inst) return;
            const net = this.computeInstitutions();
            const sel = this.selected;
            ChartManager.downloadCSV([
                ['institution', 'kind', 'type', 'partner_of', 'city', 'state', 'lat', 'lon', 'papers_with_hubs',
                 ...(sel != null ? [`papers_with_${this.hubs[sel].label}`] : [])],
                ...this.inst.institutions.map((d, id) => [d.name, d.kind, d.type, d.hub != null ? this.hubs[d.hub].label : '',
                    d.city, d.state, d.lat, d.lon, net.count[id], ...(sel != null ? [net.withSel[id]] : [])])
                    .filter(r => r[8] > 0)], `${this._filename()}_institutions`);
        } else {
            const svg = document.getElementById('co-map').cloneNode(true);
            svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
            const style = document.createElement('style');
            style.textContent = '.co-states path{fill:#eef2f5;stroke:#c9d3dc;stroke-width:0.8}' +
                '.co-label{font:11px sans-serif;fill:#2c3e50;paint-order:stroke;stroke:#fff;stroke-width:3px}' +
                '.co-label-sel{font-weight:700}';
            svg.prepend(style);
            const a = document.createElement('a');
            a.href = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)], { type: 'image/svg+xml' }));
            a.download = `${this._filename()}_map.svg`;
            a.click();
        }
    }
}
