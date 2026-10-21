/**
 * Collaboration tab: a US map of CTSA hubs and the links between them.
 *
 * collaboration.json holds one record per paper (year, the hubs of its core
 * authors, partner-only authors and cited CTSA awards, and the hub whose grants
 * are its only NCATS link). The network is recomputed in the browser for
 * whatever the controls describe, so hiding a hub or leaving out consortium
 * papers changes every number consistently: the map, the panel and the table.
 *
 * Data is loaded on first visit to the tab (about 600 KB compressed).
 * Kept in its own file rather than added to app.js, which is already large.
 */

const COLLAB_COLOR = '#2e86c1';     // hubs and links (the site's primary-light)
const COLLAB_HILITE = '#D55E00';    // the selected hub and its links
const COLLAB_OUTLIERS = ['Yale University', 'Baylor College of Medicine'];
const NETWORKS = {
    core:  { label: 'Co-authorship (hub institutions)', coauthor: true },
    broad: { label: 'Co-authorship incl. partner hospitals', coauthor: true },
    fund:  { label: 'Co-funding (shared CTSA award citations)', coauthor: false },
};

function escHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

class CollabTab {
    constructor(app) {
        this.app = app;
        this.loading = null;
        this.selected = null;          // hub index
        this.hidden = new Set();       // hub indices
        this.state = null;
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
            network: 'core', counting: 'fractional',
            from: this.data.coauthor_reliable_from, to: maxYear,
            noConsortium: false, dropSole: true, topN: 100,
        };
    }

    // ---------------------------------------------------------------- controls

    _renderControls() {
        const st = this.state;
        const yearOpts = sel => this.years.map(y =>
            `<option value="${y}"${y === sel ? ' selected' : ''}>${y}</option>`).join('');
        const netOpts = Object.entries(NETWORKS).map(([k, v]) =>
            `<option value="${k}"${k === st.network ? ' selected' : ''}>${escHtml(v.label)}</option>`).join('');
        document.getElementById('co-controls').innerHTML = `
            <div class="controls-row">
                <label>Network: <select id="co-network">${netOpts}</select></label>
                <label>Count: <select id="co-counting">
                    <option value="fractional" selected>Fractional (each paper counts once)</option>
                    <option value="full">Full (1 per shared paper)</option>
                </select></label>
                <label>From: <select id="co-from">${yearOpts(st.from)}</select></label>
                <label>To: <select id="co-to">${yearOpts(st.to)}</select></label>
                <label>Links shown: <select id="co-topn">
                    ${[50, 100, 250, 500].map(v =>
                        `<option value="${v}"${v === st.topN ? ' selected' : ''}>Top ${v}</option>`).join('')}
                    <option value="0">All</option>
                </select></label>
            </div>
            <div class="controls-row">
                <label class="co-check"><input type="checkbox" id="co-noconsortium">
                    Leave out papers naming ${this.data.consortium_hubs}+ hubs</label>
                <label>Hide a hub: <select id="co-hide">
                    <option value="">Choose…</option>
                    ${this.hubs.map((h, i) => `<option value="${i}">${escHtml(h.label)}</option>`).join('')}
                </select></label>
                <span class="co-quick">Common outliers:
                    ${COLLAB_OUTLIERS.map(l => `<button class="co-link-btn" data-outlier="${escHtml(l)}">${escHtml(l)}</button>`).join(' · ')}
                </span>
            </div>
            <div class="controls-row" id="co-hidden-row" style="display:none;">
                <span>Hidden:</span><span id="co-hidden-chips" class="picker-chips"></span>
                <label class="co-check"><input type="checkbox" id="co-dropsole" checked>
                    Also drop papers that are in the data only through a hidden hub's grants</label>
            </div>
            <p class="data-note co-warning" id="co-warning"></p>`;

        const on = (id, ev, fn) => document.getElementById(id).addEventListener(ev, fn);
        on('co-network', 'change', e => {
            st.network = e.target.value;
            // Co-funding needs no affiliations, so it can start in the first year.
            if (!NETWORKS[st.network].coauthor && st.from === this.data.coauthor_reliable_from) {
                st.from = this.data.from_year;
                document.getElementById('co-from').value = st.from;
            }
            this.render();
        });
        on('co-counting', 'change', e => { st.counting = e.target.value; this.render(); });
        on('co-from', 'change', e => { st.from = +e.target.value; this.render(); });
        on('co-to', 'change', e => { st.to = +e.target.value; this.render(); });
        on('co-topn', 'change', e => { st.topN = +e.target.value; this.render(); });
        on('co-noconsortium', 'change', e => { st.noConsortium = e.target.checked; this.render(); });
        on('co-dropsole', 'change', e => { st.dropSole = e.target.checked; this.render(); });
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

    /** The network for the current controls. Pure apart from reading this.state. */
    compute() {
        const st = this.state, n = this.n, P = this.data.papers;
        const sets = this.sets[st.network], Y = P.y, S = P.s;
        const hidden = this.hidden, cons = this.data.consortium_hubs;
        const W = new Float64Array(n * n), F = new Uint32Array(n * n);
        const papers = new Uint32Array(n), cross = new Uint32Array(n);
        let nPapers = 0, nMulti = 0;
        for (let i = 0; i < Y.length; i++) {
            const y = Y[i];
            if (y < st.from || y > st.to) continue;
            const raw = sets[i];
            if (!raw.length) continue;
            if (st.noConsortium && raw.length >= cons) continue;
            if (st.dropSole && S[i] >= 0 && hidden.has(S[i])) continue;
            const hs = hidden.size ? raw.filter(h => !hidden.has(h)) : raw;
            const k = hs.length;
            if (!k) continue;
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
        for (let a = 0; a < n; a++) for (let b = a + 1; b < n; b++) {
            const f = F[a * n + b];
            if (!f) continue;
            const w = W[a * n + b];
            links.push({ a, b, w, f });
            strength[a] += w;
            strength[b] += w;
        }
        links.sort((x, y) => y.w - x.w);
        return { papers, cross, strength, links, nPapers, nMulti };
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
        const { nPapers, nMulti, links } = this.net;
        const pairs = this.n - this.hidden.size;
        document.getElementById('co-summary').textContent =
            `${nPapers.toLocaleString()} papers with a hub · ` +
            `${nMulti.toLocaleString()} with 2 or more hubs ` +
            `(${nPapers ? (100 * nMulti / nPapers).toFixed(1) : 0}%) · ` +
            `${links.length.toLocaleString()} of ${(pairs * (pairs - 1) / 2).toLocaleString()} hub pairs linked`;
        this._drawMap();
        this._renderPanel();
        this._renderPairs();
        this._renderDownloads();
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
        const { papers, links } = this.net;
        const sel = this.selected;
        const drawable = l => pos[l.a] && pos[l.b];
        const shown = (this.state.topN ? links.slice(0, this.state.topN) : links).filter(drawable);
        const selLinks = sel == null ? [] : links.filter(l => (l.a === sel || l.b === sel) && drawable(l));
        const maxW = links.length ? links[0].w : 1;
        this.linkWidth = w => 0.5 + 4.5 * Math.sqrt(w / maxW);
        const alpha = w => 0.08 + 0.42 * Math.sqrt(w / maxW);

        // Link strokes keep their screen width when zoomed (vector-effect in CSS).
        const gl = root.append('g').attr('class', 'co-links');
        const drawLinks = (data, colour, op) => gl.selectAll(null).data([...data].reverse()).join('line')
            .attr('x1', l => pos[l.a][0]).attr('y1', l => pos[l.a][1])
            .attr('x2', l => pos[l.b][0]).attr('y2', l => pos[l.b][1])
            .attr('stroke', colour).attr('stroke-linecap', 'round')
            .attr('stroke-width', l => this.linkWidth(l.w)).attr('stroke-opacity', op);
        drawLinks(shown, COLLAB_COLOR, sel == null ? alpha : 0.05);
        if (sel != null) drawLinks(selLinks, COLLAB_HILITE, l => 0.3 + 0.6 * Math.sqrt(l.w / selLinks[0].w));
        // Wide transparent strokes so a thin link is still easy to hover.
        gl.selectAll(null).data(sel == null ? shown : selLinks).join('line')
            .attr('x1', l => pos[l.a][0]).attr('y1', l => pos[l.a][1])
            .attr('x2', l => pos[l.b][0]).attr('y2', l => pos[l.b][1])
            .attr('stroke', 'transparent').attr('stroke-width', 9)
            .on('pointermove', (e, l) => this._tip(e, this._linkTip(l)))
            .on('pointerleave', () => this._tip(null));

        const visible = this.hubs.map((_, i) => i).filter(i => pos[i] && !this.hidden.has(i) && papers[i]);
        const maxP = Math.max(1, ...visible.map(i => papers[i]));
        const radius = i => 3 + 10 * Math.sqrt(papers[i] / maxP);
        const partners = new Set(selLinks.map(l => (l.a === sel ? l.b : l.a)));
        const gn = root.append('g').attr('class', 'co-nodes');
        const dots = gn.selectAll('circle').data(visible).join('circle')
            .attr('cx', i => pos[i][0]).attr('cy', i => pos[i][1])
            .attr('fill', i => (i === sel ? COLLAB_HILITE : COLLAB_COLOR))
            .attr('fill-opacity', i => (sel == null || i === sel || partners.has(i) ? 0.95 : 0.35))
            .attr('stroke', '#fff');
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

        const labels = this._labelLayout(visible, sel, selLinks, radius, width, height);
        const texts = root.append('g').attr('class', 'co-labels').selectAll('text').data(labels).join('text')
            .attr('text-anchor', d => d.anchor).attr('class', d => d.cls).text(d => d.text);

        // Zoom and pan. Dots, hit areas and labels are rescaled by 1/k so they
        // keep their screen size while the map grows around them.
        const fit = t => {
            const k = t.k;
            root.attr('transform', t);
            dots.attr('r', i => radius(i) / k).attr('stroke-width', 2 / k);
            hits.attr('r', i => Math.max(12, radius(i) + 4) / k);
            texts.attr('x', d => d.x + d.dx / k).attr('y', d => d.y + d.dy / k)
                .style('font-size', `${11 / k}px`).style('stroke-width', `${3 / k}px`);
            document.getElementById('co-reset').style.display = k > 1.01 ? '' : 'none';
        };
        const zoom = d3.zoom().scaleExtent([1, 8])
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

        this._drawLegend(maxP, maxW);
    }

    _labelLayout(visible, sel, selLinks, radius, width, height) {
        // The selected hub and its strongest partners, or else the largest hubs.
        // Placed greedily: a label that would overlap another or leave the map is skipped.
        const { papers } = this.net;
        const pos = this.pos;
        const order = sel != null
            ? [sel, ...selLinks.slice(0, 6).map(l => (l.a === sel ? l.b : l.a))]
            : [...visible].sort((a, b) => papers[b] - papers[a]).slice(0, width < 560 ? 7 : 14);
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

    _drawLegend(maxP, maxW) {
        // HTML, not SVG, so the two keys wrap onto separate lines on a phone.
        const counting = this.state.counting === 'fractional' ? 'fractional papers' : 'shared papers';
        const r = v => 3 + 10 * Math.sqrt(v / maxP);
        const dot = v => `<svg width="${2 * r(v) + 4}" height="28" aria-hidden="true">
            <circle cx="${r(v) + 2}" cy="14" r="${r(v)}" fill="${COLLAB_COLOR}" stroke="#fff" stroke-width="2"/></svg>`;
        const line = w => `<svg width="28" height="28" aria-hidden="true">
            <line x1="2" x2="26" y1="14" y2="14" stroke="${COLLAB_COLOR}" stroke-linecap="round"
                  stroke-width="${this.linkWidth(w)}"/></svg>`;
        const item = (mark, v) => `<span class="co-legend-item">${mark}${Math.round(v).toLocaleString()}</span>`;
        document.getElementById('co-legend').innerHTML = `
            <div class="co-legend-group"><span class="co-legend-title">Hub size: papers</span>
                ${[maxP, maxP / 4, maxP / 16].map(v => item(dot(Math.max(1, v)), Math.max(1, v))).join('')}</div>
            <div class="co-legend-group"><span class="co-legend-title">Link width: ${counting}</span>
                ${[maxW, maxW / 4, maxW / 16].map(w => item(line(w), w)).join('')}</div>`;
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
        return [[frac ? `${l.w.toFixed(1)} fractional papers` : `${l.f.toLocaleString()} shared papers`, 'strong'],
                ...(frac ? [[`${l.f.toLocaleString()} shared papers`, '']] : []),
                [`${this.hubs[l.a].label} – ${this.hubs[l.b].label}`, 'muted']];
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
        tip.style.left = `${Math.min(x, box.width - tip.offsetWidth - 4)}px`;
        tip.style.top = `${Math.min(y, box.height - tip.offsetHeight - 4)}px`;
    }

    // ---------------------------------------------------------------- panel & table

    select(i) {
        this.selected = i;
        this.render();
    }

    _renderPanel() {
        const el = document.getElementById('co-panel');
        const { papers, cross, strength, links } = this.net;
        const frac = this.state.counting === 'fractional';
        const fmtW = w => (frac
            ? w.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })
            : Math.round(w).toLocaleString());
        const i = this.selected;
        if (i == null) {
            const top = this.hubs.map((_, k) => k).filter(k => !this.hidden.has(k))
                .sort((a, b) => strength[b] - strength[a]).slice(0, 10);
            el.innerHTML = `
                <h3>Most connected hubs</h3>
                <p class="data-note">Total link strength (${frac ? 'fractional' : 'full'} counting). Click a hub, on the map or here, to see its partners.</p>
                <ol class="co-list">${top.map(k => `
                    <li><button class="co-link-btn" data-select="${k}">${escHtml(this.hubs[k].label)}</button>
                        <span class="co-num">${fmtW(strength[k])}</span></li>`).join('')}</ol>`;
        } else {
            const h = this.hubs[i];
            const mine = links.filter(l => l.a === i || l.b === i).slice(0, 10);
            const o = h.outreach;
            const pct = v => (v == null || v === '' ? '–' : `${(+v).toFixed(1)}%`);
            el.innerHTML = `
                <h3>${escHtml(h.label)}</h3>
                <p class="data-note">${escHtml(h.city)}, ${escHtml(h.state)}
                    ${h.award_first ? `· CTSA award ${h.award_first}–${h.award_last}` : ''}</p>
                <dl class="co-stats">
                    <dt>Papers</dt><dd>${papers[i].toLocaleString()}</dd>
                    <dt>With another hub</dt><dd>${cross[i].toLocaleString()} (${papers[i] ? (100 * cross[i] / papers[i]).toFixed(1) : 0}%)</dd>
                    <dt>Partner hubs</dt><dd>${links.filter(l => l.a === i || l.b === i).length}</dd>
                </dl>
                <h4>Strongest partners</h4>
                <ol class="co-list">${mine.map(l => {
                    const k = l.a === i ? l.b : l.a;
                    return `<li><button class="co-link-btn" data-select="${k}">${escHtml(this.hubs[k].label)}</button>
                            <span class="co-num">${fmtW(l.w)}</span></li>`;
                }).join('') || '<li class="data-note">No links with these settings.</li>'}</ol>
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
        const rows = this.net.links.slice(0, 25);
        document.getElementById('co-pairs').innerHTML = `
            <div class="table-scroll"><table class="data-table">
                <thead><tr><th>#</th><th>Hub</th><th>Hub</th>
                    ${frac ? '<th>Fractional papers</th>' : ''}<th>Shared papers</th></tr></thead>
                <tbody>${rows.map((l, r) => `<tr>
                    <td>${r + 1}</td>
                    <td><button class="co-link-btn" data-select="${l.a}">${escHtml(this.hubs[l.a].label)}</button></td>
                    <td><button class="co-link-btn" data-select="${l.b}">${escHtml(this.hubs[l.b].label)}</button></td>
                    ${frac ? `<td>${l.w.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}</td>` : ''}<td>${l.f.toLocaleString()}</td></tr>`).join('')}
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
            <button class="download-btn" data-dl="svg">Map SVG</button></div>`;
        el.querySelectorAll('[data-dl]').forEach(b => b.addEventListener('click', () => this._download(b.dataset.dl)));
    }

    _filename() {
        const st = this.state;
        return `hub_${st.network}_${st.counting}_${st.from}-${st.to}` +
               (st.noConsortium ? '_no-consortium' : '') + (this.hidden.size ? '_some-hidden' : '');
    }

    _download(kind) {
        const { papers, cross, strength, links } = this.net;
        if (kind === 'links') {
            ChartManager.downloadCSV([
                ['hub_a', 'hub_b', 'state_a', 'state_b', 'weight', 'shared_papers'],
                ...links.map(l => [this.hubs[l.a].label, this.hubs[l.b].label, this.hubs[l.a].state,
                                   this.hubs[l.b].state, l.w.toFixed(4), l.f])], `${this._filename()}_links`);
        } else if (kind === 'hubs') {
            ChartManager.downloadCSV([
                ['hub', 'city', 'state', 'lat', 'lon', 'papers', 'cross_hub_papers', 'link_strength', 'hidden'],
                ...this.hubs.map((h, i) => [h.label, h.city, h.state, h.lat, h.lon, papers[i], cross[i],
                                            strength[i].toFixed(4), this.hidden.has(i) ? 1 : 0])], `${this._filename()}_hubs`);
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
