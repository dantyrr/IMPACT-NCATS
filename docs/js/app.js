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
                    <tr class="site-row" data-slug="${r.slug}">
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
                this.showSiteDetail(tr.dataset.slug);
            });
        });
    }

    async showSiteDetail(slug) {
        const data = this.siteCache[slug] || await this.loader.loadSite(slug);
        this.siteCache[slug] = data;

        const years = [...new Set(data.metrics.map(m => m.year))].sort();
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

        const totals = this._siteTotals(data);
        const panel = document.getElementById('site-detail');
        panel.style.display = 'block';
        panel.innerHTML = `
            <h3>${data.hub_name}</h3>
            <p class="data-note">${data.org_name} · ${data.city || ''} ${data.state || ''}</p>
            <div class="metric-row">
                <div class="metric"><span class="metric-value">${totals.pubCount.toLocaleString()}</span><span class="metric-label">Publications</span></div>
                <div class="metric"><span class="metric-value">${totals.citationCount.toLocaleString()}</span><span class="metric-label">Citations</span></div>
                <div class="metric"><span class="metric-value">${fmt(totals.meanRcr)}</span><span class="metric-label">Mean RCR</span></div>
                <div class="metric"><span class="metric-value">${fmtMoney(totals.awardTotal)}</span><span class="metric-label">Awarded</span></div>
            </div>
            <div class="chart-container"><canvas id="site-detail-chart"></canvas></div>
            <div class="download-bar">
                <span>Download:</span>
                <button class="download-btn" data-fmt="png">PNG</button>
                <button class="download-btn" data-fmt="jpg">JPG</button>
                <button class="download-btn" data-fmt="pdf">PDF</button>
                <button class="download-btn" data-fmt="csv">CSV data</button>
            </div>
            <h4>Grants (${data.grants.length})</h4>
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
            </table>`;

        const chart = ChartManager.barChart('site-detail-chart', years, datasets,
            { stacked: true, yLabel: 'Publications' });

        panel.querySelectorAll('.download-btn').forEach(btn => {
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
        panel.scrollIntoView({ behavior: 'smooth' });
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
                data: years.map(y => {
                    const rows = site.metrics.filter(m => m.year === y);
                    if (!rows.length) return null;
                    if (metric === 'mean_rcr' || metric === 'cost_per_pub') {
                        // Weighted by publication count, so a tiny mechanism
                        // cannot swing the site's value.
                        let num = 0, den = 0;
                        for (const r of rows) {
                            if (r[metric] === null || r[metric] === undefined) continue;
                            num += r[metric] * (r.pub_count || 0);
                            den += r.pub_count || 0;
                        }
                        return den > 0 ? num / den : null;
                    }
                    return rows.reduce((sum, r) => sum + (r[metric] || 0), 0);
                }),
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

            <h3>What these numbers do not mean</h3>
            <ol>
                <li>
                    <strong>Publication counts are a floor, not a census.</strong> RePORTER knows about a
                    paper only if it was reported against the award. Hubs differ in how diligently they
                    report, so cross-site comparisons partly measure reporting practice.
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
