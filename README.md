# 🎨 Pixoo64 Media Album Art for Home Assistant

<p align="center">

  <a href="https://www.home-assistant.io/"><img src="https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blueviolet.svg?style=for-the-badge&logo=home-assistant" alt="Home Assistant"></a>
  <a href="https://hacs.xyz/"><img src="https://img.shields.io/badge/HACS-Custom%20Repo-orange.svg?style=for-the-badge&logo=hacs" alt="HACS"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge" alt="License: MIT"></a>
  <a href="https://github.com/idodov/pixoo64_art/issues"><img src="https://img.shields.io/github/issues/idodov/pixoo64_art?style=for-the-badge&color=red" alt="GitHub Issues"></a>
</p>

<p align="center">
  <strong>Transform your Divoom Pixoo64 into an intelligent, adaptive media display, live volume HUD, and smart home visual alert center.</strong>
</p>

<p align="center">
  <img src="https://github.com/idodov/pixoo64-media-album-art/assets/19820046/71348538-2422-47e3-ac3d-aa1d7329333c" alt="PIXOO_album_gallery" width="85%" style="border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.3);"/>
</p>

---

## 📖 Overview

**Pixoo64 Media Album Art** brings native, studio-grade album art rendering to your **Divoom Pixoo64** 64×64 LED matrix directly through Home Assistant.

Originally developed as an AppDaemon application, this project has been completely re-architected into a **100% native Home Assistant custom integration**:
* **No AppDaemon required:** Runs directly within Home Assistant’s native asynchronous event loop.
* **100% UI Configured:** Automatic LAN device discovery and full interactive setup through the Home Assistant UI (Config Flow & Options Flow).
* **Direct LAN Communication:** Communicates directly with the Pixoo64 over local HTTP REST—instant, reliable, and completely cloud-independent for core playback.
* **Multi-Purpose Visual Hub:** Displays high-contrast album art, real-time volume feedback, retro TV mode, synchronized lyrics, ambient room light mirroring, and animated visual notifications with hardware buzzer support.

---

## ✨ Features at a Glance

| Feature | Description |
| :--- | :--- |
| 🖼️ **Adaptive Crop Engine** | **Standard Crop** trims black/white margins while keeping typography; **Extra Crop** unwraps nested color stripes (e.g. *Sweet Dreams*), unites multi-person subjects (e.g. *Pet Shop Boys*), and frames minimalist text (e.g. *Brat*). |
| 🔊 **Real-Time Volume HUD** | Detects volume changes on your AVR, soundbar, or media player and temporarily renders an instant, high-visibility volume level indicator. |
| 📺 **Intelligent TV Mode** | Detects HDMI-ARC, streaming apps (Netflix, YouTube, Disney+), and live TV sources, displaying a handcrafted retro pixel-art television with antennas and SMPTE test bars. |
| 🌊 **Multi-Tier Fallback** | When artwork is missing, it queries: **Local HA ➔ Spotify ➔ MusicBrainz ➔ TIDAL ➔ Last.fm ➔ Discogs ➔ Pollinations AI ➔ Minimalist Slate**. |
| 🎤 **Live Synced Lyrics** | Live `.lrc` lyrics via LRCLIB with event-driven timing, smart line wrapping, millisecond calibration, and native BiDi (Hebrew / Arabic RTL) layout. |
| 💡 **Ambient Lighting Sync** | Extracts primary album colors in real time and synchronizes **Home Assistant RGB lights** and **WLED fixtures** (with night-only filters). |
| 🔔 **Animated Visual Alerts** | 30+ animated pixel icons (doorbell, laundry, climate, security) with onboard **Pixoo hardware buzzer** chime integration. |

---

## 📺 Deep-Dive: Intelligent TV Mode

Streaming devices and modern smart TVs connected via HDMI eARC often populate media players with metadata like `"TV"`, `"Audio Return Channel"`, or streaming app names rather than music tracks. 

The integration includes an intelligent **TV Mode engine**:

