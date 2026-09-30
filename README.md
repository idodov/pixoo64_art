# 🎨 Pixoo64 Media Album Art for Home Assistant

[![Current Version](https://img.shields.io/badge/version-1.0.0-blue.svg?style=for-the-badge)](https://github.com/idodov/pixoo64_art)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blueviolet.svg?style=for-the-badge&logo=home-assistant)](https://www.home-assistant.io/)
[![HACS Default](https://img.shields.io/badge/HACS-Custom%20Repo-orange.svg?style=for-the-badge&logo=hacs)](https://hacs.xyz/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

Transform your **Divoom Pixoo64** into an intelligent, responsive, high-end media dashboard directly integrated into Home Assistant. 

Originally created as an AppDaemon application is now a fully native Home Assistant custom integration: **no AppDaemon required**, featuring one-click UI setup (Config Flow), automatic LAN device discovery, dynamic dashboard controls, real-time synchronized lyrics, ambient room lighting sync, and an animated notification engine with onboard buzzer support.

---

## ✨ Features at a Glance

* 🖼️ **High-Precision Image Processing:** Dynamic resizing, aspect-ratio correction, color quantization, and smart edge-cropping tailored for the 64x64 LED matrix.
* 🧠 **Multi-Tier Fallback Waterfall:** If your media player lacks cover art (e.g. streaming radio, local files), art is seamlessly fetched from **Spotify**, **MusicBrainz**, **TIDAL**, **Last.fm**, **Discogs**, or generated on the fly via **Pollinations AI**.
* 🎤 **Live Synced Lyrics Engine:** Fetches synced `.lrc` lyrics via LRCLIB with event-driven scheduling, smart multi-line wrapping, bidirectional (RTL) language rendering (Hebrew / Arabic), and millisecond time-offset calibration.
* 📊 **Smooth Dual-Layer Progress Bar:** Real-time visual track progress bar with automatic contrast color matching.
* 💡 **Ambient Lighting Sync:** Real-time color extraction that maps the album's primary palette to **Home Assistant RGB lights** and **WLED fixtures** (effects, speeds, and nighttime-only filters).
* 🔔 **Animated Interrupt Notifications:** Interrupt media to display animated alerts (alarms, smart doorbells, washer/dryer alerts, weather, boiler) complete with Pixoo hardware buzzer acoustic chimes.
* 🎛️ **Full Dashboard Control:** Every setting (crop type, clock/temperature overlay, text placement, AI toggle) is exposed as a native switch, select, or number entity.

---

## 📦 Installation

### Option 1: Via HACS (Recommended)

1. Open **HACS** in your Home Assistant instance.
2. Click the three dots in the top-right corner and select **Custom repositories**.
3. Paste the repository URL: `https://github.com/idodov/pixoo64_art`
4. Choose **Integration** as the category and click **Add**.
5. Find **Pixoo64 Media Album Art** in the integration list, click **Download**, and restart Home Assistant.

### Option 2: Manual Installation

1. Download the latest release `.zip` from GitHub.
2. Extract and copy the `pixoo64_art` folder into your Home Assistant directory:  
   `<config>/custom_components/pixoo64_art/`
3. Restart Home Assistant.

---

## ⚙️ Initial Configuration (Config Flow)

No YAML configuration needed! Everything is handled via the Home Assistant UI:

1. Go to **Settings** > **Devices & Services** > **Add Integration**.
2. Search for **Pixoo64 Media Album Art**.
3. **Step 1: Device & Media Player**
   * **Pixoo IP:** Select your automatically discovered Pixoo64 from the LAN list or choose *Manual Entry*.
   * **Media Player:** Select the target `media_player` entity to track.
   * **Temperature Sensor (Optional):** Select a temperature sensor entity to render local temps.
4. **Step 2: Ambient Lighting Sync (Optional)**
   * **Light Entities:** Choose one or more RGB lights to sync with dominant album colors.
   * **WLED IP:** Enter the IP address of a WLED controller to mirror palette and effects.
   * **Only at Night:** Restrict lighting changes to hours when the sun is below the horizon.
5. **Step 3: External APIs & Metadata Providers (Optional)**
   * **AI Generation:** Choose your model (Flux, Turbo, GPT 1.5, Gemini, etc.) and enter your [Pollinations AI Key](https://enter.pollinations.ai/keys).
   * **MusicBrainz:** Toggle open-source cover art queries.
   * **Spotify API:** Enter Client ID & Secret for high-res art and animated gallery modes.
   * **TIDAL / Last.fm / Discogs:** Add API keys for maximum fallback redundancy.

> 💡 **Reconfiguration:** All API credentials, light targets, and temperature sensors can be reconfigured anytime by clicking **Configure** on the integration card.

---

## 🎛️ Dashboard Controls & Entity Reference

When configured, the integration creates a Home Assistant Device exposing the following entities:

### 🔘 Switches

| Entity Name | Entity ID | Description |
| :--- | :--- | :--- |
| **Pixoo64 Master Control** | `switch.pixoo64_master_control` | Master On/Off switch for the integration. Turning this off clears text and gracefully turns off/restores the screen. |
| **Pixoo64 Full Control** | `switch.pixoo64_full_control` | When enabled, turns the Pixoo screen completely off when media stops. When disabled, restores the previous clock/channel. |
| **Pixoo64 Progress Bar** | `switch.pixoo64_progress_bar` | Toggles the dual-layer pseudo-bold track progress bar at the bottom of the screen. |
| **Pixoo64 Force AI Art** | `switch.pixoo64_force_ai` | Bypasses original cover art and generates custom conceptual AI art for every playing song. |
| **Pixoo64 Text Background** | `switch.pixoo64_text_background` | Adds an automatic dimmed background behind text and overlay zones to guarantee readability on bright covers. |

---

### 🎚️ Selects (Display & Layout)

#### 1. Display Mode (`select.pixoo64_display_mode`)
* **Standard:** Standard high-contrast cover art with optional overlays (clock, temperature, title).
* **Lyrics:** Full-screen live synchronized lyrics fetched from LRCLIB with event-based timing.
* **Burned:** Burns the artist and title directly into the image canvas using contrasting typography.
* **Special Mode:** Elegant centered mini-album art framed inside dynamic background gradients.
* **Spotify Slider:** *(Available when Spotify credentials are provided)* Cycles animated album variants and artist profiles in a smooth gallery animation.

#### 2. Artist & Track Text (`select.pixoo64_artist_track_text`)
* **Bottom:** Displays scrolling text along the bottom row (Y: 48).
* **Top:** Displays scrolling text along the top row (Y: 0).
* **Hidden:** Hides title and artist text completely for pure, unobstructed album art.

#### 3. Overlay Info (`select.pixoo64_overlay_info`)
* **None:** Disables the overlay layer entirely.
* **Clock:** Displays real-time digital clock.
* **Temperature:** Displays live temperature from the linked sensor.
* **Clock + Temp:** Renders both clock and temperature simultaneously.

#### 4. Overlay Vertical Position (`select.pixoo64_overlay_vertical_position`)
* **Auto (Opposite of Text):** Automatically places clock/temp on the opposite edge of the track text to prevent collisions.
* **Top:** Forces clock/temp to the top row (Y: 3).
* **Bottom:** Forces clock/temp to the bottom row (Y: 56).

#### 5. Overlay Alignment (`select.pixoo64_overlay_alignment`)
* **Clock Right, Temp Left:** Clock aligns to the right corner; temperature aligns to the left corner.
* **Clock Left, Temp Right:** Clock aligns to the left corner; temperature aligns to the right corner.
* **Centered:** Places elements toward the center of the display.

#### 6. Crop Mode (`select.pixoo64_crop_mode`)
* **Default:** Standard proportional scaling.
* **No Crop:** Preserves exact original dimensions with letterbox padding.
* **Crop:** Trims exterior borders, letterboxing, and empty whitespace.
* **Extra Crop:** Advanced multi-component subject isolation. Rejects outer album borders and background text to tightly frame the subject.

---

### 🔢 Numbers

| Entity Name | Entity ID | Range | Description |
| :--- | :--- | :--- | :--- |
| **Lyrics Sync Offset** | `number.pixoo64_lyrics_sync_offset` | `-5.0s` to `+5.0s` (Step: `0.5s`) | Fine-tune lyrics synchronization in real-time to match speaker latency or Bluetooth lag. |

---

### 📊 Sensors

#### **Pixoo64 Status** (`sensor.pixoo64_status`)
Displays the current state formatted as `Artist - Title`. Includes comprehensive diagnostic attributes:
* `image_source`: Where the current art came from (`Original`, `Spotify`, `MusicBrainz`, `TIDAL`, `AI`, etc.).
* `image_url`: Full URL or source path of the active artwork.
* `font_color`: Auto-calculated hex color optimized for legibility.
* `background_color` & `background_color_rgb`: Dominant color extracted from the artwork.
* `process_duration`: Time taken to fetch, crop, filter, and render the frame.
* `lyrics_found` & `lyrics_count`: Synced lyrics availability and total lines parsed.
* `pixoo64_channel`: Last active Pixoo device channel before takeover.

---

## 🔔 Custom Notifications Service (`pixoo64_art.send_notification`)

Send instant text or animated icon alerts directly to your Pixoo64. Notifications temporarily interrupt playback, paint a high-contrast black frame with custom themed pixel icons, sound the hardware buzzer (optional), and gracefully restore previous artwork when finished.

### Service Parameters

| Parameter | Type | Required | Default | Description |
| :--- | :---: | :---: | :---: | :--- |
| `message` | string | **Yes** | — | Text to display (supports automatic Hebrew/Arabic RTL). |
| `type` | string | No | `text` | The visual theme and animated icon (see list below). |
| `duration` | int | No | `5` | Time in seconds before returning to media art. |
| `play_buzzer` | boolean| No | `false` | Trigger the Pixoo64 onboard acoustic buzzer chime. |
| `buzzer_active`| int | No | `500` | Beep tone active duration in milliseconds. |
| `buzzer_off` | int | No | `500` | Silence duration between beeps in milliseconds. |
| `buzzer_total` | int | No | `3000` | Total buzzer cycle time in milliseconds. |
| `color` | string | No | — | Optional custom HEX color override (e.g. `#00FFCC`). |

#### Supported Notification Types
* **Status & Alert:** `text`, `info`, `success`, `warning`, `error`, `v` (Checkmark), `x` (Cancel), `alert` (Animated bell), `attack` (Animated rocket).
* **Smart Home:** `door`, `lock`, `boiler`, `shutter`, `washer`, `car`, `trash`, `mail`, `fire`, `water`.
* **Devices & Sensors:** `battery`, `wifi`, `phone` (Animated wiggle), `camera`, `calendar`, `timer` (Animated clock hand), `weather` (Sun & Cloud).
* **Atmosphere:** `music`, `sun`, `moon` / `sleep`.

### Automation Example

```yaml
alias: "Front Door Bell - Pixoo Notification"
trigger:
  - platform: state
    entity_id: binary_sensor.front_door_bell
    to: "on"
action:
  - service: pixoo64_art.send_notification
    data:
      message: "Visitor at the Door!"
      type: "door"
      duration: 7
      play_buzzer: true
      buzzer_active: 300
      buzzer_off: 200
      buzzer_total: 2000
