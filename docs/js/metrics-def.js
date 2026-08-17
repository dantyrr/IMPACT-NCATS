/**
 * One shared metric registry for both tabs.
 *
 * Site Detail and Across Sites previously kept their own hard-coded metric
 * lists, which is how "award dollars" ended up available on one tab and not the
 * other. Defining each metric once here keeps them in step.
 *
 *   key       column name in site_metrics (or a rolling-snapshot field)
 *   label     dropdown / axis text
 *   kind      'count'   sum across rows           (publications, citations, awards, $)
 *             'rate'    weighted mean by pub_count (mean RCR)
 *             'ratio'   ratio of sums              (per-$ efficiency, cost per pub)
 *             'rolling' monthly snapshot series    (rolling citation rates)
 *   fmt       'int' | 'money' | 'dec'
 */

const METRICS = [
    { key: 'pub_count',           label: 'Publications',                    kind: 'count', fmt: 'int' },
    { key: 'research_count',      label: 'Research articles',               kind: 'count', fmt: 'int' },
    { key: 'citation_count',      label: 'Citations',                       kind: 'count', fmt: 'int' },
    { key: 'award_count',         label: 'Awards',                          kind: 'count', fmt: 'int' },
    { key: 'award_total',         label: 'Award dollars',                   kind: 'count', fmt: 'money' },
    { key: 'mean_rcr',            label: 'Mean RCR',                        kind: 'rate',  fmt: 'dec' },
    { key: 'pubs_per_million',    label: 'Publications per $1M',            kind: 'ratio', fmt: 'dec',
      numer: 'pub_count' },
    { key: 'citations_per_million', label: 'Citations per $1M',             kind: 'ratio', fmt: 'dec',
      numer: 'citation_count' },
    { key: 'cost_per_pub',        label: 'Cost per publication',            kind: 'ratio', fmt: 'money',
      invert: 'pub_count' },
    { key: 'cost_per_citation',   label: 'Cost per citation',               kind: 'ratio', fmt: 'money',
      invert: 'citation_count' },
    { key: 'rate_12m',            label: 'Rolling citation rate (12-mo)',   kind: 'rolling', fmt: 'dec' },
    { key: 'rate_24m',            label: 'Rolling citation rate (24-mo)',   kind: 'rolling', fmt: 'dec' },
    { key: 'rate_5yr',            label: 'Rolling citation rate (5-yr)',    kind: 'rolling', fmt: 'dec' },
];

const METRIC_BY_KEY = Object.fromEntries(METRICS.map(m => [m.key, m]));

/** Metrics whose value depends on award dollars, so they mislead without context. */
const EFFICIENCY_METRICS = new Set([
    'pubs_per_million', 'citations_per_million', 'cost_per_pub', 'cost_per_citation',
]);

function metricOptions(selected, only) {
    return METRICS
        .filter(m => !only || only.includes(m.kind))
        .map(m => `<option value="${m.key}"${m.key === selected ? ' selected' : ''}>${m.label}</option>`)
        .join('');
}

function metricLabel(key) {
    return (METRIC_BY_KEY[key] || {}).label || key;
}

/** Format a value according to its metric's declared format. */
function metricFmt(key, value) {
    const m = METRIC_BY_KEY[key] || {};
    if (value === null || value === undefined || Number.isNaN(value)) return '—';
    if (m.fmt === 'money') return fmtMoney(value);
    if (m.fmt === 'int') return Math.round(value).toLocaleString();
    return fmt(value);
}

/**
 * Aggregate site_metrics rows into a single value for one metric.
 * Counts sum; rates are weighted by publication count; ratios are a ratio of
 * sums, and are null rather than infinite when the denominator is zero.
 */
function aggregateMetric(rows, key) {
    const m = METRIC_BY_KEY[key];
    if (!m || !rows.length) return null;

    if (m.kind === 'count') {
        return rows.reduce((s, r) => s + (r[key] || 0), 0);
    }
    if (m.kind === 'rate') {
        let num = 0, den = 0;
        for (const r of rows) {
            if (r[key] === null || r[key] === undefined) continue;
            num += r[key] * (r.pub_count || 0);
            den += r.pub_count || 0;
        }
        return den > 0 ? num / den : null;
    }
    // ratio
    const dollars = rows.reduce((s, r) => s + (r.award_total || 0), 0);
    if (m.invert) {
        const denom = rows.reduce((s, r) => s + (r[m.invert] || 0), 0);
        return denom > 0 ? dollars / denom : null;
    }
    const numer = rows.reduce((s, r) => s + (r[m.numer] || 0), 0);
    return dollars > 0 ? numer / (dollars / 1e6) : null;
}