1. **Automatic TV Detection:**  
   Monitors `media_title`, `media_artist`, `app_name`, `source`, and `media_channel`. It immediately recognizes inputs such as:
   * **HDMI Inputs:** eARC, ARC, Audio Return Channel, TV audio.
   * **Streaming Platforms:** Netflix, YouTube, Disney+, Prime Video, Apple TV, Live TV.
2. **Dedicated Visual Display (`TV_IS_ON_ICON`):**  
   When TV Mode is active, music-specific features (progress bars, synced lyrics, and Spotify carousels) are automatically suspended. Instead, the screen renders an authentic **Retro Color-Bar Television**:
   * A classic wood-grain rounded TV cabinet with top dual rabbit-ear antennas and screen reflections.
   * A 7-bar SMPTE rainbow test screen (`Red`, `Orange`, `Yellow`, `Green`, `Blue`, `Indigo`, `Violet`).
3. **Adaptive Mode:**  
   Toggle TV Mode on or off in the integration options to match your setup.

---

## 🔊 Deep-Dive: Dynamic Volume HUD Effect

When you adjust the volume on your receiver, soundbar, or TV remote, looking at a small receiver display across the room can be difficult. 

The integration tracks volume changes in real time:
* **Instant Visual Feedback:** The moment the `volume_level` attribute changes on your tracked media player, the Pixoo temporarily displays a high-visibility volume level HUD overlay.
* **Auto-Revert:** Once volume adjustment stops, the display smoothly returns to the current album artwork or live lyrics without skipping a beat.

---

## 🎵 Deep-Dive: MusicBrainz & Cover Art Archive

For music purists, offline CD rips, and vinyl collectors, the integration includes native integration with **MusicBrainz** and the **Internet Archive's Cover Art Archive**:

* **Zero API Key Required:** Completely free and open-source.
* **Intelligent Querying:** Queries releases by exact artist and track name using strict metadata filtering.
* **Rate-Limit Resilient:** Features a built-in rate-limiting governor compliant with MusicBrainz API policies (1 request per second) to prevent IP throttling.
* **Front Cover Priority:** Automatically pulls verified `250px` high-quality front cover art directly from the archive.

---

## 📐 The Crop Engine: Standard vs. Extra Crop

Pixoo's 64×64 LED resolution requires specialized image composition. The integration offers two intelligent cropping algorithms:

* **Standard Crop:** Trims outer black letterboxing, white scanner margins, and pillarbox bars while preserving full album sleeves and typography.
* **Extra Crop (Subject Isolation):**
  * **Nested Container Unwrapping:** Detects when an album has a colored vertical band or card (e.g. *Eurythmics - Sweet Dreams*) and extracts the inner photo without border bleed.
  * **Subject Clustering:** Detects two or more adjacent subjects (e.g. *Pet Shop Boys - Please*) and groups them together into a unified square, preventing two-person shots from being sliced in half.
  * **Typographic Framing:** Automatically detects minimalist covers (e.g. *Charli XCX - Brat*) and frames the text with balanced negative space rather than collapsing on hollow letter loops.

---

## 🔄 Media Art Fallback Waterfall

Never face an empty display when listening to streaming radio, Cast devices, or local files. The integration follows an automatic waterfall recovery sequence:

```
[Media Player Playing]
         │
         ▼
 1. Local HA Art Present? ─────(Yes)───► [Render Cover Art]
         │ (No)
         ▼
 2. Spotify Search API ────────(Found)─► [Render 640x640 Art]
         │ (Missing)
         ▼
 3. Discogs / Last.fm / TIDAL ─(Found)─► [Render Hi-Res Match]
         │ (Missing)
         ▼
 4. MusicBrainz Archive ───────(Found)─► [Render CoverArtArchive]
         │ (Missing)
         ▼
 5. Pollinations AI ───────────(Active)► [Generate Conceptual Art]
         │ (Disabled / No Key)
         ▼
 6. Internal Geometric Canvas ─────────► [Minimalist Burned Slate]
```

