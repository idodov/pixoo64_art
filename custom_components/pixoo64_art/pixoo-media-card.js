const DEFAULT_PREVIEW_SVG = 'data:image/svg+xml;utf8,' + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><rect width="64" height="64" fill="#0b0e17"/><circle cx="32" cy="32" r="22" fill="#181e2e" stroke="#00ffcc" stroke-width="2"/><circle cx="32" cy="32" r="8" fill="#00ffcc"/><circle cx="32" cy="32" r="3" fill="#0b0e17"/></svg>`);

const SECTIONS_METADATA = [
  { id: 'display', icon: '🖼️', name: 'Artwork Screen Display', configKey: 'show_display', defaultShow: true, weight: 300, desc: 'Main 64x64 pixel retro canvas, live rendering stream, CRT scanline grid, and live prefetch status badge.' },
  { id: 'track_info', icon: '🎵', name: 'Track & Artist Metadata', configKey: 'show_track_info', defaultShow: true, weight: 65, desc: 'Current song title and artist text formatted with dynamic album-adaptive glow colors.' },
  { id: 'media_controls', icon: '⏯️', name: 'Media Player Controls', configKey: 'show_media', defaultShow: true, weight: 85, desc: 'Playback transport buttons and interactive volume level slider.' },
  { id: 'next_track', icon: '⏭️', name: 'Next Track Prefetch Preview', configKey: 'show_next_track', defaultShow: true, weight: 30, desc: 'Displays upcoming queue item cached into device memory for seamless transitions.' },
  { id: 'modes', icon: '💽', name: 'Display Modes', configKey: 'show_modes', defaultShow: true, weight: 140, desc: 'Interactive buttons for Standard, Vinyl record rendering, and Lyrics display with inline sync.' },
  { id: 'pixoo_controls', icon: '📺', name: 'Pixoo Hardware Controls', configKey: 'show_pixoo_controls', defaultShow: true, weight: 110, desc: 'Direct controls for power, brightness, and Pixoo64 channel selectors.' },
  { id: 'advanced', icon: '⚙️', name: 'Advanced Display Tuning', configKey: 'show_advanced', defaultShow: true, weight: 130, desc: 'Collapsible configuration suite: Image crop ratios, progress bar toggle, text background, filters, and overlays.' },
  { id: 'stats', icon: '📊', name: 'Technical Diagnostics Panel', configKey: 'show_stats', defaultShow: false, weight: 180, desc: 'Live telemetry diagnostics including pipeline durations, memory caches, and slider worker state.' }
];

function getSectionWeight(id) {
  const m = SECTIONS_METADATA.find((s) => s.id === id);
  return m ? m.weight : 80;
}

function computeSmartColumns(order, config) {
  const isEnabled = (id) => {
    const m = SECTIONS_METADATA.find((s) => s.id === id);
    if (!m) return false;
    return config && config[m.configKey] !== undefined ? Boolean(config[m.configKey]) : m.defaultShow;
  };

  const enabled = order.filter((id) => isEnabled(id));
  const hasDisplay = enabled.includes('display');
  const others = enabled.filter((id) => id !== 'display');

  let imageSide = 'left';
  if (hasDisplay && enabled.length > 1) {
    const dispIdx = enabled.indexOf('display');
    if (dispIdx === 0) imageSide = 'left';
    else if (dispIdx === enabled.length - 1) imageSide = 'right';
    else if (dispIdx <= Math.floor((enabled.length - 1) / 2)) imageSide = 'left';
    else imageSide = 'center';
  }

  if (others.length === 0) {
    return {
      displayIds: hasDisplay ? ['display'] : [],
      colAIds: [],
      colBIds: [],
      imageSide
    };
  }

  if (others.length === 1) {
    return {
      displayIds: hasDisplay ? ['display'] : [],
      colAIds: [others[0]],
      colBIds: [],
      imageSide
    };
  }

  const totalWeight = others.reduce((acc, id) => acc + getSectionWeight(id), 0);
  let bestSplit = 1;
  let minDiff = Infinity;
  let runningWeight = 0;

  for (let i = 0; i < others.length - 1; i++) {
    runningWeight += getSectionWeight(others[i]);
    const remWeight = totalWeight - runningWeight;
    const diff = Math.abs(runningWeight - remWeight);
    if (diff < minDiff) {
      minDiff = diff;
      bestSplit = i + 1;
    }
  }

  return {
    displayIds: hasDisplay ? ['display'] : [],
    colAIds: others.slice(0, bestSplit),
    colBIds: others.slice(bestSplit),
    imageSide
  };
}

class PixooMediaCardEditor extends HTMLElement {
  set hass(h) {
    this._hass = h;
    if (this._config && !this._rendered) this.render();
  }

  setConfig(c) {
    this._config = c;
    if (this._hass && !this._rendered) this.render();
    else if (this._rendered) this._updateFieldValues();
  }

  _getLayoutOrder() {
    const d = SECTIONS_METADATA.map((s) => s.id);
    if (!this._config || !Array.isArray(this._config.layout_order)) return d;
    const cur = [...this._config.layout_order];
    d.forEach((id) => {
      if (!cur.includes(id)) cur.push(id);
    });
    return cur;
  }

  render() {
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    const cfg = this._config || {};
    const order = this._getLayoutOrder();
    const split = computeSmartColumns(order, cfg);
    const dispSet = new Set(split.displayIds);
    const colASet = new Set(split.colAIds);

    this.shadowRoot.innerHTML = `
      <style>
        .form{display:flex;flex-direction:column;gap:10px;font-family:sans-serif;color:#f8fafc;padding:4px}
        .box{background:#121624;border:1px solid rgba(0,255,204,.35);border-radius:8px;padding:8px 10px;display:flex;flex-direction:column;gap:4px}
        label.lbl{font-size:.82rem;color:#00ffcc;font-weight:700;display:flex;align-items:center;gap:5px}
        .desc{font-size:.74rem;color:#cbd5e1;line-height:1.35}
        select{background:#0b0e17;border:1px solid rgba(255,255,255,.28);color:#f8fafc;padding:6px 8px;border-radius:6px;font-size:.82rem;outline:none}
        select:focus{border-color:#00ffcc}
        .hdr{font-size:.75rem;font-weight:800;text-transform:uppercase;letter-spacing:.8px;color:#00ffcc;border-bottom:1px solid rgba(0,255,204,.3);padding-bottom:3px;display:flex;justify-content:space-between;align-items:center}
        .row{display:flex;align-items:center;gap:8px;font-size:.82rem;cursor:pointer;color:#f8fafc}
        .row input{accent-color:#00ffcc;width:15px;height:15px;cursor:pointer}
        .list{display:flex;flex-direction:column;gap:5px}
        .item{background:#161c2c;border:1px solid rgba(255,255,255,.15);border-radius:6px;padding:6px 8px;display:flex;align-items:center;justify-content:space-between;gap:8px}
        .item.img-col{border-left:3px solid #00ffcc}
        .info{flex:1;display:flex;flex-direction:column;gap:2px}
        .t-row{display:flex;align-items:center;gap:6px;cursor:pointer;flex-wrap:wrap}
        .t-row input{accent-color:#00ffcc;width:14px;height:14px;margin:0}
        .name{font-size:.8rem;font-weight:700;color:#ffffff}
        .col-tag{font-size:.64rem;padding:1px 6px;border-radius:4px;font-weight:700;text-transform:uppercase}
        .col-tag.img{background:#064e3b;color:#6ee7b7;border:1px solid #10b981}
        .col-tag.other{background:#1e293b;color:#e2e8f0;border:1px solid #64748b}
        .sub{font-size:.7rem;color:#cbd5e1;margin-left:20px}
        .btns{display:flex;flex-direction:column;gap:2px}
        .btn{background:#0b0e17;border:1px solid rgba(255,255,255,.25);color:#e2e8f0;border-radius:4px;width:22px;height:16px;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:.6rem}
        .btn:hover:not(:disabled){background:#00ffcc;color:#05070d;border-color:#00ffcc}
        .btn:disabled{opacity:.4;cursor:not-allowed}
      </style>
      <div class="form">
        <div class="box">
          <label class="lbl">📡 Pixoo Status Sensor</label>
          <div class="desc">Selects the Pixoo status sensor to auto-detect media player, album art, and device state.</div>
          <select id="entity_sensor"><option value="">-- Select Sensor --</option>${this._getPixooSensorOptions(cfg.entity_sensor)}</select>
        </div>
        <div class="box" style="border-color:rgba(255,255,255,.22);">
          <label class="lbl">🎨 Appearance & Spacing</label>
          <div class="row"><input type="checkbox" id="show_background" ${cfg.show_background !== false ? 'checked' : ''} /><label for="show_background">Ambient Background & WLED Glow</label></div>
          <select id="area_padding" style="margin-top:4px;">
            <option value="default" ${cfg.area_padding !== 'none' && cfg.area_padding !== 'compact' ? 'selected' : ''}>Default Padding</option>
            <option value="compact" ${cfg.area_padding === 'compact' ? 'selected' : ''}>Compact Padding</option>
            <option value="none" ${cfg.area_padding === 'none' ? 'selected' : ''}>None (Flush)</option>
          </select>
        </div>
        <div class="hdr"><span>Areas Ordering (Auto-Balanced Columns)</span></div>
        <div class="list" id="areas-container">
          ${order.map((id, idx) => {
            const m = SECTIONS_METADATA.find((s) => s.id === id);
            if (!m) return '';
            const chk = cfg[m.configKey] !== undefined ? Boolean(cfg[m.configKey]) : m.defaultShow;
            const isImgCol = chk && dispSet.has(id);
            const colLabel = isImgCol
              ? `Artwork Col (${split.imageSide})`
              : colASet.has(id)
                ? 'Controls Col A'
                : 'Controls Col B';
            const badge = chk
              ? `<span class="col-tag ${isImgCol ? 'img' : 'other'}">${colLabel}</span>`
              : '';
            return `<div class="item ${isImgCol ? 'img-col' : ''}" data-id="${m.id}"><div class="info"><label class="t-row" for="c_${m.configKey}"><input type="checkbox" id="c_${m.configKey}" data-k="${m.configKey}" ${chk ? 'checked' : ''} /><span class="name">${m.icon} ${m.name}</span>${badge}</label><div class="sub">${m.desc}</div></div><div class="btns"><button class="btn up" data-id="${m.id}" ${idx === 0 ? 'disabled' : ''}>▲</button><button class="btn down" data-id="${m.id}" ${idx === order.length - 1 ? 'disabled' : ''}>▼</button></div></div>`;
          }).join('')}
        </div>
      </div>`;
    this._rendered = true;
    this.shadowRoot.getElementById('entity_sensor')?.addEventListener('change', (e) => this._updateConfigValue('entity_sensor', e.target.value));
    this.shadowRoot.getElementById('show_background')?.addEventListener('change', (e) => this._updateConfigValue('show_background', e.target.checked));
    this.shadowRoot.getElementById('area_padding')?.addEventListener('change', (e) => this._updateConfigValue('area_padding', e.target.value));
    this.shadowRoot.querySelectorAll('input[type="checkbox"][data-k]').forEach((c) => c.addEventListener('change', (e) => {
      this._updateConfigValue(e.target.getAttribute('data-k'), e.target.checked);
      this.render();
    }));
    this.shadowRoot.querySelectorAll('.up').forEach((b) => b.addEventListener('click', () => this._moveSection(b.getAttribute('data-id'), -1)));
    this.shadowRoot.querySelectorAll('.down').forEach((b) => b.addEventListener('click', () => this._moveSection(b.getAttribute('data-id'), 1)));
  }

  _moveSection(id, dir) {
    const o = this._getLayoutOrder();
    const idx = o.indexOf(id);
    const nIdx = idx + dir;
    if (idx === -1 || nIdx < 0 || nIdx >= o.length) return;
    [o[idx], o[nIdx]] = [o[nIdx], o[idx]];
    this._updateConfigValue('layout_order', o);
    this.render();
  }

  _updateFieldValues() {
    if (!this._config || !this.shadowRoot) return;
    this.render();
  }

  _getPixooSensorOptions(val) {
    if (!this._hass) return '';
    return Object.keys(this._hass.states)
      .filter((e) => e.startsWith('sensor.') && (e.includes('pixoo64_media_display') || e.includes('pixoo64_status') || (e.includes('pixoo') && this._hass.states[e].attributes?.active_mode !== undefined)))
      .sort()
      .map((e) => `<option value="${e}" ${e === val ? 'selected' : ''}>${this._hass.states[e].attributes.friendly_name || e} (${e})</option>`)
      .join('');
  }

  _updateConfigValue(k, v) {
    if (!this._config || !this._hass) return;
    this._config = { ...this._config, [k]: v };
    this.dispatchEvent(new CustomEvent('config-changed', { detail: { config: this._config }, bubbles: true, composed: true }));
  }
}

if (!customElements.get('pixoo-media-card-editor')) {
  customElements.define('pixoo-media-card-editor', PixooMediaCardEditor);
}

class PixooMediaCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement('pixoo-media-card-editor');
  }

  static getStubConfig(h) {
    const s = h?.states
      ? Object.keys(h.states).find((e) => e.startsWith('sensor.') && (e.includes('pixoo64_media_display') || e.includes('pixoo64_status') || (e.includes('pixoo') && h.states[e].attributes?.active_mode !== undefined))) || ''
      : '';
    return {
      entity_sensor: s,
      layout_order: SECTIONS_METADATA.map((x) => x.id),
      show_background: true,
      area_padding: 'default',
      show_display: true,
      show_track_info: true,
      show_media: true,
      show_modes: true,
      show_pixoo_controls: true,
      show_advanced: true,
      show_next_track: true,
      show_stats: false
    };
  }

  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._savedNonVinylCrop = null;
    this._textBgLocalState = false;
    this._progressBarLocalState = true;
    this._userSelectedChannel = null;
    this._localPowerState = null;
    this._lastTrackTitle = '';
    this._pendingTargetMode = null;
    this._previousLiveImage = '';
    this._busyWatchdog = null;
    this._rendered = false;
    this._lastStateHash = '';
    this._lastLiveImage = '';
    this._lastModesOptionsSignature = '';
    this._lastFilterSignature = '';
    this._lastStatsSignature = '';
    this._lastThemeSignature = '';
    this._lastLayoutOrderSig = '';
    this._persistentTheme = null;
    this._entityMap = {};
  }

  _getLayoutOrder() {
    const d = SECTIONS_METADATA.map((s) => s.id);
    if (!this._config || !Array.isArray(this._config.layout_order)) return d;
    const cur = [...this._config.layout_order];
    d.forEach((id) => {
      if (!cur.includes(id)) cur.push(id);
    });
    return cur;
  }

  setConfig(c) {
    if (!c) throw new Error('Invalid config');
    this._config = {
      entity_sensor: '',
      layout_order: SECTIONS_METADATA.map((x) => x.id),
      show_background: true,
      area_padding: 'default',
      show_display: true,
      show_track_info: true,
      show_media: true,
      show_modes: true,
      show_pixoo_controls: true,
      show_advanced: true,
      show_next_track: true,
      show_stats: false,
      ...c
    };
    this._entityMap = {};
    this._lastStateHash = '';
    this._lastLayoutOrderSig = '';
    if (!this._rendered) {
      this.render();
      this._rendered = true;
    }
    if (this._hass) this.updateValues(true);
  }

  connectedCallback() {
    if (!this._rendered) {
      this.render();
      this._rendered = true;
    }
    if (this._hass) this.updateValues(true);
    this._progressInterval = setInterval(() => this._tickProgress(), 1000);
  }

  disconnectedCallback() {
    if (this._progressInterval) clearInterval(this._progressInterval);
  }

  set hass(h) {
    this._hass = h;
    if (!this._rendered) {
      this.render();
      this._rendered = true;
    }
    if (this._config && !this._config.entity_sensor && h?.states) {
      const a = Object.keys(h.states).find((e) => e.startsWith('sensor.') && (e.includes('pixoo64_media_display') || e.includes('pixoo64_status') || (e.includes('pixoo') && h.states[e].attributes?.active_mode !== undefined)));
      if (a) this._config = { ...this._config, entity_sensor: a };
    }
    this.updateValues(false);
  }

  _getMediaPlayerEntity() {
    return this._hass?.states[this._config?.entity_sensor]?.attributes?.media_player || this._config?.entity_media_player || null;
  }

  _findDeviceEntity(doms, sfxs) {
    if (!this._hass || !this._hass.states) return null;
    const sensorId = this._config?.entity_sensor || '';
    const ck = `${sensorId}_${doms.join(',')}_${sfxs.join(',')}`;
    if (this._entityMap[ck] && this._hass.states[this._entityMap[ck]]) {
      return this._entityMap[ck];
    }

    const allStates = Object.keys(this._hass.states);
    const sensorObjId = sensorId.includes('.') ? sensorId.split('.')[1] : sensorId;
    const prefixMatch = sensorObjId.match(/^(.*?)pixoo/i);
    const devicePrefix = prefixMatch && prefixMatch[1] ? prefixMatch[1].replace(/_+$/, '').toLowerCase() : '';

    const expandedSfxs = [];
    for (const s of sfxs) {
      if (!s.includes('pixoo')) {
        expandedSfxs.push(`pixoo64_media_${s}`);
        expandedSfxs.push(`pixoo64_${s}`);
      }
      expandedSfxs.push(s);
    }

    const entitiesReg = this._hass.entities;
    const sensorReg = entitiesReg && sensorId ? entitiesReg[sensorId] : null;
    if (sensorReg && (sensorReg.device_id || sensorReg.config_entry_id)) {
      const siblings = allStates.filter((id) => {
        const reg = entitiesReg[id];
        if (!reg) return false;
        if (sensorReg.device_id && reg.device_id === sensorReg.device_id) return true;
        if (sensorReg.config_entry_id && reg.config_entry_id === sensorReg.config_entry_id) return true;
        return false;
      });

      for (const d of doms) {
        for (const s of expandedSfxs) {
          const match = siblings.find((id) => id.startsWith(`${d}.`) && id.toLowerCase().includes(s.toLowerCase()));
          if (match) {
            this._entityMap[ck] = match;
            return match;
          }
        }
      }
    }

    if (devicePrefix) {
      for (const d of doms) {
        for (const s of expandedSfxs) {
          const match = allStates.find((id) => {
            const lower = id.toLowerCase();
            return lower.startsWith(`${d}.`) && lower.includes(devicePrefix) && lower.includes(s.toLowerCase());
          });
          if (match) {
            this._entityMap[ck] = match;
            return match;
          }
        }
      }
    }

    for (const d of doms) {
      for (const s of expandedSfxs) {
        const match = allStates.find((id) => {
          const lower = id.toLowerCase();
          return lower.startsWith(`${d}.`) && lower.includes(s.toLowerCase());
        });
        if (match) {
          this._entityMap[ck] = match;
          return match;
        }
      }
    }

    return null;
  }

  // =========================================================================
  // WCAG 2.1 CONTRAST & WLED COLOR ENGINE (Guarantees >= 4.5:1 everywhere)
  // =========================================================================

  _getLuminance(rgb) {
    const [r, g, b] = rgb.map((v) => {
      const s = Math.max(0, Math.min(255, v)) / 255;
      return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }

  _getContrastRatio(rgb1, rgb2) {
    const l1 = this._getLuminance(rgb1);
    const l2 = this._getLuminance(rgb2);
    const brightest = Math.max(l1, l2);
    const darkest = Math.min(l1, l2);
    return (brightest + 0.05) / (darkest + 0.05);
  }

  _rgbToHsl(r, g, b) {
    r /= 255;
    g /= 255;
    b /= 255;
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    let h = 0;
    let s = 0;
    const l = (max + min) / 2;
    if (max !== min) {
      const d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
      switch (max) {
        case r:
          h = (g - b) / d + (g < b ? 6 : 0);
          break;
        case g:
          h = (b - r) / d + 2;
          break;
        case b:
          h = (r - g) / d + 4;
          break;
      }
      h /= 6;
    }
    return [h, s, l];
  }

  _hslToRgb(h, s, l) {
    if (s === 0) {
      const v = Math.round(l * 255);
      return [v, v, v];
    }
    const hue2rgb = (p, q, t) => {
      if (t < 0) t += 1;
      if (t > 1) t -= 1;
      if (t < 1 / 6) return p + (q - p) * 6 * t;
      if (t < 1 / 2) return q;
      if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
      return p;
    };
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    return [
      Math.round(hue2rgb(p, q, h + 1 / 3) * 255),
      Math.round(hue2rgb(p, q, h) * 255),
      Math.round(hue2rgb(p, q, h - 1 / 3) * 255)
    ];
  }

  _ensureContrast(fgRgb, bgRgb, minRatio = 4.8) {
    if (this._getContrastRatio(fgRgb, bgRgb) >= minRatio) {
      return fgRgb;
    }
    const bgLum = this._getLuminance(bgRgb);
    const lighten = bgLum < 0.5;
    const [h, s, l] = this._rgbToHsl(fgRgb[0], fgRgb[1], fgRgb[2]);

    let low = lighten ? l : 0.0;
    let high = lighten ? 1.0 : l;
    let bestRgb = lighten ? [255, 255, 255] : [10, 14, 23];

    for (let i = 0; i < 18; i++) {
      const mid = (low + high) / 2;
      const cand = this._hslToRgb(h, Math.max(0.35, s), mid);
      const ratio = this._getContrastRatio(cand, bgRgb);
      if (ratio >= minRatio) {
        bestRgb = cand;
        if (lighten) high = mid;
        else low = mid;
      } else {
        if (lighten) low = mid;
        else high = mid;
      }
    }
    return bestRgb;
  }

  _tickProgress() {
    const mpId = this._getMediaPlayerEntity();
    const pixooProgBar = this.shadowRoot?.getElementById('pixoo-pixel-progress');
    const fillEl = this.shadowRoot?.getElementById('pixoo-pixel-progress-fill');
    if (!pixooProgBar || !fillEl) return;

    if (!mpId || !this._hass) {
      pixooProgBar.style.display = 'none';
      return;
    }
    const mState = this._hass.states[mpId];
    const sensorState = this._config?.entity_sensor ? this._hass.states[this._config.entity_sensor] : null;
    const sA = sensorState?.attributes || {};
    const prEnt = this._findDeviceEntity(['switch', 'select', 'input_boolean'], ['pixoo64_media_progress_bar', 'progress_bar', 'show_progress', 'progress']);

    const isPlay = mState && (mState.state === 'playing' || mState.state === 'on');
    const isP = prEnt && this._hass.states[prEnt]
      ? ['on', 'enabled', 'true'].includes(String(this._hass.states[prEnt].state).toLowerCase())
      : sA.progress_bar !== undefined
        ? ['true', 'on', 'enabled'].includes(String(sA.progress_bar).toLowerCase())
        : sA.progress_bar_active === true;

    if (!isP || !isPlay || !mState) {
      pixooProgBar.style.display = 'none';
      return;
    }

    const mA = mState.attributes || {};
    const pos = mA.media_position || 0;
    const dur = mA.media_duration || 0;
    const updatedAt = mA.media_position_updated_at;
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
    const r = this.shadowRoot;
    const o = r.getElementById('render-overlay');
    const t = r.getElementById('render-text');
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
    if (this._busyWatchdog) {
      clearTimeout(this._busyWatchdog);
      this._busyWatchdog = null;
    }
    const r = this.shadowRoot;
    const o = r.getElementById('render-overlay');
    if (o) o.style.display = 'none';
    r.getElementById('modes-controls-wrapper')?.classList.remove('locked');
    r.getElementById('cat-crop-prog')?.classList.remove('locked');
    r.getElementById('advanced-wrapper')?.classList.remove('locked');
    r.getElementById('device-controls-wrapper')?.classList.remove('locked');
    r.getElementById('media-controls-wrapper')?.classList.remove('locked');
  }

  _handleFeatureToggle(btnId, doms, sfxs, stateKey, labelBase) {
    const btn = this.shadowRoot.getElementById(btnId);
    if (!btn || !this._hass) return;

    const ent = this._findDeviceEntity(doms, sfxs);
    if (!ent || !this._hass.states[ent]) {
      console.warn(`[Pixoo Card] Could not find HA entity for ${labelBase}.`);
      btn.style.borderColor = '#ff4444';
      setTimeout(() => {
        btn.style.borderColor = 'var(--pixoo-border-tint)';
      }, 1000);
      return;
    }

    const curState = String(this._hass.states[ent].state || '').toLowerCase();
    const isCurrentlyOn = ['on', 'enabled', 'true', 'yes'].includes(curState);
    const nextOn = !isCurrentlyOn;

    this[stateKey] = nextOn;
    btn.textContent = `${labelBase}: ${nextOn ? 'On' : 'Off'}`;
    btn.classList.toggle('active', nextOn);

    const domain = ent.split('.')[0];
    if (domain === 'select') {
      const opts = this._hass.states[ent].attributes?.options || [];
      const lowerOpts = opts.map((o) => String(o).toLowerCase());
      let opt = opts.length > 0 ? opts[0] : (nextOn ? 'Enabled' : 'Disabled');

      if (nextOn) {
        const idx = lowerOpts.findIndex((x) => ['enabled', 'on', 'true', 'yes'].includes(x));
        if (idx !== -1) opt = opts[idx];
      } else {
        const idx = lowerOpts.findIndex((x) => ['disabled', 'off', 'false', 'no'].includes(x));
        if (idx !== -1) opt = opts[idx];
      }

      this._hass.callService('select', 'select_option', { entity_id: ent, option: opt });
    } else {
      this._hass.callService(domain, nextOn ? 'turn_on' : 'turn_off', { entity_id: ent });
    }

    if (stateKey === '_progressBarLocalState') {
      const pixooProgBar = this.shadowRoot?.getElementById('pixoo-pixel-progress');
      if (pixooProgBar && !nextOn) pixooProgBar.style.display = 'none';
    }
  }

  render() {
    const pad = this._config?.area_padding || 'default';
    const bg = this._config?.show_background !== false && pad !== 'none';
    const cls = [pad === 'none' ? 'p-none' : pad === 'compact' ? 'p-compact' : 'p-def', !bg ? 'no-bg' : ''].filter(Boolean).join(' ');

    this.shadowRoot.innerHTML = `
      <style>
        :host{
          --album-bg:#0d111d;
          --pixoo-primary:#00ffcc;
          --pixoo-accent2:#38bdf8;
          --pixoo-accent3:#818cf8;
          --pixoo-color1:rgba(0,255,204,.62);
          --pixoo-color2:rgba(56,189,248,.58);
          --pixoo-color3:rgba(129,140,248,.54);
          --pixoo-glow:rgba(0,255,204,.65);
          --pixoo-border-tint:rgba(0,255,204,.55);
          --pixoo-text:#f8fafc;
          --pixoo-muted:#cbd5e1;
          --pixoo-disabled-text:#94a3b8;
          --box-bg:rgba(11,15,25,.9);
          --btn-bg:rgba(7,10,18,.9);
          --text-shadow:rgba(0,0,0,.92);
          --overlay-base:rgba(9,12,20,.72);
          --pixoo-primary-text:#060911;
          display:block;
        }
        
        ha-card {
          container-type: inline-size;
          container-name: pixoocard;
          position: relative;
          background: var(--album-bg,#0d111d);
          border: 1px solid var(--pixoo-border-tint,rgba(0,255,204,.55));
          border-radius: 14px;
          color: var(--pixoo-text,#f8fafc);
          box-shadow: 0 8px 24px rgba(0,0,0,.6);
          overflow: hidden;
          box-sizing: border-box;
          transition: background 0.4s ease, border-color 0.4s ease;
        }

        ha-card.p-def{padding:12px}.p-def .box{padding:8px 10px;border-radius:8px}
        ha-card.p-compact{padding:6px}.p-compact .box{padding:5px 8px;border-radius:6px}.p-compact .disp{border-radius:6px}
        ha-card.p-none{padding:0!important;background:#0a0d14!important;border-radius:10px!important}.p-none .bg,.p-none .overlay{display:none!important}
        .p-none .disp{border-radius:0!important;border:none!important;border-bottom:1px solid rgba(255,255,255,.14)!important}
        .p-none .box{border-radius:0!important;border:none!important;border-bottom:1px solid rgba(255,255,255,.1)!important;padding:6px 10px!important;background:#0b0f19!important}
        
        /* Base (< 500px): 1 Column, flattened wrappers so exact user layout_order applies */
        .content {
          position: relative;
          z-index: 1;
          display: flex;
          flex-direction: column;
          gap: 8px;
          width: 100%;
          box-sizing: border-box;
        }
        .col-display, .col-others, .col-secondary-a, .col-secondary-b {
          display: contents;
        }
        .col-display > *, .col-secondary-a > *, .col-secondary-b > * {
          width: 100%;
          box-sizing: border-box;
        }
        ha-card.p-compact .content { gap: 4px; }
        ha-card.p-none .content { gap: 0 !important; }
        
        /* Medium (500px to 779px): 2 Balanced Columns */
        @container pixoocard (min-width: 500px) {
          .content {
            display: grid;
            grid-template-columns: clamp(210px, 43%, 320px) minmax(0, 1fr);
            gap: 10px;
            align-items: start;
          }
          .content.img-right, .content.img-center {
            grid-template-columns: minmax(0, 1fr) clamp(210px, 43%, 320px);
          }
          .content.cols-1 {
            grid-template-columns: minmax(0, 1fr) !important;
          }
          .col-display {
            display: flex;
            flex-direction: column;
            gap: 8px;
            width: 100%;
            min-width: 0;
            order: 1;
          }
          .col-others {
            display: flex;
            flex-direction: column;
            gap: 8px;
            width: 100%;
            min-width: 0;
            order: 2;
          }
          .content.img-right .col-others, .content.img-center .col-others { order: 1; }
          .content.img-right .col-display, .content.img-center .col-display { order: 2; }
          .col-secondary-a, .col-secondary-b {
            display: contents;
          }
          ha-card.p-compact .content { gap: 6px; }
          ha-card.p-compact .col-display, ha-card.p-compact .col-others { gap: 4px; }
          ha-card.p-none .content, ha-card.p-none .col-display, ha-card.p-none .col-others { gap: 0 !important; }
          ha-card.p-none .col-display { border-right: 1px solid rgba(255,255,255,.1); }
        }

        /* Wide (>= 780px): 3 Height-Balanced Columns (Standalone Artwork Column + 2 Control Columns) */
        @container pixoocard (min-width: 780px) {
          .content.cols-3 {
            grid-template-columns: clamp(240px, 34%, 320px) minmax(200px, 1fr) minmax(200px, 1fr);
            gap: 12px;
            align-items: start;
          }
          .content.cols-3.img-center {
            grid-template-columns: minmax(200px, 1fr) clamp(240px, 34%, 320px) minmax(200px, 1fr);
          }
          .content.cols-3.img-right {
            grid-template-columns: minmax(200px, 1fr) minmax(200px, 1fr) clamp(240px, 34%, 320px);
          }
          .content.cols-3 .col-others {
            display: contents;
          }
          .content.cols-3 .col-secondary-a,
          .content.cols-3 .col-secondary-b {
            display: flex;
            flex-direction: column;
            gap: 8px;
            width: 100%;
            min-width: 0;
          }
          .content.cols-3.img-left .col-display { order: 1; }
          .content.cols-3.img-left .col-secondary-a { order: 2; }
          .content.cols-3.img-left .col-secondary-b { order: 3; }

          .content.cols-3.img-center .col-secondary-a { order: 1; }
          .content.cols-3.img-center .col-display { order: 2; }
          .content.cols-3.img-center .col-secondary-b { order: 3; }

          .content.cols-3.img-right .col-secondary-a { order: 1; }
          .content.cols-3.img-right .col-secondary-b { order: 2; }
          .content.cols-3.img-right .col-display { order: 3; }

          ha-card.p-compact .content.cols-3 .col-secondary-a,
          ha-card.p-compact .content.cols-3 .col-secondary-b { gap: 4px; }
          ha-card.p-none .content.cols-3 .col-secondary-a,
          ha-card.p-none .content.cols-3 .col-secondary-b { gap: 0 !important; }
          ha-card.p-none .content.cols-3 .col-secondary-a { border-right: 1px solid rgba(255,255,255,.1); }
        }

        .bg{position:absolute;top:-40px;left:-40px;right:-40px;bottom:-40px;background-size:cover;background-position:center;filter:blur(42px) saturate(2.4) brightness(.36);opacity:0;transform:scale(1.2);pointer-events:none;z-index:0;transition:background-image .8s ease,opacity .8s ease}
        .overlay{position:absolute;top:0;left:0;width:100%;height:100%;background:radial-gradient(circle at 14% 18%,var(--pixoo-color1) 0%,transparent 62%),radial-gradient(circle at 86% 22%,var(--pixoo-color2) 0%,transparent 65%),radial-gradient(circle at 52% 88%,var(--pixoo-color3) 0%,transparent 68%),var(--overlay-base);pointer-events:none;z-index:0;transition:all 0.4s ease;}
        ha-card.no-bg{background:var(--ha-card-background,var(--card-background-color,#0d111d))!important}.no-bg .bg,.no-bg .overlay{display:none!important}
        
        .disp{position:relative;width:100%;padding-top:100%;background:#000;border:2px solid var(--pixoo-border-tint);border-radius:10px;overflow:hidden;box-shadow:0 6px 20px rgba(0,0,0,.75);box-sizing:border-box}
        .disp img{position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover;image-rendering:pixelated;display:block}
        .grid{position:absolute;top:0;left:0;width:100%;height:100%;background-image:linear-gradient(rgba(0,0,0,.65) 1px,transparent 1px),linear-gradient(90deg,rgba(0,0,0,.65) 1px,transparent 1px);background-size:calc(100%/64) calc(100%/64);box-shadow:inset 0 0 10px rgba(0,0,0,.85);pointer-events:none;z-index:2}
        .badge{position:absolute;top:6px;right:6px;z-index:3;display:flex;align-items:center;gap:5px;background:rgba(7,10,18,.92);padding:3px 8px;border-radius:12px;font-size:.68rem;font-weight:700;color:#ffffff;border:1px solid var(--pixoo-border-tint)}
        .dot{width:7px;height:7px;background-color:var(--pixoo-primary);border-radius:50%;box-shadow:0 0 7px var(--pixoo-primary)}
        .hud{position:absolute;top:0;left:0;width:100%;height:100%;z-index:4;backdrop-filter:blur(5px);background:rgba(7,10,18,.88);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px}
        .spin{width:26px;height:26px;border:2.5px solid var(--pixoo-border-tint);border-top:2.5px solid var(--pixoo-primary);border-radius:50%;animation:sp .8s linear infinite;box-shadow:0 0 12px var(--pixoo-glow)}
        .hud-txt{font-family:monospace;font-size:.74rem;font-weight:700;color:var(--pixoo-primary);text-shadow:0 0 8px rgba(0,0,0,.9);letter-spacing:.6px}
        @keyframes sp{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}
        .pixoo-pixel-progress{position:absolute;bottom:0;left:0;width:100%;height:calc(100% / 64);background:rgba(0,0,0,.65);z-index:3;pointer-events:none}
        .pixoo-pixel-progress-fill{height:100%;width:0%;background:var(--pixoo-primary,#00ffcc);box-shadow:0 0 4px var(--pixoo-primary,#00ffcc);transition:width .2s linear}
        
        .box{background:var(--box-bg);border:1px solid var(--pixoo-border-tint);border-radius:8px;padding:8px 10px;box-shadow:0 3px 10px rgba(0,0,0,.35);box-sizing:border-box;transition:all 0.4s ease;width:100%;}
        .t-info{position:relative;text-align:center;display:flex;flex-direction:column;justify-content:center;min-height:46px}
        .ttl{font-weight:800;font-size:1.14rem;line-height:1.25;color:var(--pixoo-text);text-shadow:0 1px 3px var(--text-shadow);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:0 26px}
        .art{font-size:.92rem;line-height:1.25;color:var(--pixoo-primary);font-weight:700;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:0 26px}
        .lyric-icon{position:absolute;top:6px;right:6px;width:18px;height:18px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;cursor:help;transition:all .25s ease}
        .lyric-icon.avail{background:rgba(0,255,204,.16);color:var(--pixoo-primary);border:1px solid var(--pixoo-primary);box-shadow:0 0 8px rgba(0,255,204,.25)}
        .lyric-icon.act{background:rgba(56,189,248,.2);color:var(--pixoo-accent2);border:1px solid var(--pixoo-accent2);box-shadow:0 0 8px rgba(56,189,248,.3)}
        .lyric-icon.unavail{background:rgba(148,163,184,.12);color:var(--pixoo-disabled-text);border:1px solid rgba(148,163,184,.35)}
        .lyric-icon svg{width:11px;height:11px;fill:currentColor}
        .next-box{font-size:.76rem;display:flex;flex-direction:column;gap:2px;border-left:3px solid var(--pixoo-primary)}
        .next-lbl{font-size:.66rem;color:var(--pixoo-muted);text-transform:uppercase;letter-spacing:.5px;font-weight:700}
        .next-ttl{font-weight:700;color:var(--pixoo-text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        
        .m-btns{display:flex;justify-content:center;align-items:center;gap:12px;margin-bottom:6px}
        .i-btn{background:var(--btn-bg);border:1px solid var(--pixoo-border-tint);color:var(--pixoo-text);border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:all .2s}
        .i-btn svg{width:17px;height:17px;fill:currentColor}
        .i-btn:hover{background:var(--pixoo-primary);color:var(--pixoo-primary-text);border-color:var(--pixoo-primary);box-shadow:0 0 10px var(--pixoo-glow)}
        
        .v-row{display:flex;align-items:center;gap:8px;font-size:.8rem;color:var(--pixoo-text)}
        .v-slider{flex:1;accent-color:var(--pixoo-primary);cursor:pointer;height:4px}
        .p-ctrls{display:flex;flex-direction:column;gap:6px}
        .row{display:flex;gap:5px;flex-wrap:wrap}.row>*{flex:1;min-width:60px}
        
        select,button.act-btn{background:var(--btn-bg);border:1px solid var(--pixoo-border-tint);color:var(--pixoo-text);padding:6px 5px;border-radius:6px;font-size:.73rem;font-weight:600;cursor:pointer;outline:none;text-align:center;transition:all .2s}
        select:disabled,button.act-btn:disabled{color:var(--pixoo-disabled-text)!important;border-color:rgba(148,163,184,.3)!important;background:var(--btn-bg)!important;cursor:not-allowed!important;pointer-events:none}
        select option{background:#0b0f19;color:#f8fafc}
        select:focus,button.act-btn:hover:not(.active):not(:disabled){border-color:var(--pixoo-primary);}
        button.act-btn.active{background:var(--pixoo-primary)!important;color:var(--pixoo-primary-text)!important;font-weight:800;border-color:var(--pixoo-primary);box-shadow:0 0 10px var(--pixoo-glow)}
        
        .locked{pointer-events:none!important;filter:grayscale(.25)!important}
        #modes-buttons-container button.act-btn.active{cursor:default}
        #device-channels-container button.act-btn.active{cursor:pointer;pointer-events:auto}
        #progress-toggle-btn,#textbg-toggle-btn,#pixoo-power-btn{cursor:pointer!important;pointer-events:auto!important}
        .l-dot{display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:4px;vertical-align:middle}
        .l-dot.avail{background-color:var(--pixoo-primary);box-shadow:0 0 6px var(--pixoo-primary)}
        .l-dot.unavail{background-color:var(--pixoo-disabled-text)}
        
        .sync-row{display:flex;align-items:center;gap:5px;margin-top:2px;padding:4px 8px;background:var(--btn-bg);border:1px solid var(--pixoo-border-tint);border-radius:6px}
        .sync-lbl{font-size:.73rem;font-weight:700;color:var(--pixoo-primary);white-space:nowrap}
        .s-step{flex:0 0 auto!important;min-width:34px!important;padding:5px 6px!important;font-weight:700!important}
        
        .adv{overflow:hidden;padding:0}
        .adv-hdr{padding:8px 10px;background:var(--btn-bg);font-size:.76rem;font-weight:700;color:var(--pixoo-text);cursor:pointer;display:flex;justify-content:space-between;align-items:center;user-select:none;border-bottom:1px solid var(--pixoo-border-tint)}
        .adv-hdr:hover{color:var(--pixoo-primary)}
        .adv-body{padding:8px;display:flex;flex-direction:column;gap:8px;background:var(--box-bg)}
        .cat-ttl{font-size:.66rem;font-weight:800;color:var(--pixoo-primary);text-transform:uppercase;letter-spacing:.7px;margin-bottom:2px;border-bottom:1px solid var(--pixoo-border-tint);padding-bottom:2px}
        .sub-ttl{font-size:.63rem;font-weight:800;color:var(--pixoo-muted);text-transform:uppercase;letter-spacing:.65px;margin-top:4px;padding-top:4px;border-top:1px solid rgba(255,255,255,.1)}
        
        .stats{font-family:monospace;font-size:.73rem;color:var(--pixoo-text);display:flex;flex-direction:column;gap:4px}
        #stats-content{display:flex;flex-direction:column;gap:3px}
        .stat-item{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:2px 0;border-bottom:1px solid rgba(148,163,184,.16);overflow:hidden;text-overflow:ellipsis}
        .stat-item:last-child{border-bottom:none}
        .stat-lbl{color:var(--pixoo-muted);font-weight:700;white-space:nowrap}
        .stat-val{color:var(--pixoo-text);font-weight:700;text-align:right}
      </style>
      <ha-card id="main-card" class="${cls}">
        <div class="bg" id="card-ambient-bg"></div>
        <div class="overlay" id="card-ambient-overlay"></div>
        <div class="content" id="card-content">
          <div class="col-display" id="col-display">
            <div class="disp" id="display-wrapper" data-section="display">
              <img id="artwork" src="${DEFAULT_PREVIEW_SVG}" alt="Pixoo Artwork">
              <div class="grid"></div>
              <div class="pixoo-pixel-progress" id="pixoo-pixel-progress" style="display:none;"><div class="pixoo-pixel-progress-fill" id="pixoo-pixel-progress-fill"></div></div>
              <div class="badge" id="activity-badge" style="display:none;"><div class="dot"></div><span id="activity-text">Playing</span></div>
              <div class="hud" id="render-overlay" style="display:none;"><div class="spin"></div><div class="hud-txt" id="render-text">Generating Display...</div></div>
            </div>
          </div>
          <div class="col-others" id="col-others">
            <div class="col-secondary-a" id="col-secondary-a">
              <div class="box t-info" id="track-info-wrapper" data-section="track_info" style="display:none;">
                <div id="title" class="ttl">Idle</div><div id="artist" class="art">No Media Playing</div>
                <div id="lyrics-status-icon" class="lyric-icon" style="display:none;"></div>
              </div>
              <div class="box" id="media-controls-wrapper" data-section="media_controls" style="display:none;">
                <div class="m-btns">
                  <button class="i-btn" id="prev-btn" title="Previous"><svg viewBox="0 0 24 24"><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z"/></svg></button>
                  <button class="i-btn" id="play-pause-btn" title="Play/Pause"><svg id="play-pause-svg" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg></button>
                  <button class="i-btn" id="next-btn" title="Next"><svg viewBox="0 0 24 24"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z"/></svg></button>
                </div>
                <div class="v-row" title="Volume Slider"><span>🔊</span><input type="range" class="v-slider" id="vol-slider" min="0" max="100" value="50"></div>
              </div>
              <div class="box next-box" id="next-track-wrapper" data-section="next_track" style="display:none;">
                <div class="next-lbl">Next Up (Prefetch)</div><div class="next-ttl" id="next-track-title">-</div>
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
            </div>
            <div class="col-secondary-b" id="col-secondary-b">
              <div class="box p-ctrls" id="device-controls-wrapper" data-section="pixoo_controls" style="display:none;">
                <div class="cat-ttl">Pixoo Device Controls</div>
                <div class="row" style="align-items:center;gap:6px;">
                  <button class="act-btn" id="pixoo-power-btn" style="flex:0 0 95px;" title="Power">Power: On</button>
                  <div style="flex:1;display:flex;align-items:center;gap:6px;"><span style="font-size:.7rem;font-weight:600;color:var(--pixoo-muted);">Brightness</span><input type="range" class="v-slider" id="pixoo-brightness-slider" min="0" max="100" value="100"></div>
                </div>
                <div class="sub-ttl">Pixoo64 Channels</div>
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
              <div class="box stats" id="stats-panel" data-section="stats" style="display:none;">
                <div class="cat-ttl">Technical Diagnostics</div>
                <div id="stats-content"></div>
              </div>
            </div>
          </div>
        </div>
      </ha-card>`;

    const root = this.shadowRoot;
    const art = root.getElementById('artwork');
    if (art) {
      art.addEventListener('load', () => {
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
      const btn = root.getElementById('pixoo-power-btn');
      const on = !(btn.classList.contains('active') || btn.textContent.includes('On'));
      this._localPowerState = on;
      btn.textContent = on ? 'Power: On' : 'Power: Off';
      btn.classList.toggle('active', on);
      if (this._hass && this._config.entity_sensor) {
        this._hass.callService('pixoo64_art', 'send_command', { entity_id: this._config.entity_sensor, command: 'Channel/OnOffScreen', payload: { OnOff: on ? 1 : 0 } });
      }
    });
    root.getElementById('pixoo-brightness-slider')?.addEventListener('change', (e) => {
      if (this._hass && this._config.entity_sensor) {
        this._hass.callService('pixoo64_art', 'send_command', { entity_id: this._config.entity_sensor, command: 'Channel/SetBrightness', payload: { Brightness: parseInt(e.target.value, 10) } });
      }
    });
    root.getElementById('device-channels-container')?.querySelectorAll('button').forEach((b) => {
      b.addEventListener('click', (e) => {
        const ch = parseInt(e.currentTarget.getAttribute('data-channel'), 10);
        this._userSelectedChannel = ch;
        root.getElementById('device-channels-container').querySelectorAll('button').forEach((x) => x.classList.toggle('active', parseInt(x.getAttribute('data-channel'), 10) === ch));
        if (this._hass && this._config.entity_sensor) {
          this._hass.callService('pixoo64_art', 'send_command', { entity_id: this._config.entity_sensor, command: 'Channel/SetIndex', payload: { SelectIndex: ch } });
        }
      });
    });
    const sync = (d) => {
      const eId = this._findDeviceEntity(['number'], ['pixoo64_media_lyrics_sync', 'lyrics_sync']);
      const el = root.getElementById('inline-sync-select');
      if (!eId || !this._hass || !el) return;
      const v = Math.min(5.0, Math.max(-5.0, (parseFloat(el.value) || 0) + d));
      el.value = v.toFixed(1);
      this._hass.callService('number', 'set_value', { entity_id: eId, value: v });
    };
    root.getElementById('inline-sync-minus-btn')?.addEventListener('click', () => sync(-1.0));
    root.getElementById('inline-sync-plus-btn')?.addEventListener('click', () => sync(1.0));
    root.getElementById('inline-sync-select')?.addEventListener('change', (e) => {
      const eId = this._findDeviceEntity(['number'], ['pixoo64_media_lyrics_sync', 'lyrics_sync']);
      if (eId && this._hass) this._hass.callService('number', 'set_value', { entity_id: eId, value: parseFloat(e.target.value) });
    });
    root.getElementById('crop-select')?.addEventListener('change', (e) => {
      const ce = this._findDeviceEntity(['select'], ['pixoo64_media_crop_mode', 'crop_mode']);
      const me = this._findDeviceEntity(['select'], ['pixoo64_media_display_mode', 'display_mode']);
      if (me && this._hass?.states[me]?.state !== 'Vinyl') this._savedNonVinylCrop = e.target.value;
      if (ce && this._hass) {
        this._startRenderingLock('Crop');
        this._hass.callService('select', 'select_option', { entity_id: ce, option: e.target.value });
      }
    });

    root.getElementById('progress-toggle-btn')?.addEventListener('click', () => {
      this._handleFeatureToggle('progress-toggle-btn', ['switch', 'select', 'input_boolean'], ['pixoo64_media_progress_bar', 'progress_bar', 'show_progress', 'progress'], '_progressBarLocalState', 'Progress');
    });

    root.getElementById('textbg-toggle-btn')?.addEventListener('click', () => {
      this._handleFeatureToggle('textbg-toggle-btn', ['switch', 'select', 'input_boolean'], ['pixoo64_media_text_background', 'text_background', 'text_bg'], '_textBgLocalState', 'Text BG');
    });

    root.getElementById('filter-select')?.addEventListener('change', (e) => {
      const fe = this._findDeviceEntity(['select'], ['pixoo64_media_image_filter', 'image_filter']);
      if (fe && this._hass) {
        this._startRenderingLock('Filter');
        this._hass.callService('select', 'select_option', { entity_id: fe, option: e.target.value });
      }
    });
    root.getElementById('overlay-select')?.addEventListener('change', (e) => {
      const x = this._findDeviceEntity(['select'], ['pixoo64_media_overlay_info', 'overlay_info']);
      if (x && this._hass) this._hass.callService('select', 'select_option', { entity_id: x, option: e.target.value });
    });
    root.getElementById('overlay-pos-select')?.addEventListener('change', (e) => {
      const x = this._findDeviceEntity(['select'], ['pixoo64_media_overlay_position', 'overlay_position']);
      if (x && this._hass) this._hass.callService('select', 'select_option', { entity_id: x, option: e.target.value });
    });
    root.getElementById('overlay-align-select')?.addEventListener('change', (e) => {
      const x = this._findDeviceEntity(['select'], ['pixoo64_media_overlay_align', 'overlay_align']);
      if (x && this._hass) this._hass.callService('select', 'select_option', { entity_id: x, option: e.target.value });
    });
    root.getElementById('text-pos-select')?.addEventListener('change', (e) => {
      const x = this._findDeviceEntity(['select'], ['pixoo64_media_artist_track_text', 'artist_track_text', 'text_position']);
      if (x && this._hass) this._hass.callService('select', 'select_option', { entity_id: x, option: e.target.value });
    });
    root.getElementById('advanced-toggle')?.addEventListener('click', () => {
      const b = root.getElementById('advanced-body');
      const a = root.getElementById('advanced-arrow');
      const hid = b.style.display === 'none';
      b.style.display = hid ? 'flex' : 'none';
      a.textContent = hid ? '▲' : '▼';
    });
  }

  callMediaService(s) {
    const mp = this._getMediaPlayerEntity();
    if (mp && this._hass) this._hass.callService('media_player', s, { entity_id: mp });
  }

  _parseChannelIndex(v) {
    if (v === undefined || v === null || v === '') return null;
    if (typeof v === 'number') return v >= 0 && v <= 3 ? v : null;
    const s = String(v).toLowerCase().trim();
    if (s === 'clock' || s === '0') return 0;
    if (s.includes('cloud') || s.includes('animation #1') || s === '1') return 1;
    if (s.includes('visualizer') || s === '2') return 2;
    if (s.includes('custom') || s.includes('animation #2') || s === '3') return 3;
    const p = parseInt(v, 10);
    return !isNaN(p) && p >= 0 && p <= 3 ? p : null;
  }

  _applyTheme() {
    const sA = (this._config?.entity_sensor ? this._hass?.states[this._config.entity_sensor]?.attributes : null) || {};
    const t = this._persistentTheme || { bgColor: '#0d111d', primaryColor: '#00ffcc', color1: '#00ffcc', color2: '#38bdf8', color3: '#818cf8' };

    let c1 = t.color1 || '#00ffcc';
    let c2 = t.color2 || '#38bdf8';
    let c3 = t.color3 || '#818cf8';
    if (Array.isArray(sA.wled_colors) && sA.wled_colors.length >= 3) {
      [c1, c2, c3] = sA.wled_colors;
    } else if (sA.color1 && sA.color2 && sA.color3) {
      c1 = sA.color1;
      c2 = sA.color2;
      c3 = sA.color3;
    }

    const hex2rgb = (h) => {
      if (!h || typeof h !== 'string') return [0, 0, 0];
      const clean = h.trim().replace(/^#/, '');
      if (clean.length === 3) {
        return [
          parseInt(clean[0] + clean[0], 16) || 0,
          parseInt(clean[1] + clean[1], 16) || 0,
          parseInt(clean[2] + clean[2], 16) || 0
        ];
      }
      return [
        parseInt(clean.slice(0, 2), 16) || 0,
        parseInt(clean.slice(2, 4), 16) || 0,
        parseInt(clean.slice(4, 6), 16) || 0
      ];
    };
    const rgba = (rgb, a) => `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${a})`;
    const rgbStr = (rgb) => `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
    const parseRgbStr = (str) => {
      if (!str || typeof str !== 'string') return [13, 17, 29];
      if (str.trim().startsWith('#')) return hex2rgb(str);
      const m = str.match(/\d+/g);
      return m && m.length >= 3 ? m.slice(0, 3).map(Number) : [13, 17, 29];
    };

    const rgb1 = parseRgbStr(c1);
    const rgb2 = parseRgbStr(c2);
    const rgb3 = parseRgbStr(c3);
    const rawBgRgb = parseRgbStr(t.bgColor);

    const surfaceBoxRgb = [
      Math.round(11 * 0.76 + rawBgRgb[0] * 0.16 + rgb1[0] * 0.08),
      Math.round(15 * 0.76 + rawBgRgb[1] * 0.16 + rgb1[1] * 0.08),
      Math.round(25 * 0.76 + rawBgRgb[2] * 0.16 + rgb1[2] * 0.08)
    ];
    const surfaceBtnRgb = [
      Math.round(7 * 0.82 + rawBgRgb[0] * 0.10 + rgb2[0] * 0.08),
      Math.round(10 * 0.82 + rawBgRgb[1] * 0.10 + rgb2[1] * 0.08),
      Math.round(18 * 0.82 + rawBgRgb[2] * 0.10 + rgb2[2] * 0.08)
    ];

    const rawFontColor = String(sA.font_color || '').trim().toLowerCase();
    const isGenericFont = !rawFontColor || ['#ffffff', '#fff', '#000000', '#000', 'white', 'black'].includes(rawFontColor);
    const baseAccentRgb = isGenericFont ? rgb3 : parseRgbStr(t.primaryColor);

    const safePrimaryRgb = this._ensureContrast(baseAccentRgb, surfaceBoxRgb, 4.8);
    const safeAccent2Rgb = this._ensureContrast(rgb2, surfaceBoxRgb, 4.8);
    const safeAccent3Rgb = this._ensureContrast(rgb3, surfaceBoxRgb, 4.8);
    const safeTextRgb = this._ensureContrast([248, 250, 252], surfaceBoxRgb, 7.5);
    const safeMutedRgb = this._ensureContrast([203, 213, 225], surfaceBoxRgb, 5.0);
    const safeDisabledRgb = this._ensureContrast([148, 163, 184], surfaceBtnRgb, 4.6);

    const darkCandidate = [6, 9, 17];
    const lightCandidate = [255, 255, 255];
    const ratioDark = this._getContrastRatio(darkCandidate, safePrimaryRgb);
    const ratioLight = this._getContrastRatio(lightCandidate, safePrimaryRgb);
    const primaryTextRgb = ratioDark >= ratioLight ? darkCandidate : lightCandidate;

    const sig = `${rgbStr(surfaceBoxRgb)}|${rgbStr(safePrimaryRgb)}|${c1}|${c2}|${c3}`;
    if (this._lastThemeSignature !== sig) {
      this._lastThemeSignature = sig;
      const st = this.style;
      st.setProperty('--album-bg', rgbStr(surfaceBoxRgb));
      st.setProperty('--pixoo-primary', rgbStr(safePrimaryRgb));
      st.setProperty('--pixoo-accent2', rgbStr(safeAccent2Rgb));
      st.setProperty('--pixoo-accent3', rgbStr(safeAccent3Rgb));
      st.setProperty('--pixoo-primary-text', rgbStr(primaryTextRgb));

      st.setProperty('--pixoo-color1', rgba(rgb1, 0.64));
      st.setProperty('--pixoo-color2', rgba(rgb2, 0.58));
      st.setProperty('--pixoo-color3', rgba(rgb3, 0.54));
      st.setProperty('--pixoo-glow', rgba(safePrimaryRgb, 0.65));
      st.setProperty('--pixoo-border-tint', rgba(rgb1, 0.58));

      st.setProperty('--pixoo-text', rgbStr(safeTextRgb));
      st.setProperty('--pixoo-muted', rgbStr(safeMutedRgb));
      st.setProperty('--pixoo-disabled-text', rgbStr(safeDisabledRgb));
      st.setProperty('--box-bg', rgba(surfaceBoxRgb, 0.9));
      st.setProperty('--btn-bg', rgba(surfaceBtnRgb, 0.9));
      st.setProperty('--text-shadow', 'rgba(0,0,0,0.92)');
      st.setProperty('--overlay-base', 'rgba(9,12,20,0.72)');
    }
  }

  _applyLayoutReordering() {
    const dispCol = this.shadowRoot?.getElementById('col-display');
    const colA = this.shadowRoot?.getElementById('col-secondary-a');
    const colB = this.shadowRoot?.getElementById('col-secondary-b');
    const contentEl = this.shadowRoot?.getElementById('card-content');
    if (!dispCol || !colA || !colB || !contentEl || !this._config) return;

    const order = this._getLayoutOrder();
    const enabledSig = SECTIONS_METADATA.map((m) => `${m.id}:${this._config[m.configKey] !== undefined ? Boolean(this._config[m.configKey]) : m.defaultShow}`).join(',');
    const sig = `${order.join(',')}|${enabledSig}`;
    if (this._lastLayoutOrderSig === sig) return;
    this._lastLayoutOrderSig = sig;

    const split = computeSmartColumns(order, this._config);
    const dispSet = new Set(split.displayIds);
    const colASet = new Set(split.colAIds);

    const allEls = {};
    this.shadowRoot.querySelectorAll('[data-section]').forEach((el) => {
      const id = el.getAttribute('data-section');
      if (id) allEls[id] = el;
    });

    order.forEach((id, idx) => {
      const el = allEls[id];
      if (!el) return;
      el.style.order = String(idx);
      if (dispSet.has(id)) {
        dispCol.appendChild(el);
      } else if (colASet.has(id)) {
        colA.appendChild(el);
      } else {
        colB.appendChild(el);
      }
    });

    contentEl.classList.toggle('img-left', split.imageSide === 'left');
    contentEl.classList.toggle('img-center', split.imageSide === 'center');
    contentEl.classList.toggle('img-right', split.imageSide === 'right');
  }

  updateValues(force = false) {
    if (!this._hass || !this.shadowRoot || !this._config) return;
    this._applyLayoutReordering();

    const pad = this._config?.area_padding || 'default';
    const bg = this._config?.show_background !== false && pad !== 'none';
    const card = this.shadowRoot.getElementById('main-card');
    if (card) {
      card.classList.toggle('p-none', pad === 'none');
      card.classList.toggle('p-compact', pad === 'compact');
      card.classList.toggle('p-def', pad === 'default');
      card.classList.toggle('no-bg', !bg);
    }

    const sState = this._config.entity_sensor ? this._hass.states[this._config.entity_sensor] : null;
    const mpId = this._getMediaPlayerEntity();
    const mState = mpId ? this._hass.states[mpId] : null;

    const mEnt = this._findDeviceEntity(['select'], ['pixoo64_media_display_mode', 'display_mode']);
    const fEnt = this._findDeviceEntity(['select'], ['pixoo64_media_image_filter', 'image_filter']);
    const oEnt = this._findDeviceEntity(['select'], ['pixoo64_media_overlay_info', 'overlay_info']);
    const opEnt = this._findDeviceEntity(['select'], ['pixoo64_media_overlay_position', 'overlay_position']);
    const oaEnt = this._findDeviceEntity(['select'], ['pixoo64_media_overlay_align', 'overlay_align']);
    const tpEnt = this._findDeviceEntity(['select'], ['pixoo64_media_artist_track_text', 'artist_track_text', 'text_position']);
    const syEnt = this._findDeviceEntity(['number'], ['pixoo64_media_lyrics_sync', 'lyrics_sync']);
    const cpEnt = this._findDeviceEntity(['select'], ['pixoo64_media_crop_mode', 'crop_mode']);
    const prEnt = this._findDeviceEntity(['switch', 'select', 'input_boolean'], ['pixoo64_media_progress_bar', 'progress_bar', 'show_progress', 'progress']);
    const tbEnt = this._findDeviceEntity(['switch', 'select', 'input_boolean'], ['pixoo64_media_text_background', 'text_background', 'text_bg']);

    const sA = sState?.attributes || {};
    const mA = mState?.attributes || {};
    const curHash = [
      sState?.state || 'no_s',
      sA.media_title || mA.media_title || '',
      sA.artist || mA.media_artist || '',
      sA.active_mode || '',
      sA.configured_mode || '',
      sA.color1 || '',
      sA.color2 || '',
      sA.color3 || '',
      sA.wled_colors?.join(',') || '',
      sA.lyrics_available !== undefined ? sA.lyrics_available : '',
      sA.has_timing !== undefined ? sA.has_timing : '',
      sA.live_display_url || sA.image_url || mA.entity_picture || '',
      sA.prefetch_status || '',
      sA.prefetch_next_artist || '',
      sA.prefetch_next_title || '',
      sA.background_color_rgb?.join(',') || '',
      sA.pixoo64_channel !== undefined ? sA.pixoo64_channel : '',
      sA.brightness !== undefined ? sA.brightness : '',
      sA.screen_power !== undefined ? sA.screen_power : '',
      sA.ai_generating !== undefined ? sA.ai_generating : '',
      sA.ai_status || '',
      mState ? `${mState.state}_${mA.volume_level}_${mA.media_position}` : '',
      prEnt ? this._hass.states[prEnt]?.state : '',
      tbEnt ? this._hass.states[tbEnt]?.state : '',
      mEnt ? this._hass.states[mEnt]?.state : '',
      cpEnt ? this._hass.states[cpEnt]?.state : '',
      fEnt ? this._hass.states[fEnt]?.state : '',
      oEnt ? this._hass.states[oEnt]?.state : '',
      opEnt ? this._hass.states[opEnt]?.state : '',
      oaEnt ? this._hass.states[oaEnt]?.state : '',
      tpEnt ? this._hass.states[tpEnt]?.state : '',
      syEnt ? this._hass.states[syEnt]?.state : '',
      this._lastLayoutOrderSig,
      pad,
      bg ? '1' : '0'
    ].join('|');

    if (!force && this._lastStateHash === curHash) return;
    this._lastStateHash = curHash;

    const isAiGenerating = sA.ai_generating === true;
    const confMode = sA.configured_mode || (mEnt && this._hass.states[mEnt]?.state) || sA.active_mode || 'Standard';
    const lyrAvail = sA.lyrics_available === true;
    const timing = sA.has_timing !== false;
    const curMode = (mEnt && this._hass.states[mEnt]?.state) || sA.active_mode || 'Standard';
    const isSlider = curMode === 'Spotify Slider' || curMode === 'Artist Slide';
    const isVinyl = curMode === 'Vinyl';
    const isCassette = curMode.includes('Cassette');
    const isLyrics = curMode === 'Lyrics' || (confMode === 'Lyrics' && lyrAvail);
    const curCrop = (cpEnt && this._hass.states[cpEnt]?.state) || 'No Crop';
    if (curMode !== 'Vinyl' && !this._savedNonVinylCrop) this._savedNonVinylCrop = curCrop;

    const trackTtl = sA.media_title || mA.media_title || '';
    if (this._lastTrackTitle && trackTtl && trackTtl !== this._lastTrackTitle) {
      this._persistentTheme = null;
    }
    this._lastTrackTitle = trackTtl;

    // Extract WLED palette & background_color_rgb for theme
    const wledArr = Array.isArray(sA.wled_colors) && sA.wled_colors.length >= 3 ? sA.wled_colors : null;
    const c1 = (wledArr ? wledArr[0] : sA.color1) || '#00ffcc';
    const c2 = (wledArr ? wledArr[1] : sA.color2) || '#38bdf8';
    const c3 = (wledArr ? wledArr[2] : sA.color3) || '#818cf8';

    if (sA.background_color_rgb?.length === 3) {
      const [r, g, b] = sA.background_color_rgb;
      if (r > 0 || g > 0 || b > 0) {
        const bc = `rgb(${Math.round(r * 0.75)}, ${Math.round(g * 0.75)}, ${Math.round(b * 0.75)})`;
        const pc = sA.font_color && !['#ffffff', '#000000', 'black', 'white'].includes(sA.font_color.toLowerCase()) ? sA.font_color : c3 || c1;
        this._persistentTheme = { bgColor: bc, primaryColor: pc, color1: c1, color2: c2, color3: c3 };
      }
    } else if (wledArr || sA.color1) {
      this._persistentTheme = { bgColor: c1, primaryColor: c3 || c1, color1: c1, color2: c2, color3: c3 };
    }
    this._applyTheme();

    const dWrap = this.shadowRoot.getElementById('display-wrapper');
    if (dWrap) dWrap.style.display = this._config.show_display !== false ? 'block' : 'none';

    const mWrap = this.shadowRoot.getElementById('media-controls-wrapper');
    const isPlay = mState?.state === 'playing';
    if (this._config.show_media !== false) {
      if (mWrap && mWrap.style.display !== 'block') mWrap.style.display = 'block';
      if (mState) {
        const svg = this.shadowRoot.getElementById('play-pause-svg');
        const tgt = isPlay ? '<path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>' : '<path d="M8 5v14l11-7z"/>';
        if (svg && svg.innerHTML !== tgt) svg.innerHTML = tgt;
        if (mA.volume_level !== undefined) {
          const vs = this.shadowRoot.getElementById('vol-slider');
          const nv = Math.round(mA.volume_level * 100);
          if (vs && this.shadowRoot.activeElement !== vs && Number(vs.value) !== nv) vs.value = nv;
        }
      }
    } else if (mWrap && mWrap.style.display !== 'none') {
      mWrap.style.display = 'none';
    }

    const isP = prEnt && this._hass.states[prEnt]
      ? ['on', 'enabled', 'true'].includes((this._hass.states[prEnt]?.state || '').toLowerCase())
      : sA.progress_bar !== undefined
        ? ['true', 'on', 'enabled'].includes(String(sA.progress_bar).toLowerCase())
        : sA.progress_bar_active === true;
    this._progressBarLocalState = isP;

    const pixooProgBar = this.shadowRoot.getElementById('pixoo-pixel-progress');
    const pixooProgFill = this.shadowRoot.getElementById('pixoo-pixel-progress-fill');
    if (pixooProgBar && pixooProgFill) {
      if (isP && mA.media_duration > 0 && isPlay) {
        pixooProgBar.style.display = 'block';
        const pos = mA.media_position || 0;
        const dur = mA.media_duration;
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
      devWrap.style.display = this._config.show_pixoo_controls !== false ? 'flex' : 'none';
      const pBtn = this.shadowRoot.getElementById('pixoo-power-btn');
      const scrOn = sA.screen_power !== undefined ? sA.screen_power === 'On' : this._localPowerState !== null ? this._localPowerState : String(sA.pixoo64_channel).toLowerCase() !== 'off';
      if (pBtn) {
        pBtn.textContent = scrOn ? 'Power: On' : 'Power: Off';
        pBtn.classList.toggle('active', scrOn);
      }
      const bs = this.shadowRoot.getElementById('pixoo-brightness-slider');
      if (bs && sA.brightness !== undefined) {
        const bv = parseInt(sA.brightness, 10);
        if (!isNaN(bv) && this.shadowRoot.activeElement !== bs) bs.value = bv;
      }
      const sc = this._parseChannelIndex(sA.pixoo64_channel);
      if (sc !== null) this._userSelectedChannel = sc;
      const actCh = sc !== null ? sc : this._userSelectedChannel;
      this.shadowRoot.getElementById('device-channels-container')?.querySelectorAll('button').forEach((b) => b.classList.toggle('active', actCh !== null && parseInt(b.getAttribute('data-channel'), 10) === actCh));
    }

    const tWrap = this.shadowRoot.getElementById('track-info-wrapper');
    const tEl = this.shadowRoot.getElementById('title');
    const aEl = this.shadowRoot.getElementById('artist');
    const lIco = this.shadowRoot.getElementById('lyrics-status-icon');
    const ttl = sA.media_title || mA.media_title || null;
    const art = sA.artist || mA.media_artist || null;

    if (this._config.show_track_info === false) {
      if (tWrap && tWrap.style.display !== 'none') tWrap.style.display = 'none';
    } else {
      const dispTtl = ttl || 'Idle';
      const dispArt = art || (sState && sState.state && sState.state !== 'Off' ? sState.state : 'No Media Playing');
      if (tWrap && tWrap.style.display !== 'flex') tWrap.style.display = 'flex';
      if (tEl && tEl.textContent !== dispTtl) tEl.textContent = dispTtl;
      if (tEl) tEl.style.display = 'block';
      if (aEl && aEl.textContent !== dispArt) aEl.textContent = dispArt;
      if (aEl) aEl.style.display = 'block';
      if (lIco) {
        if (isPlay && ttl) {
          lIco.style.display = 'inline-flex';
          const icoSvg = '<svg viewBox="0 0 24 24"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6zM3 6h6v2H3zm0 4h6v2H3zm0 4h4v2H3z"/></svg>';
          if (!timing) {
            lIco.className = 'lyric-icon unavail';
            lIco.title = 'Live Stream: Duration not provided';
            lIco.innerHTML = icoSvg;
          } else if (isLyrics) {
            lIco.className = 'lyric-icon act';
            lIco.title = 'Synced Lyrics Active';
            lIco.innerHTML = icoSvg;
          } else if (lyrAvail) {
            lIco.className = 'lyric-icon avail';
            lIco.title = 'Synced Lyrics Available';
            lIco.innerHTML = icoSvg;
          } else {
            lIco.className = 'lyric-icon unavail';
            lIco.title = 'No Synced Lyrics Found';
            lIco.innerHTML = icoSvg;
          }
        } else {
          lIco.style.display = 'none';
        }
      }
    }

    // Next Track Box: Appears ~10s before song ends when Prefetch populates next track info
    const nW = this.shadowRoot.getElementById('next-track-wrapper');
    const nT = this.shadowRoot.getElementById('next-track-title');
    if (this._config.show_next_track !== false && isPlay && sA.prefetch_next_artist && sA.prefetch_next_title) {
      if (nW && nW.style.display !== 'flex') nW.style.display = 'flex';
      const str = `${sA.prefetch_next_artist} - ${sA.prefetch_next_title}`;
      if (nT && nT.textContent !== str) nT.textContent = str;
    } else if (nW && nW.style.display !== 'none') {
      nW.style.display = 'none';
    }

    if (sState) {
      const img = this.shadowRoot.getElementById('artwork');
      const rawImg = Array.isArray(sA.image_url) ? sA.image_url[0] : sA.image_url;
      const live = sA.live_display_url || rawImg || (!isAiGenerating ? mA.entity_picture : null) || DEFAULT_PREVIEW_SVG;

      if (live && this._lastLiveImage !== live && img) {
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
          const u = `url("${live}")`;
          if (amb.style.backgroundImage !== u) amb.style.backgroundImage = u;
          amb.style.opacity = '0.78';
        } else {
          amb.style.backgroundImage = 'none';
          amb.style.opacity = '0';
        }
      }

      const aB = this.shadowRoot.getElementById('activity-badge');
      const aT = this.shadowRoot.getElementById('activity-text');
      const ps = sA.prefetch_status;
      const badgeLbl = ps && !['Idle', 'Disabled', 'None', '', null].includes(ps) && ((ps.includes('Vinyl') && isVinyl) || (ps.includes('Cassette') && isCassette) || (ps.includes('Slider') && isSlider) || (!ps.includes('Vinyl') && !ps.includes('Cassette') && !ps.includes('Slider')))
        ? ps
        : isPlay
          ? 'Playing'
          : null;
      if (badgeLbl && aB && aT) {
        aB.style.display = 'flex';
        if (aT.textContent !== badgeLbl) aT.textContent = badgeLbl;
      } else if (aB) {
        aB.style.display = 'none';
      }

      const sp = this.shadowRoot.getElementById('stats-panel');
      const statsContent = this.shadowRoot.getElementById('stats-content');
      if (this._config.show_stats === true && sp) {
        const itms = [];
        itms.push({ l: 'Active Mode', v: sA.active_mode || curMode || 'Standard' });
        if (sA.image_source && sA.image_source !== 'Unknown') itms.push({ l: 'Source', v: sA.image_source });
        if (sA.process_duration && !['N/A', '0.00s', '0.0s'].includes(sA.process_duration)) itms.push({ l: 'Process Time', v: sA.process_duration });
        if (sA.profile_total) itms.push({ l: 'Pipeline', v: `${sA.profile_total}s` });
        if (isPlay) {
          if (!timing) itms.push({ l: 'Lyrics Status', v: 'Live Stream' });
          else if (lyrAvail) {
            itms.push({ l: 'Lyrics Status', v: isLyrics ? 'Active' : 'Available' }, { l: 'Lyrics RAM', v: sA.lyrics_found ? 'Loaded & Synced' : 'Ready' });
          } else itms.push({ l: 'Lyrics Status', v: 'Not Found' });
        }
        itms.push({ l: 'RAM Status', v: ps && !['None', '', null].includes(ps) ? ps : 'Idle' });
        if (isSlider && sA.slider_status && !['Idle', 'None', '', null].includes(sA.slider_status)) itms.push({ l: 'Slider', v: sA.slider_status });
        itms.push({ l: 'Image Cache', v: `${sA.general_cache_size || 0} / ${sA.general_cache_limit || 40}` });

        if (sp.style.display !== 'flex') sp.style.display = 'flex';
        const html = itms.map((x) => `<div class="stat-item"><span class="stat-lbl">${x.l}:</span><span class="stat-val">${x.v}</span></div>`).join('');
        if (this._lastStatsSignature !== html && statsContent) {
          this._lastStatsSignature = html;
          statsContent.innerHTML = html;
        }
      } else if (sp && sp.style.display !== 'none') {
        sp.style.display = 'none';
      }
    }

    const mdWrap = this.shadowRoot.getElementById('modes-controls-wrapper');
    const mdCont = this.shadowRoot.getElementById('modes-buttons-container');
    const syncWrap = this.shadowRoot.getElementById('lyrics-sync-wrapper');
    if (syncWrap) syncWrap.style.display = isLyrics ? 'flex' : 'none';

    const opEl = this.shadowRoot.getElementById('overlay-pos-select');
    const oaEl = this.shadowRoot.getElementById('overlay-align-select');
    const oAct = oEnt && this._hass.states[oEnt]?.state !== 'None';
    if (opEl && opEl.disabled !== !oAct) opEl.disabled = !oAct;
    if (oaEl && oaEl.disabled !== !oAct) oaEl.disabled = !oAct;

    const pBtn = this.shadowRoot.getElementById('progress-toggle-btn');
    if (pBtn) {
      const txt = isP ? 'Progress: On' : 'Progress: Off';
      if (pBtn.textContent !== txt) pBtn.textContent = txt;
      pBtn.classList.toggle('active', isP);
    }

    const isT = tbEnt && this._hass.states[tbEnt]
      ? ['on', 'enabled', 'true'].includes((this._hass.states[tbEnt]?.state || '').toLowerCase())
      : sA.text_background !== undefined
        ? ['true', 'on', 'enabled'].includes(String(sA.text_background).toLowerCase())
        : ['true', 'on', 'enabled'].includes(String(sA.text_bg).toLowerCase());
    this._textBgLocalState = isT;
    const tBtn = this.shadowRoot.getElementById('textbg-toggle-btn');
    if (tBtn) {
      const txt = isT ? 'Text BG: On' : 'Text BG: Off';
      if (tBtn.textContent !== txt) tBtn.textContent = txt;
      tBtn.classList.toggle('active', isT);
    }

    if (this._config.show_modes !== false) {
      if (mdWrap && mdWrap.style.display !== 'flex') mdWrap.style.display = 'flex';
      const bOpts = (mEnt && this._hass.states[mEnt]?.attributes?.options) || ['Standard', 'Vinyl', 'Lyrics'];
      const oSig = `${bOpts.join(',')}|avail:${lyrAvail}|time:${timing}`;
      if (this._lastModesOptionsSignature !== oSig && mdCont) {
        this._lastModesOptionsSignature = oSig;
        const ext = [];
        bOpts.forEach((o) => {
          if (o === 'Vinyl') ext.push('Vinyl (Normal)', 'Vinyl (Zoom)', 'Vinyl (Extra Zoom)');
          else ext.push(o);
        });
        mdCont.innerHTML = ext.map((o) => {
          if (o === 'Lyrics') {
            const dc = lyrAvail ? 'l-dot avail' : 'l-dot unavail';
            const dis = (!timing || !lyrAvail) ? 'disabled' : '';
            const tit = !timing ? 'title="Live stream"' : !lyrAvail ? 'title="No synced lyrics"' : 'title="Show Lyrics"';
            return `<button class="act-btn" data-mode="${o}" ${dis} ${tit}><span class="${dc}"></span>Lyrics</button>`;
          }
          return `<button class="act-btn" data-mode="${o}">${o}</button>`;
        }).join('');

        mdCont.querySelectorAll('button').forEach((b) => {
          b.addEventListener('click', (e) => {
            if (this._pendingTargetMode || e.currentTarget.classList.contains('active') || e.currentTarget.disabled) return;
            const tgt = e.currentTarget.getAttribute('data-mode');
            this._startRenderingLock(tgt);
            const lMe = this._findDeviceEntity(['select'], ['pixoo64_media_display_mode', 'display_mode']);
            const lCe = this._findDeviceEntity(['select'], ['pixoo64_media_crop_mode', 'crop_mode']);
            const curLMe = lMe ? this._hass?.states[lMe]?.state : 'Standard';
            const curLCe = lCe ? this._hass?.states[lCe]?.state : 'No Crop';
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

      if (mdCont) {
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
      }
    } else if (mdWrap && mdWrap.style.display !== 'none') {
      mdWrap.style.display = 'none';
    }

    const advWrap = this.shadowRoot.getElementById('advanced-wrapper');
    if (this._config.show_advanced !== false) {
      if (advWrap && advWrap.style.display !== 'block') advWrap.style.display = 'block';
      const fSel = this.shadowRoot.getElementById('filter-select');
      if (fEnt && this._hass.states[fEnt] && fSel) {
        const fo = this._hass.states[fEnt].attributes.options || ['None'];
        const fs = `${this._hass.states[fEnt].state}|${fo.join(',')}`;
        if (this._lastFilterSignature !== fs) {
          this._lastFilterSignature = fs;
          fSel.innerHTML = fo.map((o) => `<option value="${o}" ${this._hass.states[fEnt].state === o ? 'selected' : ''}>${o === 'None' ? 'Filter: None' : 'Filter: ' + o}</option>`).join('');
          fSel.style.display = 'block';
        }
      }
      const cs = this.shadowRoot.getElementById('crop-select');
      if (cpEnt && this._hass.states[cpEnt] && cs && cs.value !== this._hass.states[cpEnt].state) cs.value = this._hass.states[cpEnt].state;
      const os = this.shadowRoot.getElementById('overlay-select');
      if (oEnt && this._hass.states[oEnt] && os && os.value !== this._hass.states[oEnt].state) os.value = this._hass.states[oEnt].state;
      const ops = this.shadowRoot.getElementById('overlay-pos-select');
      if (opEnt && this._hass.states[opEnt] && ops && ops.value !== this._hass.states[opEnt].state) ops.value = this._hass.states[opEnt].state;
      const oas = this.shadowRoot.getElementById('overlay-align-select');
      if (oaEnt && this._hass.states[oaEnt] && oas && oas.value !== this._hass.states[oaEnt].state) oas.value = this._hass.states[oaEnt].state;
      const tps = this.shadowRoot.getElementById('text-pos-select');
      if (tpEnt && this._hass.states[tpEnt] && tps && tps.value !== this._hass.states[tpEnt].state) tps.value = this._hass.states[tpEnt].state;
    } else if (advWrap && advWrap.style.display !== 'none') {
      advWrap.style.display = 'none';
    }

    if (isAiGenerating) {
      this._startRenderingLock('AI Art');
      const rt = this.shadowRoot.getElementById('render-text');
      if (rt) rt.textContent = sA.ai_status || 'Generating AI Artwork...';
      const ab = this.shadowRoot.getElementById('activity-badge');
      const at = this.shadowRoot.getElementById('activity-text');
      if (ab && at) {
        ab.style.display = 'flex';
        at.textContent = sA.ai_status || 'AI Generating...';
      }
    } else if (this._pendingTargetMode === 'AI Art') {
      this._releaseRenderingLock();
    }

    if (syEnt && this._hass.states[syEnt]?.state !== undefined) {
      const str = parseFloat(this._hass.states[syEnt].state).toFixed(1);
      const sel = this.shadowRoot.getElementById('inline-sync-select');
      if (sel && sel.value !== str) sel.value = str;
    }

    const dispCol = this.shadowRoot.getElementById('col-display');
    const colA = this.shadowRoot.getElementById('col-secondary-a');
    const colB = this.shadowRoot.getElementById('col-secondary-b');
    const colOthers = this.shadowRoot.getElementById('col-others');
    const contentEl = this.shadowRoot.getElementById('card-content');

    if (dispCol && colA && colB && colOthers && contentEl) {
      const hasDisp = Array.from(dispCol.children).some((ch) => ch.style.display !== 'none');
      const hasColA = Array.from(colA.children).some((ch) => ch.style.display !== 'none');
      const hasColB = Array.from(colB.children).some((ch) => ch.style.display !== 'none');
      const hasOthers = hasColA || hasColB;

      dispCol.style.display = hasDisp ? '' : 'none';
      colA.style.display = hasColA ? '' : 'none';
      colB.style.display = hasColB ? '' : 'none';
      colOthers.style.display = hasOthers ? '' : 'none';

      const activeCols = (hasDisp ? 1 : 0) + (hasColA ? 1 : 0) + (hasColB ? 1 : 0);
      contentEl.classList.toggle('cols-1', activeCols <= 1);
      contentEl.classList.toggle('cols-2', activeCols === 2);
      contentEl.classList.toggle('cols-3', activeCols === 3);
    }
  }

  getCardSize() {
    return 4;
  }
}

if (!customElements.get('pixoo-media-card')) {
  customElements.define('pixoo-media-card', PixooMediaCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === 'pixoo-media-card')) {
  window.customCards.push({
    type: 'pixoo-media-card',
    name: 'Pixoo Media Card',
    description: 'Custom pixel retro media card for Pixoo64 with dynamic ambient theme and live GIF preview.',
    preview: true
  });
}