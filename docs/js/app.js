/**
 * IMPACT-NCATS — main controller.
 *
 * Two analytic tabs:
 *   Site Detail  — one or more sites in depth, every metric by year and mechanism
 *   Across Sites — rank or trend all sites on any metric, plus top papers
 *
 * Both read the same metric registry (metrics-def.js), so a metric added there is
 * immediately available in both places. Keeping two separate metric lists is how
 * "award dollars" previously ended up on one tab but not the other.
 */

class NCATSApp {
    constructor() {
        this.loader = new DataLoader();
        this.index = null;
        this.siteCache = {};
        this.init();
    }

    async init() {
        this.setupNavigation();
        try {
            this.index = await this.loader.loadIndex();
        } catch (e) {
            document.getElementById('portfolio-summary').textContent =
                'Could not load data. If running locally, make sure docs/data/index.json exists.';
            console.error('Failed to load index.json', e);
            return;
        }
        this.renderPortfolioSummary();

        // Site files are small; loading them all up front keeps both tabs instant.
        const loaded = await Promise.all(
            this.index.sites.map(s => this.loader.loadSite(s.slug).catch(() => null)));
        this.index.sites.forEach((s, i) => { if (loaded[i]) this.siteCache[s.slug] = loaded[i]; });

        this.allYears = this._collectYears();
        this.allMonths = this._collectMonths();

        try {
            this.pubs = await this.loader.loadPublications();
        } catch (e) {
            this.pubs = { top_by_rcr: [], top_by_citations: [], site_rankings: [],
                          min_pubs_threshold: 25 };
            console.error('Failed to load publications.json', e);
        }

        this.setupSiteDetail();
        this.setupAcrossSites();
        this.setupGrants();
        this.setupInvestigators();
        this.renderAbout();
    }

