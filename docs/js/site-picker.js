/**
 * SitePicker — searchable multi-select for CTSA sites.
 * Adapted from IMPACT's JournalPicker.
 */

class SitePicker {
    constructor(containerId, sites, palette, onChange) {
        this.container = document.getElementById(containerId);
        this.sites = sites;
        this.palette = palette;
        this.onChange = onChange;
        this.selected = [];
        this.render();
    }

    render() {
        this.container.innerHTML = `
            <div class="picker">
                <input type="text" class="picker-input" placeholder="Search sites…" autocomplete="off">
                <div class="picker-results" style="display:none;"></div>
                <div class="picker-chips"></div>
            </div>`;
        this.input = this.container.querySelector('.picker-input');
        this.results = this.container.querySelector('.picker-results');
        this.chips = this.container.querySelector('.picker-chips');

        this.input.addEventListener('input', () => this._renderResults());
        this.input.addEventListener('focus', () => this._renderResults());
        document.addEventListener('click', (e) => {
            if (!this.container.contains(e.target)) this.results.style.display = 'none';
        });
        this._renderChips();
    }

    _renderResults() {
        const term = this.input.value.toLowerCase().trim();
        // No result cap: there are only ~72 sites and the dropdown scrolls.
        // A cap silently hid everything alphabetically after ~"Oregon",
        // including Yale and UAB, with no indication they existed.
        const matches = this.sites
            .filter(s => !this.selected.includes(s.slug))
            .filter(s => !term || (s.hub_name || '').toLowerCase().includes(term)
                                || (s.state || '').toLowerCase() === term);

        if (!matches.length) { this.results.style.display = 'none'; return; }
        this.results.innerHTML = matches.map(s =>
            `<div class="picker-option" data-slug="${s.slug}">${s.hub_name}
                <span class="picker-meta">${s.state || ''}</span></div>`).join('');
        this.results.style.display = 'block';
        this.results.querySelectorAll('.picker-option').forEach(el =>
            el.addEventListener('click', () => {
                this.selected.push(el.dataset.slug);
                this.input.value = '';
                this.results.style.display = 'none';
                this._renderChips();
                this.onChange();
            }));
    }

    _renderChips() {
        const map = this.getColorMap();
        this.chips.innerHTML = this.selected.map(slug => {
            const site = this.sites.find(s => s.slug === slug);
            return `<span class="picker-chip" style="background:${map[slug]}">
                        ${site ? site.hub_name : slug}
                        <button class="chip-remove" data-slug="${slug}">×</button>
                    </span>`;
        }).join('');
        this.chips.querySelectorAll('.chip-remove').forEach(btn =>
            btn.addEventListener('click', () => {
                this.selected = this.selected.filter(s => s !== btn.dataset.slug);
                this._renderChips();
                this.onChange();
            }));
    }

    getColorMap() {
        const map = {};
        this.selected.forEach((slug, i) => { map[slug] = this.palette[i % this.palette.length]; });
        return map;
    }

    getSelected() { return [...this.selected]; }
}
