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
 * points) is loaded only when one of those layers is switched on, and
 * collaboration_papers.json (theme, funding, grants, citation impact, lead
 * authors and PMIDs per paper) when the extra filters or a paper list are used.
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
const FUNDING_LABELS = { hub: 'Hub awards (UL1/UM1)', training: 'Career & training (KL2, K12, TL1, T32…)',
                         research: 'Research grants (R, U…)', small_business: 'Small business (R41–R44)' };
const TRI_LABELS = ['Human', 'Animal', 'Molecular/cellular', 'Mixed'];
const DEFAULT_FILTERS = { theme: -1, funding: 'all', grant: null, role: 'any', researchOnly: false, rcrMin: 0, tri: -1 };
const PUBMED_MAX = 200;   // PubMed shows at most 200 results per page

// Hub color by a metric: one purple hue, light (low) to dark (high), so it
// reads apart from the blue hub links. The light end keeps 2.5:1 on the states.
const COLLAB_METRIC_RAMP = d3.interpolateRgb('#a48fd0', '#3f1d6e');
const COLLAB_NO_VALUE = '#b0b7bf';
// State shading stays light so the institution dots on top remain visible.
const COLLAB_STATE_RAMP = d3.interpolateRgb('#eef2f5', '#5cb592');
const fmtPct = v => `${Math.round(v)}%`;
const fmtDollars = v => (v >= 1e9 ? `$${(v / 1e9).toFixed(1)}B` : `$${Math.round(v / 1e6).toLocaleString()}M`);
const HUB_COLOR_BY = {
    none:   { label: 'One color' },
    cross:  { label: 'Papers with another hub (%)', fmt: fmtPct },
    nonhub: { label: 'Papers with a non-hub co-author (%, 2014 on)', fmt: fmtPct },
    rcr:    { label: 'Mean citation impact (RCR)', fmt: v => v.toFixed(2) },
    first:  { label: 'First CTSA award year at NCATS', fmt: v => String(Math.round(v)) },
};
const HUB_SIZE_BY = {
    papers:   { label: 'Papers', fmt: v => Math.round(v).toLocaleString() },
    cross:    { label: 'Papers with another hub', fmt: v => Math.round(v).toLocaleString() },
    dollars:  { label: 'NCATS award dollars', fmt: fmtDollars },
};
const CENSUS_DIVISIONS = {
    'New England': ['CT', 'ME', 'MA', 'NH', 'RI', 'VT'],
    'Middle Atlantic': ['NJ', 'NY', 'PA'],
    'East North Central': ['IL', 'IN', 'MI', 'OH', 'WI'],
    'West North Central': ['IA', 'KS', 'MN', 'MO', 'NE', 'ND', 'SD'],
    'South Atlantic': ['DE', 'DC', 'FL', 'GA', 'MD', 'NC', 'SC', 'VA', 'WV'],
    'East South Central': ['AL', 'KY', 'MS', 'TN'],
    'West South Central': ['AR', 'LA', 'OK', 'TX'],
    'Mountain': ['AZ', 'CO', 'ID', 'MT', 'NV', 'NM', 'UT', 'WY'],
    'Pacific': ['AK', 'CA', 'HI', 'OR', 'WA'],
};
const CENSUS_REGIONS = {
    Northeast: ['New England', 'Middle Atlantic'],
    Midwest: ['East North Central', 'West North Central'],
    South: ['South Atlantic', 'East South Central', 'West South Central'],
    West: ['Mountain', 'Pacific'],
};
// Figure sizes: `width` is the layout width in screen pixels (text stays 11px
// there), then the figure is scaled to its physical size: about 7 pt text in print.
const FIGURE_SIZES = {
    shown:  { label: 'As shown on screen' },
    slide:  { label: 'Slide (1920 px wide)', width: 1280, px: 1920 },
    single: { label: 'Journal, 1 column (85 mm)', width: 360, mm: 85 },
    double: { label: 'Journal, 2 columns (180 mm)', width: 760, mm: 180 },
};
const PLAY_MS = 900;

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
        this.attrs = null;             // per-paper attributes, once loaded
        this.filters = { ...DEFAULT_FILTERS };
        this.selectedLink = null;      // {a, b} when a link was clicked
        this.selectedInst = null;      // institution index when an institution was clicked
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

    async _loadAttributes() {
        if (this.attrs || this._attrLoading) return this._attrLoading;
        const note = document.getElementById('co-filter-note');
        if (note) note.textContent = 'Loading paper details…';
        this._attrLoading = this.app.loader.loadCollaborationPapers().then(d => {
            if (d.build !== this.data.build) {
                console.warn('collaboration_papers.json is from a different export', d.build, this.data.build);
            }
            const pm = new Float64Array(d.pmid_delta.length);
            let acc = 0;
            d.pmid_delta.forEach((v, i) => { acc += v; pm[i] = acc; });
            d.pmids = pm;
            this.attrs = d;
            this._renderFilterControls();
            if (note) note.textContent = '';
        }).catch(e => {
            if (note) note.textContent = 'Paper details are not available.';
            console.error('Failed to load collaboration_papers.json', e);
        });
        return this._attrLoading;
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
            showHubLinks: true, partnerLines: false, otherLines: false, instLinesPer: 3, labels: 'auto',
            showHubs: true, colorBy: 'none', sizeBy: 'papers', region: 'all', curved: false,
            minLink: 0, shadeStates: false,
        };
    }

    /** The states of the region in focus ('r:South', 'd:Pacific'), or null for the whole US. */
    _regionStates(value = this.state.region) {
        if (value === 'all') return null;
        const [kind, name] = [value.slice(0, 1), value.slice(2)];
        const divisions = kind === 'r' ? CENSUS_REGIONS[name] : [name];
        return new Set(divisions.flatMap(d => CENSUS_DIVISIONS[d]));
    }

    _regionLabel() {
        const v = this.state.region;
        return v === 'all' ? 'United States' : `${v.slice(2)} (Census ${v[0] === 'r' ? 'region' : 'division'})`;
    }

    _minLinkOptions() {
        return this.state.measure === 'relative'
            ? [[0, 'No minimum'], [1.5, '×1.5 expected'], [2, '×2 expected'], [3, '×3 expected'], [5, '×5 expected']]
            : [[0, 'No minimum'], [10, '10 papers'], [25, '25 papers'], [50, '50 papers'], [100, '100 papers'], [250, '250 papers']];
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
                <button class="download-btn co-play" id="co-play" title="Step the To year forward from the From year, one year at a time">▶ Play years</button>
            </div>
            <div class="controls-row">
                <label>Link strength: <select id="co-measure">${opts([
                    ['relative', 'Relative to expected'], ['papers', 'Shared papers']], st.measure)}</select></label>
                <label>Count: <select id="co-counting">${opts([
                    ['fractional', 'Fractional (each paper counts once)'], ['full', 'Full (1 per shared paper)']], st.counting)}</select></label>
                <label>Links shown: <select id="co-topn">${opts([[30, 'Top 30'], [60, 'Top 60'], [120, 'Top 120'], [250, 'Top 250'], [0, 'All']], st.topN)}</select></label>
                <label>Weakest link: <select id="co-minlink">${opts(this._minLinkOptions(), st.minLink)}</select></label>
                <label>Selected hub's partners: <select id="co-partners">${opts([[5, 'Top 5'], [10, 'Top 10'], [20, 'Top 20'], [0, 'All']], st.partnersShown)}</select></label>
            </div>
            <div class="controls-row">
                <label>Hub color: <select id="co-colorby">${opts(Object.entries(HUB_COLOR_BY).map(([k, v]) => [k, v.label]), st.colorBy)}</select></label>
                <label>Hub size: <select id="co-sizeby">${opts(Object.entries(HUB_SIZE_BY).map(([k, v]) => [k, v.label]), st.sizeBy)}</select></label>
                <label>Region: <select id="co-region">${opts([['all', 'Whole US'],
                    ...Object.entries(CENSUS_REGIONS).flatMap(([r, ds]) => [[`r:${r}`, r],
                        ...ds.map(d => [`d:${d}`, `   ${d}`])])], st.region)}</select></label>
                <label class="co-check"><input type="checkbox" id="co-curved"${st.curved ? ' checked' : ''}> Curved lines</label>
                <label class="co-check" title="Papers with a co-author at a located non-hub institution in each state (institutions with at least 3 papers)">
                    <input type="checkbox" id="co-shade"${st.shadeStates ? ' checked' : ''}>
                    <span class="co-swatch co-swatch-box" style="background:${COLLAB_STATE_RAMP(0.8)}"></span> Shade states by non-hub co-authors</label>
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
                <span class="co-layers-title">Dots:</span>
                <label class="co-check" title="A selected hub stays on the map"><input type="checkbox" id="co-show-hubs"${st.showHubs ? ' checked' : ''}>
                    <span class="co-swatch" style="background:${COLLAB_COLORS.hub}"></span> Hubs</label>
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
            <div class="controls-row">
                <span class="co-layers-title">Lines:</span>
                <label class="co-check"><input type="checkbox" id="co-hub-lines"${st.showHubLinks ? ' checked' : ''}>
                    <span class="co-swatch co-swatch-line" style="background:${COLLAB_RAMP(0.7)}"></span> Between hubs</label>
                <label class="co-check"><input type="checkbox" id="co-partner-lines">
                    <span class="co-swatch co-swatch-line" style="background:${COLLAB_COLORS.partner}"></span> Hubs – partner institutions</label>
                <label class="co-check"><input type="checkbox" id="co-other-lines">
                    <span class="co-swatch co-swatch-line" style="background:${COLLAB_COLORS.other}"></span> Hubs – other non-hub institutions</label>
                <label id="co-inst-lines-label">Lines per institution: <select id="co-inst-lines">${opts([[1, 'To its top hub'], [3, 'To its top 3 hubs'],
                    [5, 'To its top 5 hubs'], [0, 'To all its hubs']], st.instLinesPer)}</select></label>
                <label>Labels: <select id="co-labels">${opts([['auto', 'Largest hubs'], ['all', 'As many as fit'],
                    ['none', 'None']], st.labels)}</select></label>
            </div>
            <details class="co-more" id="co-more">
                <summary>More filters: theme, funding, grant or PI, lead authors, citation impact</summary>
                <div id="co-filter-controls"><p class="data-note">Opening this loads paper details (about 1 MB).</p></div>
                <span class="data-note" id="co-filter-note"></span>
            </details>
            <div class="co-active-filters" id="co-active-filters"></div>
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
        on('co-measure', 'change', e => {
            st.measure = e.target.value;
            // The minimum is in different units for each measure.
            st.minLink = 0;
            document.getElementById('co-minlink').innerHTML = opts(this._minLinkOptions(), 0);
            this.render();
        });
        on('co-counting', 'change', set('counting'));
        on('co-from', 'change', e => { this._stopPlay(); set('from', Number)(e); });
        on('co-to', 'change', e => { this._stopPlay(); set('to', Number)(e); });
        on('co-play', 'click', () => (this._playTimer ? this._stopPlay() : this._play()));
        on('co-topn', 'change', set('topN', Number));
        on('co-minlink', 'change', set('minLink', Number));
        on('co-colorby', 'change', async e => {
            st.colorBy = e.target.value;
            if (st.colorBy === 'rcr') await this._loadAttributes();
            this.render();
        });
        on('co-sizeby', 'change', set('sizeBy'));
        on('co-region', 'change', e => {
            st.region = e.target.value;
            this.zoomT = d3.zoomIdentity;
            this.render();
        });
        on('co-curved', 'change', e => { st.curved = e.target.checked; this.render(); });
        on('co-shade', 'change', async e => {
            st.shadeStates = e.target.checked;
            if (st.shadeStates) await this._loadInstitutions();
            this.render();
        });
        on('co-show-hubs', 'change', e => { st.showHubs = e.target.checked; this.render(); });
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
        on('co-hub-lines', 'change', e => { st.showHubLinks = e.target.checked; this.render(); });
        on('co-inst-lines', 'change', set('instLinesPer', Number));
        on('co-labels', 'change', set('labels'));
        // Lines to institutions need their dots: switching lines on turns the dots on too.
        const lines = (key, dotKey, dotId) => async e => {
            st[key] = e.target.checked;
            if (e.target.checked && !st[dotKey]) {
                st[dotKey] = true;
                document.getElementById(dotId).checked = true;
                document.getElementById('co-other-filters').style.display = st.showOther ? '' : 'none';
            }
            if (e.target.checked) await this._loadInstitutions();
            this.render();
        };
        on('co-partner-lines', 'change', lines('partnerLines', 'showPartner', 'co-show-partner'));
        on('co-other-lines', 'change', lines('otherLines', 'showOther', 'co-show-other'));
        on('co-more', 'toggle', e => { if (e.target.open) this._loadAttributes(); });
        on('co-hide', 'change', e => {
            if (e.target.value !== '') this.hideHub(+e.target.value);
            e.target.value = '';
        });
        document.querySelectorAll('[data-outlier]').forEach(btn => btn.addEventListener('click', () => {
            const i = this.hubs.findIndex(h => h.label === btn.dataset.outlier);
            if (i >= 0) this.hideHub(i);
        }));
    }

    _renderFilterControls() {
        const A = this.attrs, f = this.filters;
        if (!A) return;
        const opts = (pairs, sel) => pairs.map(([v, l]) =>
            `<option value="${v}"${String(v) === String(sel) ? ' selected' : ''}>${escHtml(l)}</option>`).join('');
        const shorten = l => (l.length > 70 ? `${l.slice(0, 68)}…` : l);
        // Search options: every grant and every PI, mapped to the grants they stand for.
        this._searchOptions = new Map();
        A.grant_list.forEach((g, k) => this._searchOptions.set(
            `${g.num} · ${g.code} · ${g.org} · ${g.title}`, { label: `Grant ${g.num} · ${g.org}`, grants: [k] }));
        A.pis.forEach(pi => this._searchOptions.set(
            `${pi.name} · PI on ${pi.g.length} grant${pi.g.length === 1 ? '' : 's'}`,
            { label: `${pi.name}'s grants`, grants: pi.g }));
        const nTheme = A.theme.filter(t => t >= 0).length;
        document.getElementById('co-filter-controls').innerHTML = `
            <div class="controls-row">
                <label>Theme: <select id="co-f-theme">${opts([[-1, 'All papers'], ...A.themes.map((t, k) =>
                    [k, `${shorten(t.label)} (${t.size.toLocaleString()})`])], f.theme)}</select></label>
                <span class="data-note">${Math.round(100 * nTheme / A.theme.length)}% of papers have a theme.</span>
            </div>
            <div class="controls-row">
                <label>Funding: <select id="co-f-funding">${opts([['all', 'Any NCATS grant'],
                    ...Object.entries(FUNDING_LABELS)], f.funding)}</select></label>
                <label>Grant or PI: <input type="search" id="co-f-grant" list="co-f-grant-list"
                    placeholder="Grant number or PI name…" autocomplete="off" size="34"></label>
                <datalist id="co-f-grant-list">${[...this._searchOptions.keys()].map(k =>
                    `<option value="${escHtml(k)}"></option>`).join('')}</datalist>
            </div>
            <div class="controls-row">
                <label>Count a hub when it has: <select id="co-f-role">${opts([['any', 'Any author'],
                    ['lead', 'The first or last author']], f.role)}</select></label>
                <label class="co-check"><input type="checkbox" id="co-f-research"${f.researchOnly ? ' checked' : ''}>
                    Research articles only</label>
                <label>Citation impact: <select id="co-f-rcr">${opts([[0, 'Any'], [1, 'RCR ≥ 1 (field average or above)'],
                    [2, 'RCR ≥ 2'], [5, 'RCR ≥ 5']], f.rcrMin)}</select></label>
                <label>Translational: <select id="co-f-tri">${opts([[-1, 'Any'],
                    ...TRI_LABELS.map((l, k) => [k, l])], f.tri)}</select></label>
            </div>`;
        const on = (id, ev, fn) => document.getElementById(id).addEventListener(ev, fn);
        const set = (key, conv) => e => { this.filters[key] = conv(e.target.value); this.render(); };
        on('co-f-theme', 'change', set('theme', Number));
        on('co-f-funding', 'change', set('funding', v => v));
        on('co-f-role', 'change', set('role', v => v));
        on('co-f-rcr', 'change', set('rcrMin', Number));
        on('co-f-tri', 'change', set('tri', Number));
        on('co-f-research', 'change', e => { this.filters.researchOnly = e.target.checked; this.render(); });
        on('co-f-grant', 'change', e => {
            const hit = this._searchOptions.get(e.target.value);
            if (!hit) return;
            this.filters.grant = { label: hit.label, grants: new Set(hit.grants) };
            e.target.value = '';
            this.render();
        });
    }

    _filtersActive() {
        const f = this.filters;
        return !!this.attrs && (f.theme >= 0 || f.funding !== 'all' || f.grant || f.role !== 'any' ||
                                f.researchOnly || f.rcrMin > 0 || f.tri >= 0);
    }

    _renderActiveFilters() {
        const el = document.getElementById('co-active-filters');
        if (!this._filtersActive()) { el.innerHTML = ''; return; }
        const f = this.filters, A = this.attrs, chips = [];
        if (f.theme >= 0) chips.push(['theme', `Theme: ${A.themes[f.theme].label.split(';')[0]}`]);
        if (f.funding !== 'all') chips.push(['funding', `Funding: ${FUNDING_LABELS[f.funding].split(' (')[0]}`]);
        if (f.grant) chips.push(['grant', f.grant.label]);
        if (f.role !== 'any') chips.push(['role', this.state.network === 'fund'
            ? 'Lead authors only (not used for co-funding)' : 'Lead authors only']);
        if (f.researchOnly) chips.push(['researchOnly', 'Research articles']);
        if (f.rcrMin > 0) chips.push(['rcrMin', `RCR ≥ ${f.rcrMin}`]);
        if (f.tri >= 0) chips.push(['tri', `Translational: ${TRI_LABELS[f.tri]}`]);
        el.innerHTML = `<span>Filters:</span>${chips.map(([k, l]) =>
            `<span class="picker-chip" style="background:var(--primary)">${escHtml(l)}
                <button class="chip-remove" data-clear="${k}" aria-label="Remove filter">×</button></span>`).join('')}
            <button class="co-link-btn" data-clear="all">Clear all</button>`;
        el.querySelectorAll('[data-clear]').forEach(b => b.addEventListener('click', () => {
            const k = b.dataset.clear;
            if (k === 'all') this.filters = { ...DEFAULT_FILTERS };
            else this.filters[k] = DEFAULT_FILTERS[k];
            this._renderFilterControls();
            this.render();
        }));
    }

    hideHub(i) {
        this.hidden.add(i);
        if (this.selected === i) this.selected = null;
        this.render();
    }

    /** Step the To year forward from the From year, keeping every other setting. */
    _play() {
        const st = this.state, last = this.years[this.years.length - 1];
        const show = () => { document.getElementById('co-to').value = st.to; this.render(); };
        if (st.to >= last) { st.to = st.from; show(); }   // start over from the first year
        document.getElementById('co-play').textContent = '❚❚ Pause';
        this._playTimer = setInterval(() => {
            st.to++;
            show();
            if (st.to >= last) this._stopPlay();
        }, PLAY_MS);
    }

    _stopPlay() {
        clearInterval(this._playTimer);
        this._playTimer = null;
        const btn = document.getElementById('co-play');
        if (btn) btn.textContent = '▶ Play years';
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
        let raw = this.sets[st.network][i];
        if (!raw.length) return null;
        if (st.noConsortium && raw.length >= this.data.consortium_hubs) return null;
        if (st.dropSole && P.s[i] >= 0 && this.hidden.has(P.s[i])) return null;
        if (this._active) {
            const A = this.attrs, f = this.filters;
            if (f.theme >= 0 && A.theme[i] !== f.theme) return null;
            if (f.funding !== 'all' && !(A.funding[i] & A.funding_bits[f.funding])) return null;
            if (f.grant && !A.grants[i].some(g => f.grant.grants.has(g))) return null;
            if (f.researchOnly && A.research[i] !== 1) return null;
            if (f.rcrMin > 0 && A.rcr10[i] < f.rcrMin * 10) return null;
            if (f.tri >= 0 && A.tri[i] !== f.tri) return null;
            // A hub counts only through its first or last author (co-authorship only).
            if (f.role === 'lead' && st.network !== 'fund') {
                raw = st.network === 'core' ? A.lead_core[i] : A.lead_broad[i];
                if (!raw.length) return null;
            }
        }
        const hs = this.hidden.size ? raw.filter(h => !this.hidden.has(h)) : raw;
        return hs.length ? hs : null;
    }

    /** Paper positions under the current controls that pass pred(i, hubs). */
    _papersWhere(pred) {
        const out = [];
        for (let i = 0; i < this.data.papers.y.length; i++) {
            const hs = this._paperHubs(i);
            if (hs && pred(i, hs)) out.push(i);
        }
        return out;
    }

    /** The hub network for the current controls. */
    compute() {
        const st = this.state, n = this.n, N = this.data.papers.y.length;
        const W = new Float64Array(n * n), F = new Uint32Array(n * n);
        const papers = new Uint32Array(n), cross = new Uint32Array(n);
        // Mean RCR per hub, once paper details are loaded.
        const rcr10 = this.attrs?.rcr10, rcrSum = new Float64Array(n), rcrN = new Uint32Array(n);
        let nPapers = 0, nMulti = 0;
        for (let i = 0; i < N; i++) {
            const hs = this._paperHubs(i);
            if (!hs) continue;
            const k = hs.length;
            nPapers++;
            for (const h of hs) papers[h]++;
            if (rcr10 && rcr10[i] >= 0) for (const h of hs) { rcrSum[h] += rcr10[i] / 10; rcrN[h]++; }
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
        // Ranked links feed the map, the panel and the table: the strength
        // minimum and the region apply to all three. × expected stays national.
        const R = this._regionSet;
        const inRegion = i => !R || R.has(this.hubs[i].state);
        const ranked = links.filter(l => (!relative || l.f >= MIN_SHARED_FOR_RELATIVE) && value(l) >= st.minLink &&
                                         inRegion(l.a) && inRegion(l.b))
            .sort((x, y) => value(y) - value(x));
        const rcrMean = rcr10 ? Array.from(rcrSum, (s, h) => (rcrN[h] ? s / rcrN[h] : NaN)) : null;
        return { papers, cross, strength, links, ranked, value, nPapers, nMulti, rcrMean };
    }

    /** Papers per institution under the current controls (and with the selected hub). */
    computeInstitutions() {
        if (!this.inst) return null;
        const m = this.inst.institutions.length, sel = this.selected;
        const n = this.n;
        const count = new Uint32Array(m), withSel = new Uint32Array(m);
        const byHub = new Uint32Array(m * n);          // papers per (institution, hub)
        // Papers with a non-hub co-author located in each state (with the selected hub, if any).
        const list = this.inst.institutions;
        const stateOf = list.map(d => (d.kind === 'other' ? d.state : null));
        const byState = new Map();
        const { rows, inst } = this.inst;
        for (let r = 0; r < rows.length; r++) {
            const hs = this._paperHubs(rows[r]);
            if (!hs) continue;
            const has = sel != null && hs.includes(sel);
            const seen = new Set();
            for (const id of inst[r]) {
                count[id]++;
                if (has) withSel[id]++;
                for (const h of hs) byHub[id * n + h]++;
                if (stateOf[id] && (sel == null || has)) seen.add(stateOf[id]);
            }
            for (const s of seen) byState.set(s, (byState.get(s) || 0) + 1);
        }
        return { count, withSel, byHub, byState };
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
        this._active = this._filtersActive();
        this._renderActiveFilters();
        this._regionSet = this._regionStates();
        this.net = this.compute();
        this.instNet = (st.showPartner || st.showOther || st.shadeStates) ? this.computeInstitutions() : null;
        // Lines per institution applies only to institution lines with no hub selected.
        const perOn = (st.partnerLines || st.otherLines) && this.selected == null;
        const per = document.getElementById('co-inst-lines-label');
        document.getElementById('co-inst-lines').disabled = !perOn;
        per.classList.toggle('co-disabled', !perOn);
        per.title = perOn ? 'How many hubs each institution draws lines to'
            : this.selected != null ? 'With a hub selected, each institution has one line: to that hub'
            : 'Turn on lines to partner or other non-hub institutions to use this';
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
        // circle so each stays visible and clickable. Hubs outside the region in focus get no position.
        const R = this._regionSet;
        const pts = this.hubs.map(h => (h.lat == null || (R && !R.has(h.state)) ? null : projection([h.lon, h.lat])));
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
        const list = this.inst.institutions, R = this._regionSet;
        const pick = kind => list.map((d, id) => id).filter(id => {
            const d = list[id];
            if (d.kind !== kind || !val[id] || (R && !R.has(d.state))) return false;
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

    /** Lines from shown institutions to the hubs they publish with: each
     *  institution's top hubs, or only the selected hub. A partner's line to
     *  its own hub is affiliation, not collaboration, so it is not drawn. */
    _institutionLines(marks, pos) {
        const st = this.state, sel = this.selected, n = this.n;
        if (!marks.length || !(st.partnerLines || st.otherLines)) return [];
        const { byHub } = this.instNet;
        const out = [];
        for (const m of marks) {
            const kind = m.d.kind;
            if (!(kind === 'partner' ? st.partnerLines : st.otherLines)) continue;
            let hubs = [];
            for (let h = 0; h < n; h++) {
                const c = byHub[m.id * n + h];
                if (!c || !pos[h] || (kind === 'partner' && h === m.d.hub)) continue;
                if (sel != null && h !== sel) continue;
                hubs.push([h, c]);
            }
            hubs.sort((x, y) => y[1] - x[1]);
            if (sel == null && st.instLinesPer) hubs = hubs.slice(0, st.instLinesPer);
            for (const [h, c] of hubs) out.push({ m, h, c });
        }
        return out.sort((a, b) => a.c - b.c);   // strongest on top
    }

    /** A link's path: straight, or (with curved lines on) bowed to one side by
     *  an eighth of its length, always the same way so parallel links stay apart. */
    _arc(p, q) {
        const r = v => Math.round(v * 10) / 10;
        if (!this.state.curved) return `M${r(p[0])},${r(p[1])}L${r(q[0])},${r(q[1])}`;
        const [a, b] = p[0] <= q[0] ? [p, q] : [q, p];
        const cx = (a[0] + b[0]) / 2 + 0.25 * (b[1] - a[1]), cy = (a[1] + b[1]) / 2 - 0.25 * (b[0] - a[0]);
        return `M${r(a[0])},${r(a[1])}Q${r(cx)},${r(cy)} ${r(b[0])},${r(b[1])}`;
    }

    /** Per-hub values for a hub size key, or for a hub color key with
     *  `color` set (NaN where unknown). */
    _hubValues(key, color = false) {
        const { papers, cross, rcrMean } = this.net;
        const num = v => (v == null || v === '' ? NaN : +v);
        return this.hubs.map((h, i) => {
            switch (key) {
                case 'papers': return papers[i];
                case 'cross': return !color ? cross[i] : (papers[i] ? 100 * cross[i] / papers[i] : NaN);
                case 'dollars': return h.award_total || 0;
                case 'nonhub': return num(h.outreach?.pct_with_nonhub_coauthor);
                case 'rcr': return rcrMean ? rcrMean[i] : NaN;
                case 'first': return num(h.award_first);
                default: return NaN;
            }
        });
    }

    _drawMap() {
        const wrap = document.getElementById('co-map-wrap');
        const st = this.state;
        const width = this._layoutWidth || Math.max(320, wrap.clientWidth - 16);
        const height = Math.round(width * 0.6);
        const svg = d3.select('#co-map').attr('viewBox', `0 0 ${width} ${height}`)
            .attr('width', width).attr('height', height);
        svg.selectAll('*').remove();
        const root = svg.append('g');

        // A region in focus fills the map. Alaska and Hawaii are insets, so they
        // are left out of the fit.
        const R = this._regionSet;
        const code = f => f.properties.stusps;
        const focus = R ? { type: 'FeatureCollection', features: this.geo.features.filter(f =>
            R.has(code(f)) && code(f) !== 'AK' && code(f) !== 'HI') } : this.geo;
        const projection = R ? d3.geoAlbersUsa().fitExtent([[12, 12], [width - 12, height - 12]], focus)
            : d3.geoAlbersUsa().fitSize([width, height], this.geo);
        const path = d3.geoPath(projection);
        const byState = st.shadeStates && this.instNet ? this.instNet.byState : null;
        const stateMax = byState ? Math.max(1, ...[...byState].filter(([s]) => !R || R.has(s)).map(([, v]) => v)) : 1;
        this._stateMax = byState ? stateMax : null;
        root.append('g').attr('class', 'co-states').selectAll('path')
            .data(this.geo.features).join('path').attr('d', path)
            .classed('co-state-out', f => R && !R.has(code(f)))
            .style('fill', f => (byState && (!R || R.has(code(f)))
                ? COLLAB_STATE_RAMP(Math.sqrt((byState.get(code(f)) || 0) / stateMax)) : null))
            .on('pointermove', byState ? (e, f) => {
                if (R && !R.has(code(f))) return this._tip(null);
                const v = byState.get(code(f)) || 0;
                this._tip(e, [[`${v.toLocaleString()} papers`, 'strong'],
                    [`with a co-author at a non-hub institution in ${f.properties.name}`, ''],
                    ...(this.selected != null ? [[`and ${this.hubs[this.selected].label}`, 'muted']] : [])]);
            } : null)
            .on('pointerleave', byState ? () => this._tip(null) : null);

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
        if (!this.state.showHubLinks) shown = [];
        gl.selectAll(null).data([...shown].reverse()).join('path')
            .attr('d', l => this._arc(pos[l.a], pos[l.b])).attr('fill', 'none')
            .attr('stroke', l => COLLAB_RAMP(this._linkT(l))).attr('stroke-linecap', 'round')
            .attr('stroke-width', l => 0.8 + 6.2 * this._linkT(l))
            .attr('stroke-opacity', l => 0.35 + 0.6 * this._linkT(l));
        // Wide transparent strokes so a thin link is still easy to hover.
        gl.selectAll(null).data(shown).join('path').attr('class', 'co-link-hit')
            .attr('d', l => this._arc(pos[l.a], pos[l.b])).attr('fill', 'none')
            .attr('stroke', 'transparent').attr('stroke-width', 9)
            .on('pointermove', (e, l) => this._tip(e, this._linkTip(l)))
            .on('pointerleave', () => this._tip(null))
            .on('click', (e, l) => { this.selectedLink = { a: l.a, b: l.b }; this.selectedInst = null; this._renderPanel(); });

        // Partner and non-hub institutions, under the hubs.
        const marks = this._institutionMarks(projection);
        const instLines = this._institutionLines(marks, pos);
        this._instLineMax = Math.max(1, ...instLines.map(d => d.c));
        const iw = c => 0.5 + 3.5 * Math.sqrt(c / this._instLineMax);
        const gil = root.append('g').attr('class', 'co-links co-inst-links');
        gil.selectAll(null).data(instLines).join('path')
            .attr('d', d => this._arc([d.m.x, d.m.y], pos[d.h])).attr('fill', 'none')
            .attr('stroke', d => COLLAB_COLORS[d.m.d.kind]).attr('stroke-linecap', 'round')
            .attr('stroke-width', d => iw(d.c)).attr('stroke-opacity', d => 0.2 + 0.5 * Math.sqrt(d.c / this._instLineMax));
        gil.selectAll(null).data(instLines).join('path').attr('class', 'co-link-hit')
            .attr('d', d => this._arc([d.m.x, d.m.y], pos[d.h])).attr('fill', 'none')
            .attr('stroke', 'transparent').attr('stroke-width', 7)
            .on('pointermove', (e, d) => this._tip(e, [[`${d.c.toLocaleString()} shared papers`, 'strong'],
                [`${d.m.d.name} – ${this.hubs[d.h].label}`, 'muted']]))
            .on('pointerleave', () => this._tip(null));
        const gi = root.append('g').attr('class', 'co-insts');
        const instDots = gi.selectAll('circle').data(marks).join('circle')
            .attr('cx', m => m.x).attr('cy', m => m.y)
            .attr('fill', m => COLLAB_COLORS[m.d.kind]).attr('fill-opacity', 0.85)
            .attr('stroke', '#fff').style('cursor', 'pointer')
            .on('pointermove', (e, m) => this._tip(e, this._instTip(m)))
            .on('pointerleave', () => this._tip(null))
            .on('click', (e, m) => { this.selectedInst = m.id; this.selectedLink = null; this._renderPanel(); });

        // Hubs on the map. Scales use all of them, so sizes and colors hold
        // when the hub dots are switched off and only the selected hub shows.
        const onMap = this.hubs.map((_, i) => i).filter(i => pos[i] && !this.hidden.has(i) && papers[i]);
        const visible = st.showHubs ? onMap : onMap.filter(i => i === sel);
        const sizeV = this._hubValues(st.sizeBy);
        const maxP = Math.max(1, ...onMap.map(i => sizeV[i] || 0));
        const radius = i => 3 + 16 * Math.sqrt((sizeV[i] || 0) / maxP);
        this._hubSize = { max: maxP };
        let fill = () => COLLAB_COLORS.hub;
        this._hubColor = null;
        if (st.colorBy !== 'none') {
            const cv = this._hubValues(st.colorBy, true);
            const known = onMap.map(i => cv[i]).filter(Number.isFinite);
            const lo = Math.min(...known), hi = Math.max(...known);
            fill = i => (Number.isFinite(cv[i]) ? COLLAB_METRIC_RAMP(hi > lo ? (cv[i] - lo) / (hi - lo) : 0.5) : COLLAB_NO_VALUE);
            this._hubColor = { lo, hi, missing: known.length < onMap.length, values: cv };
        }
        const dim = i => sel != null && i !== sel && !partners.has(i);
        const gn = root.append('g').attr('class', 'co-nodes');
        const dots = gn.selectAll('circle').data(visible).join('circle')
            .attr('cx', i => pos[i][0]).attr('cy', i => pos[i][1])
            .attr('fill', fill)
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

        const bySize = [...visible].sort((a, b) => papers[b] - papers[a]);
        const mode = this.state.labels;
        const isVisible = new Set(visible);
        const order = (mode === 'none' ? []
            : sel != null ? [sel, ...this.shownLinks.slice(0, mode === 'all' ? this.shownLinks.length : 10).map(l => (l.a === sel ? l.b : l.a)),
                             ...(mode === 'all' ? bySize : [])]
            : (mode === 'all' ? bySize : bySize.slice(0, width < 560 ? 7 : 14))).filter(i => isVisible.has(i));
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

    /** The legend as data, drawn as HTML on the page and as SVG in exports. */
    _legendModel(maxP, marks) {
        const st = this.state, relative = st.measure === 'relative', sel = this.selected;
        const r = v => 3 + 16 * Math.sqrt(v / maxP);
        const dot = (radius, color, label) => ({ type: 'dot', r: radius, color, label });
        const groups = [];
        const hubsShown = st.showHubs || sel != null;
        const hubFill = this._hubColor ? COLLAB_METRIC_RAMP(0.5) : COLLAB_COLORS.hub;
        const kinds = [];
        if (hubsShown) kinds.push(dot(5, hubFill, st.showHubs ? 'CTSA hub' : 'Selected hub'));
        if (st.showPartner) kinds.push(dot(4, COLLAB_COLORS.partner, 'Partner institution'));
        if (st.showOther) kinds.push(dot(4, COLLAB_COLORS.other, 'Other non-hub institution'));
        if (kinds.length) groups.push({ title: null, items: kinds });
        if (hubsShown) {
            const size = HUB_SIZE_BY[st.sizeBy];
            groups.push({ title: `Hub size: ${size.label}`, items: [maxP, maxP / 4, maxP / 16].map(v =>
                dot(r(v), hubFill, size.fmt(v))) });
            if (this._hubColor && Number.isFinite(this._hubColor.lo)) {
                const { lo, hi, missing } = this._hubColor, color = HUB_COLOR_BY[st.colorBy];
                const items = [lo, (lo + hi) / 2, hi].map((v, k) => dot(5, COLLAB_METRIC_RAMP(k / 2), color.fmt(v)));
                if (missing) items.push(dot(5, COLLAB_NO_VALUE, 'No data'));
                groups.push({ title: `Hub color: ${color.label}`, items });
            }
        }
        if (st.showHubLinks) {
            const top = this._linkTop;
            const fake = v => this._linkT(relative ? { rel: v } : { w: v });
            const samples = relative
                ? [Math.sqrt(top), Math.pow(top, 0.75), top].filter((v, k, a) => k === 0 || v > a[k - 1] + 0.05)
                : [top / 4, top / 2, top];
            groups.push({
                title: `Hub link: ${relative ? 'times the expected rate' : (st.counting === 'fractional' ? 'fractional papers' : 'shared papers')}` +
                       (sel != null ? ` (scaled to ${this.hubs[sel].label}'s strongest tie)` : ''),
                items: samples.map(v => {
                    const t = fake(v);
                    return { type: 'line', width: 0.8 + 6.2 * t, color: COLLAB_RAMP(t), opacity: 0.35 + 0.6 * t,
                             label: relative ? `${fmtX(v)}${sel == null && v === RELATIVE_MAX ? '+' : ''}` : Math.round(v).toLocaleString() };
                }) });
        }
        const instKinds = [st.partnerLines && 'partner', st.otherLines && 'other'].filter(Boolean);
        if (instKinds.length && marks.length) {
            const mx = this._instLineMax || 1;
            groups.push({ title: 'Institution link: shared papers', items: [mx, mx / 4].map(v => ({
                type: 'line', width: 0.5 + 3.5 * Math.sqrt(v / mx), color: COLLAB_COLORS[instKinds[0]],
                opacity: 0.2 + 0.5 * Math.sqrt(v / mx), label: Math.max(1, Math.round(v)).toLocaleString() })) });
        }
        if (marks.length) {
            groups.push({ title: `Institution size: papers ${sel == null ? 'with hubs' : 'with the selected hub'}`,
                          items: [{ type: 'text', label: `${marks.length.toLocaleString()} shown, from ${this.inst.from_year}` }] });
        }
        if (this._stateMax) {
            const mx = this._stateMax;
            groups.push({ title: `State shading: papers with a non-hub co-author there${sel != null ? ' (and the selected hub)' : ''}`,
                          items: [mx / 16, mx / 4, mx].map(v => ({ type: 'box', color: COLLAB_STATE_RAMP(Math.sqrt(v / mx)),
                                                                   label: Math.max(1, Math.round(v)).toLocaleString() })) });
        }
        return groups;
    }

    _drawLegend(maxP, marks) {
        // HTML, not SVG, so the keys wrap onto separate lines on a phone.
        this._legend = this._legendModel(maxP, marks);
        const mark = it => {
            if (it.type === 'dot') {
                const h = Math.max(16, 2 * it.r + 4);
                return `<svg width="${2 * it.r + 4}" height="${h}" aria-hidden="true"><circle cx="${it.r + 2}" cy="${h / 2}"
                    r="${it.r}" fill="${it.color}" stroke="#fff" stroke-width="1.5"/></svg>`;
            }
            if (it.type === 'line') {
                return `<svg width="30" height="16" aria-hidden="true"><line x1="2" x2="28" y1="8" y2="8" stroke="${it.color}"
                    stroke-linecap="round" stroke-opacity="${it.opacity}" stroke-width="${it.width}"/></svg>`;
            }
            if (it.type === 'box') {
                return `<svg width="18" height="14" aria-hidden="true"><rect x="1" y="2" width="16" height="10" rx="2"
                    fill="${it.color}" stroke="#c9d3dc"/></svg>`;
            }
            return '';
        };
        document.getElementById('co-legend').innerHTML = this._legend.map(g => `
            <div class="co-legend-group">${g.title ? `<span class="co-legend-title">${escHtml(g.title)}</span>` : ''}
                ${g.items.map(it => `<span class="co-legend-item">${mark(it)}${escHtml(it.label)}</span>`).join('')}</div>`).join('');
    }

    // ---------------------------------------------------------------- export

    /** One line per setting that shapes the picture, for the exported caption. */
    _captionLines() {
        const st = this.state, f = this.filters, A = this.attrs;
        const parts = [NETWORKS[st.network].label,
            st.measure === 'relative' ? 'link strength relative to expected' : 'link strength in shared papers',
            `${st.counting} counting`, `${st.from}–${st.to}`];
        if (st.noConsortium) parts.push(`papers naming ${this.data.consortium_hubs}+ hubs left out`);
        const lines = [parts.join(' · ')];
        const more = [];
        if (this._regionSet) more.push(`region: ${this._regionLabel()}`);
        if (st.minLink) more.push(`links of at least ${st.measure === 'relative' ? `×${st.minLink} expected` : `${st.minLink} papers`}`);
        if (st.sizeBy !== 'papers') more.push(`hub size: ${HUB_SIZE_BY[st.sizeBy].label}`);
        if (st.colorBy !== 'none') more.push(`hub color: ${HUB_COLOR_BY[st.colorBy].label}`);
        if (this.selected != null) more.push(`selected: ${this.hubs[this.selected].label}`);
        if (this.hidden.size) more.push(`hidden: ${[...this.hidden].map(i => this.hubs[i].label).join(', ')}`);
        if (this._active) {
            if (f.theme >= 0) more.push(`theme: ${A.themes[f.theme].label.split(';')[0]}`);
            if (f.funding !== 'all') more.push(`funding: ${FUNDING_LABELS[f.funding].split(' (')[0]}`);
            if (f.grant) more.push(f.grant.label);
            if (f.role !== 'any') more.push('first or last author only');
            if (f.researchOnly) more.push('research articles');
            if (f.rcrMin > 0) more.push(`RCR ≥ ${f.rcrMin}`);
            if (f.tri >= 0) more.push(`translational: ${TRI_LABELS[f.tri]}`);
        }
        if (more.length) lines.push(more.join(' · '));
        lines.push(document.getElementById('co-summary').textContent);
        return lines;
    }

    /** The figure as a standalone SVG: title, caption, the map as shown
     *  (including zoom), legend and source line. `mm` gives the file a
     *  physical width for print. */
    _exportSvg(title = 'CTSA hub collaboration', mm = null) {
        const map = document.getElementById('co-map');
        const mw = +map.getAttribute('width'), mh = +map.getAttribute('height');
        const pad = 20, W = mw + 2 * pad, cw = 5.7;                 // cw: approx. px per 11px legend character
        const wrap = (text, size) => {
            const max = Math.floor((W - 2 * pad) / (size * 0.55)), out = [];
            let line = '';
            for (const word of text.split(' ')) {
                if ((line + ' ' + word).trim().length > max) { out.push(line); line = word; }
                else line = (line + ' ' + word).trim();
            }
            if (line) out.push(line);
            return out;
        };
        const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
        let y = pad - 4, out = '';
        for (const line of wrap(title || ' ', 18)) {
            y += 22;
            out += `<text x="${pad}" y="${y}" class="x-title">${esc(line)}</text>`;
        }
        y += 8;
        for (const line of this._captionLines().flatMap(l => wrap(l, 11))) {
            y += 15;
            out += `<text x="${pad}" y="${y}" class="x-cap">${esc(line)}</text>`;
        }
        y += 12;
        out += `<svg x="${pad}" y="${y}" width="${mw}" height="${mh}" viewBox="0 0 ${mw} ${mh}">${map.innerHTML}</svg>`;
        out += `<rect x="${pad}" y="${y}" width="${mw}" height="${mh}" fill="none" stroke="#e0e0e0"/>`;
        y += mh + 18;
        // Legend: items flow left to right and wrap.
        let x = pad;
        for (const g of this._legend || []) {
            const titleW = g.title ? g.title.length * cw + 10 : 0;
            const markW = it => (it.type === 'dot' ? 2 * it.r + 8 : it.type === 'line' ? 34 : it.type === 'box' ? 22 : 0);
            const itemsW = g.items.reduce((sum, it) => sum + markW(it) + it.label.length * cw + 14, 0);
            if (x > pad && x + titleW + itemsW > W - pad) { x = pad; y += 26; }
            if (g.title) { out += `<text x="${x}" y="${y + 4}" class="x-leg-t">${esc(g.title)}</text>`; x += titleW; }
            for (const it of g.items) {
                if (it.type === 'dot') {
                    out += `<circle cx="${x + it.r + 2}" cy="${y}" r="${it.r}" fill="${it.color}" stroke="#fff" stroke-width="1.5"/>`;
                    x += 2 * it.r + 8;
                } else if (it.type === 'line') {
                    out += `<line x1="${x}" x2="${x + 26}" y1="${y}" y2="${y}" stroke="${it.color}" stroke-linecap="round"
                        stroke-opacity="${it.opacity}" stroke-width="${it.width}"/>`;
                    x += 34;
                } else if (it.type === 'box') {
                    out += `<rect x="${x}" y="${y - 5}" width="16" height="10" rx="2" fill="${it.color}" stroke="#c9d3dc"/>`;
                    x += 22;
                }
                out += `<text x="${x}" y="${y + 4}" class="x-leg">${esc(it.label)}</text>`;
                x += it.label.length * cw + 14;
            }
            x += 16;
        }
        y += 12;
        const source = `Source: IMPACT-NCATS (dantyrr.github.io/IMPACT-NCATS), data of ${this.data.generated}. ` +
                       'PubMed affiliations, NIH RePORTER, iCite; US Census Bureau boundaries and Gazetteer.';
        for (const line of wrap(source, 10)) {
            y += 14;
            out += `<text x="${pad}" y="${y}" class="x-src">${esc(line)}</text>`;
        }
        const H = y + pad;
        const style = `
            .co-states path { fill: #eef2f5; stroke: #c9d3dc; stroke-width: 0.8; vector-effect: non-scaling-stroke; }
            .co-states path.co-state-out { fill: #f7f9fa; stroke: #e1e7ec; }
            .co-links path { vector-effect: non-scaling-stroke; }
            .co-label { font-family: Helvetica, Arial, sans-serif; fill: #2c3e50; paint-order: stroke; stroke: #fff; stroke-linejoin: round; }
            .co-label-sel { font-weight: 700; }
            text.x-title { font: 700 18px Helvetica, Arial, sans-serif; fill: #1a5276; }
            text.x-cap { font: 11px Helvetica, Arial, sans-serif; fill: #2c3e50; }
            text.x-leg-t { font: 700 11px Helvetica, Arial, sans-serif; fill: #7f8c8d; }
            text.x-leg { font: 11px Helvetica, Arial, sans-serif; fill: #7f8c8d; }
            text.x-src { font: 10px Helvetica, Arial, sans-serif; fill: #7f8c8d; }`;
        const size = mm ? `width="${mm}mm" height="${(mm * H / W).toFixed(1)}mm"` : `width="${W}" height="${H}"`;
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" ${size} viewBox="0 0 ${W} ${H}">` +
                    `<style>${style}</style><rect width="${W}" height="${H}" fill="#fff"/>${out}</svg>`;
        return { svg, W, H };
    }

    /** The export SVG for a figure size. Other sizes redraw the map at that
     *  width (keeping the view, zoom included), then restore the screen map. */
    _figureSvg(sizeKey, title) {
        const size = FIGURE_SIZES[sizeKey];
        if (!size.width) return this._exportSvg(title);
        const keep = { t: this.zoomT || d3.zoomIdentity, w: this.zoomWidth };
        const mapW = Math.max(320, size.width - 40);   // the figure adds 20px margins
        const s = keep.w ? mapW / keep.w : 1;
        this._layoutWidth = mapW;
        this.zoomT = d3.zoomIdentity.translate(keep.t.x * s, keep.t.y * s).scale(keep.t.k);
        this.zoomWidth = mapW;
        try {
            this._drawMap();
            return this._exportSvg(title, size.mm);
        } finally {
            this._layoutWidth = null;
            this.zoomT = keep.t;
            this.zoomWidth = keep.w;
            this._drawMap();
        }
    }

    /** Rasterize an export SVG at `scale` times its size. */
    async _exportCanvas({ svg, W, H }, scale = 3) {
        const img = new Image();
        await new Promise((resolve, reject) => {
            img.onload = resolve;
            img.onerror = () => reject(new Error('Could not render the map image'));
            img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
        });
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(W * scale);
        canvas.height = Math.round(H * scale);
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#fff';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        return { canvas, W, H };
    }

    async _downloadFigure(format) {
        const sizeKey = document.getElementById('co-fig-size').value;
        const title = document.getElementById('co-fig-title').value.trim();
        const size = FIGURE_SIZES[sizeKey];
        const name = `${this._filename()}_map${sizeKey === 'shown' ? '' : `_${sizeKey}`}`;
        const fig = this._figureSvg(sizeKey, title);
        if (format === 'svg') {
            const a = document.createElement('a');
            a.href = URL.createObjectURL(new Blob([fig.svg], { type: 'image/svg+xml' }));
            a.download = `${name}.svg`;
            a.click();
            return;
        }
        const { W, H } = fig;
        // Print sizes rasterize at 300 dpi; the slide size at 1920 px wide.
        const scale = size.mm ? (size.mm / 25.4) * 300 / W : size.px ? size.px / W : 3;
        const { canvas } = await this._exportCanvas(fig, scale);
        const png = canvas.toDataURL('image/png');
        if (format === 'png') {
            const a = document.createElement('a');
            a.href = png;
            a.download = `${name}.png`;
            a.click();
        } else {
            const { jsPDF } = window.jspdf;
            const pw = size.mm ? size.mm * 72 / 25.4 : W, ph = pw * H / W;   // page size in points
            // Compressed: without it jsPDF stores the image raw (about 16 MB at 3x).
            const pdf = new jsPDF({ orientation: pw >= ph ? 'landscape' : 'portrait', unit: 'pt', format: [pw, ph], compress: true });
            pdf.addImage(png, 'PNG', 0, 0, pw, ph, undefined, 'FAST');
            pdf.save(`${name}.pdf`);
        }
    }

    // ---------------------------------------------------------------- tooltip

    _hubTip(i) {
        const { papers, cross } = this.net;
        const h = this.hubs[i], st = this.state;
        const lines = [[`${papers[i].toLocaleString()} papers`, 'strong'],
                       [`${cross[i].toLocaleString()} with another hub (${papers[i] ? Math.round(100 * cross[i] / papers[i]) : 0}%)`, '']];
        if (st.sizeBy === 'dollars') {
            lines.push([`${HUB_SIZE_BY[st.sizeBy].label}: ${HUB_SIZE_BY[st.sizeBy].fmt(this._hubValues(st.sizeBy)[i])}`, '']);
        }
        if (this._hubColor && st.colorBy !== 'cross') {
            const v = this._hubColor.values[i];
            lines.push([`${HUB_COLOR_BY[st.colorBy].label}: ${Number.isFinite(v) ? HUB_COLOR_BY[st.colorBy].fmt(v) : 'no data'}`, '']);
        }
        return lines.concat([[h.label, 'muted'], [`${h.city}, ${h.state}`, 'muted']]);
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
        this.selectedLink = null;
        this.selectedInst = null;
        // A hub picked from a list may be outside the region in focus: show the whole US.
        if (i != null && this._regionSet && !this._regionSet.has(this.hubs[i].state)) {
            this.state.region = 'all';
            this.zoomT = d3.zoomIdentity;
            document.getElementById('co-region').value = 'all';
        }
        this.render();
    }

    // ---------------------------------------------------------------- papers

    /** Newest first; opens up to PUBMED_MAX of them in PubMed. */
    async openPubMed(positions) {
        await this._loadAttributes();
        if (!this.attrs) return;
        const P = this.data.papers, pm = this.attrs.pmids;
        const ids = [...positions].sort((x, y) => P.y[y] - P.y[x] || pm[y] - pm[x])
            .slice(0, PUBMED_MAX).map(i => pm[i]);
        window.open(`https://pubmed.ncbi.nlm.nih.gov/?term=${encodeURIComponent(ids.join(','))}&size=${PUBMED_MAX}`,
                    '_blank', 'noopener');
    }

    async downloadPapers(positions, name) {
        await this._loadAttributes();
        if (!this.attrs) return;
        const P = this.data.papers, A = this.attrs, st = this.state;
        const hubsOf = i => this.sets[st.network][i].map(h => this.hubs[h].label).join('; ');
        ChartManager.downloadCSV([
            ['pmid', 'year', 'hubs', 'theme', 'rcr', 'research_article', 'grants', 'pubmed_url'],
            ...[...positions].sort((x, y) => P.y[y] - P.y[x]).map(i => [
                A.pmids[i], P.y[i], hubsOf(i), A.theme[i] >= 0 ? A.themes[A.theme[i]].label : '',
                A.rcr10[i] >= 0 ? (A.rcr10[i] / 10).toFixed(1) : '', A.research[i] === 1 ? 1 : 0,
                A.grants[i].map(g => A.grant_list[g].num).join('; '),
                `https://pubmed.ncbi.nlm.nih.gov/${A.pmids[i]}/`])], `${this._filename()}_${name}_papers`);
    }

    /** The two paper buttons for a set of paper positions, wired by _wirePaperButtons. */
    _paperButtons(key, n) {
        return n ? `<div class="co-actions">
            <button class="download-btn" data-papers-open="${key}">Open ${n > PUBMED_MAX ? `newest ${PUBMED_MAX}` : 'all'} in PubMed</button>
            <button class="download-btn" data-papers-csv="${key}">Paper list CSV</button></div>` : '';
    }

    _wirePaperButtons(el, sets) {
        el.querySelectorAll('[data-papers-open]').forEach(b => b.addEventListener('click', () =>
            this.openPubMed(sets[b.dataset.papersOpen]())));
        el.querySelectorAll('[data-papers-csv]').forEach(b => b.addEventListener('click', () =>
            this.downloadPapers(sets[b.dataset.papersCsv](), b.dataset.papersCsv)));
    }

    _partnerCell(l) {
        const relative = this.state.measure === 'relative';
        const papers = l.f.toLocaleString();
        return relative ? `${fmtX(l.rel)} <span class="co-sub">(${papers})</span>`
                        : `${papers} <span class="co-sub">(${fmtX(l.rel)})</span>`;
    }

    _renderPanel() {
        const el = document.getElementById('co-panel');
        if (this.selectedLink) return this._renderLinkPanel(el);
        if (this.selectedInst != null && this.inst) return this._renderInstPanel(el);
        const { papers, cross, strength, links, ranked } = this.net;
        const st = this.state, relative = st.measure === 'relative';
        const i = this.selected;
        const paperSets = {};
        if (i == null) {
            const top = ranked.slice(0, 10);
            el.innerHTML = `
                <h3>${relative ? 'Strongest ties' : 'Most shared papers'}</h3>
                <p class="data-note">${relative
                    ? `Pairs that share the most papers relative to what their overall collaboration predicts (at least ${MIN_SHARED_FOR_RELATIVE} shared papers).`
                    : 'Pairs with the most shared papers.'} Click a hub, on the map or here, to see its partners;
                    click a line or an institution dot to list its papers.</p>
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
                    ${h.award_first ? `· CTSA award ${h.award_first}–${h.award_last}` : ''}
                    ${h.award_total ? `· ${fmtDollars(h.award_total)} in NCATS awards` : ''}</p>
                <dl class="co-stats">
                    <dt>Papers</dt><dd>${papers[i].toLocaleString()}</dd>
                    <dt>With another hub</dt><dd>${cross[i].toLocaleString()} (${papers[i] ? (100 * cross[i] / papers[i]).toFixed(1) : 0}%)</dd>
                    <dt>Hubs it shares papers with</dt><dd>${nPartners}</dd>
                </dl>
                ${this._paperButtons('hub', papers[i])}
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
        if (i != null) paperSets.hub = () => this._papersWhere((_, hs) => hs.includes(i));
        this._wirePaperButtons(el, paperSets);
    }

    _renderLinkPanel(el) {
        const { a, b } = this.selectedLink;
        const l = this.net.links.find(x => x.a === a && x.b === b);
        const frac = this.state.counting === 'fractional';
        el.innerHTML = `
            <p><button class="co-link-btn" data-back="1">← Back</button></p>
            <h3>${escHtml(this.hubs[a].label)} – ${escHtml(this.hubs[b].label)}</h3>
            ${l ? `<dl class="co-stats">
                <dt>Shared papers</dt><dd>${l.f.toLocaleString()}</dd>
                ${frac ? `<dt>Fractional papers</dt><dd>${fmt1(l.w)}</dd>` : ''}
                <dt>Times the expected rate</dt><dd>${fmtX(l.rel)}</dd>
            </dl>
            <p class="data-note">With the current controls and filters. The list opens newest first.</p>
            ${this._paperButtons('link', l.f)}` : '<p class="data-note">These hubs share no papers with the current settings.</p>'}`;
        el.querySelector('[data-back]').addEventListener('click', () => { this.selectedLink = null; this._renderPanel(); });
        this._wirePaperButtons(el, { link: () => this._papersWhere((_, hs) => hs.includes(a) && hs.includes(b)) });
    }

    _renderInstPanel(el) {
        const id = this.selectedInst, d = this.inst.institutions[id], sel = this.selected;
        const { count, withSel } = this.instNet || this.computeInstitutions();
        const rowsOf = new Map(this.inst.rows.map((r, k) => [r, k]));
        const has = i => { const k = rowsOf.get(i); return k !== undefined && this.inst.inst[k].includes(id); };
        el.innerHTML = `
            <p><button class="co-link-btn" data-back="1">← Back</button></p>
            <h3>${escHtml(d.name)}</h3>
            <p class="data-note">${d.kind === 'partner' ? `Partner of ${escHtml(this.hubs[d.hub]?.label ?? 'a hub')}` : 'Non-hub institution'}
                · ${escHtml(d.type)}${d.city ? ` · ${escHtml(d.city)}, ${escHtml(d.state)}` : ''}</p>
            <dl class="co-stats">
                <dt>Papers with hubs</dt><dd>${count[id].toLocaleString()}</dd>
                ${sel != null ? `<dt>With ${escHtml(this.hubs[sel].label)}</dt><dd>${withSel[id].toLocaleString()}</dd>` : ''}
            </dl>
            <p class="data-note">Papers from ${this.inst.from_year} on, with the current controls and filters.</p>
            <h4>All papers with hubs</h4>${this._paperButtons('inst', count[id])}
            ${sel != null ? `<h4>With ${escHtml(this.hubs[sel].label)}</h4>${this._paperButtons('instsel', withSel[id])}` : ''}`;
        el.querySelector('[data-back]').addEventListener('click', () => { this.selectedInst = null; this._renderPanel(); });
        this._wirePaperButtons(el, {
            inst: () => this._papersWhere(i => has(i)),
            instsel: () => this._papersWhere((i, hs) => hs.includes(sel) && has(i)),
        });
    }

    _renderPairs() {
        const frac = this.state.counting === 'fractional';
        const rows = this.net.ranked.slice(0, 25);
        document.getElementById('co-pairs').innerHTML = `
            <p class="data-note">Ranked by the link strength chosen above${this._regionSet
                ? `; pairs with both hubs in the ${escHtml(this._regionLabel())}` : ''}.</p>
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
        el.innerHTML = `<div class="download-bar co-figure-bar"><span>Figure:</span>
            <label>Title <input type="text" id="co-fig-title" value="CTSA hub collaboration" size="30"></label>
            <label>Size <select id="co-fig-size">${Object.entries(FIGURE_SIZES).map(([k, v]) =>
                `<option value="${k}">${escHtml(v.label)}</option>`).join('')}</select></label>
            <button class="download-btn" data-fig="png">PNG</button>
            <button class="download-btn" data-fig="pdf">PDF</button>
            <button class="download-btn" data-fig="svg">SVG</button></div>
            <div class="download-bar"><span>Data:</span>
            <button class="download-btn" data-dl="links">Links CSV</button>
            <button class="download-btn" data-dl="hubs">Hubs CSV</button>
            <button class="download-btn" data-dl="insts">Institutions CSV</button></div>
            <p class="data-note">The figure is the map as shown (same view and zoom), with a legend and a caption listing the settings.
                Journal sizes are laid out for about 7-point text at 85 or 180 mm wide and saved at 300 dpi.</p>`;
        el.querySelectorAll('[data-dl]').forEach(b => b.addEventListener('click', () => this._download(b.dataset.dl)));
        el.querySelectorAll('[data-fig]').forEach(b => b.addEventListener('click', async () => {
            b.disabled = true;
            try { await this._downloadFigure(b.dataset.fig); }
            catch (e) { console.error('Figure export failed', e); alert('Sorry, the figure could not be exported in this browser.'); }
            finally { b.disabled = false; }
        }));
    }

    _filename() {
        const st = this.state;
        return `hub_${st.network}_${st.measure}_${st.counting}_${st.from}-${st.to}` +
               (st.noConsortium ? '_no-consortium' : '') + (this.hidden.size ? '_some-hidden' : '');
    }

    async _download(kind) {
        const { papers, cross, strength, links, rcrMean } = this.net;
        if (kind === 'links') {
            ChartManager.downloadCSV([
                ['hub_a', 'hub_b', 'state_a', 'state_b', 'times_expected', 'shared_papers', 'weight'],
                ...links.map(l => [this.hubs[l.a].label, this.hubs[l.b].label, this.hubs[l.a].state,
                                   this.hubs[l.b].state, l.rel.toFixed(4), l.f, l.w.toFixed(4)])], `${this._filename()}_links`);
        } else if (kind === 'hubs') {
            ChartManager.downloadCSV([
                ['hub', 'city', 'state', 'lat', 'lon', 'papers', 'cross_hub_papers', 'link_strength',
                 'ncats_award_dollars', 'first_ctsa_award_year', 'mean_rcr', 'hidden'],
                ...this.hubs.map((h, i) => [h.label, h.city, h.state, h.lat, h.lon, papers[i], cross[i],
                                            strength[i].toFixed(4), h.award_total ?? '', h.award_first ?? '',
                                            rcrMean && Number.isFinite(rcrMean[i]) ? rcrMean[i].toFixed(3) : '',
                                            this.hidden.has(i) ? 1 : 0])], `${this._filename()}_hubs`);
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
        }
    }
}