    setupNavigation() {
        document.querySelectorAll('.nav-link').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                this.showSection(link.dataset.section);
            });
        });
        this.showSection(location.hash.replace('#', '') || 'site-detail');
    }

    showSection(sectionId) {
        // Older tab names, kept working for existing links and bookmarks.
        const ALIASES = {
            sites: 'site-detail',
            publications: 'across-sites',
            trends: 'across-sites',
            compare: 'across-sites',
        };
        sectionId = ALIASES[sectionId] || sectionId;
        if (!document.getElementById(sectionId)) sectionId = 'site-detail';

        document.querySelectorAll('.section').forEach(s =>
            s.classList.toggle('active', s.id === sectionId));
        document.querySelectorAll('.nav-link').forEach(l =>
            l.classList.toggle('active', l.dataset.section === sectionId));
        history.replaceState(null, '', `#${sectionId}`);
    }

    renderPortfolioSummary() {
        const d = this.index;
        document.getElementById('portfolio-summary').textContent =
            `${d.total_sites} CTSA sites · ${d.total_grants.toLocaleString()} NCATS grants · ` +
            `${d.total_publications.toLocaleString()} linked publications · ` +
            `${fmtMoney(d.total_award_amount)} awarded`;
    }

    // ---------------- shared helpers ----------------

    _collectYears() {
        const y = new Set();
        for (const d of Object.values(this.siteCache)) {
            for (const m of d.metrics) if (m.year) y.add(m.year);
        }
        return [...y].sort((a, b) => a - b);
    }

    _collectMonths() {
        const m = new Set();
        for (const d of Object.values(this.siteCache)) {
            for (const s of (d.snapshots || [])) m.add(s.month);
        }
        return [...m].sort();
    }

    _yearOptions(sel) {
        return this.allYears.map(y =>
            `<option value="${y}"${y === sel ? ' selected' : ''}>${y}</option>`).join('');
    }

    _mechOptions() {
        return `
            <option value="all">All</option>
            <option value="U">U — hub &amp; cooperative</option>
            <option value="K">K — career development</option>
            <option value="T">T — training</option>
            <option value="R">R — research</option>`;
    }

    /**
     * Render a PNG/JPG/PDF/CSV download bar. The getters run at click time so an
     * export always matches the controls as they are now.
     */
    _attachDownloadBar(containerId, getChart, getCsvRows, getFilename) {
        const el = document.getElementById(containerId);
        if (!el) return;
        el.innerHTML = `
            <div class="download-bar">
                <span>Download:</span>
                <button class="download-btn" data-fmt="png">PNG</button>
                <button class="download-btn" data-fmt="jpg">JPG</button>
                <button class="download-btn" data-fmt="pdf">PDF</button>
                <button class="download-btn" data-fmt="csv">CSV data</button>
            </div>`;
        el.querySelectorAll('.download-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const f = btn.dataset.fmt;
                if (f === 'csv') { ChartManager.downloadCSV(getCsvRows(), getFilename()); return; }
                const c = getChart();
                if (c) ChartManager.download(c, f, getFilename());
            });
        });
    }

    /** site_metrics rows for a site, filtered by year window and mechanism. */
    _rows(siteData, years, mech) {
        const allowed = new Set(years);
        return siteData.metrics.filter(m =>
            allowed.has(m.year) && (mech === 'all' || m.activity_group === mech));
    }

    _yearSeries(siteData, metricKey, mech, years) {
        return years.map(y => aggregateMetric(this._rows(siteData, [y], mech), metricKey));
    }

    _monthSeries(siteData, metricKey, months) {
        const by = {};
        for (const s of (siteData.snapshots || [])) by[s.month] = s[metricKey];
        return months.map(m => (by[m] === undefined ? null : by[m]));
    }

    _isRolling(key) {
        return (METRIC_BY_KEY[key] || {}).kind === 'rolling';
    }

    _monthsInRange(from, to) {
        return this.allMonths.filter(m => {
            const y = parseInt(m.slice(0, 4), 10);
            return y >= from && y <= to;
        });
    }

    // ================= SITE DETAIL =================

    setupSiteDetail() {
        this.sdSelected = [];
        this.sdPicker = new SitePicker('sd-picker', this.index.sites, ChartManager.PALETTE,
            () => { this.sdSelected = this.sdPicker.getSelected(); this.renderSiteDetail(); });

        document.getElementById('sd-controls').innerHTML = `
            <div class="controls-row">
                <label>View:
                    <select id="sd-view">
                        <option value="both" selected>Cards + combined chart</option>
                        <option value="cards">Cards only</option>
                        <option value="combined">Combined chart only</option>
                    </select>
                </label>
                <label>Combined metric:
                    <select id="sd-metric">${metricOptions('pub_count', ['count', 'rate', 'ratio'])}</select>
                </label>
                <label>Mechanism: <select id="sd-mech">${this._mechOptions()}</select></label>
                <label>From: <select id="sd-from">${this._yearOptions(Math.max(this.allYears[0], 2012))}</select></label>
                <label>To: <select id="sd-to">${this._yearOptions(this.allYears[this.allYears.length - 1])}</select></label>
            </div>`;
        ['sd-view', 'sd-metric', 'sd-mech', 'sd-from', 'sd-to'].forEach(id =>
            document.getElementById(id).addEventListener('input', () => this.renderSiteDetail()));

        this._attachDownloadBar('sd-combined-downloads',
            () => this.sdChart,
            () => this._sdCsvRows(),
            () => `ncats-sites-${document.getElementById('sd-metric').value}`);

        this.renderSiteDetail();
    }

    _sdState() {
        const from = parseInt(document.getElementById('sd-from').value, 10);
        const to = parseInt(document.getElementById('sd-to').value, 10);
        const [lo, hi] = from <= to ? [from, to] : [to, from];
        return {
            view: document.getElementById('sd-view').value,
            metric: document.getElementById('sd-metric').value,
            mech: document.getElementById('sd-mech').value,
            years: this.allYears.filter(y => y >= lo && y <= hi),
        };
    }

    renderSiteDetail() {
        const controls = document.getElementById('sd-controls');
        const combined = document.getElementById('sd-combined');
        const cards = document.getElementById('sd-cards');
        const hint = document.getElementById('sd-hint');

        if (!this.sdSelected.length) {
            controls.style.display = 'none';
            combined.style.display = 'none';
            cards.innerHTML = '';
            hint.style.display = 'block';
            return;
        }
        controls.style.display = 'block';
        hint.style.display = 'none';

        const { view, metric, mech, years } = this._sdState();
        const showCombined = view === 'both' || view === 'combined';
        combined.style.display = showCombined ? 'block' : 'none';

        if (showCombined) {
            const colors = this.sdPicker.getColorMap();
            this.sdChart = ChartManager.barChart('sd-combined-chart', years,
                this.sdSelected.map(slug => ({
                    label: this.siteCache[slug].hub_name,
                    data: this._yearSeries(this.siteCache[slug], metric, mech, years),
                    backgroundColor: colors[slug],
                    borderColor: colors[slug],
                })),
                { yLabel: metricLabel(metric) });   // grouped bars, not stacked
        }

        cards.innerHTML = (view === 'combined') ? ''
            : this.sdSelected.map(slug => this._sdCardHtml(slug, years, mech)).join('');
        if (view !== 'combined') {
            this.sdCardCharts = {};
            this.sdSelected.forEach(slug => this._sdDrawCard(slug, years, mech));
        }
    }

    /** Every metric this card reports, per year. */
    get _sdColumns() {
        return ['pub_count', 'research_count', 'citation_count', 'award_count',
                'award_total', 'mean_rcr', 'pubs_per_million',
                'citations_per_million', 'cost_per_pub'];
    }

    _sdCardHtml(slug, years, mech) {
        const d = this.siteCache[slug];
        const rows = this._rows(d, years, mech);
        const tiles = ['pub_count', 'citation_count', 'award_count', 'award_total',
                       'mean_rcr', 'citations_per_million'];
        const cols = this._sdColumns;
        const latest = (d.snapshots || []).filter(s => s.rate_24m !== null).slice(-1)[0];

        return `
        <div class="detail-panel site-card" data-slug="${slug}">
            <button class="card-close" data-slug="${slug}" title="Remove">×</button>
            <h3>${d.hub_name}</h3>
            <p class="data-note">${d.org_name} · ${d.city || ''} ${d.state || ''}
                · ${years[0]}–${years[years.length - 1]}${mech === 'all' ? '' : ` · ${mech} awards only`}</p>
            <div class="metric-row">
                ${tiles.map(k => `<div class="metric">
                    <span class="metric-value">${metricFmt(k, aggregateMetric(rows, k))}</span>
                    <span class="metric-label">${metricLabel(k)}</span></div>`).join('')}
                ${latest ? `<div class="metric">
                    <span class="metric-value">${fmt(latest.rate_24m)}</span>
                    <span class="metric-label">Rolling rate (24-mo, ${latest.month})</span></div>` : ''}
            </div>
            <div class="chart-container"><canvas id="sd-chart-${slug}"></canvas></div>
            <div class="download-bar">
                <span>Download:</span>
                <button class="download-btn" data-slug="${slug}" data-fmt="png">PNG</button>
                <button class="download-btn" data-slug="${slug}" data-fmt="jpg">JPG</button>
                <button class="download-btn" data-slug="${slug}" data-fmt="pdf">PDF</button>
                <button class="download-btn" data-slug="${slug}" data-fmt="csv">CSV data</button>
            </div>
            <details open>
                <summary>Metrics by year</summary>
                <div class="table-scroll">
                <table class="data-table compact">
                    <thead><tr><th>Year</th>${cols.map(k => `<th>${metricLabel(k)}</th>`).join('')}</tr></thead>
                    <tbody>${years.map(y => {
                        const yr = this._rows(d, [y], mech);
                        if (!yr.length) return '';
                        return `<tr><td>${y}</td>${cols.map(k =>
                            `<td>${metricFmt(k, aggregateMetric(yr, k))}</td>`).join('')}</tr>`;
                    }).join('')}</tbody>
                </table></div>
            </details>
            <details>
                <summary>Awards (${d.grants.length})</summary>
                <div class="table-scroll">
                <table class="data-table compact">
                    <thead><tr><th>Core project</th><th>Activity</th><th>Title</th><th>Years</th><th>Awarded</th></tr></thead>
                    <tbody>${d.grants.map(g => `
                        <tr>
                            <td><a href="https://reporter.nih.gov/search/?projectNums=${g.core_project_num}" target="_blank" rel="noopener">${g.core_project_num}</a></td>
                            <td>${g.activity_code || '—'}</td>
                            <td>${g.title || '—'}</td>
                            <td>${g.first_fy}–${g.last_fy}</td>
                            <td>${fmtMoney(g.total_award_amount)}</td>
                        </tr>`).join('')}
                    </tbody>
                </table></div>
            </details>
        </div>`;
    }

    _sdDrawCard(slug, years, mech) {
        const d = this.siteCache[slug];
        const groups = [...new Set(d.metrics.map(m => m.activity_group))].sort()
            .filter(g => mech === 'all' || g === mech);

        const chart = ChartManager.barChart(`sd-chart-${slug}`, years,
            groups.map((g, i) => ({
                label: `${g} awards`,
                data: years.map(y => {
                    const row = d.metrics.find(m => m.year === y && m.activity_group === g);
                    return row ? row.pub_count : 0;
                }),
                backgroundColor: ChartManager.color(i),
                borderColor: ChartManager.color(i),
            })),
            { stacked: true, yLabel: 'Publications' });
        this.sdCardCharts[slug] = chart;

        const card = document.querySelector(`.site-card[data-slug="${slug}"]`);
        if (!card) return;
        card.querySelector('.card-close').addEventListener('click', () => {
            this.sdPicker.selected = this.sdPicker.selected.filter(s => s !== slug);
            this.sdPicker._renderChips();
            this.sdSelected = this.sdPicker.getSelected();
            this.renderSiteDetail();
        });
        card.querySelectorAll('.download-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const name = `ncats-${slug}`;
                if (btn.dataset.fmt === 'csv') {
                    const cols = this._sdColumns;
                    ChartManager.downloadCSV(
                        [['site', 'year', ...cols],
                         ...years.map(y => {
                             const yr = this._rows(d, [y], mech);
                             return [d.hub_name, y, ...cols.map(k => aggregateMetric(yr, k) ?? '')];
                         })], name);
                } else {
                    ChartManager.download(chart, btn.dataset.fmt, name);
                }
            });
        });
    }

    _sdCsvRows() {
        const { metric, mech, years } = this._sdState();
        const rows = [['site', 'year', metric]];
        for (const slug of this.sdSelected) {
            const series = this._yearSeries(this.siteCache[slug], metric, mech, years);
            series.forEach((v, i) => rows.push([this.siteCache[slug].hub_name, years[i], v ?? '']));
        }
        return rows;
    }

    // ================= ACROSS SITES =================

    setupAcrossSites() {
        const thr = this.pubs.min_pubs_threshold;
        document.getElementById('as-controls').innerHTML = `
            <div class="controls-row">
                <label>Metric: <select id="as-metric">${metricOptions('pub_count')}</select></label>
                <label>View:
                    <select id="as-view">
                        <option value="rank" selected>Ranking</option>
                        <option value="time">Over time</option>
                    </select>
                </label>
                <label>Show:
                    <select id="as-topn">
                        <option value="10" selected>Top 10</option>
                        <option value="20">Top 20</option>
                        <option value="0">All sites</option>
                    </select>
                </label>
                <label>Mechanism: <select id="as-mech">${this._mechOptions()}</select></label>
                <label>From: <select id="as-from">${this._yearOptions(Math.max(this.allYears[0], 2012))}</select></label>
                <label>To: <select id="as-to">${this._yearOptions(this.allYears[this.allYears.length - 1])}</select></label>
                <label title="Later years are still filling in as papers are published and reported">
                    <input type="checkbox" id="as-drop-partial" checked> Hide incomplete recent years
                </label>
                <label title="One very large site can flatten every other line">
                    <input type="checkbox" id="as-log"> Log scale
                </label>
                <label title="A site with very few scored papers can post an extreme average">
                    <input type="checkbox" id="as-min" checked> Only sites with ≥${thr} scored papers
                </label>
            </div>`;
        ['as-metric', 'as-view', 'as-topn', 'as-mech', 'as-from', 'as-to',
         'as-drop-partial', 'as-log', 'as-min'].forEach(id =>
            document.getElementById(id).addEventListener('input', () => this.renderAcross()));

        this._attachDownloadBar('as-downloads',
            () => this.asChart,
            () => this._asCsvRows(),
            () => `ncats-across-sites-${document.getElementById('as-metric').value}`);

        document.getElementById('as-paper-controls').innerHTML = `
            <div class="controls-row">
                <label>Rank papers by:
                    <select id="as-paper-metric">
                        <option value="top_by_rcr">RCR</option>
                        <option value="top_by_citations">Citations</option>
                    </select>
                </label>
                <label><input type="checkbox" id="as-research-only"> Research articles only</label>
                <input type="text" id="as-paper-search" placeholder="Filter by title, journal, or site…">
            </div>
            <p class="data-note" id="as-paper-count"></p>`;
        ['as-paper-metric', 'as-research-only', 'as-paper-search'].forEach(id =>
            document.getElementById(id).addEventListener('input', () => this.renderPapers()));

        this._attachDownloadBar('as-paper-downloads',
            () => null,   // the paper list is a table, so image formats do not apply
            () => [['rank', 'pmid', 'title', 'journal', 'year', 'rcr', 'citations', 'sites'],
                   ...(this.papersShown || []).map((p, i) =>
                       [i + 1, p.pmid, p.title, p.journal, p.year, p.rcr, p.citations,
                        p.sites.join('; ')])],
            () => `ncats-top-papers-${document.getElementById('as-paper-metric').value}`);

        this.asSort = { key: 'pub_count', dir: 'desc' };
        this.renderAcross();
        this.renderPapers();
    }

    _asState() {
        const metric = document.getElementById('as-metric').value;
        const from = parseInt(document.getElementById('as-from').value, 10);
        const to = parseInt(document.getElementById('as-to').value, 10);
        const [lo, hi] = from <= to ? [from, to] : [to, from];
        const dropPartial = document.getElementById('as-drop-partial').checked;
        const cutoff = new Date().getFullYear() - 1;

        let years = this.allYears.filter(y => y >= lo && y <= hi);
        if (dropPartial) years = years.filter(y => y <= cutoff);

        const rolling = this._isRolling(metric);
        const months = rolling
            ? this._monthsInRange(lo, dropPartial ? Math.min(hi, cutoff) : hi) : [];

        const mech = document.getElementById('as-mech').value;
        const topN = parseInt(document.getElementById('as-topn').value, 10);
        const applyMin = document.getElementById('as-min').checked;
        const thr = this.pubs.min_pubs_threshold;

        // The small-sample guard only matters for averages, not counts.
        const kind = (METRIC_BY_KEY[metric] || {}).kind;
        const needsThreshold = kind === 'rate' || kind === 'rolling';
        const small = new Set(
            this.pubs.site_rankings.filter(r => r.below_threshold).map(r => r.slug));

        let sites = this.index.sites;
        let excluded = 0;
        if (applyMin && needsThreshold) {
            const before = sites.length;
            sites = sites.filter(s => !small.has(s.slug));
            excluded = before - sites.length;
        }

        const ranked = sites.map(s => {
            const d = this.siteCache[s.slug];
            if (!d) return null;
            const series = rolling
                ? this._monthSeries(d, metric, months)
                : this._yearSeries(d, metric, mech, years);
            let total;
            if (kind === 'count') {
                total = aggregateMetric(this._rows(d, years, mech), metric);
            } else {
                // Averages and rates: mean of the non-null points in the window.
                const v = series.filter(x => x !== null && x !== undefined);
                total = v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
            }
            return { slug: s.slug, hub_name: s.hub_name, state: s.state, series, total };
        }).filter(r => r && r.total !== null).sort((a, b) => b.total - a.total);

        return { metric, mech, years, months, rolling, ranked,
                 limited: topN > 0 ? ranked.slice(0, topN) : ranked,
                 axis: rolling ? months : years,
                 cutoff, dropPartial, excluded, thr,
                 view: document.getElementById('as-view').value };
    }

    renderAcross() {
        const st = this._asState();
        const label = metricLabel(st.metric);
        const useLog = document.getElementById('as-log').checked;
        const container = document.getElementById('as-chart-container');

        if (st.view === 'rank') {
            // Horizontal bars need room per site or labels overlap into an
            // unreadable pile once "All sites" is picked. Height grows with the
            // bar count instead of squeezing everything into a fixed box.
            const perBar = 26;
            const chrome = 90; // axis + padding
            container.style.height = `${Math.max(440, st.limited.length * perBar + chrome)}px`;
        } else {
            container.style.height = '520px';
        }

        if (st.view === 'rank') {
            this.asChart = ChartManager.barChart('as-chart',
                st.limited.map(r => r.hub_name),
                [{ label, data: st.limited.map(r => r.total),
                   backgroundColor: st.limited.map((_, i) => ChartManager.color(i)) }],
                { yLabel: label,
                  chartOptions: {
                      indexAxis: 'y',
                      plugins: { legend: { display: false } },
                      scales: {
                          y: { ticks: { autoSkip: false } },
                          x: useLog ? { type: 'logarithmic' } : { beginAtZero: true },
                      },
                  } });
        } else {
            this.asChart = ChartManager.lineChart('as-chart', st.axis,
                st.limited.map((r, i) => ({
                    label: r.hub_name,
                    data: useLog ? r.series.map(v => (v === 0 ? null : v)) : r.series,
                    borderColor: ChartManager.color(i),
                    backgroundColor: ChartManager.color(i),
                    spanGaps: true, tension: 0.25, pointRadius: 2,
                })),
                { xLabel: st.rolling ? 'Month' : 'Year', yLabel: label,
                  chartOptions: useLog ? {
                      scales: { y: { type: 'logarithmic',
                                     title: { display: true, text: `${label} (log)` } } },
                  } : undefined });
        }

        this.renderAcrossTable(st);
        this.renderAcrossNote(st, label);
    }

    renderAcrossNote(st, label) {
        const isEff = EFFICIENCY_METRICS.has(st.metric);
        const span = st.axis.length
            ? `${st.axis[0]}–${st.axis[st.axis.length - 1]}` : 'no range selected';
        document.getElementById('as-note').innerHTML = `
            ${isEff ? `<p class="data-note warn">
                <strong>Read per-dollar metrics carefully.</strong> Citations accrue for years
                after money is spent, so recently funded sites look inefficient. Hub awards
                (UL1/UM1) pay for cores, staff and services rather than papers directly, and a
                paper shared by several hubs counts in full at each. A high value is not proof of
                a better-run site, and a low one is not evidence of waste.
            </p>` : ''}
            <p class="data-note">
                Showing ${st.limited.length} of ${st.ranked.length} sites by
                ${label.toLowerCase()}, ${span}.
                ${st.rolling
                    ? 'Rolling citation rates use the same formula as the main IMPACT site: citations in a 12-month window divided by research papers published in the preceding window.'
                    : ''}
                ${st.excluded
                    ? `${st.excluded} site${st.excluded === 1 ? '' : 's'} with fewer than ${st.thr} RCR-scored papers hidden, since small samples give unstable averages.`
                    : ''}
                ${st.dropPartial
                    ? `Years after ${st.cutoff} are hidden as still filling in.`
                    : '<strong>Recent years are incomplete</strong> and understate output.'}
                A publication linked to several hubs counts in full at each, so site totals sum to
                more than the ${this.index.total_publications.toLocaleString()} unique
                publications. See <a href="#about">About</a>.
            </p>`;
    }

    renderAcrossTable(st) {
        const cols = ['pub_count', 'citation_count', 'award_count', 'award_total',
                      'mean_rcr', 'citations_per_million'];
        const { key, dir } = this.asSort;

        const rows = this.index.sites.map(s => {
            const d = this.siteCache[s.slug];
            if (!d) return null;
            const r = this._rows(d, st.years, st.mech);
            const out = { slug: s.slug, hub_name: s.hub_name, state: s.state };
            for (const k of cols) out[k] = aggregateMetric(r, k);
            return out;
        }).filter(Boolean).sort((a, b) => {
            const av = a[key], bv = b[key];
            if (typeof av === 'string') {
                return dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
            }
            // Nulls always sort last, whichever direction.
            if (av === null || av === undefined) return 1;
            if (bv === null || bv === undefined) return -1;
            return dir === 'asc' ? av - bv : bv - av;
        });

        const head = [['hub_name', 'Site'], ['state', 'State'],
                      ...cols.map(k => [k, metricLabel(k)])];
        const container = document.getElementById('as-table-container');
        container.innerHTML = `
            <p class="data-note">Click a site to open it in Site Detail.</p>
            <div class="table-scroll">
            <table class="data-table compact">
                <thead><tr>${head.map(([k, l]) =>
                    `<th class="sortable" data-key="${k}">${l}${key === k ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}</th>`
                ).join('')}</tr></thead>
                <tbody>${rows.map(r => `
                    <tr class="site-row" data-slug="${r.slug}">
                        <td><a href="#" class="site-link">${r.hub_name}</a></td>
                        <td>${r.state || '—'}</td>
                        ${cols.map(k => `<td>${metricFmt(k, r[k])}</td>`).join('')}
                    </tr>`).join('')}
                </tbody>
            </table></div>`;

        container.querySelectorAll('th.sortable').forEach(th =>
            th.addEventListener('click', () => {
                const k = th.dataset.key;
                const isText = k === 'hub_name' || k === 'state';
                this.asSort = (this.asSort.key === k)
                    ? { key: k, dir: this.asSort.dir === 'asc' ? 'desc' : 'asc' }
                    : { key: k, dir: isText ? 'asc' : 'desc' };
                this.renderAcrossTable(this._asState());
            }));

        container.querySelectorAll('.site-row').forEach(tr =>
            tr.addEventListener('click', (e) => {
                e.preventDefault();
                const slug = tr.dataset.slug;
                if (!this.sdPicker.selected.includes(slug)) this.sdPicker.selected.push(slug);
                this.sdPicker._renderChips();
                this.sdSelected = this.sdPicker.getSelected();
                this.renderSiteDetail();
                this.showSection('site-detail');
                window.scrollTo(0, 0);
            }));
    }

    _asCsvRows() {
        const st = this._asState();
        if (st.view === 'rank') {
            return [['site', 'state', st.metric],
                    ...st.limited.map(r => [r.hub_name, r.state, r.total ?? ''])];
        }
        const rows = [['site', st.rolling ? 'month' : 'year', st.metric]];
        for (const r of st.limited) {
            r.series.forEach((v, i) => rows.push([r.hub_name, st.axis[i], v ?? '']));
        }
        return rows;
    }

    renderPapers() {
        const which = document.getElementById('as-paper-metric').value;
        const researchOnly = document.getElementById('as-research-only').checked;
        const term = document.getElementById('as-paper-search').value.toLowerCase().trim();

        let papers = this.pubs[which] || [];
        if (researchOnly) papers = papers.filter(p => p.is_research === 1);
        if (term) {
            papers = papers.filter(p =>
                `${p.title || ''} ${p.journal || ''} ${p.sites.join(' ')}`
                    .toLowerCase().includes(term));
        }
        this.papersShown = papers;
        document.getElementById('as-paper-count').textContent =
            `${papers.length.toLocaleString()} papers`;

        document.getElementById('as-papers-container').innerHTML = `
            <div class="table-scroll tall">
            <table class="data-table compact">
                <thead><tr><th>#</th><th>Title</th><th>Journal</th><th>Year</th>
                           <th>RCR</th><th>Citations</th><th>Site(s)</th></tr></thead>
                <tbody>${papers.map((p, i) => `
                    <tr>
                        <td>${i + 1}</td>
                        <td><a href="https://pubmed.ncbi.nlm.nih.gov/${p.pmid}/" target="_blank" rel="noopener">${p.title || '(untitled)'}</a></td>
                        <td>${p.journal || '—'}</td>
                        <td>${p.year || '—'}</td>
                        <td>${fmt(p.rcr, 1)}</td>
                        <td>${(p.citations || 0).toLocaleString()}</td>
                        <td>${p.sites.length ? p.sites.join(', ') : '—'}
                            ${p.n_linked_hubs > 1 ? `<span class="badge">${p.n_linked_hubs} hubs</span>` : ''}</td>
                    </tr>`).join('')}
                </tbody>
            </table></div>`;
    }

    // ================= GRANTS =================

    setupGrants() {
        this.allGrants = [];
        for (const [slug, data] of Object.entries(this.siteCache)) {
            for (const g of data.grants) {
                this.allGrants.push({ ...g, site_slug: slug,
                                      hub_name: data.hub_name, state: data.state });
            }
        }
        const groups = [...new Set(this.allGrants.map(g => (g.activity_code || '?')[0]))].sort();
        document.getElementById('grants-controls').innerHTML = `
            <div class="controls-row">
                <input type="text" id="grants-search" placeholder="Search title, project number, or site…">
                <select id="grants-group">
                    <option value="">All mechanisms</option>
                    ${groups.map(g => `<option value="${g}">${g} awards</option>`).join('')}
                </select>
                <label><input type="checkbox" id="grants-hubs-only"> Hub awards only</label>
            </div>
            <p class="data-note" id="grants-count"></p>`;
        ['grants-search', 'grants-group', 'grants-hubs-only'].forEach(id =>
            document.getElementById(id).addEventListener('input', () => this.renderGrantsTable()));
        this.grantsSort = { key: 'total_award_amount', dir: 'desc' };
        this.renderGrantsTable();
    }

    renderGrantsTable() {
        const term = document.getElementById('grants-search').value.toLowerCase().trim();
        const group = document.getElementById('grants-group').value;
        const hubsOnly = document.getElementById('grants-hubs-only').checked;
        const { key, dir } = this.grantsSort;

        const rows = this.allGrants.filter(g => {
            if (hubsOnly && !g.is_hub_award) return false;
            if (group && (g.activity_code || '?')[0] !== group) return false;
            if (term) {
                const hay = `${g.core_project_num} ${g.title || ''} ${g.hub_name}`.toLowerCase();
                if (!hay.includes(term)) return false;
            }
            return true;
        }).sort((a, b) => {
            const av = a[key], bv = b[key];
            if (av === null || av === undefined || av === '') return 1;
            if (bv === null || bv === undefined || bv === '') return -1;
            if (typeof av === 'string' || typeof bv === 'string') {
                return dir === 'asc' ? String(av).localeCompare(String(bv))
                                     : String(bv).localeCompare(String(av));
            }
            return dir === 'asc' ? av - bv : bv - av;
        });

        document.getElementById('grants-count').textContent =
            `${rows.length.toLocaleString()} of ${this.allGrants.length.toLocaleString()} grants`;

        const cols = [
            ['core_project_num', 'Core project'], ['activity_code', 'Activity'],
            ['hub_name', 'Site'], ['title', 'Title'],
            ['first_fy', 'Years'], ['total_award_amount', 'Awarded'],
        ];
        const container = document.getElementById('grants-table-container');
        container.innerHTML = `
            <div class="table-scroll">
            <table class="data-table compact">
                <thead><tr>${cols.map(([k, l]) =>
                    `<th class="sortable" data-key="${k}">${l}${key === k ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}</th>`
                ).join('')}</tr></thead>
                <tbody>${rows.slice(0, 500).map(g => `
                    <tr>
                        <td><a href="https://reporter.nih.gov/search/?projectNums=${g.core_project_num}" target="_blank" rel="noopener">${g.core_project_num}</a></td>
                        <td>${g.activity_code || '—'}</td>
                        <td>${g.hub_name}</td>
                        <td>${g.title || '—'}</td>
                        <td>${g.first_fy}–${g.last_fy}</td>
                        <td>${fmtMoney(g.total_award_amount)}</td>
                    </tr>`).join('')}
                </tbody>
            </table></div>
            ${rows.length > 500
                ? `<p class="data-note">Showing the first 500 of ${rows.length.toLocaleString()} matching grants, by the current sort.</p>`
                : ''}`;

        container.querySelectorAll('th.sortable').forEach(th =>
            th.addEventListener('click', () => {
                const k = th.dataset.key;
                const isText = ['core_project_num', 'activity_code', 'hub_name', 'title'].includes(k);
                this.grantsSort = (this.grantsSort.key === k)
                    ? { key: k, dir: this.grantsSort.dir === 'asc' ? 'desc' : 'asc' }
                    : { key: k, dir: isText ? 'asc' : 'desc' };
                this.renderGrantsTable();
            }));
    }

    // ================= INVESTIGATORS =================

    setupInvestigators() {
        document.getElementById('investigator-search')
            .addEventListener('input', () => this.renderInvestigatorResults());
        this.renderInvestigatorResults();
    }

    renderInvestigatorResults() {
        const term = document.getElementById('investigator-search').value.toLowerCase().trim();
        const all = this.index.investigators || [];
        const container = document.getElementById('investigator-results');
        if (!term) {
            container.innerHTML = `<p class="data-note">${all.length.toLocaleString()} investigators hold NCATS awards. Type a name to search.</p>`;
            return;
        }
        const rows = all.filter(i => (i.full_name || '').toLowerCase().includes(term)).slice(0, 100);
        if (!rows.length) {
            container.innerHTML = '<p class="data-note">No investigators match that name.</p>';
            return;
        }
        container.innerHTML = `
            <table class="data-table compact">
                <thead><tr><th>Name</th><th>Grants</th></tr></thead>
                <tbody>${rows.map(i => `
                    <tr class="pi-row" data-pid="${i.profile_id}">
                        <td><a href="#" class="pi-link">${i.full_name || '(unnamed)'}</a></td>
                        <td>${i.n_grants}</td>
                    </tr>`).join('')}
                </tbody>
            </table>`;
        container.querySelectorAll('.pi-row').forEach(tr =>
            tr.addEventListener('click', (e) => {
                e.preventDefault();
                this.showInvestigatorDetail(tr.dataset.pid);
            }));
    }

    async showInvestigatorDetail(profileId) {
        let data;
        try {
            data = await this.loader.loadInvestigator(profileId);
        } catch (e) {
            console.error('Failed to load investigator', profileId, e);
            return;
        }
        const panel = document.getElementById('investigator-detail');
        panel.style.display = 'block';
        panel.innerHTML = `
            <h3>${data.full_name || '(unnamed)'}</h3>
            <p class="data-note">
                Publications are those linked to this investigator's NCATS grants.
                Work published outside those awards is not included. See <a href="#about">About</a>.
            </p>
            <div class="metric-row">
                <div class="metric"><span class="metric-value">${data.grants.length}</span><span class="metric-label">Grants</span></div>
                <div class="metric"><span class="metric-value">${data.pub_count.toLocaleString()}</span><span class="metric-label">Publications</span></div>
                <div class="metric"><span class="metric-value">${data.citation_count.toLocaleString()}</span><span class="metric-label">Citations</span></div>
            </div>
            <div class="table-scroll">
            <table class="data-table compact">
                <thead><tr><th>Core project</th><th>Activity</th><th>Title</th><th>Awarded</th><th>Role</th></tr></thead>
                <tbody>${data.grants.map(g => `
                    <tr>
                        <td><a href="https://reporter.nih.gov/search/?projectNums=${g.core_project_num}" target="_blank" rel="noopener">${g.core_project_num}</a></td>
                        <td>${g.activity_code || '—'}</td>
                        <td>${g.title || '—'}</td>
                        <td>${fmtMoney(g.total_award_amount)}</td>
                        <td>${g.is_contact_pi ? 'Contact PI' : 'PI'}</td>
                    </tr>`).join('')}
                </tbody>
            </table></div>`;
        panel.scrollIntoView({ behavior: 'smooth' });
    }

    // ================= ABOUT =================

    renderAbout() {
        const d = this.index;
        document.getElementById('about-content').innerHTML = `
            <p>
                IMPACT-NCATS measures the publication output of the NIH National Center for
                Advancing Translational Sciences portfolio — ${d.total_grants.toLocaleString()}
                awards totalling ${fmtMoney(d.total_award_amount)} across
                ${d.total_sites} CTSA sites, linked to
                ${d.total_publications.toLocaleString()} publications.
            </p>

            <h3>Where the data comes from</h3>
            <ul>
                <li><strong>NIH RePORTER</strong> — awards FY2012 onward: activity code, organization, investigators, dollars.</li>
                <li><strong>RePORTER publications</strong> — the grant-to-publication linkage.</li>
                <li><strong>iCite</strong> — Relative Citation Ratio.</li>
                <li><strong>IMPACT</strong> — journals, citation events, and article types for 24.9M papers.</li>
            </ul>

            <h3>Which awards are included</h3>
            <p>
                Every NCATS award FY2012 onward whose activity code maps to a standard NIH
                mechanism letter (R, K, U, T). R01, R21, R03 and the rest of the R series are
                fully included. Excluded by scope: Other Transactions (OT2/OT3), R&amp;D contracts
                (N01/N03/N43/N44), SB1 and DP2 — 41 records totalling $108.6M. <strong>The dollar
                figures here are therefore not the full NCATS obligation.</strong>
            </p>

            <h3>Rolling citation rate</h3>
            <p>
                Computed with the same formula as the main
                <a href="https://dantyrr.github.io/IMPACT" target="_blank" rel="noopener">IMPACT</a>
                site, applied to each hub's linked publications: citations received in a 12-month
                window divided by the research papers published in the preceding window
                (12-month, 24-month, or 5-year year-2-to-6 variants).
            </p>

            <h3>What these numbers do not mean</h3>
            <ol>
                <li>
                    <strong>Publication counts are a floor, not a census.</strong> RePORTER knows about
                    a paper only if it was reported against the award, and hubs differ enormously in
                    how much they report. <em>Yale is the clearest case: it tags roughly 20% of
                    everything the institution publishes to its CTSA, against about 8% at Vanderbilt
                    and 3.6% at Emory. Yale's papers really are Yale's — it simply claims far more of
                    them. Rankings here substantially measure reporting practice, not productivity.</em>
                </li>
                <li>
                    <strong>The timeline starts at FY2012.</strong> NCATS was created in December 2011.
                    The CTSA program itself began in 2006 under NCRR. A hub funded since 2006 will
                    appear to start in 2012 — the left edge of a trend line is not program inception.
                </li>
                <li>
                    <strong>Shared papers are counted in full at every hub.</strong> A multi-site paper
                    linked to three hubs counts once for each, so per-site totals sum to more than the
                    ${d.total_publications.toLocaleString()} unique publications above.
                </li>
                <li>
                    <strong>Investigator publications come from grant linkage only.</strong> No
                    author-name matching is performed, so a hub's contact PI is credited with the
                    hub's entire linked output, and work outside NCATS awards is absent.
                </li>
                <li>
                    <strong>Per-dollar metrics are blunt.</strong> Publications and citations lag
                    funding by years, and infrastructure and training awards fund cores and people
                    rather than papers. A high cost per publication is not evidence of waste.
                </li>
            </ol>

            <p class="data-note">
                Full methodology: <a href="https://github.com/dantyrr/IMPACT-NCATS/blob/main/METHODS_ncats.md"
                target="_blank" rel="noopener">METHODS_ncats.md</a>.
                Related: <a href="https://dantyrr.github.io/IMPACT">IMPACT</a> ·
                <a href="https://dantyrr.github.io/IMPACT-gender">IMPACT-gender</a>.
            </p>`;
    }
}

document.addEventListener('DOMContentLoaded', () => { window.app = new NCATSApp(); });
