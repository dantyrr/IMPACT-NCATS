/**
 * Themes & Translation tab.
 *
 * Three views over the same data:
 *   translational — Triangle of Biomedicine mix over time (portfolio or one site)
 *   themes        — theme volume over time
 *   gaps          — a site's theme mix against the portfolio, to surface where a
 *                   hub is over- or under-represented relative to its peers
 *
 * Kept in its own file rather than added to app.js, which is already large.
 */

const TRI_CLASSES = [
    { key: 'human',            label: 'Human',              color: '#0072B2' },
    { key: 'molecular_cellular', label: 'Molecular/cellular', color: '#D55E00' },
    { key: 'animal',           label: 'Animal',             color: '#009E73' },
    { key: 'mixed',            label: 'Mixed',              color: '#7f7f7f' },
];

class ThemesTab {
    constructor(app, data) {
        this.app = app;
        this.data = data;
        this.themeById = Object.fromEntries((data.themes || []).map(t => [t.theme_id, t]));
    }

    setup() {
        const sites = this.app.index.sites;
        const years = [...new Set((this.data.trans_year || []).map(r => r.year))]
            .sort((a, b) => a - b);
        this.years = years;
        const yearOpts = (sel) => years.map(y =>
            `<option value="${y}"${y === sel ? ' selected' : ''}>${y}</option>`).join('');

        document.getElementById('th-controls').innerHTML = `
            <div class="controls-row">
                <label>View:
                    <select id="th-view">
                        <option value="translational" selected>Translational mix over time</option>
                        <option value="themes">Themes over time</option>
                        <option value="gaps">Theme gaps vs portfolio</option>
                    </select>
                </label>
                <label>Site:
                    <select id="th-site">
                        <option value="">All sites (portfolio)</option>
                        ${sites.map(s => `<option value="${s.slug}">${s.hub_name}</option>`).join('')}
                    </select>
                </label>
                <label>Show:
                    <select id="th-topn">
                        <option value="10" selected>Top 10 themes</option>
                        <option value="20">Top 20 themes</option>
                        <option value="30">Top 30 themes</option>
                    </select>
                </label>
                <label>Units:
                    <select id="th-units">
                        <option value="pct" selected>Percent</option>
                        <option value="count">Paper count</option>
                    </select>
                </label>
                <label>From: <select id="th-from">${yearOpts(Math.max(years[0], 2012))}</select></label>
                <label>To: <select id="th-to">${yearOpts(years[years.length - 1])}</select></label>
            </div>`;

        ['th-view', 'th-site', 'th-topn', 'th-units', 'th-from', 'th-to'].forEach(id =>
            document.getElementById(id).addEventListener('input', () => this.render()));

        this.app._attachDownloadBar('th-downloads',
            () => this.chart,
            () => this.csvRows(),
            () => `ncats-${document.getElementById('th-view').value}`);

        this.render();
    }

    _state() {
        const from = parseInt(document.getElementById('th-from').value, 10);
        const to = parseInt(document.getElementById('th-to').value, 10);
        const [lo, hi] = from <= to ? [from, to] : [to, from];
        return {
            view: document.getElementById('th-view').value,
            slug: document.getElementById('th-site').value,
            topN: parseInt(document.getElementById('th-topn').value, 10),
            pct: document.getElementById('th-units').value === 'pct',
            years: this.years.filter(y => y >= lo && y <= hi),
        };
    }

    render() {
        const st = this._state();
        // Theme controls are meaningless on the translational view; hide rather
        // than leave a dead control the user can fiddle with.
        document.getElementById('th-topn').closest('label').style.display =
            st.view === 'translational' ? 'none' : '';

        if (st.view === 'translational') this.renderTranslational(st);
        else if (st.view === 'themes') this.renderThemes(st);
        else this.renderGaps(st);
    }

    // ---- Triangle of Biomedicine mix over time ----

