<h1 align="center">🎨 Pixoo64 Media Album Art for Home Assistant (v2.1)</h1>

<p align="center">
  <a href="https://www.home-assistant.io/"><img src="https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blueviolet.svg?style=for-the-badge&logo=home-assistant" alt="Home Assistant 2024.1+"></a>
  <a href="https://hacs.xyz/"><img src="https://img.shields.io/badge/HACS-Custom%20Repo-orange.svg?style=for-the-badge&logo=hacs" alt="HACS Custom Repository"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge" alt="License: MIT"></a>
  <a href="https://github.com/idodov/pixoo64_art/releases"><img src="https://img.shields.io/badge/Version-2.1.0-emerald.svg?style=for-the-badge" alt="Version 2.1.0"></a>
  <a href="https://github.com/idodov/pixoo64_art/issues"><img src="https://img.shields.io/github/issues/idodov/pixoo64_art?style=for-the-badge&color=red" alt="GitHub Issues"></a>
</p>

<p align="center">
  <strong>Transform your Divoom Pixoo64 into an ultra-fast retro media companion: adaptive album art, real-time synced lyrics, animated Hit Parade charts, live playback analytics, ambient light sync, and snappy pixel-art notifications powered by AWTRIX Hub & LaMetric.</strong>
</p>

---

## 🌟 Why Pixoo64 Media Album Art Stands Out

**Pixoo64 Media Album Art** is a 100% native Home Assistant custom integration engineered to turn your 64×64 LED matrix into an intelligent, studio-grade media display.

Unlike traditional media display scripts that rely on single-platform APIs or cloud webhooks, this integration provides an autonomous, music-service-agnostic visual hub:

