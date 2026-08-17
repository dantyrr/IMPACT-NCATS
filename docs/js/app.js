/**
 * IMPACT-NCATS — main controller.
 * Mirrors IMPACT's IMPACTApp: hash nav, showSection, per-section setup.
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
            document.getElementById('sites-summary').textContent =
                'Could not load data. If running locally, make sure docs/data/index.json exists.';
            console.error('Failed to load index.json', e);
            return;
        }
        this.renderSitesSummary();
        await this.setupSites();
        await this.setupPublications();
        this.setupTrends();
        this.setupGrants();
        this.setupInvestigators();
        this.setupCompare();
        this.renderAbout();
    }

    setupNavigation() {
        document.querySelectorAll('.nav-link').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                this.showSection(link.dataset.section);
            });
        });
        const initial = location.hash.replace('#', '') || 'sites';
        this.showSection(initial);
    }

    showSection(sectionId) {
        document.querySelectorAll('.section').forEach(s =>
            s.classList.toggle('active', s.id === sectionId));
        document.querySelectorAll('.nav-link').forEach(l =>
            l.classList.toggle('active', l.dataset.section === sectionId));
        history.replaceState(null, '', `#${sectionId}`);
    }

    renderSitesSummary() {
        const d = this.index;
        document.getElementById('sites-summary').textContent =
            `${d.total_sites} CTSA sites · ${d.total_grants.toLocaleString()} NCATS grants · ` +
            `${d.total_publications.toLocaleString()} linked publications · ` +
            `${fmtMoney(d.total_award_amount)} awarded`;
    }

    // ---------------- Sites ----------------

    async setupSites() {
        const sites = this.index.sites;
        const loaded = await Promise.all(
            sites.map(s => this.loader.loadSite(s.slug).catch(() => null))
        );
        this.siteSummaries = sites.map((s, i) => {
            const data = loaded[i];
            if (data) this.siteCache[s.slug] = data;
            return { ...s, ...this._siteTotals(data) };
        });
        this.sitesSort = { key: 'pubCount', dir: 'desc' };
        this.selectedSites = [];
        this.renderSitesTable();
    }

    _siteTotals(siteData) {
        if (!siteData) return { pubCount: 0, citationCount: 0, meanRcr: null, awardTotal: 0 };
        let pubCount = 0, citationCount = 0, awardTotal = 0;
        let rcrSum = 0, rcrN = 0;
        for (const m of siteData.metrics) {
            pubCount += m.pub_count || 0;
            citationCount += m.citation_count || 0;
            awardTotal += m.award_total || 0;
            if (m.mean_rcr !== null && m.mean_rcr !== undefined) {
                rcrSum += m.mean_rcr * (m.pub_count || 0);
                rcrN += m.pub_count || 0;
            }
        }
        return { pubCount, citationCount, awardTotal, meanRcr: rcrN > 0 ? rcrSum / rcrN : null };
    }

    renderSitesTable() {
        const { key, dir } = this.sitesSort;
        const rows = [...this.siteSummaries].sort((a, b) => {
            const av = a[key], bv = b[key];
            if (typeof av === 'string') return dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
            return dir === 'asc' ? (av ?? 0) - (bv ?? 0) : (bv ?? 0) - (av ?? 0);
        });

        const cols = [
            ['hub_name', 'Site'], ['state', 'State'],
            ['pubCount', 'Publications'], ['citationCount', 'Citations'],
            ['meanRcr', 'Mean RCR'], ['awardTotal', 'Awarded'],
        ];

        const container = document.getElementById('sites-table-container');
        container.innerHTML = `
            <p class="data-note">
                A publication linked to grants at several hubs is counted in full at each one,
                so this column sums to more than the ${this.index.total_publications.toLocaleString()}
                unique publications in the portfolio. See <a href="#about">About</a>.
            </p>
            <table class="data-table">
                <thead><tr>${cols.map(([k, label]) =>
                    `<th class="sortable" data-key="${k}">${label}${key === k ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}</th>`
                ).join('')}</tr></thead>
                <tbody>${rows.map(r => `
                    <tr class="site-row${this.selectedSites.includes(r.slug) ? ' selected' : ''}" data-slug="${r.slug}">
                        <td><a href="#" class="site-link">${r.hub_name}</a></td>
                        <td>${r.state || '—'}</td>
                        <td>${r.pubCount.toLocaleString()}</td>
                        <td>${r.citationCount.toLocaleString()}</td>
                        <td>${fmt(r.meanRcr)}</td>
                        <td>${fmtMoney(r.awardTotal)}</td>
                    </tr>`).join('')}
                </tbody>
            </table>`;

        container.querySelectorAll('th.sortable').forEach(th => {
            th.addEventListener('click', () => {
                const k = th.dataset.key;
                this.sitesSort = {
                    key: k,
                    dir: this.sitesSort.key === k && this.sitesSort.dir === 'desc' ? 'asc' : 'desc',
                };
                this.renderSitesTable();
            });
        });
        container.querySelectorAll('.site-row').forEach(tr => {
            tr.addEventListener('click', (e) => {
                e.preventDefault();
                this.toggleSite(tr.dataset.slug);
            });
        });
    }

    /** Add or remove a site from the stacked detail cards. */
    async toggleSite(slug) {
        const i = this.selectedSites.indexOf(slug);
        if (i >= 0) this.selectedSites.splice(i, 1);
        else this.selectedSites.push(slug);
        this.renderSitesTable();
        await this.renderSiteDetails();
    }

    renderSelectionBar() {
        const bar = document.getElementById('sites-selection-bar');
        if (!this.selectedSites.length) { bar.style.display = 'none'; return; }
        bar.style.display = 'block';
        bar.innerHTML = `
            <div class="controls-row">
                <strong>${this.selectedSites.length} site${this.selectedSites.length > 1 ? 's' : ''} selected</strong>
                <button class="download-btn" id="sites-clear">Clear all</button>
                <span class="data-note">Click any row to add or remove it.</span>
            </div>`;
        document.getElementById('sites-clear').addEventListener('click', () => {
            this.selectedSites = [];
            this.renderSitesTable();
            this.renderSiteDetails();
        });
    }

    /** View mode + year range controls, shown once at least one site is picked. */
    renderSiteViewControls() {
        const el = document.getElementById('sites-view-controls');
        if (!this.selectedSites.length) { el.style.display = 'none'; return; }
        if (el.dataset.built === '1') { el.style.display = 'block'; return; }

        const years = new Set();
        for (const d of Object.values(this.siteCache)) {
            for (const m of d.metrics) if (m.year) years.add(m.year);
        }
        const all = [...years].sort((a, b) => a - b);
        this.siteYearOptions = all;
        const opts = all.map(y => `<option value="${y}">${y}</option>`).join('');

        el.innerHTML = `
            <div class="controls-row">
                <label>View:
                    <select id="sites-view">
                        <option value="cards">Separate cards</option>
                        <option value="combined">Combined chart</option>
                        <option value="both" selected>Both</option>
                    </select>
                </label>
                <label>Combined metric:
                    <select id="sites-combined-metric">
                        <option value="pub_count">Publications</option>
                        <option value="citation_count">Citations</option>
                        <option value="mean_rcr">Mean RCR</option>
                        <option value="research_count">Research articles</option>
                        <option value="award_total">Award dollars</option>
                        <option value="citations_per_million">Citations per $1M</option>
                    </select>
                </label>
                <label>From: <select id="sites-year-from">${opts}</select></label>
                <label>To: <select id="sites-year-to">${opts}</select></label>
                <button class="download-btn" id="sites-year-reset">Reset years</button>
            </div>`;
        el.dataset.built = '1';
        el.style.display = 'block';

        const from = document.getElementById('sites-year-from');
        const to = document.getElementById('sites-year-to');
        from.value = String(Math.max(all[0], 2012));
        to.value = String(all[all.length - 1]);

        ['sites-view', 'sites-combined-metric', 'sites-year-from', 'sites-year-to']
            .forEach(id => document.getElementById(id)
                .addEventListener('input', () => this.renderSiteDetails()));
        document.getElementById('sites-year-reset').addEventListener('click', () => {
            from.value = String(Math.max(all[0], 2012));
            to.value = String(all[all.length - 1]);
            this.renderSiteDetails();
        });

        this._attachDownloadBar('sites-combined-downloads',
            () => this.combinedChart,
            () => this._combinedCsvRows(),
            () => `ncats-sites-combined-${document.getElementById('sites-combined-metric').value}`);
    }

    /** The year window currently selected on the Sites tab. */
    _siteYearRange() {
        const fromEl = document.getElementById('sites-year-from');
        const toEl = document.getElementById('sites-year-to');
        if (!fromEl || !toEl) return this.siteYearOptions || [];
        let from = parseInt(fromEl.value, 10);
        let to = parseInt(toEl.value, 10);
        // Tolerate a reversed range rather than silently drawing nothing.
        if (from > to) [from, to] = [to, from];
        return (this.siteYearOptions || []).filter(y => y >= from && y <= to);
    }

    /** Render selected sites as stacked cards, a combined chart, or both. */
    async renderSiteDetails() {
        this.renderSelectionBar();
        const panel = document.getElementById('site-detail');
        const combinedWrap = document.getElementById('sites-combined');

        if (!this.selectedSites.length) {
            panel.innerHTML = '';
            combinedWrap.style.display = 'none';
            document.getElementById('sites-view-controls').style.display = 'none';
            return;
        }

        for (const slug of this.selectedSites) {
            if (!this.siteCache[slug]) {
                this.siteCache[slug] = await this.loader.loadSite(slug);
            }
        }

        this.renderSiteViewControls();
        const view = (document.getElementById('sites-view') || {}).value || 'both';
        const years = this._siteYearRange();

        combinedWrap.style.display = (view === 'combined' || view === 'both') ? 'block' : 'none';
        if (view === 'combined' || view === 'both') this.renderCombinedChart(years);

        if (view === 'combined') {
            panel.innerHTML = '';
            return;
        }

        panel.innerHTML = this.selectedSites
            .map(slug => this._siteCardHtml(slug, this.siteCache[slug])).join('');

        // Charts must be built after the markup exists in the DOM.
        for (const slug of this.selectedSites) {
            this._drawSiteCard(slug, this.siteCache[slug], years);
        }
    }

    /** One grouped bar per year, one series per selected site. */
    renderCombinedChart(years) {
        const metric = document.getElementById('sites-combined-metric').value;
        const label = document.getElementById('sites-combined-metric').selectedOptions[0].text;

        this.combinedChart = ChartManager.barChart('sites-combined-chart', years,
            this.selectedSites.map((slug, i) => ({
                label: this.siteCache[slug].hub_name,
                data: this._siteYearSeries(this.siteCache[slug], metric, 'all', years),
                backgroundColor: ChartManager.color(i),
                borderColor: ChartManager.color(i),
            })),
            { yLabel: label });   // not stacked: bars sit side by side
    }

    _combinedCsvRows() {
        const years = this._siteYearRange();
        const metric = document.getElementById('sites-combined-metric').value;
        const rows = [['site', 'year', metric]];
        for (const slug of this.selectedSites) {
            const series = this._siteYearSeries(this.siteCache[slug], metric, 'all', years);
            series.forEach((v, i) => rows.push([this.siteCache[slug].hub_name, years[i], v ?? '']));
        }
        return rows;
    }

    _siteCardHtml(slug, data) {
        const totals = this._siteTotals(data);
        return `
        <div class="detail-panel site-card" data-slug="${slug}">
            <button class="card-close" data-slug="${slug}" title="Remove">×</button>
            <h3>${data.hub_name}</h3>
            <p class="data-note">${data.org_name} · ${data.city || ''} ${data.state || ''}</p>
            <div class="metric-row">
                <div class="metric"><span class="metric-value">${totals.pubCount.toLocaleString()}</span><span class="metric-label">Publications</span></div>
                <div class="metric"><span class="metric-value">${totals.citationCount.toLocaleString()}</span><span class="metric-label">Citations</span></div>
                <div class="metric"><span class="metric-value">${fmt(totals.meanRcr)}</span><span class="metric-label">Mean RCR</span></div>
                <div class="metric"><span class="metric-value">${fmtMoney(totals.awardTotal)}</span><span class="metric-label">Awarded</span></div>
            </div>
            <div class="chart-container"><canvas id="site-chart-${slug}"></canvas></div>
            <div class="download-bar">
                <span>Download:</span>
                <button class="download-btn" data-slug="${slug}" data-fmt="png">PNG</button>
                <button class="download-btn" data-slug="${slug}" data-fmt="jpg">JPG</button>
                <button class="download-btn" data-slug="${slug}" data-fmt="pdf">PDF</button>
                <button class="download-btn" data-slug="${slug}" data-fmt="csv">CSV data</button>
            </div>
            <details>
                <summary>Grants (${data.grants.length})</summary>
                <table class="data-table">
                    <thead><tr><th>Core project</th><th>Activity</th><th>Title</th><th>Years</th><th>Awarded</th></tr></thead>
                    <tbody>${data.grants.map(g => `
                        <tr>
                            <td><a href="https://reporter.nih.gov/search/?projectNums=${g.core_project_num}" target="_blank" rel="noopener">${g.core_project_num}</a></td>
                            <td>${g.activity_code || '—'}</td>
                            <td>${g.title || '—'}</td>
                            <td>${g.first_fy}–${g.last_fy}</td>
                            <td>${fmtMoney(g.total_award_amount)}</td>
                        </tr>`).join('')}
                    </tbody>
                </table>
            </details>
        </div>`;
    }

    _drawSiteCard(slug, data, yearFilter) {
        let years = [...new Set(data.metrics.map(m => m.year))].sort();
        if (yearFilter && yearFilter.length) {
            const allowed = new Set(yearFilter);
            years = years.filter(y => allowed.has(y));
        }
        const groups = [...new Set(data.metrics.map(m => m.activity_group))].sort();

        const datasets = groups.map((g, i) => ({
            label: `${g} awards`,
            data: years.map(y => {
                const row = data.metrics.find(m => m.year === y && m.activity_group === g);
                return row ? row.pub_count : 0;
            }),
            backgroundColor: ChartManager.color(i),
            borderColor: ChartManager.color(i),
        }));

        const chart = ChartManager.barChart(`site-chart-${slug}`, years, datasets,
            { stacked: true, yLabel: 'Publications' });

        const card = document.querySelector(`.site-card[data-slug="${slug}"]`);
        if (!card) return;

        card.querySelectorAll('.download-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const f = btn.dataset.fmt;
                if (f === 'csv') {
                    ChartManager.downloadCSV(
                        [['year', 'activity_group', 'pub_count', 'citation_count', 'mean_rcr', 'award_total'],
                         ...data.metrics.map(m => [m.year, m.activity_group, m.pub_count, m.citation_count, m.mean_rcr, m.award_total])],
                        `${slug}-metrics`);
                } else {
                    ChartManager.download(chart, f, `${slug}-publications`);
                }
            });
        });
        card.querySelector('.card-close').addEventListener('click',
            () => this.toggleSite(slug));
    }

    // ---------------- Shared helpers ----------------

    /**
     * Render a PNG/JPG/PDF/CSV download bar into `containerId`.
     * `getChart` and `getCsvRows` are called at click time so the export always
     * reflects the current state of the controls, not the state at wire-up.
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
                const fmt = btn.dataset.fmt;
                const name = getFilename();
                if (fmt === 'csv') {
                    ChartManager.downloadCSV(getCsvRows(), name);
                    return;
                }
                const chart = getChart();
                if (chart) ChartManager.download(chart, fmt, name);
            });
        });
    }

    /**
     * Per-year values for one site and metric, optionally restricted to a
     * single mechanism group. Rate metrics are weighted by publication count so
     * a tiny mechanism cannot swing a site's value; count metrics are summed.
     */
    _siteYearSeries(siteData, metric, mechanism, years) {
        const isRate = metric === 'mean_rcr' || metric === 'cost_per_pub' ||
                       metric === 'cost_per_citation' || metric === 'mean_journal_if';
        // Derived efficiency metrics are a ratio of sums, never a mean of
        // yearly ratios, and are null (a gap) rather than infinite when no
        // award dollars are recorded for that slice.
        const perMillion = metric === 'citations_per_million' || metric === 'pubs_per_million';
        const numerKey = metric === 'pubs_per_million' ? 'pub_count' : 'citation_count';
        return years.map(y => {
            const rows = siteData.metrics.filter(m =>
                m.year === y && (mechanism === 'all' || m.activity_group === mechanism));
            if (!rows.length) return null;
            if (perMillion) {
                let numer = 0, dollars = 0;
                for (const r of rows) {
                    numer += r[numerKey] || 0;
                    dollars += r.award_total || 0;
                }
                return dollars > 0 ? numer / (dollars / 1e6) : null;
            }
            if (isRate) {
                let num = 0, den = 0;
                for (const r of rows) {
                    if (r[metric] === null || r[metric] === undefined) continue;
                    num += r[metric] * (r.pub_count || 0);
                    den += r.pub_count || 0;
                }
                return den > 0 ? num / den : null;
            }
            return rows.reduce((s, r) => s + (r[metric] || 0), 0);
        });
    }

    // ---------------- Trends ----------------

    setupTrends() {
        document.getElementById('trends-controls').innerHTML = `
            <div class="controls-row">
                <label>Metric:
                    <select id="trends-metric">
                        <option value="pub_count">Publications</option>
                        <option value="citation_count">Citations</option>
                        <option value="mean_rcr">Mean RCR</option>
                        <option value="research_count">Research articles</option>
                        <option value="award_total">Award dollars</option>
                        <option value="cost_per_pub">Cost per publication</option>
                        <option value="citations_per_million">Citations per $1M</option>
                        <option value="pubs_per_million">Publications per $1M</option>
                    </select>
                </label>
                <label>Sites:
                    <select id="trends-topn">
                        <option value="5">Top 5</option>
                        <option value="10" selected>Top 10</option>
                        <option value="20">Top 20</option>
                    </select>
                </label>
                <label>View:
                    <select id="trends-view">
                        <option value="combined" selected>Combined chart</option>
                        <option value="cards">Individual cards</option>
                        <option value="both">Both</option>
                    </select>
                </label>
                <label>Mechanism:
                    <select id="trends-mech">
                        <option value="all">All</option>
                        <option value="U">U (hub &amp; cooperative)</option>
                        <option value="K">K (career development)</option>
                        <option value="T">T (training)</option>
                        <option value="R">R (research)</option>
                    </select>
                </label>
                <label>From:
                    <select id="trends-from"></select>
                </label>
                <label>To:
                    <select id="trends-to"></select>
                </label>
                <label title="Later years are incomplete: papers are still being published and reported">
                    <input type="checkbox" id="trends-drop-partial" checked> Hide incomplete recent years
                </label>
                <label title="One very large site can flatten every other line; a log scale keeps them all readable">
                    <input type="checkbox" id="trends-log"> Log scale
                </label>
            </div>`;

        // Year range comes from the data itself.
        const allYears = new Set();
        for (const d of Object.values(this.siteCache)) {
            for (const m of d.metrics) if (m.year) allYears.add(m.year);
        }
        this.trendYears = [...allYears].sort((a, b) => a - b);
        const from = document.getElementById('trends-from');
        const to = document.getElementById('trends-to');
        from.innerHTML = this.trendYears.map(y => `<option value="${y}">${y}</option>`).join('');
        to.innerHTML = this.trendYears.map(y => `<option value="${y}">${y}</option>`).join('');
        from.value = String(Math.max(this.trendYears[0], 2012));
        to.value = String(this.trendYears[this.trendYears.length - 1]);

        ['trends-metric', 'trends-topn', 'trends-mech', 'trends-from', 'trends-to',
         'trends-drop-partial', 'trends-log', 'trends-view'].forEach(id =>
            document.getElementById(id).addEventListener('input', () => this.renderTrends()));

        this._attachDownloadBar('trends-downloads',
            () => this.trendsChart,
            () => this._trendsCsvRows(),
            () => `ncats-trends-${document.getElementById('trends-metric').value}`);

        // Explicit site selection. When nothing is picked the tab falls back to
        // the Top-N ranking, so it is useful before the user chooses anything.
        this.trendsPicker = new SitePicker(
            'trends-picker', this.index.sites, ChartManager.PALETTE,
            () => this.renderTrends());

        this.renderTrends();
    }

    _trendsState() {
        const metric = document.getElementById('trends-metric').value;
        const topN = parseInt(document.getElementById('trends-topn').value, 10);
        const mech = document.getElementById('trends-mech').value;
        const from = parseInt(document.getElementById('trends-from').value, 10);
        const to = parseInt(document.getElementById('trends-to').value, 10);
        const dropPartial = document.getElementById('trends-drop-partial').checked;

        // The current and next calendar year are always incomplete.
        const cutoff = new Date().getFullYear() - 1;
        let years = this.trendYears.filter(y => y >= from && y <= to);
        if (dropPartial) years = years.filter(y => y <= cutoff);

        // An explicit picker selection wins; otherwise fall back to Top N.
        const picked = this.trendsPicker ? this.trendsPicker.getSelected() : [];
        const pool = picked.length
            ? this.index.sites.filter(s => picked.includes(s.slug))
            : this.index.sites;

        const ranked = pool
            .map(s => {
                const data = this.siteCache[s.slug];
                if (!data) return null;
                const series = this._siteYearSeries(data, metric, mech, years);
                const vals = series.filter(v => v !== null);
                if (!vals.length) return null;
                const isRate = metric === 'mean_rcr' || metric === 'cost_per_pub' ||
                               metric === 'citations_per_million' || metric === 'pubs_per_million';
                const score = isRate
                    ? vals.reduce((a, b) => a + b, 0) / vals.length
                    : vals.reduce((a, b) => a + b, 0);
                return { slug: s.slug, hub_name: s.hub_name, series, score };
            })
            .filter(Boolean)
            .sort((a, b) => b.score - a.score);
        const limited = picked.length ? ranked : ranked.slice(0, topN);

        return { metric, mech, years, ranked: limited, cutoff, dropPartial,
                 explicit: picked.length > 0 };
    }

    renderTrends() {
        const { metric, years, ranked, cutoff, dropPartial, explicit } = this._trendsState();
        const view = (document.getElementById('trends-view') || {}).value || 'combined';
        const showCombined = view === 'combined' || view === 'both';
        const showCards = view === 'cards' || view === 'both';

        document.getElementById('trends-combined').style.display = showCombined ? 'block' : 'none';
        this._renderTrendCards(showCards ? ranked : [], years, metric);
        if (!showCombined) { this._renderTrendsNote(ranked, years, metric, cutoff, dropPartial, explicit); return; }
        const label = document.getElementById('trends-metric').selectedOptions[0].text;

        const useLog = document.getElementById('trends-log').checked;
        this.trendsChart = ChartManager.lineChart('trends-chart', years,
            ranked.map((r, i) => ({
                label: r.hub_name,
                // A log axis cannot plot zero; treat it as a gap instead.
                data: useLog ? r.series.map(v => (v === 0 ? null : v)) : r.series,
                borderColor: ChartManager.color(i),
                backgroundColor: ChartManager.color(i),
                spanGaps: true,
                tension: 0.25,
                pointRadius: 2,
            })),
            {
                xLabel: 'Year', yLabel: label,
                chartOptions: useLog ? {
                    scales: {
                        y: { type: 'logarithmic', title: { display: true, text: `${label} (log scale)` } },
                        x: { title: { display: true, text: 'Year' } },
                    },
                } : undefined,
            });

        this._renderTrendsNote(ranked, years, metric, cutoff, dropPartial, explicit);
    }

    _renderTrendsNote(ranked, years, metric, cutoff, dropPartial, explicit) {
        const label = document.getElementById('trends-metric').selectedOptions[0].text;
        const isEff = metric === 'citations_per_million' || metric === 'pubs_per_million';
        if (!years.length || !ranked.length) {
            document.getElementById('trends-note').innerHTML =
                '<p class="data-note">No data for the selected sites and year range.</p>';
            return;
        }
        document.getElementById('trends-note').innerHTML = `
            ${isEff ? `<p class="data-note warn">
                <strong>Per-year efficiency is noisy.</strong> A quarter of site-years have
                publications linked but no award dollars recorded, because papers are reported
                against a grant outside its funded years — those points are gaps, not zeros.
                Citations also lag spending by years, so the most recent points understate every site.
            </p>` : ''}
            <p class="data-note">
                ${explicit
                    ? `Showing the ${ranked.length} site${ranked.length === 1 ? '' : 's'} you selected`
                    : `Showing the top ${ranked.length} sites by ${label.toLowerCase()}`}
                over ${years[0]}–${years[years.length - 1]}.
                ${dropPartial
                    ? `Years after ${cutoff} are hidden because they are still filling in — papers keep being published and reported against a grant for years.`
                    : `<strong>Recent years are incomplete</strong> and will understate output.`}
                ${explicit ? '' : `Sites are ranked within the selected window, so changing the
                year range can change which sites appear.`}
            </p>`;
    }

    /** One small line chart per site, for reading a single site clearly. */
    _renderTrendCards(ranked, years, metric) {
        const wrap = document.getElementById('trends-cards');
        if (!ranked.length) { wrap.innerHTML = ''; return; }
        const label = document.getElementById('trends-metric').selectedOptions[0].text;

        wrap.innerHTML = ranked.map(r => `
            <div class="detail-panel site-card" data-slug="${r.slug}">
                <h3>${r.hub_name}</h3>
                <div class="chart-container"><canvas id="trend-card-${r.slug}"></canvas></div>
                <div class="download-bar">
                    <span>Download:</span>
                    <button class="download-btn" data-slug="${r.slug}" data-fmt="png">PNG</button>
                    <button class="download-btn" data-slug="${r.slug}" data-fmt="jpg">JPG</button>
                    <button class="download-btn" data-slug="${r.slug}" data-fmt="pdf">PDF</button>
                    <button class="download-btn" data-slug="${r.slug}" data-fmt="csv">CSV data</button>
                </div>
            </div>`).join('');

        this.trendCardCharts = {};
        ranked.forEach((r, i) => {
            this.trendCardCharts[r.slug] = ChartManager.lineChart(
                `trend-card-${r.slug}`, years,
                [{
                    label: r.hub_name,
                    data: r.series,
                    borderColor: ChartManager.color(i),
                    backgroundColor: ChartManager.color(i),
                    spanGaps: true, tension: 0.25, pointRadius: 2,
                }],
                { xLabel: 'Year', yLabel: label });
        });

        wrap.querySelectorAll('.download-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const slug = btn.dataset.slug;
                const row = ranked.find(x => x.slug === slug);
                const name = `ncats-trend-${slug}-${metric}`;
                if (btn.dataset.fmt === 'csv') {
                    ChartManager.downloadCSV(
                        [['site', 'year', metric],
                         ...row.series.map((v, i) => [row.hub_name, years[i], v ?? ''])],
                        name);
                } else {
                    ChartManager.download(this.trendCardCharts[slug], btn.dataset.fmt, name);
                }
            });
        });
    }

    _trendsCsvRows() {
        const { years, ranked } = this._trendsState();
        const metric = document.getElementById('trends-metric').value;
        const rows = [['site', 'year', metric]];
        for (const r of ranked) {
            r.series.forEach((v, i) => rows.push([r.hub_name, years[i], v ?? '']));
        }
        return rows;
    }

    // ---------------- Publications ----------------

    async setupPublications() {
        try {
            this.pubs = await this.loader.loadPublications();
        } catch (e) {
            document.getElementById('pub-controls').innerHTML =
                '<p class="data-note">Could not load publications data.</p>';
            console.error('Failed to load publications.json', e);
            return;
        }

        const thr = this.pubs.min_pubs_threshold;
        document.getElementById('pub-controls').innerHTML = `
            <div class="controls-row">
                <label>Rank sites by:
                    <select id="pub-metric">
                        <option value="mean_rcr">Mean RCR</option>
                        <option value="citation_count">Total citations</option>
                        <option value="mean_citations">Mean citations per paper</option>
                        <option value="citations_per_million">Citations per $1M awarded</option>
                        <option value="pubs_per_million">Publications per $1M awarded</option>
                        <option value="pub_count">Publications</option>
                    </select>
                </label>
                <label>Show:
                    <select id="pub-topn">
                        <option value="10">Top 10</option>
                        <option value="20">Top 20</option>
                        <option value="0">All sites</option>
                    </select>
                </label>
                <label title="A site with very few scored papers can post an extreme mean RCR">
                    <input type="checkbox" id="pub-min" checked>
                    Only sites with ≥${thr} scored papers
                </label>
            </div>`;
        ['pub-metric', 'pub-topn', 'pub-min'].forEach(id =>
            document.getElementById(id).addEventListener('input', () => this.renderPubChart()));

        document.getElementById('pub-paper-controls').innerHTML = `
            <div class="controls-row">
                <label>Rank papers by:
                    <select id="pub-paper-metric">
                        <option value="top_by_rcr">RCR</option>
                        <option value="top_by_citations">Citations</option>
                    </select>
                </label>
                <label><input type="checkbox" id="pub-research-only"> Research articles only</label>
                <input type="text" id="pub-paper-search" placeholder="Filter by title, journal, or site…">
            </div>
            <p class="data-note" id="pub-paper-count"></p>`;
        ['pub-paper-metric', 'pub-research-only', 'pub-paper-search'].forEach(id =>
            document.getElementById(id).addEventListener('input', () => this.renderPubPapers()));

        this._attachDownloadBar('pub-chart-downloads',
            () => this.pubChart,
            () => {
                const metric = document.getElementById('pub-metric').value;
                return [['site', 'state', 'publications', 'rcr_scored_papers', metric],
                        ...this.pubChartRows.map(r =>
                            [r.hub_name, r.state, r.pub_count, r.rcr_n, r[metric]])];
            },
            () => `ncats-sites-by-${document.getElementById('pub-metric').value}`);

        this._attachDownloadBar('pub-paper-downloads',
            () => null,   // the paper list is a table, not a chart
            () => [['rank', 'pmid', 'title', 'journal', 'year', 'rcr', 'citations', 'sites'],
                   ...this.pubPapersShown.map((p, i) =>
                       [i + 1, p.pmid, p.title, p.journal, p.year, p.rcr,
                        p.citations, p.sites.join('; ')])],
            () => `ncats-top-papers-${document.getElementById('pub-paper-metric').value}`);

        this.renderPubChart();
        this.renderPubPapers();
    }

    renderPubChart() {
        const metric = document.getElementById('pub-metric').value;
        const topN = parseInt(document.getElementById('pub-topn').value, 10);
        const applyMin = document.getElementById('pub-min').checked;
        const thr = this.pubs.min_pubs_threshold;

        let rows = this.pubs.site_rankings.filter(r => r[metric] !== null && r[metric] !== undefined);
        const excluded = applyMin ? rows.filter(r => r.below_threshold).length : 0;
        if (applyMin) rows = rows.filter(r => !r.below_threshold);

        rows.sort((a, b) => (b[metric] || 0) - (a[metric] || 0));
        if (topN > 0) rows = rows.slice(0, topN);
        this.pubChartRows = rows;

        const label = document.getElementById('pub-metric').selectedOptions[0].text;
        this.pubChart = ChartManager.barChart('pub-site-chart',
            rows.map(r => r.hub_name),
            [{
                label,
                data: rows.map(r => r[metric]),
                backgroundColor: rows.map((_, i) => ChartManager.color(i)),
            }],
            {
                yLabel: label,
                chartOptions: {
                    indexAxis: 'y',
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                afterLabel: (ctx) => {
                                    const r = rows[ctx.dataIndex];
                                    return `${r.pub_count.toLocaleString()} publications · ` +
                                           `${r.rcr_n.toLocaleString()} with an RCR`;
                                },
                            },
                        },
                    },
                    scales: { y: { ticks: { autoSkip: false } }, x: { beginAtZero: true } },
                },
            });

        const isEfficiency = metric === 'citations_per_million' || metric === 'pubs_per_million';
        document.getElementById('pub-chart-note').innerHTML = `
            ${isEfficiency ? `<p class="data-note warn">
                <strong>Read this one carefully.</strong> Citations accrue for years after the
                money is spent, so recently funded sites look inefficient. Hub awards (UL1/UM1)
                pay for cores, staff and services rather than papers directly, and a paper shared
                by several hubs counts in full at each. A high value here is not proof of a
                better-run site, and a low one is not evidence of waste.
            </p>` : ''}
            <p class="data-note">
                ${applyMin
                    ? `${excluded} site${excluded === 1 ? '' : 's'} with fewer than ${thr} RCR-scored papers ${excluded === 1 ? 'is' : 'are'} hidden — small samples produce unstable averages.`
                    : `<strong>Showing all sites, including those with very few scored papers.</strong> A site with a handful of publications can post an extreme mean RCR that is not meaningful.`}
                Mean RCR counts each site's linked publications in full, so a paper shared by
                several hubs contributes to each. See <a href="#about">About</a>.
            </p>`;
    }

    renderPubPapers() {
        const which = document.getElementById('pub-paper-metric').value;
        const researchOnly = document.getElementById('pub-research-only').checked;
        const term = document.getElementById('pub-paper-search').value.toLowerCase().trim();

        let papers = this.pubs[which];
        if (researchOnly) papers = papers.filter(p => p.is_research === 1);
        if (term) {
            papers = papers.filter(p =>
                `${p.title || ''} ${p.journal || ''} ${p.sites.join(' ')}`.toLowerCase().includes(term));
        }

        this.pubPapersShown = papers;
        document.getElementById('pub-paper-count').textContent =
            `${papers.length.toLocaleString()} papers`;

        document.getElementById('pub-papers-container').innerHTML = `
            <table class="data-table">
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
            </table>`;
    }

    // ---------------- Grants ----------------

    setupGrants() {
        this.allGrants = [];
        for (const [slug, data] of Object.entries(this.siteCache)) {
            for (const g of data.grants) {
                this.allGrants.push({ ...g, site_slug: slug, hub_name: data.hub_name, state: data.state });
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
            // Missing values always sort last, regardless of direction.
            if (av === null || av === undefined || av === '') return 1;
            if (bv === null || bv === undefined || bv === '') return -1;
            if (typeof av === 'string' || typeof bv === 'string') {
                return dir === 'asc'
                    ? String(av).localeCompare(String(bv))
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
            <table class="data-table">
                <thead><tr>${cols.map(([k, label]) =>
                    `<th class="sortable" data-key="${k}">${label}${key === k ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}</th>`
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
            </table>
            ${rows.length > 500
                ? `<p class="data-note">Showing the first 500 of ${rows.length.toLocaleString()} matching grants, by the current sort. Narrow the search to see the rest.</p>`
                : ''}`;

        container.querySelectorAll('th.sortable').forEach(th => {
            th.addEventListener('click', () => {
                const k = th.dataset.key;
                // Text columns start ascending (A-Z); numbers start descending (largest first).
                const isText = ['core_project_num', 'activity_code', 'hub_name', 'title'].includes(k);
                this.grantsSort = (this.grantsSort.key === k)
                    ? { key: k, dir: this.grantsSort.dir === 'asc' ? 'desc' : 'asc' }
                    : { key: k, dir: isText ? 'asc' : 'desc' };
                this.renderGrantsTable();
            });
        });
    }

    // ---------------- Investigators ----------------

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
            <table class="data-table">
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
            <table class="data-table">
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
            </table>`;
        panel.scrollIntoView({ behavior: 'smooth' });
    }

    // ---------------- Compare ----------------

    setupCompare() {
        document.getElementById('compare-controls').innerHTML = `
            <div class="controls-row">
                <label>Metric:
                    <select id="compare-metric">
                        <option value="pub_count">Publications</option>
                        <option value="citation_count">Citations</option>
                        <option value="mean_rcr">Mean RCR</option>
                        <option value="award_total">Award dollars</option>
                        <option value="cost_per_pub">Cost per publication</option>
                        <option value="citations_per_million">Citations per $1M</option>
                    </select>
                </label>
            </div>`;
        document.getElementById('compare-metric')
            .addEventListener('change', () => this.renderCompareChart());

        this.comparePicker = new SitePicker(
            'compare-picker', this.index.sites, ChartManager.PALETTE,
            () => this.renderCompareChart());
    }

    async renderCompareChart() {
        const slugs = this.comparePicker.getSelected();
        const container = document.getElementById('compare-chart-container');
        const hint = document.getElementById('compare-hint');

        if (!slugs.length) {
            container.style.display = 'none';
            hint.style.display = 'block';
            return;
        }
        hint.style.display = 'none';
        container.style.display = 'block';

        const metric = document.getElementById('compare-metric').value;
        const colorMap = this.comparePicker.getColorMap();

        const loaded = {};
        for (const slug of slugs) {
            loaded[slug] = this.siteCache[slug] || await this.loader.loadSite(slug);
            this.siteCache[slug] = loaded[slug];
        }

        const years = [...new Set(slugs.flatMap(s => loaded[s].metrics.map(m => m.year)))].sort();

        const datasets = slugs.map(slug => {
            const site = loaded[slug];
            return {
                label: site.hub_name,
                data: this._siteYearSeries(site, metric, 'all', years),
                borderColor: colorMap[slug],
                backgroundColor: colorMap[slug],
                spanGaps: true,
            };
        });

        ChartManager.lineChart('compare-chart', years, datasets, {
            xLabel: 'Year',
            yLabel: document.getElementById('compare-metric').selectedOptions[0].text,
        });
    }

    // ---------------- About ----------------

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

            <h3>What these numbers do not mean</h3>
            <ol>
                <li>
                    <strong>Publication counts are a floor, not a census.</strong> RePORTER knows about a
                    paper only if it was reported against the award. Hubs differ in how diligently they
                    report, so cross-site comparisons partly measure reporting practice.
                    <em>Yale is the clearest example: its hub award carries roughly six times more
                    publications per year than any peer, despite a shorter award period and almost no
                    pre-award tagging. That gap reflects how broadly a hub attributes papers to its
                    CTSA, not how much research it does.</em>
                </li>
                <li>
                    <strong>The timeline starts at FY2012.</strong> NCATS was created in December 2011.
                    The CTSA program itself began in 2006 under NCRR. A hub funded since 2006 will appear
                    to start in 2012 — the left edge of a trend line is not program inception.
                </li>
                <li>
                    <strong>Shared papers are counted in full at every hub.</strong> A multi-site paper
                    linked to three hubs counts once for each. Per-site totals therefore sum to more than
                    the ${d.total_publications.toLocaleString()} unique publications shown above.
                </li>
                <li>
                    <strong>Investigator publications come from grant linkage only.</strong> No author-name
                    matching is performed, so a hub's contact PI is credited with the hub's entire linked
                    output, and work published outside NCATS awards is absent.
                </li>
                <li>
                    <strong>Cost per publication is a blunt instrument.</strong> Publications lag funding by
                    years, and infrastructure and training awards fund cores and people rather than papers
                    directly. A high cost per publication is not evidence of waste.
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