    renderTranslational(st) {
        const rows = st.slug
            ? (this.data.trans_site_year || []).filter(r => r.slug === st.slug)
            : (this.data.trans_year || []);

        const byYear = {};
        for (const r of rows) {
            if (!byYear[r.year]) byYear[r.year] = {};
            byYear[r.year][r.tri] = (byYear[r.year][r.tri] || 0) + r.n;
        }

        const datasets = TRI_CLASSES.map(c => ({
            label: c.label,
            data: st.years.map(y => {
                const row = byYear[y] || {};
                const v = row[c.key] || 0;
                if (!st.pct) return v;
                const tot = Object.values(row).reduce((a, b) => a + b, 0);
                return tot ? 100 * v / tot : null;
            }),
            backgroundColor: c.color,
            borderColor: c.color,
        }));

        this.chart = ChartManager.barChart('th-chart', st.years, datasets, {
            stacked: true,
            yLabel: st.pct ? '% of papers' : 'Papers',
            chartOptions: st.pct ? { scales: { y: { stacked: true, max: 100 }, x: { stacked: true } } } : undefined,
        });

        const cov = this.data.coverage || {};
        const site = st.slug ? this.app.siteCache[st.slug] : null;
        document.getElementById('th-note').innerHTML = `
            <p class="data-note">
                ${site ? `<strong>${site.hub_name}</strong>` : '<strong>Whole portfolio</strong>'} ·
                Triangle of Biomedicine, computed by NIH from MeSH. A paper counts toward a
                vertex when that vertex holds at least
                ${Math.round((this.data.vertex_threshold || 0.5) * 100)}% of its mix; genuinely
                hybrid papers are reported as Mixed rather than forced to a vertex.
                ${(cov.with_translational || 0).toLocaleString()} of
                ${(cov.total || 0).toLocaleString()} publications are classified.
                Recent years are still filling in on both indexing and grant reporting,
                so the right-hand edge is provisional.
            </p>`;
        this.renderTransTable(st, byYear);
    }

    renderTransTable(st, byYear) {
        const rowsFor = st.slug
            ? (this.data.trans_site_year || []).filter(r => r.slug === st.slug)
            : null;
        const aptByYear = {};
        const clinByYear = {};
        if (rowsFor) {
            for (const r of rowsFor) {
                aptByYear[r.year] = aptByYear[r.year] || [];
                if (r.mean_apt != null) aptByYear[r.year].push([r.mean_apt, r.n]);
                clinByYear[r.year] = (clinByYear[r.year] || 0) + (r.cited_by_clinical || 0);
            }
        } else {
            for (const r of (this.data.trans_year || [])) {
                aptByYear[r.year] = aptByYear[r.year] || [];
                if (r.mean_apt != null) aptByYear[r.year].push([r.mean_apt, r.n]);
            }
        }

        document.getElementById('th-table-container').innerHTML = `
            <h3>By year</h3>
            <div class="table-scroll">
            <table class="data-table compact">
                <thead><tr><th>Year</th>
                    ${TRI_CLASSES.map(c => `<th>${c.label}</th>`).join('')}
                    <th>Total</th><th>Mean APT</th>
                    ${rowsFor ? '<th>Cited by clinical</th>' : ''}
                </tr></thead>
                <tbody>${st.years.map(y => {
                    const row = byYear[y] || {};
                    const tot = Object.values(row).reduce((a, b) => a + b, 0);
                    const apt = aptByYear[y] || [];
                    const den = apt.reduce((s, [, n]) => s + n, 0);
                    const wApt = den ? apt.reduce((s, [v, n]) => s + v * n, 0) / den : null;
                    return `<tr><td>${y}</td>
                        ${TRI_CLASSES.map(c => {
                            const v = row[c.key] || 0;
                            return `<td>${tot ? `${v.toLocaleString()} (${(100 * v / tot).toFixed(1)}%)` : '—'}</td>`;
                        }).join('')}
                        <td>${tot.toLocaleString()}</td>
                        <td>${wApt == null ? '—' : wApt.toFixed(3)}</td>
                        ${rowsFor ? `<td>${(clinByYear[y] || 0).toLocaleString()}</td>` : ''}
                    </tr>`;
                }).join('')}</tbody>
            </table></div>`;
    }

    // ---- theme volume over time ----