* **100% Music Service Agnostic** — Works out-of-the-box with Spotify, Apple Music, TIDAL, YouTube Music, Sonos, Plex, Jellyfin, Kodi, VLC, local file libraries, DLNA, and internet radio streams.
* **🏆 Hit Parade Charts & Local Analytics** — Features a built-in SQLite WAL playback analytics database that scrobbles your plays locally, tracks full album and EP completion sessions, and generates animated countdown charts on your Pixoo matrix.
* **⚡ Sub-Second Display Latency** — Pulls artwork directly from Home Assistant's in-memory media player component in less than 1 ms, delivering near-instant transitions when tracks change.
* **🎤 Asynchronous Background Lyrics** — Synced lyrics lookups (via LRCLIB) run completely decoupled in the background. Your cover art and titles appear on the Pixoo instantly without waiting for remote network responses.
* **🔔 High-Speed Smart Notifications with AWTRIX & LaMetric Icons** — Seamlessly display animated pixel icons from **[AWTRIX Hub](https://awtrix.de/icons)** and **[LaMetric](https://developer.lametric.com/icons)** at double-speed refresh rates with full burned-text typography and hardware buzzer beeps.
* **🛡️ Smart Channel Memory & Black-Screen Immunity** — Strictly guards against getting trapped on Channel 4 (the empty HTTP GIF screen). Your preferred channel (Clock, Cloud, Visualizer, or Custom) is remembered and restored automatically.
* **Zero Paid Subscriptions Required** — Core playback works with native Home Assistant metadata and free community databases. Optional free developer keys (Spotify, TIDAL, Discogs, Last.fm) can be added for enhanced resolution and animated carousel modes.
* **100% Local LAN Communication** — Sends pixel payloads directly over your local Wi-Fi via HTTP POST requests, guaranteeing privacy, zero external cloud dependencies, and instant response times.

---

## 🚀 What's New in Version 2.1.0

Version 2.1.0 expands the notification and pixel-art system with community icon libraries, high-frame-rate animations, and persistent SQLite icon caching:

| Feature | Enhancement | User Benefit |
| :--- | :--- | :--- |
| **🌐 AWTRIX Hub Integration** | Direct support for [awtrix.de/icons](https://awtrix.de/icons) via icon slugs (e.g., `house-climate`, `btccoin`, `kick`) or full URLs. | Access thousands of community-crafted 8×8 and 16×16 pixel icons and animations directly from automations or the dashboard card. |
| **⚡ 2× Animated Frame Speed** | Precise extraction of native GIF Graphic Control Blocks & WebP ANMF headers with doubled playback speed (`raw_speed * 0.5`). | Eliminates sluggish slideshow playback on the Pixoo LED hardware; animations look lively, fluid, and responsive. |
| **🏎️ Custom Animation Speed Control** | New optional `anim_speed` parameter (in milliseconds per frame). | Fine-tune animation speed on demand (e.g. `anim_speed: 50` for fast 20 fps animations). |
| **💾 Persistent SQLite & Disk Icon Cache** | 3-tier hybrid caching (RAM $\to$ SQLite WAL database $\to$ `.storage/pixoo64/icons/`). | Icons download once and load in **0.0 ms** thereafter with zero network overhead. Easily pruned or cleared via `pixoo64_art.clear_cache` (`scope: icons`). |
| **🎛️ Lovelace Card AWTRIX Selector** | Added **Custom AWTRIX Icon** dropdown option and quick **🌐 Browse AWTRIX ↗** button. | Preview and send any AWTRIX Hub icon directly from the Home Assistant dashboard in seconds. |

---

## 🏆 Hit Parade Charts & Playback Analytics

Version 2.0+ includes a comprehensive **local music analytics and leaderboard system**. Home Assistant automatically tracks every track, artist, and full album playthrough into a local SQLite database (`.storage/pixoo64/pixoo64_analytics.db`), operating with zero external telemetry or cloud tracking.

```
       [Track Playback Event]
                 │
                 ▼
      Scrobble Verification (30s+ playback)
                 │
                 ▼
       Local SQLite Database (WAL Mode)
        ├── tracked_songs (Plays, Fingerprint, Canonical Title)
        ├── play_history (Timestamps, Granular Ledger)
        ├── album_completions (Full Album & EP Playthroughs)
        └── pixel_icons (AWTRIX & LaMetric Cached Metadata)
                 │
                 ▼
    ┌─────────────────────────────┴─────────────────────────────┐
    ▼                                                           ▼
Hit Parade Animated Display                       Dedicated Sensors & Services
• Gradient Intro Card + Gold Trophy               • sensor.pixoo64_analytics
• #1 Gold (Pulsating Frame), #2 Silver, #3 Bronze • sensor.pixoo64_status (current_track_rank)
• Plays Badge (e.g., "34x")                       • pixoo64_art.create_chart
• MicroPixelFont Artist & Title                   • pixoo64_art.get_leaderboard
```

### 📊 Leaderboard Categories & Timeframes

You can trigger a **Hit Parade Countdown** directly on your Pixoo64 matrix using the dashboard card, the `pixoo64_art.create_chart` action, or Home Assistant automations:

* **Chart Types:**
  * **Top Tracks** — Your most-played individual songs.
  * **Top Artists** — Artists with the highest cumulative play counts.
  * **Completed Albums** — Full studio albums listened to from start to finish (detected via queue inspection).
  * **Completed EPs** — Short-format records and EPs played to completion.
  * **Top Radio** — Most-frequented live radio stations and internet streams.
* **Timeframes:** `Daily`, `Weekly` (customizable Sunday–Saturday or Monday–Sunday), `Monthly`, `Yearly`, and `All-Time`.
* **Historical Periods:** Step back in time to view specific past calendar weeks or months (e.g., *"October 2026"*).
* **Countdown Direction:** Choose between dramatic countdown order (`10 ➔ 1`) or ascending order (`1 ➔ 10`).

### 📺 Visual On-Matrix Countdown Slides

During a Hit Parade countdown, the Pixoo64 displays a broadcast-style visual carousel:
1. **Intro Title Card:** Features a gradient background, a retro gold trophy icon, the chart category name, and the active timeframe label.
2. **Podium Badges:** Rank #1 displays a bold gold badge with a pulsating outer gold border; Rank #2 displays metallic silver; Rank #3 displays bronze; and Ranks #4+ display high-visibility cyan.
3. **Play Counter:** Top-right counter shows exact play counts (e.g., `42x`).
4. **Artwork Canvas:** Renders the album cover with a semi-transparent dark bottom strip and dual-line typography for track and artist.

#### 💡 Automation Example: Scheduled Weekly Chart Countdown

Trigger a broadcast countdown of your weekly top tracks every Sunday evening at 20:00:

```yaml
alias: "Pixoo64 - Sunday Hit Parade Countdown"
description: "Broadcast your top 10 most-played tracks of the week on the Pixoo64"
trigger:
  - trigger: time
    at: "20:00:00"
condition:
  - condition: time
    weekday:
      - sun
action:
  - action: pixoo64_art.create_chart
    data:
      chart_type: "Top Tracks"
      timeframe: "Weekly"
      direction: "Countdown (10 to 1)"
      limit: 10
      slide_duration: 5
```

---

## 💽 Display Modes Showcase

Switch visual rendering modes on the fly via the Lovelace card, select entities, or Home Assistant automations:

| Mode | Description | Preview / Animation |
| :--- | :--- | :--- |
| **Standard** | Crisp crop engine rendering album art with adaptive dynamic text overlays (title, artist, album, clock, temperature). | <img width="64" height="64" alt="pixoo_std_FKA_twigs__Koreless_Drums_of_Death_Cyberpunk_Neon" src="https://github.com/user-attachments/assets/d300f962-d15d-4c9a-b108-155a4307aee4" /> |
| **Vinyl Record** | Smooth rotating turntable animation featuring grooved micro-pixel vinyl textures and realistic glossy reflections. | <img width="64" height="64" alt="pixoo_vinyl_FKA_twigs__Koreless_Drums_of_Death_No_Crop" src="https://github.com/user-attachments/assets/d9bf8683-866d-49c7-b16c-47b11f01977a" /> <img width="64" height="64" alt="pixoo_vinyl_FKA_twigs__Koreless_Drums_of_Death_Extra_Crop" src="https://github.com/user-attachments/assets/f6aedd0f-26db-4e1c-83e0-b742db0909f5" /> |
| **Cassette Tape** | Vintage animated cassette tape mode with moving spools and proportional micro-pixel typography labels. | <img width="64" height="64" alt="pixoo_cassette_FKA_twigs__Koreless_Drums_of_Death" src="https://github.com/user-attachments/assets/2bc917cf-eff5-4c35-b29a-9a301c26dd61" /> |
| **Spotify Slider** | Dynamic animated carousel cycling through the artist's discography and top album covers. *(Requires free Spotify developer API credentials)* | <img width="64" height="64" alt="pixoo_slider_FKA_twigs__Koreless_Drums_of_Death" src="https://github.com/user-attachments/assets/ee1d9b6e-69ed-4b8e-80c5-b6cdb61a32e4" /> |
| **Artist Gallery** | Dedicated visual mode cycling through high-resolution artist fanart and portraits sourced from TheAudioDB. | <img width="64" height="64" alt="pixoo_artist_gallery_FKA_twigs__Koreless" src="https://github.com/user-attachments/assets/0a083f65-2fcf-43ab-99b6-3c3ff606e9ca" /> |
| **Synced Lyrics** | Real-time synchronized lyrics powered by LRCLIB, featuring intelligent multi-line wrapping, dimming backdrop filter, and BiDi language support. | *(Live text rendered synchronously)* |
| **Analog Clock** | Classical retro analog clock overlay projected over atmospheric, softly dimmed album art. | <img width="64" height="64" alt="pixoo_clock_FKA_twigs__Koreless_Drums_of_Death_Cyberpunk_Neon" src="https://github.com/user-attachments/assets/ad3512d4-992e-486e-8f00-fd484588a843" /> |
| **Force AI** | Generates bespoke conceptual pop-art via Pollinations AI for tracks, streams, or mixes lacking official artwork. | <img width="64" height="64" alt="pixoo_std_FKA_twigs__Koreless_Drums_of_Death_Cyberpunk_Neon" src="https://github.com/user-attachments/assets/e0d59056-c783-43c6-8a59-21d7f910da9f" /> |

---

## 🎛️ The Lovelace Card (`pixoo-media-card`)

<table border="0" cellpadding="0" cellspacing="0" style="border-collapse: collapse; border: none; background: transparent;">
  <tr>
    <td width="62%" valign="top" style="border: none; background: transparent; padding-right: 20px;">
      <b>Pixoo64 Media Album Art</b> includes an advanced companion Lovelace card: <b><code>pixoo-media-card</code></b>.
      <br><br>
      The card functions as a <b>live visual dashboard simulator</b>, mirroring in real time exactly what is being drawn on your Pixoo64 LED matrix—complete with CRT scanline grids, ambient backdrops, dynamic color glow extracted from the artwork, and real-time prefetch badges.
      <br><br>
      <ul>
        <li><b>Live Visual Mirror & Seeking</b> — View the exact 64×64 pixel canvas, applied image filters, and active animation frames directly on your dashboard. Click directly on the display preview to seek through playback.</li>
        <li><b>Fluid Responsive Multi-Column Engine</b> — Automatically adapts cleanly across 1-column, 2-column, and 3-column wide screens without aspect-ratio stretching or clipping.</li>
        <li><b>🔔 Quick Notifications Suite</b> — Send animated AWTRIX, LaMetric, or built-in pixel alerts with a 1-click <b>Browse AWTRIX</b> button directly from the card.</li>
        <li><b>🏆 Hit Parade Charts Panel</b> — Select chart category, timeframe, and period, then click <b>Show Chart</b> to trigger animated countdowns on your Pixoo matrix directly from the dashboard.</li>
        <li><b>Modular Section Reordering</b> — Tailor the card to your workflow. Using the visual UI editor or YAML, you can freely reorder, show, or hide any section (Display, Metadata, Next Track, Media Controls, Display Modes, Hardware Controls, and Diagnostics).</li>
        <li><b>Dynamic Ambient Theme Engine</b> — Automatically samples the dominant color palette from the current album art or synced WLED strips to paint ambient glows, borders, and buttons.</li>
        <li><b>Real-Time Lyrics Status</b> — Live visual indicator badge illuminates when lyrics are available, allowing instant one-click mode switching.</li>
        <li><b>Diagnostics & Pipeline Telemetry</b> — Collapsible technical diagnostics panel showing sub-millisecond pipeline durations, RAM image cache hit rates, and prefetch telemetry.</li>
      </ul>
    </td>
    <td width="38%" valign="middle" align="center" style="border: none; background: transparent;">
      <video src="https://github.com/user-attachments/assets/587d92a3-c4e8-48b8-ad5f-42e072b8940e" width="100%" autoplay loop muted playsinline style="border-radius: 10px; display: block; border: none;"></video>
    </td>
  </tr>
</table>

<img width="1242" height="643" alt="image" src="https://github.com/user-attachments/assets/7c5a1368-2021-4bd0-a072-7b2c2c5c2b01" />

> [!TIP]
> **Automatic Frontend Registration:** The companion Lovelace card (`pixoo-media-card.js`) is automatically served and injected into Home Assistant upon integration startup (`/pixoo64_card/pixoo-media-card.js`). You do not need to manually add resources in your Lovelace dashboards settings!

### 🎛️ Card Configuration (UI Editor & YAML)

The `pixoo-media-card` is fully integrated with Home Assistant's visual dashboard editor:

- **Via the UI:** Edit your dashboard, click **Add Card**, search for **Pixoo Media Card**, and customize your layout using interactive switches, column selectors, and drag-and-drop section handles.
- **Via YAML:** You can configure the card directly using the following comprehensive template:

```yaml
type: custom:pixoo-media-card
entity_sensor: sensor.pixoo64_status
area_padding: default
wide_layout: auto           # Options: auto, 1col, 2col, 3col
show_display: true          # 64x64 Live CRT mirror canvas
show_track_info: true       # Title, artist, and album badges
show_media: true            # Play/pause/next transport & volume slider
show_modes: true            # Display mode switcher (Standard, Vinyl, etc.)
show_charts: true           # 🏆 Hit Parade interactive chart panel
show_notifications: true    # 🔔 Instant notifications & buzzer trigger
show_pixoo_controls: true   # Screen power, brightness & channel selectors
show_next_track: true       # Queue prefetch preview
show_advanced: true         # Crop, filter, and overlay settings
show_stats: false           # Live telemetry & cache diagnostic metrics
show_background: true       # Ambient artwork theme glow backdrop
layout_order:
  - display
  - track_info
  - next_track
  - media_controls
  - modes
  - charts
  - notifications
  - pixoo_controls
  - advanced
  - stats
grid_options:
  columns: 24
  rows: auto
```

---

## 🎨 Advanced Image Processing, Filters & Smart Cropping

Rendering high-resolution album covers legibly on a 64×64 LED matrix requires intelligent composition. **Pixoo64 Media Album Art** features a dedicated computer-vision and image processing pipeline built specifically for low-resolution displays:

### ✂️ Surgical Crop Engine

Standard center-cropping often slices off faces or leaves distracting black bars. Our smart crop engine offers three distinct algorithms:

| Crop Mode | Description & Algorithm | Preview / Image |
| :--- | :--- | :--- |
| **No Crop** | Preserves the complete original album sleeve aspect ratio without automated framing adjustments. | <img width="64" height="64" alt="pixoo_std_Kate_Bush_Running_Up_That_Hill__A_Deal_With_God__Cyberpunk_Neon" src="https://github.com/user-attachments/assets/9b864c96-1450-44cd-8f17-47eadb533969" /> |
| **Standard Crop** | Intelligently trims black letterboxing, white scanner margins, and pillarbox bars while protecting core artwork elements and typography. | <img width="64" height="64" alt="pixoo_std_Kate_Bush_Running_Up_That_Hill__A_Deal_With_God__Cyberpunk_Neon" src="https://github.com/user-attachments/assets/c107e471-58ca-479e-bca1-235b233979fa" /> |
| **Extra Crop** <br>*(Subject Isolation)* | Computer vision engine featuring **Nested Container Unwrapping** (extracts inner photos from bordered sleeves), **Subject Clustering** (keeps band members and duos centered together), and **Typographic Framing** for minimalist text sleeves. | <img width="64" height="64" alt="pixoo_std_Kate_Bush_Running_Up_That_Hill__A_Deal_With_God__Cyberpunk_Neon" src="https://github.com/user-attachments/assets/0899f138-7503-4502-881b-9e583c3e7128" /> |

---

### ✨ Real-Time Image Filters

Downscaling modern album art can soften micro-contrast. The built-in **Image Filter Engine** applies Pillow-powered pre- and post-quantization enhancements:

| Filter Mode | Visual Aesthetic & Profile | Preview / Image |
| :--- | :--- | :--- |
| **Vibrant** | Amplifies saturation, dynamic range, and local contrast to make LEDs punchy and deep. | <img width="64" height="64" alt="pixoo_std_Kate_Bush_Running_Up_That_Hill__A_Deal_With_God__Vibrant" src="https://github.com/user-attachments/assets/161a460c-fa8f-481a-a738-acf24336b210" /> |
| **Retro Arcade** | Posterizes color channels and reduces bit-depth for an authentic 8-bit/16-bit arcade aesthetic. | <img width="64" height="64" alt="pixoo_std_Kate_Bush_Running_Up_That_Hill__A_Deal_With_God__Retro_Arcade" src="https://github.com/user-attachments/assets/a48724e9-457c-4cd3-b79b-fec58602668c" /> |
| **Cyberpunk Neon** | Maximizes micro-contrast and edge luminescence for a glowing sci-fi atmosphere. | <img width="64" height="64" alt="pixoo_std_Kate_Bush_Running_Up_That_Hill__A_Deal_With_God__Cyberpunk_Neon" src="https://github.com/user-attachments/assets/c0722ef3-dbce-45da-b94b-b6a730d082e2" /> |
| **Noir B&W** | High-contrast monochrome tonal mapping for timeless, moody acoustic and jazz sessions. | <img width="64" height="64" alt="pixoo_std_Kate_Bush_Running_Up_That_Hill__A_Deal_With_God__Noir_B_W" src="https://github.com/user-attachments/assets/bf41703b-baf4-4258-bd8d-66eae19ed7cc" /> |
| **Crisp & Sharp** | Unsharp masking filter calibrated to restore fine edge sharpness lost during downscaling. | <img width="64" height="64" alt="pixoo_std_Kate_Bush_Running_Up_That_Hill__A_Deal_With_God__Crisp___Sharp" src="https://github.com/user-attachments/assets/f216b36f-2776-4932-aea9-7e54463456f4" /> |

---

## 🔔 Smart Home Notifications Service

The `pixoo64_art.send_notification` action allows Home Assistant automations to display animated pixel-art alerts and sound audible buzzer signals on your Pixoo64.

### ✨ What Makes Version 2.1 Notifications Special:
* **🌐 AWTRIX Hub & LaMetric Ecosystem** — Pass any icon slug from **[AWTRIX Hub](https://awtrix.de/icons)** (e.g., `house-climate`, `btccoin`, `kick`), numeric/animated ID from **[LaMetric](https://developer.lametric.com/icons)** (e.g., `a2710`, `28340`), or any direct image URL.
* **⚡ 2× Doubled Frame Speed** — Native frame timings are extracted from GIF Graphic Control Blocks and WebP ANMF chunks, then doubled automatically for lively, fluid animations on the LED matrix.
* **⏱️ Custom Speed Override** — Pass `anim_speed: 60` (in milliseconds) to customize frame duration directly.
* **💾 Hybrid Persistent Caching** — Icons are saved to local SQLite and disk (`.storage/pixoo64/icons/`). Subsequent triggers render instantly in **0 ms** with zero network delay.
* **🔥 Burned-Text Typography Engine** — Text is rendered onto the 64×64 pixel buffer via Pillow and sent as atomic frames, eliminating hardware font collisions or flickering.
* **👑 Dedicated Bold Title Header** — Renders the `title` in **True Bold** white at the top, cleanly separated from the message underneath (no awkward colons or concatenated strings).
* **📐 Adaptive Icon Sizing (Zero Cutout Guarantee)** — The visual engine dynamically assesses text volume:
  * *Short Messages (1 line)*: Icon scales 2× to **16×16** centered at the top.
  * *Medium Messages (2–3 lines)*: Icon scales to **12×12**.
  * *Dense Messages (4+ lines)*: Icon stays at native **8×8** (compact) in the top header, stepping font size from 8 down to 7 or 6 so text never clips.
* **🌐 Multilingual & Arabic / Hebrew BiDi Support** — Bundles 100% freeware open-source fonts (**DejaVu Sans**, **DejaVu Sans Bold**, and **Noto Sans Arabic**). Automatic bidirectional text ordering (`get_bidi()`) and Arabic cursive letter shaping (`arabic_reshaper`).
* **🎛️ Lovelace Dashboard Card Support** — In `pixoo-media-card`, users can select **Custom AWTRIX Icon** or **Custom LaMetric Icon** and enter any slug or ID with a 1-click **Browse** button.

### 💡 Notification Examples

#### Example 1: Smart Notification with AWTRIX Icon & Buzzer
```yaml
action: pixoo64_art.send_notification
data:
  title: "Climate"
  message: "Living room AC turned on"
  type: "custom"
  icon: "house-climate"      # AWTRIX Hub icon slug (or "awtrix:house-climate")
  duration: 5
  color: "#00DCFF"
  play_buzzer: true
```

#### Example 2: Crypto Alert with LaMetric Animated Icon & Custom Speed
```yaml
action: pixoo64_art.send_notification
data:
  title: "Crypto"
  message: "Bitcoin broke $100k!"
  icon: "a2710"              # LaMetric animated icon ID (or "btccoin")
  anim_speed: 60             # Fast 60ms frame delay override
  duration: 8
  color: "#FFA500"
```

#### Example 3: Standard Home Assistant `notify` Platform
```yaml
action: notify.send_message
target:
  entity_id: notify.pixoo64_media_display_notification
data:
  title: "Front Door"
  message: "Motion detected outside"
  data:
    awtrix_icon: "front-door-icon"
    color: "#32CD32"
    duration: 6
    play_buzzer: true
```

### Action Parameters

| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `message` | string | **Yes** | — | Notification message. English, Hebrew, and Arabic text are automatically aligned with full BiDi support. |
| `title` | string | No | — | Bold header title displayed prominently at the top of the canvas. |
| `icon` | string | No | — | Custom pixel icon: AWTRIX icon slug (e.g. `house-climate`, `btccoin`), LaMetric ID (`a2710`, `28340`), or direct image URL. Browse icons at [AWTRIX Hub](https://awtrix.de/icons) or [LaMetric Gallery](https://developer.lametric.com/icons). |
| `anim_speed` | int | No | Native / 2× | Optional frame delay in ms for animated icons (e.g., `50`–`100`). Defaults to native speed doubled. |
| `type` | string | No | `text` | Icon animation profile (see catalog below) or `custom` for external/AWTRIX/LaMetric icons. |
| `burned_text` | boolean | No | `true` | When true (recommended), renders text directly onto the pixel buffer with freeware typography and bold titles. When false, uses Pixoo hardware font 190. |
| `duration` | int | No | `5` | Display duration in seconds before returning to media art or idle channel. |
| `color` | string | No | Theme default | Custom HEX color code override (e.g., `#FF0055`). |
| `play_buzzer` | boolean | No | `false` | Sound the Pixoo64's onboard hardware buzzer. |
| `buzzer_active` | int | No | `500` | Beep length per cycle in milliseconds. |
| `buzzer_off` | int | No | `500` | Silence duration between beeps in milliseconds. |
| `buzzer_total` | int | No | `3000` | Total buzzer duration in milliseconds. |

### Visual Icon Catalog (40+ Animations)

| Category | Available Animation Profiles |
| :--- | :--- |
| **Community Icons** | `custom` (Pass any [AWTRIX Hub Icon](https://awtrix.de/icons) slug like `house-climate`, `btccoin`, or [LaMetric Icon](https://developer.lametric.com/icons) ID like `a2710`, `28340`, or image URL in `icon`) |
| **System & Alerts** | `text` (clean text banner), `info`, `success`, `warning`, `error`, `v` (checkmark), `x` (cancel), `alert` (animated ringing bell), `alarm` (emergency siren), `attack` (animated rocket) |
| **Smart Home Infrastructure** | `door`, `lock`, `garage`, `shutter`, `boiler`, `ac` (snowflake), `fan`, `light`, `vacuum`, `power`, `home`, `motion`, `fire`, `water` |
| **Domestic Life & Daily Routines** | `washer`, `dryer`, `trash`, `mail`, `coffee`, `package`, `pet` (paw), `plant` (leaf), `car` |
| **Sensors, Hardware & Devices** | `battery`, `wifi` (pulsing waves), `phone` (ringing wiggle), `camera`, `calendar`, `timer` (animated clock hand), `weather` (sun/cloud) |
| **Atmosphere & Music** | `music`, `sun`, `moon` / `sleep` |

---

## 🛠️ Home Assistant Entities & Services Reference

### Entities Created by the Integration

The integration automatically exposes standard, fully documented Home Assistant entities for complete automation control:

| Entity ID Pattern | Domain | Description |
| :--- | :--- | :--- |
| `sensor.pixoo64_status` | `sensor` | Main status sensor reporting active mode, track title, artist, live GIF URL, rank, and lyrics availability. |
| `sensor.pixoo64_analytics` | `sensor` | Dedicated playback analytics sensor reporting total plays, 24h/7d/30d plays, completed albums, and DB size. |
| `select.pixoo64_display_mode` | `select` | Switch between Standard, Vinyl, Cassette, Analog Clock, Lyrics, Burned, Special Mode, Artist Slide, and Force AI. |
| `select.pixoo64_image_filter` | `select` | Switch active image filter (None, Vibrant, Retro Arcade, Crisp & Sharp, Noir B&W, Cyberpunk Neon). |
| `select.pixoo64_crop_mode` | `select` | Switch cropping algorithm (No Crop, Crop, Extra Crop). |
| `select.pixoo64_text_position` | `select` | Position track typography (Bottom, Top, Hidden). |
| `select.pixoo64_overlay_info` | `select` | Configure display overlay (Clock, Temperature, Clock + Temp, None). |
| `select.pixoo64_overlay_position` | `select` | Set overlay vertical alignment (Auto, Top, Bottom). |
| `select.pixoo64_overlay_align` | `select` | Set horizontal overlay alignment (Clock Right, Clock Left, Centered). |
| `select.pixoo64_pause_timeout` | `select` | Inactive pause timeout before screen off or return to channel (0s, 5s, 15s, 30s, 60s, Never). |
| `select.pixoo64_volume_alert_duration` | `select` | Volume HUD display duration (0s, 1s, 2s, 3s, 5s). |
| `switch.pixoo64_master_control` | `switch` | Integration master enable switch. |
| `switch.pixoo64_full_control` | `switch` | Hardware power management (turns screen on when music plays; off when stopped). |
| `switch.pixoo64_progress_bar` | `switch` | Real-time track progress bar overlay toggle. |
| `switch.pixoo64_text_background` | `switch` | Dimmed text backing strip for high-contrast readability. |
| `switch.pixoo64_artwork_race_mode` | `switch` | Parallel API race mode toggle. |
| `number.pixoo64_lyrics_sync_offset` | `number` | Fine-tune synchronized lyrics timing from -10.0s to +10.0s. |
| `button.pixoo64_clear_pixoo_cache` | `button` | Purges persistent master images, artist sliders, pixel icons, and RAM caches on demand. |

---

### Registered Action Services

| Service Name | Description | Key Parameters |
| :--- | :--- | :--- |
| `pixoo64_art.create_chart` | Initiates an animated Hit Parade countdown on the Pixoo64 screen. | `chart_type`, `timeframe`, `period`, `direction`, `limit`, `slide_duration` |
| `pixoo64_art.cancel_chart` | Immediately cancels an active chart countdown and restores artwork or clock. | *(None required)* |
| `pixoo64_art.get_leaderboard` | Returns response data containing the top played tracks, artists, or albums. | `chart_type`, `timeframe`, `period`, `limit` |
| `pixoo64_art.get_analytics` | Returns response data with complete database statistics and metrics. | *(None required)* |
| `pixoo64_art.send_notification` | Displays an animated notification with optional hardware buzzer beeps. | `message`, `title`, `icon`, `anim_speed`, `type`, `duration`, `color`, `play_buzzer` |
| `pixoo64_art.send_command` | Sends a raw or custom command directly to the Pixoo64 HTTP API. | `command`, `payload` |
| `pixoo64_art.clear_cache` | Purges specific scopes of the persistent SQLite and disk storage. | `scope` (`all`, `masters`, `artists`, `analytics`, `icons`) |

#### 💡 Script Example: Querying Leaderboard Response Data

Fetch leaderboard data directly into Home Assistant automations or notifications using `response_variable`:

```yaml
sequence:
  - action: pixoo64_art.get_leaderboard
    data:
      chart_type: "Top Tracks"
      timeframe: "Weekly"
      limit: 5
    response_variable: weekly_chart
  - action: notify.persistent_notification
    data:
      title: "Weekly #1 Track"
      message: "Top track this week is '{{ weekly_chart.items[0].title }}' by {{ weekly_chart.items[0].artist }} ({{ weekly_chart.items[0].play_count }} plays)!"
```

---

## 📦 Installation

### Option 1: Via HACS (Recommended)

1. Open **HACS** from your Home Assistant sidebar.
2. Click the three dots **⋮** in the top right corner and select **Custom repositories**.
3. Paste the repository URL: `https://github.com/idodov/pixoo64_art`
4. Set the category to **Integration** and click **Add**.
5. Locate **Pixoo64 Media Album Art**, click **Download**, and restart Home Assistant.

### Option 2: Manual Installation

1. Download the latest release archive from the [Releases page](https://github.com/idodov/pixoo64_art/releases).
2. Unpack the archive and copy the `pixoo64_art` directory into your Home Assistant custom components folder:
   `config/custom_components/pixoo64_art/`
3. Restart Home Assistant.

---

## ⚙️ Initial Setup & Configuration Flow

Everything is configured directly through the Home Assistant UI — no YAML editing required.

1. Navigate to **Settings ➔ Devices & Services ➔ Add Integration**.
2. Search for **Pixoo64 Media Album Art**.
3. Follow the guided setup steps:

### Step 1 — Hardware & Primary Media Player

| Setting | Parameter Key | Description |
| :--- | :--- | :--- |
| **Pixoo IP Address** | `pixoo_ip` | Select the auto-discovered Pixoo64 or enter its static LAN IP address manually. |
| **Media Player Entity** | `media_player` | The primary media player to track (e.g., `media_player.spotify`, Sonos, Apple TV, Google Cast, Plex). |
| **Temperature Sensor** | `temperature_entity` | *Optional.* Any Home Assistant temperature sensor to display live temperature overlays. |

### Step 2 — Ambient Lighting & Smart TV Mode

| Setting | Parameter Key | Description |
| :--- | :--- | :--- |
| **Ambient Lights** | `light_entity` | One or more RGB/RGBW smart lights that dynamically mirror dominant album art colors. |
| **WLED Controller IP** | `wled_ip` | Addressable WLED light strip synchronized with dominant artwork color accents in real time. |
| **Only at Night** | `only_at_night` | Restricts ambient light synchronization to hours between sunset and sunrise (`sun.sun`). |
| **Intelligent TV Mode** | `tv_mode` | Automatically switches to a vintage TV graphic and color bars when video apps or HDMI-ARC sources are active. |

### Step 3 — Metadata APIs, Search & AI Art

| Setting | Parameter Key | Description |
| :--- | :--- | :--- |
| **Artwork Race Mode** | `artwork_race_mode` | Fires multiple metadata queries simultaneously and renders whichever finishes first. *(Requires at least one external API key).* |
| **MusicBrainz** | `musicbrainz_enabled` | Open-source Cover Art Archive lookups with built-in rate-limit governance. |
| **Internet Archive** | `internet_archive_enabled` | Metadata and artwork lookups from archive.org. |
| **Pollinations AI** | `pollinations_key` | Optional API key enabling generative conceptual artwork for bootlegs or unmapped tracks. |
| **AI Model** | `ai_model` | Preferred generative image model (e.g., `flux.1-schnell`, `turbo`). |
| **Spotify Credentials** | `spotify_client_id`, `spotify_client_secret` | Free developer credentials for fast high-res artwork search and the animated *Spotify Slider* carousel. |
| **TIDAL Credentials** | `tidal_client_id`, `tidal_client_secret` | Free developer credentials for catalogue artwork resolution. |
| **Last.fm / Discogs** | `lastfm_key`, `discogs_token` | Personal developer tokens for vinyl release covers and B-side matching. |

> [!TIP]
> All settings can be adjusted at any time via **Settings ➔ Devices & Services ➔ Pixoo64 Media Album Art ➔ Configure**.

---

## ❓ Frequently Asked Questions (FAQ)

### 🔌 Setup, Connectivity & Power Controls

<details>
<summary><strong>🌐 Does this integration require an internet connection?</strong></summary>

<br>

**Not for core playback.** Communication between Home Assistant and your Pixoo64 takes place entirely over your local Wi-Fi network (LAN HTTP POST).

Internet connectivity is only utilized when fetching external assets from online providers (Spotify, TIDAL, Discogs, Last.fm, MusicBrainz, TheAudioDB, LRCLIB lyrics, AWTRIX Hub, LaMetric, or Pollinations AI).

</details>

<details>
<summary><strong>📡 How do I set a static IP for my Pixoo64?</strong></summary>

<br>

Assign a **DHCP reservation** for your Pixoo64 within your router's administration interface to prevent its local LAN IP address from shifting over time.

</details>

<details>
<summary><strong>🎛️ What is the difference between "Master Control" and "Full Control"?</strong></summary>

<br>

* **Master Control (Software Loop Switch):** The primary master switch for the integration. Turning it off stops artwork processing, lyrics queries, and display updates. The Pixoo64 remains powered on and reverts immediately to your default Divoom channel (Clock, Cloud, or Custom).
* **Full Control (Hardware Power Ownership):** When enabled, the integration manages hardware screen power directly. When playback starts, it automatically turns the LED display on; when music stops, it turns the screen completely off (black).

</details>

<details>
<summary><strong>🛡️ Will the Pixoo64 get stuck on a black screen when music finishes?</strong></summary>

<br>

**No.** The integration incorporates a dedicated **Channel Memory & Fail-Safe Engine**. When music starts, the integration saves your active Divoom channel (0=Clock, 1=Cloud, 2=Visualizer, 3=Custom). Channel 4 (the internal HTTP GIF receiver) is strictly filtered out and never saved. When music stops or the pause timer expires, the integration safely restores your original channel or turns off the screen per your configuration.

</details>

---

### 🔔 Smart Notifications & Icons

<details>
<summary><strong>🔔 How do I find and use icons for notifications?</strong></summary>

<br>

You can pass icons from multiple sources into the `icon` parameter:

* **[AWTRIX Hub](https://awtrix.de/icons)**: Copy any icon slug (e.g. `house-climate`, `btccoin`, `kick`, `partly-cloudy-2`) and pass `icon: "house-climate"` (or `icon: "awtrix:house-climate"`).
* **[LaMetric Icon Gallery](https://developer.lametric.com/icons)**: Copy any icon ID (e.g. `a2710` for animated, `28340` for static) and pass `icon: "a2710"`.
* **Direct Image URLs**: Any direct link to a `.gif`, `.png`, or `.webp` image.
* **Animation Speed**: Native frame speeds are extracted and automatically doubled for lively, snappy playback on the LED matrix. You can also override speed manually with `anim_speed: 60`.
* **Instant Caching**: Icons are cached locally in SQLite and disk (`.storage/pixoo64/icons/`) after their first display. Repeated triggers load in **0 ms**.

</details>

---

### 🏆 Hit Parade Charts & Analytics

<details>
<summary><strong>📈 When does a song count as a "play" (scrobble)?</strong></summary>

<br>

To ensure accurate leaderboards, the analytics engine scrobbles a song only after it has played continuously for **at least 30 seconds** (or 50% of its duration for very short tracks). Skipping through tracks quickly will not pollute your statistics.

</details>

<details>
<summary><strong>📀 How does the engine detect "Completed Albums"?</strong></summary>

<br>

The session controller inspects your media player's queue and track numbering. When you play through an album's tracks consecutively, the engine records an **Album Completion Event** in the database. You can view your most completed albums and EPs in the Hit Parade charts.

</details>

<details>
<summary><strong>📅 Can I customize the first day of the week for weekly charts?</strong></summary>

<br>

Yes. Under **Settings ➔ Devices & Services ➔ Pixoo64 ➔ Configure ➔ Persistent Cache & Playback Analytics**, you can select whether weekly chart boundaries calculate from **Sunday to Saturday** (default) or **Monday to Sunday**.

</details>

---

### 🔑 APIs, Accounts & Privacy

<details>
<summary><strong>🎵 Do I need a music subscription or specific streaming service?</strong></summary>

<br>

**No.** The integration works with local audio files, DLNA shares, internet radio, and any media player platform. As long as your player provides standard track metadata (Title and Artist), the fallback engine will resolve and render matching cover art.

</details>

<details>
<summary><strong>💸 Do I need to pay for external API keys?</strong></summary>

<br>

**No.** The integration is completely free to operate:
* **Zero-config open APIs:** MusicBrainz, Internet Archive, TheAudioDB, and LRCLIB operate without any API keys.
* **Free developer accounts:** Spotify, TIDAL, Last.fm, and Discogs provide free developer API access without requiring paid subscription plans.

</details>

<details>
<summary><strong>🌊 How does the multi-tier Fallback Waterfall operate?</strong></summary>

<br>

When a song begins, the integration evaluates metadata through this structured sequence:

```text
[Media Player Active]
         │
         ▼
 1. Local HA Artwork (RAM Cache) ─────────(Found)─► Render immediately (0ms)
         │ (Missing)
         ▼
 2. Persistent Master Cache (SQLite) ─────(Found)─► Render from local storage
         │ (Missing)
         ▼
 3. Spotify Search API ──────────────────(Found)─► Render 640×640 artwork / Slider
         │ (Missing)
         ▼
 4. TIDAL / Discogs / Last.fm ───────────(Found)─► Render high-res release cover
         │ (Missing)
         ▼
 5. MusicBrainz / Internet Archive ──────(Found)─► Render Cover Art Archive image
         │ (Missing)
         ▼
 6. TheAudioDB ──────────────────────────(Found)─► Render Artist Gallery portrait
         │ (Missing)
         ▼
 7. Pollinations AI (if configured) ─────(Active)► Generate conceptual artwork
         │ (Disabled / unconfigured)
         ▼
 8. Geometric Canvas Fallback ───────────────────► Clean minimalist layout
```

</details>

---

### 🎤 Synchronized Lyrics & Performance

<details>
<summary><strong>🎤 How does the Synced Lyrics mode work?</strong></summary>

<br>

Synced lyrics are retrieved via LRCLIB based on track title, artist, and duration. 

In Version 2.0+, lyrics queries run **asynchronously in the background**. Album art and song titles display immediately on the Pixoo64 without waiting for remote network responses. If lyrics are discovered, the Lovelace card illuminates an active green lyrics indicator, and the screen smoothly transitions into lyrics mode with an automated background dimming filter.

</details>

<details>
<summary><strong>📻 Are lyrics supported on live internet radio streams?</strong></summary>

<br>

No. Synced lyrics require frame-accurate time tracking against a known track duration. Continuous live radio broadcasts do not provide fixed playback timelines.

</details>

<details>
<summary><strong>⏱️ Can I adjust the synchronization timing of the lyrics?</strong></summary>

<br>

Yes. Audio processing delays (such as Bluetooth or multi-room AirPlay buffers) can be corrected using the **Lyrics Sync Offset** number entity in Home Assistant or directly on your dashboard (e.g., `+1.5s` or `-2.0s`).

</details>

<details>
<summary><strong>🚀 How does Playlist Prefetch eliminate track transition delay?</strong></summary>

<br>

With **Playlist Prefetch** enabled, the integration inspects your media player's queue and downloads, crops, and processes upcoming album covers into RAM *before* the current song ends. When the next track starts, its visual frame is already processed and sends immediately with 0ms delay.

</details>

---

## 🛠️ Diagnostics & Troubleshooting

* **Enable Verbose Logging:** Add the following snippet to your `configuration.yaml` and restart Home Assistant to inspect the real-time telemetry stream:
  ```yaml
  logger:
    default: info
    logs:
      custom_components.pixoo64_art: debug
  ```
* **Network Connectivity:** Ensure your Pixoo64 is assigned to a stable 2.4 GHz Wi-Fi network and that local HTTP traffic on port 80 is not blocked by VLAN isolation rules.
* **Issue Reporting:** Encountering unexpected behavior? Please [open an issue on GitHub](https://github.com/idodov/pixoo64_art/issues) and include your diagnostics information, Home Assistant version, and media player model.

---

## 🤝 Contributing

Contributions, feature ideas, and pull requests are warmly welcomed:

1. Fork the repository.
2. Create your dedicated feature branch: `git checkout -b feature/NewFeature`
3. Commit your changes: `git commit -m "Add NewFeature"`
4. Push to your branch: `git push origin feature/NewFeature`
5. Submit a Pull Request.

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](https://github.com/idodov/pixoo64_art/blob/main/LICENSE) for full details.

---

## 🌟 Acknowledgments

* [Divoom](https://www.divoom.com/) — for the Pixoo64 64×64 LED matrix hardware.
* [Blueforcer](https://github.com/Blueforcer) & [AWTRIX Hub](https://awtrix.de/) — for the community pixel icon repository and matrix firmware ecosystem.
* [LaMetric](https://lametric.com/) & [LaMetric Developer](https://developer.lametric.com/icons) — for the extensive library of community pixel art and animations.
* [LRCLIB](https://lrclib.net/) — for the free, open-source synced lyrics API.
* [TheAudioDB](https://www.theaudiodb.com/) — for artist portraits and fanart databases.
* [MusicBrainz](https://musicbrainz.org/) & [Cover Art Archive](https://coverartarchive.org/) — for open music metadata.
* [Pollinations.ai](https://pollinations.ai/) — for generative AI art APIs.
* The [Home Assistant Community](https://community.home-assistant.io/) — for continuous feedback, testing, and creative ideas.