---

## 📦 Installation

### Option 1: Via HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=idodov&repository=pixoo64_art&category=integration)

1. Open **HACS** in your Home Assistant sidebar.
2. Click the **three dots** in the top right corner and select **Custom repositories**.
3. Paste repository: `https://github.com/idodov/pixoo64_art`
4. Choose Category: **Integration**.
5. Click **Add**, locate **Pixoo64 Media Album Art**, click **Download**, and restart Home Assistant.

### Option 2: Manual Installation

1. Download the latest release `.zip` from the [Releases Page](https://github.com/idodov/pixoo64_art/releases).
2. Extract the folder into your Home Assistant directory:
   ```
   config/custom_components/pixoo64_art/
   ```
3. Restart Home Assistant.

---

## ⚙️ Initial Configuration (UI Config Flow)

All settings are configured through the native Home Assistant user interface—no YAML required!

1. Navigate to **Settings** > **Devices & Services** > **Add Integration**.
2. Search for **Pixoo64 Media Album Art**.
3. Complete the interactive setup:

### Step 1: Device & Media Source
* **Pixoo IP (`pixoo_ip`):** Choose your automatically discovered Pixoo64 or enter its LAN IP manually.
* **Media Player (`media_player`):** Select your target media player entity (`media_player.living_room`, Sonos, Apple TV, Cast, etc.).
* **Temperature Sensor (`temperature_entity`):** Optional. Link any temperature sensor entity to render live room or outdoor temps.

### Step 2: Ambient Lighting & TV Display
* **Light Entities (`light_entity`):** Choose one or more RGB/RGBW lights to mirror dominant album colors.
* **WLED IP (`wled_ip`):** Synchronize an addressable WLED strip with real-time album colors.
* **Only at Night (`only_at_night`):** Restricts ambient lighting automations to hours after sunset.
* **TV Mode (`tv_mode`):** Enable/disable automatic switching to the retro TV icon and test pattern when TV sources, streaming apps, or HDMI-ARC are playing.

### Step 3: Metadata APIs, MusicBrainz & AI Art
* **MusicBrainz (`musicbrainz_enabled`):** Enable or disable free open-source Cover Art Archive lookups (enabled by default, zero API key required).
* **Pollinations AI Key (`pollinations_key`):** Enter your API key to generate prompt-based conceptual artwork when tracks lack cover art.
* **AI Model (`ai_model`):** Select your preferred generative image model (e.g. `black-forest-labs/flux.1-schnell`, `turbo`, `lightning`, `vector`).
* **Spotify Credentials (`spotify_client_id` & `spotify_client_secret`):** Enables high-res art lookups and multi-album animation carousels.
* **TIDAL Credentials (`tidal_client_id` & `tidal_client_secret`):** TIDAL Developer credentials for lossless catalogue artwork.
* **Last.fm Key (`lastfm_key`):** Personal API key for album art search.
* **Discogs Token (`discogs_token`):** Personal access token for vinyl and release art search.

> 💡 **Reconfiguration:** Every setting can be updated at any time by clicking **Configure** on the integration card in **Settings > Devices & Services**.

---

## 🔔 Smart Notifications Service

The `pixoo64_art.send_notification` action allows Home Assistant automations to display animated alerts and play sound effects on the Pixoo64. Notifications pause media rendering, display a high-contrast black canvas with custom pixel art, trigger the hardware buzzer, and automatically restore your artwork when finished.

```yaml
action: pixoo64_art.send_notification
data:
  message: "Washing cycle finished!"
  type: "washer"
  duration: 8
  play_buzzer: true
  buzzer_active: 400
  buzzer_off: 200
  buzzer_total: 2400
```

### Parameters

| Key | Type | Required | Default | Description |
| :--- | :---: | :---: | :---: | :--- |
| `message` | string | **Yes** | — | Notification body (supports automatic English, Hebrew, and Arabic bi-directional layout). |
| `type` | string | No | `text` | The visual theme and animation profile (see catalog below). |
| `duration` | int | No | `5` | Display duration in seconds before returning to media art. |
| `color` | string | No | Theme Default | Custom HEX color override (e.g., `#FF0055`). |
| `play_buzzer` | boolean | No | `false` | Trigger the Pixoo64 onboard acoustic buzzer. |
| `buzzer_active`| int | No | `500` | Beep duration in milliseconds per cycle. |
| `buzzer_off` | int | No | `500` | Silence duration in milliseconds between beeps. |
| `buzzer_total` | int | No | `3000` | Total buzzer duration in milliseconds. |

### Visual Icon Catalog

* **Alerts & Status:** `text` (Pure text), `info`, `success`, `warning`, `error`, `v` (Checkmark), `x` (Cancel), `alert` (Animated bell), `attack` (Animated rocket).
* **Smart Home:** `door`, `lock`, `boiler`, `shutter`, `washer`, `car`, `trash`, `mail`, `fire`, `water`.
* **Hardware & Sensors:** `battery`, `wifi` (Animated waves), `phone` (Animated wiggle), `camera`, `calendar`, `timer` (Animated clock hand), `weather` (Sun and cloud).
* **Ambience:** `music`, `sun`, `moon` / `sleep`.

---

## 💡 Automation Recipes

### 1. Smart Doorbell with Buzzer Chime
```yaml
alias: "Pixoo - Front Doorbell Alert"
trigger:
  - platform: state
    entity_id: binary_sensor.doorbell_ringing
    to: "on"
action:
  - action: pixoo64_art.send_notification
    data:
      message: "Visitor at Front Door"
      type: "door"
      duration: 6
      play_buzzer: true
      buzzer_active: 250
      buzzer_off: 150
      buzzer_total: 1200
```

### 2. Washer / Dryer Cycle Complete
```yaml
alias: "Pixoo - Laundry Alert"
trigger:
  - platform: state
    entity_id: sensor.washing_machine_status
    to: "finished"
action:
  - action: pixoo64_art.send_notification
    data:
      message: "Laundry is done!"
      type: "washer"
      duration: 10
      play_buzzer: true
      buzzer_active: 500
      buzzer_off: 500
      buzzer_total: 3000
```

### 3. Critical Leak / Flood Warning
```yaml
alias: "Pixoo - Water Leak Alert"
trigger:
  - platform: state
    entity_id: binary_sensor.kitchen_leak_sensor
    to: "on"
action:
  - action: pixoo64_art.send_notification
    data:
      message: "Water leak detected in kitchen!"
      type: "water"
      color: "#FF0000"
      duration: 15
      play_buzzer: true
      buzzer_active: 200
      buzzer_off: 100
      buzzer_total: 5000
```

---

## ❓ Frequently Asked Questions (FAQ)

<details>
<summary><strong>Q: Where do I get API keys for all the supported services?</strong></summary>

Here are the direct links to obtain developer credentials for every supported metadata provider:

* **Spotify (Client ID & Client Secret):**  
  👉 [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)  
  *Log in with your Spotify account, click "Create an App", set the Redirect URI to `https://localhost`, and copy your Client ID and Client Secret.*

* **Pollinations AI (API Key):**  
  👉 [Pollinations.ai Dashboard](https://enter.pollinations.ai/)  
  *Sign in to generate your API key for prompt-based conceptual artwork generation.*

* **Discogs (Personal Access Token):**  
  👉 [Discogs Developer Settings](https://www.discogs.com/settings/developers)  
  *Sign in, scroll to "User Tokens", and click "Generate new token".*

* **Last.fm (API Key):**  
  👉 [Last.fm API Account Creation](https://www.last.fm/api/account/create)  
  *Fill in an application name and description to receive an instant 32-character API key.*

* **TIDAL (Client ID & Client Secret):**  
  👉 [TIDAL Developer Portal](https://developer.tidal.com/)  
  *Log in with your TIDAL account to access your developer dashboard and create client-credentials keys.*

* **MusicBrainz & Cover Art Archive:**  
  👉 [MusicBrainz](https://musicbrainz.org/) & [Cover Art Archive](https://coverartarchive.org/)  
  * **No key or token required!** Completely free and open-source. The integration handles compliant rate-limiting automatically.
</details>

<details>
<summary><strong>Q: Does this integration require an internet connection?</strong></summary>

> **No, for local playback.** Communication between Home Assistant and the Pixoo64 happens entirely over your local area network (LAN HTTP POST). 
> 
> Internet access is only required if you use online fallback providers (Spotify, MusicBrainz, TIDAL, LRCLIB lyrics, or Pollinations AI).
</details>

<details>
<summary><strong>Q: How does TV Mode detect that my TV is playing?</strong></summary>

> The integration monitors your media player's attributes. If `app_name`, `media_title`, `source`, or `channel` matches keywords like `TV`, `Netflix`, `YouTube`, `Disney+`, `Audio Return Channel`, or `eARC`, it automatically switches to TV mode and draws the custom retro TV icon, turning off music progress bars and lyrics.
</details>

<details>
<summary><strong>Q: How does the volume effect work?</strong></summary>

> The integration monitors changes to the `volume_level` attribute on your linked media player entity. When you adjust the volume using a remote, soundbar, or app, the Pixoo64 immediately renders a temporary high-visibility volume HUD overlay before returning to the active artwork.
</details>

<details>
<summary><strong>Q: Why are Hebrew or Arabic lyrics/text displayed correctly without reversing?</strong></summary>

> The integration includes an internal Bidirectional (BiDi) layout algorithm. Text containing Hebrew or Arabic characters is parsed and formatted for Right-to-Left (RTL) reading order before rendering to the Pixoo LED matrix.
</details>

<details>
<summary><strong>Q: How does Extra Crop handle albums with white stripes or minimalist typography?</strong></summary>

> Extra Crop uses an advanced computer vision pipeline:
> 1. **Container Unwrapping:** Unwraps secondary background containers (like the white vertical stripe in *Sweet Dreams*) to isolate the photograph inside.
> 2. **Subject Clustering:** Groups adjacent figures (like Neil Tennant and Chris Lowe in *Pet Shop Boys*) so multi-person shots are kept together.
> 3. **Hollow Center Immunity:** Scans from boundary windows inwards, preventing typography (like *Charli XCX - Brat*) from collapsing when the geometric center of a word is empty space.
</details>

<details>
<summary><strong>Q: How do I set a static IP for my Pixoo64?</strong></summary>

> It is strongly recommended to assign a permanent **DHCP Reservation** for your Pixoo64 within your home router's admin settings to ensure its LAN IP address never changes.
</details>

---

## 🛠️ Diagnostics & Troubleshooting

* **Logs:** If you encounter unexpected behavior, add the following to your `configuration.yaml` and restart Home Assistant:
  ```yaml
  logger:
    default: info
    logs:
      custom_components.pixoo64_art: debug
  ```
* **Network Timeouts:** Ensure your Pixoo64 is connected to a stable 2.4 GHz Wi-Fi network and that port `80` is not filtered between your Home Assistant instance and the Pixoo.

---

## 🤝 Contributing

Contributions, feature requests, and bug reports are welcome!
1. Fork the Project.
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`).
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`).
4. Push to the Branch (`git push origin feature/AmazingFeature`).
5. Open a Pull Request.

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for more information.

---

## 🌟 Acknowledgments

* [Divoom](https://www.divoom.com/) for building the Pixoo64 hardware.
* [LRCLIB](https://lrclib.net/) for providing a free, open-source synced lyrics API.
* [MusicBrainz](https://musicbrainz.org/) & [Cover Art Archive](https://coverartarchive.org/) for open metadata.
* [Pollinations.ai](https://pollinations.ai/) for accessible generative AI art APIs.
* The [Home Assistant Community](https://community.home-assistant.io/) for continuous testing and feedback.