    _themeRows(slug) {
        if (!slug) return this.data.theme_year || [];
        // theme_site has no year dimension, so a site view needs the per-site
        // per-year table produced by the exporter.
        return (this.data.theme_site_year || []).filter(r => r.slug === slug);
    }

    renderThemes(st) {
        const rows = this._themeRows(st.slug);
        const totals = {};
        for (const r of rows) {
            if (!st.years.includes(r.year)) continue;
            totals[r.theme_id] = (totals[r.theme_id] || 0) + r.n;
        }
        const top = Object.entries(totals)
            .sort((a, b) => b[1] - a[1]).slice(0, st.topN).map(([id]) => +id);

        const byTheme = {};
        for (const r of rows) {
            byTheme[r.theme_id] = byTheme[r.theme_id] || {};
            byTheme[r.theme_id][r.year] = r.n;
        }
        const yearTotals = {};
        for (const r of rows) yearTotals[r.year] = (yearTotals[r.year] || 0) + r.n;

        this.chart = ChartManager.lineChart('th-chart', st.years,
            top.map((id, i) => ({
                label: (this.themeById[id] || {}).label || `Theme ${id}`,
                data: st.years.map(y => {
                    const v = (byTheme[id] || {})[y] || 0;
                    if (!st.pct) return v;
                    return yearTotals[y] ? 100 * v / yearTotals[y] : null;
                }),
                borderColor: ChartManager.color(i),
                backgroundColor: ChartManager.color(i),
                spanGaps: true, tension: 0.25, pointRadius: 2,
            })),
            { xLabel: 'Year', yLabel: st.pct ? '% of themed papers' : 'Papers' });

        document.getElementById('th-note').innerHTML = `
            <p class="data-note">
                Themes are clusters of publication abstracts, labelled by the terms that most
                distinguish each cluster from the others. Built from abstracts rather than MeSH
                because MeSH indexing lags: coverage in this corpus falls from about 94% for
                2012–2018 to 75% for 2023–2026, which would make every MeSH-based theme appear
                to decline recently for purely administrative reasons.
                ${(this.data.coverage?.with_theme || 0).toLocaleString()} papers carry a theme;
                papers too dissimilar to join any cluster are left unassigned rather than forced
                into one.
            </p>`;
        this.renderThemeTable(top, totals);
    }

    renderThemeTable(ids, totals) {
        document.getElementById('th-table-container').innerHTML = `
            <h3>Themes</h3>
            <div class="table-scroll">
            <table class="data-table compact">
                <thead><tr><th>#</th><th>Theme</th><th>Distinguishing terms</th><th>Papers (range)</th><th>Papers (all time)</th></tr></thead>
                <tbody>${ids.map(id => {
                    const t = this.themeById[id] || {};
                    return `<tr>
                        <td>${id}</td>
                        <td><strong>${t.label || '—'}</strong></td>
                        <td>${(t.top_terms || []).join(', ')}</td>
                        <td>${(totals[id] || 0).toLocaleString()}</td>
                        <td>${(t.size || 0).toLocaleString()}</td>
                    </tr>`;
                }).join('')}</tbody>
            </table></div>`;
    }

    // ---- gap analysis: one site's mix vs the portfolio ----

