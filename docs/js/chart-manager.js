/**
 * IMPACT-NCATS Chart Manager
 * Chart.js construction and download helpers.
 */

class ChartManager {
    // Okabe-Ito colorblind-safe palette (matches IMPACT).
    // Yellow and black replaced with purple and gray for web legibility.
    static PALETTE = [
        '#0072B2', // 1 blue
        '#D55E00', // 2 vermilion
        '#009E73', // 3 bluish green
        '#56B4E9', // 4 sky blue
        '#E69F00', // 5 orange/amber
        '#CC79A7', // 6 reddish purple
        '#7B2D8B', // 7 purple
        '#7f7f7f', // 8 gray
        '#44AA99', // 9 teal
        '#AA4499', // 10 mauve
    ];

    static color(i) {
        return ChartManager.PALETTE[i % ChartManager.PALETTE.length];
    }

    static _destroy(canvasId) {
        const existing = Chart.getChart(canvasId);
        if (existing) existing.destroy();
    }

    static lineChart(canvasId, labels, datasets, opts = {}) {
        ChartManager._destroy(canvasId);
        return new Chart(document.getElementById(canvasId), {
            type: 'line',
            data: { labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'nearest', intersect: false },
                plugins: {
                    legend: { position: 'top', labels: { boxWidth: 14 } },
                    tooltip: { enabled: true },
                },
                scales: {
                    y: { beginAtZero: true, title: { display: !!opts.yLabel, text: opts.yLabel } },
                    x: { title: { display: !!opts.xLabel, text: opts.xLabel } },
                },
                ...opts.chartOptions,
            },
        });
    }

    static barChart(canvasId, labels, datasets, opts = {}) {
        ChartManager._destroy(canvasId);
        return new Chart(document.getElementById(canvasId), {
            type: 'bar',
            data: { labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'top', labels: { boxWidth: 14 } } },
                scales: {
                    y: {
                        beginAtZero: true, stacked: !!opts.stacked,
                        title: { display: !!opts.yLabel, text: opts.yLabel },
                    },
                    x: { stacked: !!opts.stacked },
                },
                ...opts.chartOptions,
            },
        });
    }

    static download(chart, format, filename) {
        if (format === 'png' || format === 'jpg') {
            const mime = format === 'png' ? 'image/png' : 'image/jpeg';
            const a = document.createElement('a');
            a.href = chart.canvas.toDataURL(mime, 1.0);
            a.download = `${filename}.${format}`;
            a.click();
            return;
        }
        if (format === 'pdf') {
            const { jsPDF } = window.jspdf;
            const pdf = new jsPDF({ orientation: 'landscape' });
            pdf.addImage(chart.canvas.toDataURL('image/png', 1.0), 'PNG', 10, 10, 275, 150);
            pdf.save(`${filename}.pdf`);
        }
    }

    static downloadCSV(rows, filename) {
        const csv = rows.map(r => r.map(c => {
            const s = c === null || c === undefined ? '' : String(c);
            return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
        }).join(',')).join('\n');
        const a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
        a.download = `${filename}.csv`;
        a.click();
    }
}

/** Format a possibly-null metric for display. Never shows "null" or "NaN". */
function fmt(value, digits = 2) {
    if (value === null || value === undefined || Number.isNaN(value)) return '—';
    return Number(value).toFixed(digits);
}

/** Format a dollar amount with thousands separators. */
function fmtMoney(value) {
    if (value === null || value === undefined || Number.isNaN(value)) return '—';
    return `$${Math.round(value).toLocaleString()}`;
}
