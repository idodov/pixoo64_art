const DEFAULT_PREVIEW_SVG = 'data:image/svg+xml;utf8,' + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><rect width="64" height="64" fill="#0b0e17"/><circle cx="32" cy="32" r="22" fill="#181e2e" stroke="#00ffcc" stroke-width="2"/><circle cx="32" cy="32" r="8" fill="#00ffcc"/><circle cx="32" cy="32" r="3" fill="#0b0e17"/></svg>`);

const SECTIONS_METADATA = [
  { id: 'display', icon: '🖼️', name: 'Artwork Screen Display', configKey: 'show_display', defaultShow: true, desc: 'Main 64x64 pixel retro canvas, live rendering stream, CRT scanline grid, and live prefetch status badge.' },
  { id: 'track_info', icon: '🎵', name: 'Track & Artist Metadata', configKey: 'show_track_info', defaultShow: true, desc: 'Current song title and artist text formatted with dynamic album-adaptive glow colors.' },
  { id: 'next_track', icon: '⏭️', name: 'Next Track Prefetch Preview', configKey: 'show_next_track', defaultShow: true, desc: 'Displays upcoming queue item cached into device memory for seamless transitions.' },
  { id: 'media_controls', icon: '⏯️', name: 'Media Player Controls', configKey: 'show_media', defaultShow: true, desc: 'Playback transport buttons and interactive volume level slider.' },
  { id: 'modes', icon: '💽', name: 'Display Modes', configKey: 'show_modes', defaultShow: true, desc: 'Interactive buttons for Standard, Vinyl record rendering, and Lyrics display with inline sync.' },
  { id: 'pixoo_controls', icon: '📺', name: 'Pixoo Hardware Controls', configKey: 'show_pixoo_controls', defaultShow: true, desc: 'Direct controls for power, brightness, and channel selectors.' },
  { id: 'advanced', icon: '⚙️', name: 'Advanced Display Tuning', configKey: 'show_advanced', defaultShow: true, desc: 'Collapsible configuration suite: Image crop ratios, progress bar toggle, text background, filters, and overlays.' },
  { id: 'stats', icon: '📊', name: 'Technical Diagnostics Panel', configKey: 'show_stats', defaultShow: false, desc: 'Live telemetry diagnostics including pipeline durations, memory caches, and slider worker state.' }
];

class PixooMediaCardEditor extends HTMLElement {
  set hass(h) { this._hass = h; if (this._config && !this._rendered) this.render(); }
  setConfig(c) { this._config = c; if (this._hass && !this._rendered) this.render(); else if (this._rendered) this._updateFieldValues(); }
  _getLayoutOrder() {
    const d = SECTIONS_METADATA.map((s) => s.id);
    if (!this._config || !Array.isArray(this._config.layout_order)) return d;
    const cur = [...this._config.layout_order];
    d.forEach((id) => { if (!cur.includes(id)) cur.push(id); });
    return cur;
  }
  render() {
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    const cfg = this._config || {}, order = this._getLayoutOrder();
    this.shadowRoot.innerHTML = `
      <style>
        .form{display:flex;flex-direction:column;gap:10px;font-family:sans-serif;color:#e2e8f0;padding:4px}
        .box{background:rgba(18,22,36,.85);border:1px solid rgba(0,255,204,.25);border-radius:8px;padding:8px 10px;display:flex;flex-direction:column;gap:4px}
        label.lbl{font-size:.82rem;color:#00ffcc;font-weight:700;display:flex;align-items:center;gap:5px}
        .desc{font-size:.72rem;color:#94a3b8;line-height:1.3}
        select{background:#101422;border:1px solid rgba(255,255,255,.18);color:#fff;padding:6px 8px;border-radius:6px;font-size:.82rem;outline:none}
        select:focus{border-color:#00ffcc}
        .hdr{font-size:.75rem;font-weight:800;text-transform:uppercase;letter-spacing:.8px;color:#00ffcc;border-bottom:1px solid rgba(0,255,204,.2);padding-bottom:3px;display:flex;justify-content:space-between;align-items:center}
        .row{display:flex;align-items:center;gap:8px;font-size:.82rem;cursor:pointer}
        .row input{accent-color:#00ffcc;width:15px;height:15px;cursor:pointer}
        .list{display:flex;flex-direction:column;gap:5px}
        .item{background:rgba(22,28,44,.7);border:1px solid rgba(255,255,255,.08);border-radius:6px;padding:6px 8px;display:flex;align-items:center;justify-content:space-between;gap:8px}
        .info{flex:1;display:flex;flex-direction:column;gap:2px}
        .t-row{display:flex;align-items:center;gap:6px;cursor:pointer}
        .t-row input{accent-color:#00ffcc;width:14px;height:14px;margin:0}
        .name{font-size:.8rem;font-weight:700;color:#f8fafc}
        .sub{font-size:.68rem;color:#94a3b8;margin-left:20px}
        .btns{display:flex;flex-direction:column;gap:2px}
        .btn{background:rgba(16,20,34,.85);border:1px solid rgba(255,255,255,.15);color:#94a3b8;border-radius:4px;width:22px;height:16px;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:.6rem}
        .btn:hover:not(:disabled){background:#00ffcc;color:#05070d;border-color:#00ffcc}
        .btn:disabled{opacity:.25;cursor:not-allowed}
      </style>
      <div class="form">
        <div class="box">
          <label class="lbl">📡 Pixoo Status Sensor</label>
          <div class="desc">Selects the Pixoo status sensor to auto-detect media player, album art, and device state.</div>
          <select id="entity_sensor"><option value="">-- Select Sensor --</option>${this._getPixooSensorOptions(cfg.entity_sensor)}</select>
        </div>
        <div class="box" style="border-color:rgba(255,255,255,.15);">
          <label class="lbl">🎨 Appearance & Spacing</label>
          <div class="row"><input type="checkbox" id="show_background" ${cfg.show_background !== false ? 'checked' : ''} /><label for="show_background">Ambient Background & Glow</label></div>
          <select id="area_padding" style="margin-top:4px;">
            <option value="default" ${cfg.area_padding !== 'none' && cfg.area_padding !== 'compact' ? 'selected' : ''}>Default Padding</option>
            <option value="compact" ${cfg.area_padding === 'compact' ? 'selected' : ''}>Compact Padding</option>
            <option value="none" ${cfg.area_padding === 'none' ? 'selected' : ''}>None (Flush)</option>
          </select>
        </div>
        <div class="hdr"><span>Areas Ordering</span></div>
        <div class="list" id="areas-container">
          ${order.map((id, idx) => {
            const m = SECTIONS_METADATA.find((s) => s.id === id); if (!m) return '';
            const chk = cfg[m.configKey] !== undefined ? Boolean(cfg[m.configKey]) : m.defaultShow;
            return `<div class="item" data-id="${m.id}"><div class="info"><label class="t-row" for="c_${m.configKey}"><input type="checkbox" id="c_${m.configKey}" data-k="${m.configKey}" ${chk ? 'checked' : ''} /><span class="name">${m.icon} ${m.name}</span></label><div class="sub">${m.desc}</div></div><div class="btns"><button class="btn up" data-id="${m.id}" ${idx === 0 ? 'disabled' : ''}>▲</button><button class="btn down" data-id="${m.id}" ${idx === order.length - 1 ? 'disabled' : ''}>▼</button></div></div>`;
          }).join('')}
        </div>
      </div>`;
    this._rendered = true;
    this.shadowRoot.getElementById('entity_sensor')?.addEventListener('change', (e) => this._updateConfigValue('entity_sensor', e.target.value));
    this.shadowRoot.getElementById('show_background')?.addEventListener('change', (e) => this._updateConfigValue('show_background', e.target.checked));
    this.shadowRoot.getElementById('area_padding')?.addEventListener('change', (e) => this._updateConfigValue('area_padding', e.target.value));
    this.shadowRoot.querySelectorAll('input[type="checkbox"][data-k]').forEach((c) => c.addEventListener('change', (e) => this._updateConfigValue(e.target.getAttribute('data-k'), e.target.checked)));
    this.shadowRoot.querySelectorAll('.up').forEach((b) => b.addEventListener('click', () => this._moveSection(b.getAttribute('data-id'), -1)));
    this.shadowRoot.querySelectorAll('.down').forEach((b) => b.addEventListener('click', () => this._moveSection(b.getAttribute('data-id'), 1)));
  }
  _moveSection(id, dir) {
    const o = this._getLayoutOrder(), idx = o.indexOf(id), nIdx = idx + dir;
    if (idx === -1 || nIdx < 0 || nIdx >= o.length) return;
    [o[idx], o[nIdx]] = [o[nIdx], o[idx]];
    this._updateConfigValue('layout_order', o);
    this.render();
  }
  _updateFieldValues() {
    if (!this._config || !this.shadowRoot) return;
    SECTIONS_METADATA.forEach((m) => { const c = this.shadowRoot.getElementById(`c_${m.configKey}`); if (c) c.checked = this._config[m.configKey] !== undefined ? Boolean(this._config[m.configKey]) : m.defaultShow; });
    const s = this.shadowRoot.getElementById('entity_sensor'); if (s && this._config.entity_sensor) s.value = this._config.entity_sensor;
    const bg = this.shadowRoot.getElementById('show_background'); if (bg) bg.checked = this._config.show_background !== false;
    const p = this.shadowRoot.getElementById('area_padding'); if (p && this._config.area_padding) p.value = this._config.area_padding;
  }
  _getPixooSensorOptions(val) {
    if (!this._hass) return '';
    return Object.keys(this._hass.states).filter((e) => e.startsWith('sensor.') && (e.includes('pixoo64_media_display') || e.includes('pixoo64_status') || (e.includes('pixoo') && this._hass.states[e].attributes?.active_mode !== undefined))).sort().map((e) => `<option value="${e}" ${e === val ? 'selected' : ''}>${this._hass.states[e].attributes.friendly_name || e} (${e})</option>`).join('');
  }
  _updateConfigValue(k, v) {
    if (!this._config || !this._hass) return;
    this._config = { ...this._config, [k]: v };
    this.dispatchEvent(new CustomEvent('config-changed', { detail: { config: this._config }, bubbles: true, composed: true }));
  }
}
if (!customElements.get('pixoo-media-card-editor')) customElements.define('pixoo-media-card-editor', PixooMediaCardEditor);

class PixooMediaCard extends HTMLElement {
  static getConfigElement() { return document.createElement('pixoo-media-card-editor'); }
  static getStubConfig(h) {
    const s = h?.states ? Object.keys(h.states).find((e) => e.startsWith('sensor.') && (e.includes('pixoo64_media_display') || e.includes('pixoo64_status') || (e.includes('pixoo') && h.states[e].attributes?.active_mode !== undefined))) || '' : '';
    return { entity_sensor: s, layout_order: SECTIONS_METADATA.map((x) => x.id), show_background: true, area_padding: 'default', show_display: true, show_track_info: true, show_media: true, show_modes: true, show_pixoo_controls: true, show_advanced: true, show_next_track: true, show_stats: false };
  }
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._savedNonVinylCrop = null; this._textBgLocalState = false; this._progressBarLocalState = true;
    this._userSelectedChannel = null; this._localPowerState = null; this._lastTrackTitle = '';
    this._pendingTargetMode = null; this._previousLiveImage = ''; this._busyWatchdog = null;
    this._rendered = false; this._lastStateHash = ''; this._lastLiveImage = ''; this._lastModesOptionsSignature = '';
    this._lastFilterSignature = ''; this._lastStatsSignature = ''; this._lastThemeSignature = ''; this._lastLayoutOrderSig = '';
    this._persistentTheme = null; this._imageExtractedTheme = null; this._entityMap = {};
  }
  setConfig(c) {
    if (!c) throw new Error('Invalid config');
    this._config = { entity_sensor: '', layout_order: SECTIONS_METADATA.map((x) => x.id), show_background: true, area_padding: 'default', show_display: true, show_track_info: true, show_media: true, show_modes: true, show_pixoo_controls: true, show_advanced: true, show_next_track: true, show_stats: false, ...c };
    this._entityMap = {}; this._lastStateHash = '';
    if (!this._rendered) { this.render(); this._rendered = true; }
    if (this._hass) this.updateValues(true);
  }
  connectedCallback() {
    if (!this._rendered) { this.render(); this._rendered = true; }
    if (this._hass) this.updateValues(true);
    // Local tick timer to update progress bar smoothly every second during playback
    this._progressInterval = setInterval(() => this._tickProgress(), 1000);
  }
  disconnectedCallback() {
    if (this._progressInterval) clearInterval(this._progressInterval);
  }
  set hass(h) {
    this._hass = h;
    if (!this._rendered) { this.render(); this._rendered = true; }
    if (this._config && !this._config.entity_sensor && h?.states) {
      const a = Object.keys(h.states).find((e) => e.startsWith('sensor.') && (e.includes('pixoo64_media_display') || e.includes('pixoo64_status') || (e.includes('pixoo') && h.states[e].attributes?.active_mode !== undefined)));
      if (a) this._config = { ...this._config, entity_sensor: a };
    }
    this.updateValues(false);
  }
  _getMediaPlayerEntity() { return this._hass?.states[this._config?.entity_sensor]?.attributes?.media_player || this._config?.entity_media_player || null; }
  _findDeviceEntity(doms, sfxs) {
    if (!this._hass || !this._config?.entity_sensor) return null;
    const ck = `${doms.join(',')}_${sfxs.join(',')}`;
    if (ck in this._entityMap) return this._entityMap[ck] && this._hass.states[this._entityMap[ck]] ? this._entityMap[ck] : null;
    const raw = (this._config.entity_sensor.split('.')[1] || '').replace(/_pixoo64_status$/, '').replace(/_status$/, '');
    const clean = raw.replace(/_media_display$/, '');
    for (const d of doms) {
      for (const s of sfxs) {
        for (const c of [`${d}.${raw}_${s}`, `${d}.${clean}_${s}`, `${d}.${clean}_pixoo64_${s}`, `${d}.pixoo64_${s}`, `${d}.${s}`]) {
          if (this._hass.states[c]) { this._entityMap[ck] = c; return c; }
        }
      }
    }
    const all = Object.keys(this._hass.states);
    for (const d of doms) {
      for (const s of sfxs) {
        const m = all.find((id) => id.startsWith(`${d}.`) && id.includes(s) && (id.includes('pixoo') || (clean && id.includes(clean))));
        if (m) { this._entityMap[ck] = m; return m; }
      }
    }
    this._entityMap[ck] = null; return null;
  }
  _tickProgress() {
    const mpId = this._getMediaPlayerEntity();
    const pixooProgBar = this.shadowRoot.getElementById('pixoo-pixel-progress');
    const fillEl = this.shadowRoot.getElementById('pixoo-pixel-progress-fill');
    if (!pixooProgBar || !fillEl) return;

    if (!mpId || !this._hass) {
      pixooProgBar.style.display = 'none';
      return;
    }
    const mState = this._hass.states[mpId];
    const sensorState = this._config?.entity_sensor ? this._hass.states[this._config.entity_sensor] : null;
    const sA = sensorState?.attributes || {};
    
    const isPlay = mState && (mState.state === 'playing' || mState.state === 'on');
    let isP = sA.progress_bar !== undefined ? ['true', 'on', 'enabled'].includes(String(sA.progress_bar).toLowerCase()) : sA.progress_bar_active === true;

    if (!isP || !isPlay || !mState) {
      pixooProgBar.style.display = 'none';
      return;
    }

    const mA = mState.attributes || {};
    const pos = mA.media_position || 0, dur = mA.media_duration || 0, updatedAt = mA.media_position_updated_at;
    if (dur <= 0) {
      pixooProgBar.style.display = 'none';
      return;
    }

    pixooProgBar.style.display = 'block';
    let curPos = pos;
    if (updatedAt && mState.state === 'playing') {
      const diff = (Date.now() - new Date(updatedAt).getTime()) / 1000;
      if (diff > 0 && diff < 3600) curPos += diff;
    }
    const pct = Math.min(100, Math.max(0, (curPos / dur) * 100));
    fillEl.style.width = `${pct}%`;
  }
  _startRenderingLock(mode) {
    this._pendingTargetMode = mode;
    this._previousLiveImage = this._lastLiveImage || '';
    const r = this.shadowRoot, o = r.getElementById('render-overlay'), t = r.getElementById('render-text');
    if (o && t) {
      t.textContent = mode.startsWith('Vinyl') ? 'Rendering Vinyl Disc...' : mode === 'Lyrics' ? 'Syncing Lyrics...' : mode === 'AI Art' ? 'Generating AI Artwork...' : 'Generating Display...';
      o.style.display = 'flex';
    }
    r.getElementById('modes-controls-wrapper')?.classList.add('locked');
    r.getElementById('cat-crop-prog')?.classList.add('locked');
    r.getElementById('advanced-wrapper')?.classList.add('locked');
    r.getElementById('device-controls-wrapper')?.classList.add('locked');
    r.getElementById('media-controls-wrapper')?.classList.add('locked');

    if (this._busyWatchdog) clearTimeout(this._busyWatchdog);
    const timeout = mode === 'AI Art' ? 45000 : 12000;
    this._busyWatchdog = setTimeout(() => {
      const s = this._hass?.states[this._config?.entity_sensor];
      if (s?.attributes?.ai_generating === true) return;
      this._releaseRenderingLock();
    }, timeout);
  }
  _releaseRenderingLock() {
    this._pendingTargetMode = null;
    if (this._busyWatchdog) { clearTimeout(this._busyWatchdog); this._busyWatchdog = null; }
    const r = this.shadowRoot, o = r.getElementById('render-overlay');
    if (o) o.style.display = 'none';
    r.getElementById('modes-controls-wrapper')?.classList.remove('locked');
    r.getElementById('cat-crop-prog')?.classList.remove('locked');
    r.getElementById('advanced-wrapper')?.classList.remove('locked');
    r.getElementById('device-controls-wrapper')?.classList.remove('locked');
    r.getElementById('media-controls-wrapper')?.classList.remove('locked');
  }
  render() {
    const pad = this._config?.area_padding || 'default', bg = this._config?.show_background !== false && pad !== 'none';
    const cls = [pad === 'none' ? 'p-none' : pad === 'compact' ? 'p-compact' : 'p-def', !bg ? 'no-bg' : ''].filter(Boolean).join(' ');
    this.shadowRoot.innerHTML = `
      <style>
        :host{--album-bg:#111420;--pixoo-primary:#00ffcc;--pixoo-color1:rgba(0,255,204,.35);--pixoo-color2:rgba(56,189,248,.3);--pixoo-color3:rgba(129,140,248,.25);--pixoo-glow:rgba(0,255,204,.35);--pixoo-border-tint:rgba(0,255,204,.25);--pixoo-text:#f8fafc;--pixoo-muted:#94a3b8;display:block}
        ha-card{position:relative;background:var(--album-bg,#0e121e);border:1px solid var(--pixoo-border-tint,rgba(0,255,204,.25));border-radius:14px;color:var(--pixoo-text,#f8fafc);box-shadow:0 8px 24px rgba(0,0,0,.6);overflow:hidden;box-sizing:border-box}
        ha-card.p-def{padding:12px}.p-def .content{gap:8px}.p-def .box{padding:8px 10px;border-radius:8px}
        ha-card.p-compact{padding:6px}.p-compact .content{gap:4px}.p-compact .box{padding:5px 8px;border-radius:6px}.p-compact .disp{border-radius:6px}
        ha-card.p-none{padding:0!important;background:#0a0d14!important;border-radius:10px!important}.p-none .bg,.p-none .overlay{display:none!important}.p-none .content{gap:0!important;padding:0!important}
        .p-none .disp{border-radius:0!important;border:none!important;border-bottom:1px solid rgba(255,255,255,.12)!important}
        .p-none .box{border-radius:0!important;border:none!important;border-bottom:1px solid rgba(255,255,255,.08)!important;padding:6px 10px!important;background:#0c0f18!important}
        .p-none .content>*:last-child{border-bottom:none!important}
        .bg{position:absolute;top:-40px;left:-40px;right:-40px;bottom:-40px;background-size:cover;background-position:center;filter:blur(40px) saturate(2.4) brightness(.38);opacity:0;transform:scale(1.2);pointer-events:none;z-index:0;transition:background-image .8s ease,opacity .8s ease}
        .overlay{position:absolute;top:0;left:0;width:100%;height:100%;background:radial-gradient(circle at 12% 15%,var(--pixoo-color1,rgba(0,255,204,.32)) 0%,transparent 60%),radial-gradient(circle at 88% 22%,var(--pixoo-color2,rgba(56,189,248,.28)) 0%,transparent 60%),radial-gradient(circle at 50% 88%,var(--pixoo-color3,rgba(129,140,248,.25)) 0%,transparent 65%),rgba(11,14,23,.62);pointer-events:none;z-index:0}
        ha-card.no-bg{background:var(--ha-card-background,var(--card-background-color,#111420))!important}.no-bg .bg,.no-bg .overlay{display:none!important}
        .content{position:relative;z-index:1;display:flex;flex-direction:column}
        .disp{position:relative;width:100%;padding-top:100%;background:#000;border:2px solid rgba(255,255,255,.14);border-radius:10px;overflow:hidden;box-shadow:0 6px 20px rgba(0,0,0,.75);box-sizing:border-box}
        .disp img{position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover;image-rendering:pixelated;display:block}
        .grid{position:absolute;top:0;left:0;width:100%;height:100%;background-image:linear-gradient(rgba(0,0,0,.65) 1px,transparent 1px),linear-gradient(90deg,rgba(0,0,0,.65) 1px,transparent 1px);background-size:calc(100%/64) calc(100%/64);box-shadow:inset 0 0 10px rgba(0,0,0,.85);pointer-events:none;z-index:2}
        .badge{position:absolute;top:6px;right:6px;z-index:3;display:flex;align-items:center;gap:5px;background:rgba(0,0,0,.82);padding:3px 8px;border-radius:12px;font-size:.68rem;font-weight:600;color:#fff;border:1px solid var(--pixoo-border-tint)}
        .dot{width:7px;height:7px;background-color:var(--pixoo-primary);border-radius:50%;box-shadow:0 0 7px var(--pixoo-primary)}
        .hud{position:absolute;top:0;left:0;width:100%;height:100%;z-index:4;backdrop-filter:blur(5px);background:rgba(8,12,22,.82);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px}
        .spin{width:26px;height:26px;border:2.5px solid rgba(0,255,204,.2);border-top:2.5px solid var(--pixoo-primary);border-radius:50%;animation:sp .8s linear infinite;box-shadow:0 0 12px var(--pixoo-glow)}
        .hud-txt{font-family:monospace;font-size:.74rem;font-weight:700;color:var(--pixoo-primary);text-shadow:0 0 8px var(--pixoo-glow);letter-spacing:.6px}
        @keyframes sp{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}
        .pixoo-pixel-progress{position:absolute;bottom:0;left:0;width:100%;height:calc(100% / 64);background:rgba(0,0,0,.5);z-index:3;pointer-events:none}
        .pixoo-pixel-progress-fill{height:100%;width:0%;background:var(--pixoo-primary,#00ffcc);box-shadow:0 0 4px var(--pixoo-primary,#00ffcc);transition:width .2s linear}
        .box{background:rgba(12,15,24,.76);border:1px solid rgba(255,255,255,.11);border-radius:8px;padding:8px 10px;box-shadow:0 3px 10px rgba(0,0,0,.25);box-sizing:border-box}
        .t-info{position:relative;text-align:center;display:flex;flex-direction:column;justify-content:center;min-height:46px}
        .ttl{font-weight:800;font-size:1.18rem;line-height:1.25;color:#fff;text-shadow:0 2px 5px rgba(0,0,0,.9);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:0 26px}
        .art{font-size:.92rem;line-height:1.2;color:var(--pixoo-primary);font-weight:700;text-shadow:0 0 10px var(--pixoo-glow);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:0 26px}
        .lyric-icon{position:absolute;top:6px;right:6px;width:18px;height:18px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;cursor:help;transition:all .25s ease}
        .lyric-icon.avail{background:rgba(0,255,204,.14);color:#00ffcc;border:1px solid rgba(0,255,204,.4);box-shadow:0 0 8px rgba(0,255,204,.3)}
        .lyric-icon.act{background:rgba(56,189,248,.18);color:#38bdf8;border:1px solid rgba(56,189,248,.5);box-shadow:0 0 8px rgba(56,189,248,.35)}
        .lyric-icon.unavail{background:rgba(148,163,184,.08);color:#64748b;border:1px solid rgba(148,163,184,.18);opacity:.4}
        .lyric-icon svg{width:11px;height:11px;fill:currentColor}
        .next-box{font-size:.75rem;display:flex;flex-direction:column;gap:1px;border-left:3px solid var(--pixoo-primary)}
        .next-lbl{font-size:.65rem;color:var(--pixoo-muted);text-transform:uppercase;letter-spacing:.5px}
        .next-ttl{font-weight:bold;color:#f8fafc;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .m-btns{display:flex;justify-content:center;align-items:center;gap:12px;margin-bottom:6px}
        .i-btn{background:rgba(28,34,52,.9);border:1px solid rgba(255,255,255,.15);color:#f8fafc;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:all .2s}
        .i-btn svg{width:17px;height:17px;fill:currentColor}
        .i-btn:hover{background:var(--pixoo-primary);color:#06080e;border-color:var(--pixoo-primary);box-shadow:0 0 10px var(--pixoo-glow)}
        .v-row{display:flex;align-items:center;gap:8px;font-size:.8rem;color:#cbd5e1}
        .v-slider{flex:1;accent-color:var(--pixoo-primary);cursor:pointer;height:4px}
        .p-ctrls{display:flex;flex-direction:column;gap:6px}
        .row{display:flex;gap:5px;flex-wrap:wrap}.row>*{flex:1;min-width:60px}
        select,button.act-btn{background:rgba(26,32,50,.88);border:1px solid rgba(255,255,255,.14);color:#f8fafc;padding:6px 5px;border-radius:6px;font-size:.72rem;cursor:pointer;outline:none;text-align:center;transition:all .2s}
        select:disabled,button.act-btn:disabled{opacity:.35;cursor:not-allowed!important;pointer-events:none}
        select option{background:#111420;color:#fff}
        select:focus,button.act-btn:hover:not(.active):not(:disabled){border-color:var(--pixoo-primary);color:#fff}
        button.act-btn.active{background:var(--pixoo-primary)!important;color:#05070d!important;font-weight:800;border-color:var(--pixoo-primary);box-shadow:0 0 10px var(--pixoo-glow)}
        .locked{pointer-events:none!important;opacity:.55!important;filter:grayscale(.3)!important}
        #modes-buttons-container button.act-btn.active{cursor:default}
        #device-channels-container button.act-btn.active{cursor:pointer;pointer-events:auto}
        #progress-toggle-btn,#textbg-toggle-btn,#pixoo-power-btn{cursor:pointer!important;pointer-events:auto!important}
        .l-dot{display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:4px;vertical-align:middle}
        .l-dot.avail{background-color:#00ffcc;box-shadow:0 0 6px #00ffcc}
        .l-dot.unavail{background-color:#64748b;opacity:.5}
        .sync-row{display:flex;align-items:center;gap:5px;margin-top:2px;padding:4px 8px;background:rgba(16,21,35,.78);border:1px solid rgba(0,255,204,.28);border-radius:6px}
        .sync-lbl{font-size:.72rem;font-weight:700;color:var(--pixoo-primary);white-space:nowrap}
        .s-step{flex:0 0 auto!important;min-width:34px!important;padding:5px 6px!important;font-weight:700!important}
        .adv{overflow:hidden;padding:0}
        .adv-hdr{padding:8px 10px;background:rgba(22,28,44,.85);font-size:.76rem;font-weight:bold;color:#cbd5e1;cursor:pointer;display:flex;justify-content:space-between;align-items:center;user-select:none}
        .adv-hdr:hover{color:var(--pixoo-primary)}
        .adv-body{padding:8px;display:flex;flex-direction:column;gap:8px;border-top:1px solid rgba(255,255,255,.1);background:rgba(10,13,20,.65)}
        .cat-ttl{font-size:.65rem;font-weight:800;color:var(--pixoo-primary);text-transform:uppercase;letter-spacing:.7px;margin-bottom:3px;border-bottom:1px solid var(--pixoo-border-tint);padding-bottom:1px}
        .stats{font-family:monospace;font-size:.7rem;color:var(--pixoo-primary);display:flex;flex-direction:column;gap:2px}
        .stat-item{display:flex;justify-content:space-between;gap:6px;overflow:hidden;text-overflow:ellipsis}
        .stat-lbl{color:var(--pixoo-muted);white-space:nowrap}
      </style>
      <ha-card id="main-card" class="${cls}">
        <div class="bg" id="card-ambient-bg"></div>
        <div class="overlay" id="card-ambient-overlay"></div>
        <div class="content" id="card-content">
          <div class="disp" id="display-wrapper" data-section="display">
            <img id="artwork" src="${DEFAULT_PREVIEW_SVG}" alt="Pixoo Artwork">
            <div class="grid"></div>
            <div class="pixoo-pixel-progress" id="pixoo-pixel-progress" style="display:none;"><div class="pixoo-pixel-progress-fill" id="pixoo-pixel-progress-fill"></div></div>
            <div class="badge" id="activity-badge" style="display:none;"><div class="dot"></div><span id="activity-text">Playing</span></div>
            <div class="hud" id="render-overlay" style="display:none;"><div class="spin"></div><div class="hud-txt" id="render-text">Generating Display...</div></div>
          </div>
          <div class="box t-info" id="track-info-wrapper" data-section="track_info" style="display:none;">
            <div id="title" class="ttl"></div><div id="artist" class="art"></div>
            <div id="lyrics-status-icon" class="lyric-icon" style="display:none;"></div>
          </div>
          <div class="box next-box" id="next-track-wrapper" data-section="next_track" style="display:none;">
            <div class="next-lbl">Next Up (Prefetch)</div><div class="next-ttl" id="next-track-title">-</div>
          </div>
          <div class="box" id="media-controls-wrapper" data-section="media_controls" style="display:none;">
            <div class="m-btns">
              <button class="i-btn" id="prev-btn" title="Previous"><svg viewBox="0 0 24 24"><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z"/></svg></button>
              <button class="i-btn" id="play-pause-btn" title="Play/Pause"><svg id="play-pause-svg" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg></button>
              <button class="i-btn" id="next-btn" title="Next"><svg viewBox="0 0 24 24"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z"/></svg></button>
            </div>
            <div class="v-row" title="Volume Slider"><span>🔊</span><input type="range" class="v-slider" id="vol-slider" min="0" max="100" value="50"></div>
          </div>
          <div class="box p-ctrls" id="modes-controls-wrapper" data-section="modes" style="display:none;">
            <div class="cat-ttl">Display Modes</div>
            <div class="row" id="modes-buttons-container"></div>
            <div class="sync-row" id="lyrics-sync-wrapper" style="display:none;">
              <span class="sync-lbl">⏱️ Sync:</span>
              <button class="act-btn s-step" id="inline-sync-minus-btn" title="1s earlier">-1s</button>
              <select id="inline-sync-select" style="flex:1;" title="Lyrics Sync">
                <option value="-5.0">-5.0s</option><option value="-4.0">-4.0s</option><option value="-3.0">-3.0s</option><option value="-2.0">-2.0s</option><option value="-1.0">-1.0s</option><option value="0.0" selected>0.0s (Normal)</option><option value="1.0">+1.0s</option><option value="2.0">+2.0s</option><option value="3.0">+3.0s</option><option value="4.0">+4.0s</option><option value="5.0">+5.0s</option>
              </select>
              <button class="act-btn s-step" id="inline-sync-plus-btn" title="1s later">+1s</button>
            </div>
          </div>
          <div class="box p-ctrls" id="device-controls-wrapper" data-section="pixoo_controls" style="display:none;">
            <div class="cat-ttl">Pixoo Device Controls</div>
            <div class="row"><button class="act-btn" id="pixoo-power-btn" title="Power">Power: On</button></div>
            <div class="row" style="align-items:center;gap:8px;margin-top:2px;"><span style="font-size:.72rem;color:var(--pixoo-muted);">Brightness</span><input type="range" class="v-slider" id="pixoo-brightness-slider" min="0" max="100" value="100"></div>
            <div class="row" id="device-channels-container" style="margin-top:2px;">
              <button class="act-btn" data-channel="0">Clock</button><button class="act-btn" data-channel="1">Animation #1</button><button class="act-btn" data-channel="3">Animation #2</button><button class="act-btn" data-channel="2">Visualizer</button>
            </div>
          </div>
          <div class="box adv" id="advanced-wrapper" data-section="advanced" style="display:none;">
            <div class="adv-hdr" id="advanced-toggle"><span>⚙️ Advanced Controls</span><span id="advanced-arrow">▼</span></div>
            <div class="adv-body" id="advanced-body" style="display:none;">
              <div id="cat-crop-prog">
                <div class="cat-ttl">Crop & Progress Bar</div>
                <div class="row">
                  <select id="crop-select"><option value="No Crop">Crop: Normal</option><option value="Crop">Crop: Zoom</option><option value="Extra Crop">Crop: Extra Zoom</option></select>
                  <button class="act-btn" id="progress-toggle-btn">Progress: Off</button>
                </div>
              </div>
              <div id="cat-filter"><div class="cat-ttl">Image Filter</div><div class="row"><select id="filter-select"><option value="None">Filter: None</option></select></div></div>
              <div id="cat-text-lyrics">
                <div class="cat-ttl">Artist & Track Title Text</div>
                <div class="row">
                  <select id="text-pos-select"><option value="Bottom">Position: Bottom</option><option value="Top">Position: Top</option><option value="Hidden">Position: Hidden</option></select>
                  <button class="act-btn" id="textbg-toggle-btn">Text BG: Off</button>
                </div>
              </div>
              <div id="cat-overlays">
                <div class="cat-ttl">Clock & Temperature Overlays</div>
                <div class="row">
                  <select id="overlay-select"><option value="None">Overlay: None</option><option value="Clock">Clock</option><option value="Temperature">Temp</option><option value="Clock + Temp">Clock+Temp</option></select>
                  <select id="overlay-pos-select"><option value="Auto (Opposite of Text)">Pos: Auto</option><option value="Top">Pos: Top</option><option value="Bottom">Pos: Bottom</option></select>
                  <select id="overlay-align-select"><option value="Clock Right, Temp Left">Align: Def</option><option value="Clock Left, Temp Right">Align: Rev</option><option value="Centered">Align: Ctr</option></select>
                </div>
              </div>
            </div>
          </div>
          <div class="stats" id="stats-panel" data-section="stats" style="display:none;"></div>
        </div>
      </ha-card>`;

    const root = this.shadowRoot, art = root.getElementById('artwork');
    if (art) {
      art.addEventListener('load', () => {
        const ext = this._extractColorsFromImage(art);
        if (ext) { this._imageExtractedTheme = ext; this._applyTheme(); }
        const s = this._hass?.states[this._config?.entity_sensor];
        if (this._pendingTargetMode && s?.attributes?.ai_generating !== true) {
          this._releaseRenderingLock();
        }
      });
    }
    root.getElementById('prev-btn')?.addEventListener('click', () => this.callMediaService('media_previous_track'));
    root.getElementById('play-pause-btn')?.addEventListener('click', () => this.callMediaService('media_play_pause'));
    root.getElementById('next-btn')?.addEventListener('click', () => this.callMediaService('media_next_track'));
    root.getElementById('vol-slider')?.addEventListener('change', (e) => {
      const mp = this._getMediaPlayerEntity();
      if (mp && this._hass) this._hass.callService('media_player', 'volume_set', { entity_id: mp, volume_level: e.target.value / 100 });
    });
    root.getElementById('display-wrapper')?.addEventListener('click', (e) => {
      const mp = this._getMediaPlayerEntity();
      if (!mp || !this._hass) return;
      const st = this._hass.states[mp];
      const dur = st?.attributes?.media_duration;
      if (!dur) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const pct = Math.max(0, Math.min(1, clickX / rect.width));
      this._hass.callService('media_player', 'media_seek', { entity_id: mp, seek_position: pct * dur });
    });
    root.getElementById('pixoo-power-btn')?.addEventListener('click', () => {
      const btn = root.getElementById('pixoo-power-btn'), on = !(btn.classList.contains('active') || btn.textContent.includes('On'));
      this._localPowerState = on; btn.textContent = on ? 'Power: On' : 'Power: Off'; btn.classList.toggle('active', on);
      if (this._hass && this._config.entity_sensor) this._hass.callService('pixoo64_art', 'send_command', { entity_id: this._config.entity_sensor, command: 'Channel/OnOffScreen', payload: { OnOff: on ? 1 : 0 } });
    });
    root.getElementById('pixoo-brightness-slider')?.addEventListener('change', (e) => {
      if (this._hass && this._config.entity_sensor) this._hass.callService('pixoo64_art', 'send_command', { entity_id: this._config.entity_sensor, command: 'Channel/SetBrightness', payload: { Brightness: parseInt(e.target.value, 10) } });
    });
    root.getElementById('device-channels-container')?.querySelectorAll('button').forEach((b) => {
      b.addEventListener('click', (e) => {
        const ch = parseInt(e.currentTarget.getAttribute('data-channel'), 10);
        this._userSelectedChannel = ch;
        root.getElementById('device-channels-container').querySelectorAll('button').forEach((x) => x.classList.toggle('active', parseInt(x.getAttribute('data-channel'), 10) === ch));
        if (this._hass && this._config.entity_sensor) this._hass.callService('pixoo64_art', 'send_command', { entity_id: this._config.entity_sensor, command: 'Channel/SetIndex', payload: { SelectIndex: ch } });
      });
    });
    const sync = (d) => {
      const eId = this._findDeviceEntity(['number'], ['lyrics_sync']), el = root.getElementById('inline-sync-select');
      if (!eId || !this._hass || !el) return;
      const v = Math.min(5.0, Math.max(-5.0, (parseFloat(el.value) || 0) + d));
      el.value = v.toFixed(1);
      this._hass.callService('number', 'set_value', { entity_id: eId, value: v });
    };
    root.getElementById('inline-sync-minus-btn')?.addEventListener('click', () => sync(-1.0));
    root.getElementById('inline-sync-plus-btn')?.addEventListener('click', () => sync(1.0));
    root.getElementById('inline-sync-select')?.addEventListener('change', (e) => {
      const eId = this._findDeviceEntity(['number'], ['lyrics_sync']);
      if (eId && this._hass) this._hass.callService('number', 'set_value', { entity_id: eId, value: parseFloat(e.target.value) });
    });
    root.getElementById('crop-select')?.addEventListener('change', (e) => {
      const ce = this._findDeviceEntity(['select'], ['crop_mode']), me = this._findDeviceEntity(['select'], ['display_mode']);
      if (me && this._hass?.states[me]?.state !== 'Vinyl') this._savedNonVinylCrop = e.target.value;
      if (ce && this._hass) { this._startRenderingLock('Crop'); this._hass.callService('select', 'select_option', { entity_id: ce, option: e.target.value }); }
    });
    root.getElementById('progress-toggle-btn')?.addEventListener('click', () => {
      const btn = root.getElementById('progress-toggle-btn'), on = btn.textContent.includes('Off');
      this._progressBarLocalState = on; btn.textContent = on ? 'Progress: On' : 'Progress: Off'; btn.classList.toggle('active', on);
      const pe = this._findDeviceEntity(['switch', 'select', 'input_boolean'], ['progress_bar']);
      if (pe && this._hass) {
        const d = pe.split('.')[0];
        if (d === 'select') this._hass.callService('select', 'select_option', { entity_id: pe, option: on ? 'Enabled' : 'Disabled' });
        else this._hass.callService(d, on ? 'turn_on' : 'turn_off', { entity_id: pe });
      }
    });
    root.getElementById('textbg-toggle-btn')?.addEventListener('click', () => {
      const btn = root.getElementById('textbg-toggle-btn'), on = btn.textContent.includes('Off');
      this._textBgLocalState = on; btn.textContent = on ? 'Text BG: On' : 'Text BG: Off'; btn.classList.toggle('active', on);
      const te = this._findDeviceEntity(['switch', 'select', 'input_boolean'], ['text_background', 'text_bg']);
      if (te && this._hass) {
        const d = te.split('.')[0];
        if (d === 'select') this._hass.callService('select', 'select_option', { entity_id: te, option: on ? 'Enabled' : 'Disabled' });
        else this._hass.callService(d, on ? 'turn_on' : 'turn_off', { entity_id: te });
      }
    });
    root.getElementById('filter-select')?.addEventListener('change', (e) => {
      const fe = this._findDeviceEntity(['select'], ['image_filter']);
      if (fe && this._hass) { this._startRenderingLock('Filter'); this._hass.callService('select', 'select_option', { entity_id: fe, option: e.target.value }); }
    });
    root.getElementById('overlay-select')?.addEventListener('change', (e) => { const x = this._findDeviceEntity(['select'], ['overlay_info']); if (x && this._hass) this._hass.callService('select', 'select_option', { entity_id: x, option: e.target.value }); });
    root.getElementById('overlay-pos-select')?.addEventListener('change', (e) => { const x = this._findDeviceEntity(['select'], ['overlay_position']); if (x && this._hass) this._hass.callService('select', 'select_option', { entity_id: x, option: e.target.value }); });
    root.getElementById('overlay-align-select')?.addEventListener('change', (e) => { const x = this._findDeviceEntity(['select'], ['overlay_align']); if (x && this._hass) this._hass.callService('select', 'select_option', { entity_id: x, option: e.target.value }); });
    root.getElementById('text-pos-select')?.addEventListener('change', (e) => { const x = this._findDeviceEntity(['select'], ['artist_track_text']); if (x && this._hass) this._hass.callService('select', 'select_option', { entity_id: x, option: e.target.value }); });
    root.getElementById('advanced-toggle')?.addEventListener('click', () => {
      const b = root.getElementById('advanced-body'), a = root.getElementById('advanced-arrow'), hid = b.style.display === 'none';
      b.style.display = hid ? 'flex' : 'none'; a.textContent = hid ? '▲' : '▼';
    });
  }
  callMediaService(s) { const mp = this._getMediaPlayerEntity(); if (mp && this._hass) this._hass.callService('media_player', s, { entity_id: mp }); }
  _parseChannelIndex(v) {
    if (v === undefined || v === null || v === '') return null;
    if (typeof v === 'number') return v >= 0 && v <= 3 ? v : null;
    const s = String(v).toLowerCase().trim();
    if (s === 'clock' || s === '0') return 0;
    if (s.includes('cloud') || s.includes('animation #1') || s === '1') return 1;
    if (s.includes('visualizer') || s === '2') return 2;
    if (s.includes('custom') || s.includes('animation #2') || s === '3') return 3;
    const p = parseInt(v, 10); return !isNaN(p) && p >= 0 && p <= 3 ? p : null;
  }
  _extractColorsFromImage(img) {
    try {
      if (!img?.complete || img.naturalWidth === 0) return null;
      const cv = document.createElement('canvas'); cv.width = 16; cv.height = 16;
      const ctx = cv.getContext('2d', { willReadFrequently: true }); if (!ctx) return null;
      ctx.drawImage(img, 0, 0, 16, 16);
      const d = ctx.getImageData(0, 0, 16, 16).data;
      let rS = 0, gS = 0, bS = 0, cnt = 0, top = [];
      for (let i = 0; i < d.length; i += 16) {
        const r = d[i], g = d[i + 1], b = d[i + 2], bri = (r + g + b) / 3;
        if (d[i + 3] < 128 || bri < 12 || bri > 245) continue;
        rS += r; gS += g; bS += b; cnt++; top.push([r, g, b]);
      }
      if (!cnt) return null;
      const ar = Math.round(rS / cnt), ag = Math.round(gS / cnt), ab = Math.round(bS / cnt);
      const c1 = top[0] || [ar, ag, ab], c2 = top[Math.floor(top.length / 2)] || [ag, ab, ar], c3 = top[top.length - 1] || [ab, ar, ag];
      return {
        bgColor: `rgb(${Math.round(ar * .22)}, ${Math.round(ag * .22)}, ${Math.round(ab * .22)})`,
        primaryColor: `rgb(${Math.min(255, ar + 65)}, ${Math.min(255, ag + 65)}, ${Math.min(255, ab + 65)})`,
        color1: `rgba(${c1[0]}, ${c1[1]}, ${c1[2]}, .35)`, color2: `rgba(${c2[0]}, ${c2[1]}, ${c2[2]}, .30)`, color3: `rgba(${c3[0]}, ${c3[1]}, ${c3[2]}, .28)`
      };
    } catch { return null; }
  }
  _applyTheme() {
    const sA = (this._config?.entity_sensor ? this._hass?.states[this._config.entity_sensor]?.attributes : null) || {};
    let t = this._persistentTheme || this._imageExtractedTheme || { bgColor: '#111420', primaryColor: '#00ffcc', color1: 'rgba(0,255,204,.35)', color2: 'rgba(56,189,248,.30)', color3: 'rgba(129,140,248,.25)' };
    
    if (Array.isArray(sA.wled_colors) && sA.wled_colors.length >= 3) {
      const [c1, c2, c3] = sA.wled_colors;
      t.color1 = c1.startsWith('#') ? `${c1}55` : c1;
      t.color2 = c2.startsWith('#') ? `${c2}44` : c2;
      t.color3 = c3.startsWith('#') ? `${c3}44` : c3;
    } else if (sA.color1 && sA.color2 && sA.color3) {
      t.color1 = sA.color1.startsWith('#') ? `${sA.color1}55` : sA.color1;
      t.color2 = sA.color2.startsWith('#') ? `${sA.color2}44` : sA.color2;
      t.color3 = sA.color3.startsWith('#') ? `${sA.color3}44` : sA.color3;
    }

    const sig = `${t.bgColor}|${t.primaryColor}|${t.color1}|${t.color2}|${t.color3}`;
    if (this._lastThemeSignature !== sig) {
      this._lastThemeSignature = sig;
      const st = this.style;
      st.setProperty('--album-bg', t.bgColor); st.setProperty('--pixoo-primary', t.primaryColor);
      st.setProperty('--pixoo-color1', t.color1); st.setProperty('--pixoo-color2', t.color2); st.setProperty('--pixoo-color3', t.color3);
      st.setProperty('--pixoo-glow', 'rgba(0,255,204,.28)'); st.setProperty('--pixoo-border-tint', 'rgba(255,255,255,.16)');
    }
  }
  _applyLayoutReordering() {
    const c = this.shadowRoot.getElementById('card-content'); if (!c || !this._config) return;
    const o = Array.isArray(this._config.layout_order) ? this._config.layout_order : SECTIONS_METADATA.map((x) => x.id);
    const sig = o.join(','); if (this._lastLayoutOrderSig === sig) return;
    this._lastLayoutOrderSig = sig;
    const m = {}; Array.from(c.children).forEach((ch) => { const id = ch.getAttribute('data-section'); if (id) m[id] = ch; });
    o.forEach((id) => { if (m[id]) c.appendChild(m[id]); });
  }
  updateValues(force = false) {
    if (!this._hass || !this.shadowRoot || !this._config) return;
    this._applyLayoutReordering();
    const pad = this._config?.area_padding || 'default', bg = this._config?.show_background !== false && pad !== 'none';
    const card = this.shadowRoot.getElementById('main-card');
    if (card) { card.classList.toggle('p-none', pad === 'none'); card.classList.toggle('p-compact', pad === 'compact'); card.classList.toggle('p-def', pad === 'default'); card.classList.toggle('no-bg', !bg); }

    const sState = this._config.entity_sensor ? this._hass.states[this._config.entity_sensor] : null;
    const mpId = this._getMediaPlayerEntity(), mState = mpId ? this._hass.states[mpId] : null;
    const mEnt = this._findDeviceEntity(['select'], ['display_mode']), fEnt = this._findDeviceEntity(['select'], ['image_filter']);
    const oEnt = this._findDeviceEntity(['select'], ['overlay_info']), opEnt = this._findDeviceEntity(['select'], ['overlay_position']), oaEnt = this._findDeviceEntity(['select'], ['overlay_align']);
    const tpEnt = this._findDeviceEntity(['select'], ['artist_track_text']), syEnt = this._findDeviceEntity(['number'], ['lyrics_sync']);
    const cpEnt = this._findDeviceEntity(['select'], ['crop_mode']), prEnt = this._findDeviceEntity(['switch', 'select', 'input_boolean'], ['progress_bar']), tbEnt = this._findDeviceEntity(['switch', 'select', 'input_boolean'], ['text_background', 'text_bg']);

    const sA = sState?.attributes || {}, mA = mState?.attributes || {};
    const curHash = [sState?.state || 'no_s', sA.media_title || mA.media_title || '', sA.artist || mA.media_artist || '', sA.active_mode || '', sA.configured_mode || '', sA.color1 || '', sA.color2 || '', sA.color3 || '', sA.wled_colors?.join(',') || '', sA.lyrics_available !== undefined ? sA.lyrics_available : '', sA.has_timing !== undefined ? sA.has_timing : '', sA.live_display_url || sA.image_url || mA.entity_picture || '', sA.prefetch_status || '', sA.background_color_rgb?.join(',') || '', sA.pixoo64_channel !== undefined ? sA.pixoo64_channel : '', sA.brightness !== undefined ? sA.brightness : '', sA.screen_power !== undefined ? sA.screen_power : '', sA.ai_generating !== undefined ? sA.ai_generating : '', sA.ai_status || '', mState ? `${mState.state}_${mA.volume_level}_${mA.media_position}` : '', pad, bg ? '1' : '0'].join('|');
    if (!force && this._lastStateHash === curHash) return;
    this._lastStateHash = curHash;

    const isAiGenerating = sA.ai_generating === true;
    const confMode = sA.configured_mode || (mEnt && this._hass.states[mEnt]?.state) || sA.active_mode || 'Standard';
    const lyrAvail = sA.lyrics_available === true, timing = sA.has_timing !== false;
    const curMode = (mEnt && this._hass.states[mEnt]?.state) || sA.active_mode || 'Standard';
    const isSlider = curMode === 'Spotify Slider' || curMode === 'Artist Slide', isVinyl = curMode === 'Vinyl', isCassette = curMode.includes('Cassette');
    const isLyrics = curMode === 'Lyrics' || (confMode === 'Lyrics' && lyrAvail);
    const curCrop = (cpEnt && this._hass.states[cpEnt]?.state) || 'No Crop';
    if (curMode !== 'Vinyl' && !this._savedNonVinylCrop) this._savedNonVinylCrop = curCrop;

    const trackTtl = sA.media_title || mA.media_title || '';
    if (this._lastTrackTitle && trackTtl && trackTtl !== this._lastTrackTitle) { this._persistentTheme = null; this._imageExtractedTheme = null; }
    this._lastTrackTitle = trackTtl;

    if (sA.background_color_rgb?.length === 3) {
      const [r, g, b] = sA.background_color_rgb;
      if (r > 0 || g > 0 || b > 0) {
        const bc = `rgb(${Math.round(r * .28)}, ${Math.round(g * .28)}, ${Math.round(b * .28)})`;
        const pc = sA.font_color && !['#ffffff', '#000000', 'black', 'white'].includes(sA.font_color.toLowerCase()) ? sA.font_color : `rgb(${Math.min(255, r + 60)}, ${Math.min(255, g + 60)}, ${Math.min(255, b + 60)})`;
        this._persistentTheme = { bgColor: bc, primaryColor: pc, color1: sA.color1 ? `${sA.color1}66` : `${pc}44`, color2: sA.color2 ? `${sA.color2}55` : 'rgba(56,189,248,.25)', color3: sA.color3 ? `${sA.color3}44` : 'rgba(129,140,248,.22)' };
      }
    }
    this._applyTheme();

    const dWrap = this.shadowRoot.getElementById('display-wrapper');
    if (dWrap) dWrap.style.display = this._config.show_display !== false ? 'block' : 'none';

    const mWrap = this.shadowRoot.getElementById('media-controls-wrapper'), isPlay = mState?.state === 'playing';
    if (this._config.show_media === true && mpId) {
      if (mWrap.style.display !== 'block') mWrap.style.display = 'block';
      if (mState) {
        const svg = this.shadowRoot.getElementById('play-pause-svg'), tgt = isPlay ? '<path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>' : '<path d="M8 5v14l11-7z"/>';
        if (svg.innerHTML !== tgt) svg.innerHTML = tgt;
        if (mA.volume_level !== undefined) {
          const vs = this.shadowRoot.getElementById('vol-slider'), nv = Math.round(mA.volume_level * 100);
          if (this.shadowRoot.activeElement !== vs && Number(vs.value) !== nv) vs.value = nv;
        }
      }
    } else if (mWrap.style.display !== 'none') mWrap.style.display = 'none';

    // Pixoo Pixel Progress Bar on Artwork bottom row
    let isP = prEnt ? ['on', 'enabled', 'true'].includes((this._hass.states[prEnt]?.state || '').toLowerCase()) : sA.progress_bar !== undefined ? ['true', 'on', 'enabled'].includes(String(sA.progress_bar).toLowerCase()) : sA.progress_bar_active === true;
    this._progressBarLocalState = isP;

    const pixooProgBar = this.shadowRoot.getElementById('pixoo-pixel-progress');
    const pixooProgFill = this.shadowRoot.getElementById('pixoo-pixel-progress-fill');
    if (pixooProgBar && pixooProgFill) {
      if (isP && mA.media_duration > 0) {
        pixooProgBar.style.display = 'block';
        const pos = mA.media_position || 0, dur = mA.media_duration;
        let curPos = pos;
        if (mA.media_position_updated_at && isPlay) {
          const diff = (Date.now() - new Date(mA.media_position_updated_at).getTime()) / 1000;
          if (diff > 0 && diff < 3600) curPos += diff;
        }
        const pct = Math.min(100, Math.max(0, (curPos / dur) * 100));
        pixooProgFill.style.width = `${pct}%`;
      } else {
        pixooProgBar.style.display = 'none';
      }
    }

    const devWrap = this.shadowRoot.getElementById('device-controls-wrapper');
    if (devWrap) {
      devWrap.style.display = this._config.show_pixoo_controls !== false ? 'block' : 'none';
      const pBtn = this.shadowRoot.getElementById('pixoo-power-btn');
      let scrOn = sA.screen_power !== undefined ? sA.screen_power === 'On' : this._localPowerState !== null ? this._localPowerState : String(sA.pixoo64_channel).toLowerCase() !== 'off';
      if (pBtn) { pBtn.textContent = scrOn ? 'Power: On' : 'Power: Off'; pBtn.classList.toggle('active', scrOn); }
      const bs = this.shadowRoot.getElementById('pixoo-brightness-slider');
      if (bs && sA.brightness !== undefined) { const bv = parseInt(sA.brightness, 10); if (!isNaN(bv) && this.shadowRoot.activeElement !== bs) bs.value = bv; }
      const sc = this._parseChannelIndex(sA.pixoo64_channel); if (sc !== null) this._userSelectedChannel = sc;
      const actCh = sc !== null ? sc : this._userSelectedChannel;
      this.shadowRoot.getElementById('device-channels-container')?.querySelectorAll('button').forEach((b) => b.classList.toggle('active', actCh !== null && parseInt(b.getAttribute('data-channel'), 10) === actCh));
    }

    if (sState) {
      const img = this.shadowRoot.getElementById('artwork'), ttl = sA.media_title || mA.media_title || null, art = sA.artist || mA.media_artist || null;
      const tEl = this.shadowRoot.getElementById('title'), aEl = this.shadowRoot.getElementById('artist'), tWrap = this.shadowRoot.getElementById('track-info-wrapper'), lIco = this.shadowRoot.getElementById('lyrics-status-icon');
      if (this._config.show_track_info === false || (!ttl && !art)) { if (tWrap.style.display !== 'none') tWrap.style.display = 'none'; }
      else {
        if (tWrap.style.display !== 'flex') tWrap.style.display = 'flex';
        if (tEl.textContent !== (ttl || '')) tEl.textContent = ttl || '';
        tEl.style.display = ttl ? 'block' : 'none';
        if (aEl.textContent !== (art || '')) aEl.textContent = art || '';
        aEl.style.display = art ? 'block' : 'none';
        if (lIco) {
          if (isPlay && ttl) {
            lIco.style.display = 'inline-flex';
            const icoSvg = '<svg viewBox="0 0 24 24"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6zM3 6h6v2H3zm0 4h6v2H3zm0 4h4v2H3z"/></svg>';
            if (!timing) { lIco.className = 'lyric-icon unavail'; lIco.title = 'Live Stream: Duration not provided'; lIco.innerHTML = icoSvg; }
            else if (isLyrics) { lIco.className = 'lyric-icon act'; lIco.title = 'Synced Lyrics Active'; lIco.innerHTML = icoSvg; }
            else if (lyrAvail) { lIco.className = 'lyric-icon avail'; lIco.title = 'Synced Lyrics Available'; lIco.innerHTML = icoSvg; }
            else { lIco.className = 'lyric-icon unavail'; lIco.title = 'No Synced Lyrics Found'; lIco.innerHTML = icoSvg; }
          } else lIco.style.display = 'none';
        }
      }

      const rawImg = Array.isArray(sA.image_url) ? sA.image_url[0] : sA.image_url;
      const live = sA.live_display_url || rawImg || (!isAiGenerating ? mA.entity_picture : null) || DEFAULT_PREVIEW_SVG;
      
      if (live && this._lastLiveImage !== live) {
        if (!isAiGenerating || sA.image_source === 'AI') {
          this._lastLiveImage = live;
          img.src = live;
        }
      }

      if (this._pendingTargetMode && !isAiGenerating) {
        if (!this._pendingTargetMode.startsWith('Vinyl')) {
          const clean = this._pendingTargetMode.replace(/ \(.*\)/, '');
          if ((confMode === clean || sA.active_mode === clean) && live === this._previousLiveImage) {
            this._releaseRenderingLock();
          }
        }
      }

      const amb = this.shadowRoot.getElementById('card-ambient-bg');
      if (amb) {
        if (live && live !== DEFAULT_PREVIEW_SVG && bg) {
          const u = `url("${live}")`; if (amb.style.backgroundImage !== u) amb.style.backgroundImage = u;
          amb.style.opacity = '0.75';
        } else { amb.style.backgroundImage = 'none'; amb.style.opacity = '0'; }
      }

      const aB = this.shadowRoot.getElementById('activity-badge'), aT = this.shadowRoot.getElementById('activity-text'), ps = sA.prefetch_status;
      let badgeLbl = (ps && !['Idle', 'Disabled', 'None', '', null].includes(ps) && ((ps.includes('Vinyl') && isVinyl) || (ps.includes('Cassette') && isCassette) || (ps.includes('Slider') && isSlider) || (!ps.includes('Vinyl') && !ps.includes('Cassette') && !ps.includes('Slider')))) ? ps : isPlay ? 'Playing' : null;
      if (badgeLbl) { aB.style.display = 'flex'; if (aT.textContent !== badgeLbl) aT.textContent = badgeLbl; } else aB.style.display = 'none';

      const nW = this.shadowRoot.getElementById('next-track-wrapper'), nT = this.shadowRoot.getElementById('next-track-title');
      if (this._config.show_next_track === true && isPlay && sA.prefetch_next_artist && sA.prefetch_next_title) {
        if (nW.style.display !== 'flex') nW.style.display = 'flex';
        const str = `${sA.prefetch_next_artist} - ${sA.prefetch_next_title}`; if (nT.textContent !== str) nT.textContent = str;
      } else if (nW.style.display !== 'none') nW.style.display = 'none';

      const sp = this.shadowRoot.getElementById('stats-panel');
      if (this._config.show_stats === true) {
        const itms = [];
        if (isPlay) {
          if (sA.image_source && sA.image_source !== 'Unknown') itms.push({ l: 'Source', v: sA.image_source });
          if (sA.process_duration && !['N/A', '0.00s', '0.0s'].includes(sA.process_duration)) itms.push({ l: 'Process Time', v: sA.process_duration });
          if (sA.profile_total) itms.push({ l: 'Pipeline', v: `${sA.profile_total}s` });
          if (!timing) itms.push({ l: 'Lyrics Status', v: 'Live Stream' });
          else if (lyrAvail) { itms.push({ l: 'Lyrics Status', v: isLyrics ? 'Active' : 'Available' }, { l: 'Lyrics RAM', v: sA.lyrics_found ? 'Loaded & Synced' : 'Ready' }); }
          else itms.push({ l: 'Lyrics Status', v: 'Not Found' });
        }
        if (ps && !['Idle', 'Disabled', 'None', '', null].includes(ps)) itms.push({ l: 'RAM Status', v: ps });
        if (isSlider && sA.slider_status && !['Idle', 'None', '', null].includes(sA.slider_status)) itms.push({ l: 'Slider', v: sA.slider_status });
        if (sA.general_cache_size > 0) itms.push({ l: 'Image Cache', v: `${sA.general_cache_size} / ${sA.general_cache_limit || 40}` });
        if (itms.length) {
          if (sp.style.display !== 'flex') sp.style.display = 'flex';
          const html = itms.map((x) => `<div class="stat-item"><span class="stat-lbl">${x.l}:</span><span>${x.v}</span></div>`).join('');
          if (this._lastStatsSignature !== html) { this._lastStatsSignature = html; sp.innerHTML = html; }
        } else if (sp.style.display !== 'none') sp.style.display = 'none';
      } else if (sp.style.display !== 'none') sp.style.display = 'none';
    }

    const mdWrap = this.shadowRoot.getElementById('modes-controls-wrapper'), mdCont = this.shadowRoot.getElementById('modes-buttons-container');
    const syncWrap = this.shadowRoot.getElementById('lyrics-sync-wrapper');
    if (syncWrap) syncWrap.style.display = isLyrics ? 'flex' : 'none';

    const opEl = this.shadowRoot.getElementById('overlay-pos-select'), oaEl = this.shadowRoot.getElementById('overlay-align-select');
    const oAct = oEnt && this._hass.states[oEnt]?.state !== 'None';
    if (opEl && opEl.disabled !== !oAct) opEl.disabled = !oAct;
    if (oaEl && oaEl.disabled !== !oAct) oaEl.disabled = !oAct;

    const pBtn = this.shadowRoot.getElementById('progress-toggle-btn');
    if (pBtn) { const txt = isP ? 'Progress: On' : 'Progress: Off'; if (pBtn.textContent !== txt) pBtn.textContent = txt; pBtn.classList.toggle('active', isP); }

    let isT = tbEnt ? ['on', 'enabled', 'true'].includes((this._hass.states[tbEnt]?.state || '').toLowerCase()) : sA.text_background !== undefined ? ['true', 'on', 'enabled'].includes(String(sA.text_background).toLowerCase()) : ['true', 'on', 'enabled'].includes(String(sA.text_bg).toLowerCase());
    this._textBgLocalState = isT;
    const tBtn = this.shadowRoot.getElementById('textbg-toggle-btn');
    if (tBtn) { const txt = isT ? 'Text BG: On' : 'Text BG: Off'; if (tBtn.textContent !== txt) tBtn.textContent = txt; tBtn.classList.toggle('active', isT); }

    if (this._config.show_modes === true && mEnt && this._hass.states[mEnt]) {
      if (mdWrap.style.display !== 'flex') mdWrap.style.display = 'flex';
      const bOpts = this._hass.states[mEnt].attributes.options || ['Standard', 'Vinyl', 'Lyrics'];
      const oSig = `${bOpts.join(',')}|avail:${lyrAvail}|time:${timing}`;
      if (this._lastModesOptionsSignature !== oSig) {
        this._lastModesOptionsSignature = oSig;
        let ext = [];
        bOpts.forEach((o) => { if (o === 'Vinyl') ext.push('Vinyl (Normal)', 'Vinyl (Zoom)', 'Vinyl (Extra Zoom)'); else ext.push(o); });
        mdCont.innerHTML = ext.map((o) => {
          if (o === 'Lyrics') {
            const dc = lyrAvail ? 'l-dot avail' : 'l-dot unavail', dis = (!timing || !lyrAvail) ? 'disabled' : '', tit = !timing ? 'title="Live stream"' : !lyrAvail ? 'title="No synced lyrics"' : 'title="Show Lyrics"';
            return `<button class="act-btn" data-mode="${o}" ${dis} ${tit}><span class="${dc}"></span>Lyrics</button>`;
          }
          return `<button class="act-btn" data-mode="${o}">${o}</button>`;
        }).join('');

        mdCont.querySelectorAll('button').forEach((b) => {
          b.addEventListener('click', (e) => {
            if (this._pendingTargetMode || e.currentTarget.classList.contains('active') || e.currentTarget.disabled) return;
            const tgt = e.currentTarget.getAttribute('data-mode');
            this._startRenderingLock(tgt);
            const lMe = this._findDeviceEntity(['select'], ['display_mode']), lCe = this._findDeviceEntity(['select'], ['crop_mode']);
            const curLMe = lMe ? this._hass?.states[lMe]?.state : 'Standard', curLCe = lCe ? this._hass?.states[lCe]?.state : 'No Crop';
            if (tgt.startsWith('Vinyl')) {
              if (curLMe !== 'Vinyl') this._savedNonVinylCrop = curLCe;
              const tc = tgt === 'Vinyl (Zoom)' ? 'Crop' : tgt === 'Vinyl (Extra Zoom)' ? 'Extra Crop' : 'No Crop';
              if (lCe) this._hass.callService('select', 'select_option', { entity_id: lCe, option: tc });
              if (lMe && curLMe !== 'Vinyl') this._hass.callService('select', 'select_option', { entity_id: lMe, option: 'Vinyl' });
            } else {
              if (curLMe === 'Vinyl' && lCe) this._hass.callService('select', 'select_option', { entity_id: lCe, option: this._savedNonVinylCrop || 'No Crop' });
              if (lMe) this._hass.callService('select', 'select_option', { entity_id: lMe, option: tgt });
            }
            mdCont.querySelectorAll('button').forEach((btn) => btn.classList.toggle('active', btn.getAttribute('data-mode') === tgt));
          });
        });
      }

      mdCont.querySelectorAll('button').forEach((b) => {
        const o = b.getAttribute('data-mode');
        let act = false;
        if (this._pendingTargetMode) {
          act = (o === this._pendingTargetMode);
        } else if (o.startsWith('Vinyl')) {
          if (confMode === 'Vinyl') act = (o === 'Vinyl (Normal)' && curCrop === 'No Crop') || (o === 'Vinyl (Zoom)' && curCrop === 'Crop') || (o === 'Vinyl (Extra Zoom)' && curCrop === 'Extra Crop');
        } else if (o === 'Lyrics') {
          act = (confMode === 'Lyrics' && lyrAvail);
        } else if (o === 'Standard') {
          act = (confMode === 'Standard') || (confMode === 'Lyrics' && !lyrAvail);
        } else {
          act = confMode === o;
        }
        b.classList.toggle('active', act);
      });
    } else if (mdWrap.style.display !== 'none') mdWrap.style.display = 'none';

    const advWrap = this.shadowRoot.getElementById('advanced-wrapper');
    if (this._config.show_advanced === true) {
      if (advWrap.style.display !== 'block') advWrap.style.display = 'block';
      const fSel = this.shadowRoot.getElementById('filter-select');
      if (fEnt && this._hass.states[fEnt]) {
        const fo = this._hass.states[fEnt].attributes.options || ['None'], fs = `${this._hass.states[fEnt].state}|${fo.join(',')}`;
        if (this._lastFilterSignature !== fs) {
          this._lastFilterSignature = fs;
          fSel.innerHTML = fo.map((o) => `<option value="${o}" ${this._hass.states[fEnt].state === o ? 'selected' : ''}>${o === 'None' ? 'Filter: None' : 'Filter: ' + o}</option>`).join('');
          fSel.style.display = 'block';
        }
      }
      const cs = this.shadowRoot.getElementById('crop-select'); if (cpEnt && this._hass.states[cpEnt] && cs.value !== this._hass.states[cpEnt].state) cs.value = this._hass.states[cpEnt].state;
      const os = this.shadowRoot.getElementById('overlay-select'); if (oEnt && this._hass.states[oEnt] && os.value !== this._hass.states[oEnt].state) os.value = this._hass.states[oEnt].state;
      const ops = this.shadowRoot.getElementById('overlay-pos-select'); if (opEnt && this._hass.states[opEnt] && ops.value !== this._hass.states[opEnt].state) ops.value = this._hass.states[opEnt].state;
      const oas = this.shadowRoot.getElementById('overlay-align-select'); if (oaEnt && this._hass.states[oaEnt] && oas.value !== this._hass.states[oaEnt].state) oas.value = this._hass.states[oaEnt].state;
      const tps = this.shadowRoot.getElementById('text-pos-select'); if (tpEnt && this._hass.states[tpEnt] && tps.value !== this._hass.states[tpEnt].state) tps.value = this._hass.states[tpEnt].state;
    } else if (advWrap.style.display !== 'none') advWrap.style.display = 'none';

    if (isAiGenerating) {
      this._startRenderingLock('AI Art');
      const rt = this.shadowRoot.getElementById('render-text');
      if (rt) rt.textContent = sA.ai_status || 'Generating AI Artwork...';
      const ab = this.shadowRoot.getElementById('activity-badge'), at = this.shadowRoot.getElementById('activity-text');
      if (ab && at) { ab.style.display = 'flex'; at.textContent = sA.ai_status || 'AI Generating...'; }
    } else if (this._pendingTargetMode === 'AI Art') {
      this._releaseRenderingLock();
    }

    if (syEnt && this._hass.states[syEnt]?.state !== undefined) {
      const str = parseFloat(this._hass.states[syEnt].state).toFixed(1), sel = this.shadowRoot.getElementById('inline-sync-select');
      if (sel && sel.value !== str) sel.value = str;
    }
  }
  getCardSize() { return 5; }
}

if (!customElements.get('pixoo-media-card')) customElements.define('pixoo-media-card', PixooMediaCard);
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === 'pixoo-media-card')) {
  window.customCards.push({ type: 'pixoo-media-card', name: 'Pixoo Media Card', description: 'Custom pixel retro media card for Pixoo64 with dynamic ambient theme and live GIF preview.', preview: true });
}