    renderGaps(st) {
        if (!st.slug) {
            this.chart = ChartManager.barChart('th-chart', [], []);
            document.getElementById('th-note').innerHTML =
                '<p class="data-note">Pick a site above to compare its theme mix against the whole portfolio.</p>';
            document.getElementById('th-table-container').innerHTML = '';
            return;
        }

        const siteTot = {};
        for (const r of (this.data.theme_site || [])) {
            if (r.slug === st.slug) siteTot[r.theme_id] = r.n;
        }
        const portTot = {};
        for (const t of (this.data.themes || [])) portTot[t.theme_id] = t.size;

        const siteN = Object.values(siteTot).reduce((a, b) => a + b, 0);
        const portN = Object.values(portTot).reduce((a, b) => a + b, 0);
        if (!siteN) {
            document.getElementById('th-note').innerHTML =
                '<p class="data-note">No themed publications for this site.</p>';
            return;
        }

        // Difference in share, in percentage points. Positive = the hub does more
        // of this than the portfolio average.
        const diffs = Object.keys(portTot).map(id => {
            const sShare = 100 * (siteTot[id] || 0) / siteN;
            const pShare = 100 * (portTot[id] || 0) / portN;
            return { id: +id, diff: sShare - pShare, sShare, pShare, n: siteTot[id] || 0 };
        }).filter(d => d.n > 0 || d.pShare > 0.5);

        diffs.sort((a, b) => b.diff - a.diff);
        const half = Math.max(3, Math.floor(st.topN / 2));
        const shown = [...diffs.slice(0, half), ...diffs.slice(-half)];

        this.chart = ChartManager.barChart('th-chart',
            shown.map(d => (this.themeById[d.id] || {}).label || `Theme ${d.id}`),
            [{
                label: 'Percentage points vs portfolio',
                data: shown.map(d => d.diff),
                backgroundColor: shown.map(d => d.diff >= 0 ? '#0072B2' : '#D55E00'),
            }],
            {
                yLabel: 'Difference from portfolio (pp)',
                chartOptions: {
                    indexAxis: 'y',
                    plugins: { legend: { display: false } },
                    scales: { y: { ticks: { autoSkip: false } } },
                },
            });

        const site = this.app.siteCache[st.slug];
        document.getElementById('th-note').innerHTML = `
            <p class="data-note">
                <strong>${site ? site.hub_name : st.slug}</strong> against the whole portfolio,
                in percentage points of themed output. Bars to the right are themes this hub does
                more of than average; bars to the left are themes it does less of.
                Based on ${siteN.toLocaleString()} themed papers at this site against
                ${portN.toLocaleString()} portfolio-wide.
                <strong>An under-represented theme is not automatically a gap</strong> — hubs
                specialise deliberately, and a low share may reflect a local decision or another
                institution nearby covering it.
            </p>`;

        document.getElementById('th-table-container').innerHTML = `
            <h3>Theme mix</h3>
            <div class="table-scroll">
            <table class="data-table compact">
                <thead><tr><th>Theme</th><th>Terms</th><th>Site papers</th><th>Site share</th><th>Portfolio share</th><th>Difference</th></tr></thead>
                <tbody>${diffs.map(d => {
                    const t = this.themeById[d.id] || {};
                    const sign = d.diff >= 0 ? '+' : '';
                    return `<tr>
                        <td><strong>${t.label || d.id}</strong></td>
                        <td>${(t.top_terms || []).slice(0, 5).join(', ')}</td>
                        <td>${d.n.toLocaleString()}</td>
                        <td>${d.sShare.toFixed(2)}%</td>
                        <td>${d.pShare.toFixed(2)}%</td>
                        <td>${sign}${d.diff.toFixed(2)} pp</td>
                    </tr>`;
                }).join('')}</tbody>
            </table></div>`;
    }

    csvRows() {
        const st = this._state();
        if (st.view === 'translational') {
            const rows = st.slug
                ? (this.data.trans_site_year || []).filter(r => r.slug === st.slug)
                : (this.data.trans_year || []);
            return [['year', 'triangle_class', 'papers', 'mean_apt'],
                    ...rows.filter(r => st.years.includes(r.year))
                           .map(r => [r.year, r.tri, r.n, r.mean_apt ?? ''])];
        }
        if (st.view === 'themes') {
            const rows = this._themeRows(st.slug).filter(r => st.years.includes(r.year));
            return [['theme_id', 'theme_label', 'year', 'papers'],
                    ...rows.map(r => [r.theme_id,
                                      (this.themeById[r.theme_id] || {}).label || '',
                                      r.year, r.n])];
        }
        const siteTot = {};
        for (const r of (this.data.theme_site || [])) {
            if (r.slug === st.slug) siteTot[r.theme_id] = r.n;
        }
        return [['theme_id', 'theme_label', 'site_papers', 'portfolio_papers'],
                ...(this.data.themes || []).map(t =>
                    [t.theme_id, t.label, siteTot[t.theme_id] || 0, t.size])];
    }
}
