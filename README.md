<h1 align="center">🎨 Pixoo64 Media Album Art for Home Assistant</h1>

<p align="center">
  <a href="https://www.home-assistant.io/"><img src="https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blueviolet.svg?style=for-the-badge&logo=home-assistant" alt="Home Assistant 2024.1+"></a>
  <a href="https://hacs.xyz/"><img src="https://img.shields.io/badge/HACS-Custom%20Repo-orange.svg?style=for-the-badge&logo=hacs" alt="HACS Custom Repository"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge" alt="License: MIT"></a>
  <a href="https://github.com/idodov/pixoo64_art/issues"><img src="https://img.shields.io/github/issues/idodov/pixoo64_art?style=for-the-badge&color=red" alt="GitHub Issues"></a>
</p>

<p align="center">
  <strong>Turn your Divoom Pixoo64 into an adaptive media display, live volume HUD, and smart-home visual alert center.</strong>
</p>

<p align="center">
  <img src="https://github.com/idodov/pixoo64-media-album-art/assets/19820046/71348538-2422-47e3-ac3d-aa1d7329333c" alt="Pixoo64 displaying a gallery of album covers" width="85%">
</p>

---

## 📑 Table of Contents

- [Overview](#-overview)
- [Features at a Glance](#-features-at-a-glance)
- [Installation](#-installation)
- [Initial Configuration](#️-initial-configuration-ui-config-flow)
- [Smart Notifications Service](#-smart-notifications-service)
- [Automation Recipes](#-automation-recipes)
- [FAQ](#-frequently-asked-questions-faq)
- [Diagnostics & Troubleshooting](#️-diagnostics--troubleshooting)
- [Contributing](#-contributing)
- [License](#-license)
- [Acknowledgments](#-acknowledgments)

---

## 📖 Overview

**Pixoo64 Media Album Art** brings studio-grade album art rendering to the **Divoom Pixoo64** 64×64 LED matrix — directly from Home Assistant.

It is a **100% native Home Assistant custom integration**:

- **Native performance** — runs inside Home Assistant's asynchronous event loop.
- **Fully UI-configured** — automatic LAN discovery plus complete setup via Config Flow and Options Flow. No YAML required.
- **Direct LAN communication** — talks to the Pixoo64 over local HTTP. Core playback is instant, reliable, and cloud-independent.
- **Multi-purpose visual hub** — album art, artist slideshows, volume HUD, retro TV mode, synced lyrics, ambient light mirroring, and animated notifications with hardware buzzer support.

---

## ✨ Features at a Glance

| Feature | Description |
| :--- | :--- |
| 🖼️ **Adaptive Crop Engine** | **Standard Crop** trims margins while keeping typography. **Extra Crop** unwraps nested borders, groups multi-person subjects, and frames minimalist text covers. |
| 🧑‍🎤 **Dynamic Artist Gallery** | A dedicated **Artist Slide** mode (also used as a fallback layer) that parses artist names and fetches high-quality fanart from TheAudioDB. |
| 💿 **Vintage Animations** | **Vinyl Turntable** and **Cassette Tape** animations with transparent grooves, glossy reflections, and full-width micro-pixel track labels. |
| 🌊 **Multi-Tier Fallback** | When artwork is missing: **Local HA ➔ Spotify ➔ Discogs / Last.fm / TIDAL ➔ MusicBrainz / Internet Archive ➔ TheAudioDB ➔ Pollinations AI ➔ Minimalist Slate**. |
| 🔊 **Real-Time Volume HUD** | Detects volume changes on your AVR, soundbar, or media player and briefly shows a high-visibility volume indicator. |
| 📺 **Intelligent TV Mode** | Detects HDMI-ARC, streaming apps, and live TV sources, then shows a hand-crafted retro pixel TV with antennas and SMPTE color bars. |
| 🎤 **Live Synced Lyrics** | `.lrc` lyrics via LRCLIB with event-driven timing, smart line wrapping, millisecond calibration, and native BiDi (Hebrew/Arabic RTL) layout. |
| 💡 **Ambient Lighting Sync** | Extracts dominant album colors in real time and syncs **Home Assistant RGB lights** and **WLED** fixtures (with an optional night-only filter). |
| 🔔 **Animated Visual Alerts** | 30+ animated pixel icons (doorbell, laundry, climate, security) with **Pixoo hardware buzzer** chimes. |

<table>
  <tr>
    <td><img src="https://github.com/user-attachments/assets/f689500a-509d-491c-8a8f-1cacf897d61e" alt="Pixoo64 demo 3"></td>
    <td><img src="https://github.com/user-attachments/assets/c073ea7a-0b81-4dd3-9845-dfd0cd679844" alt="Pixoo64 demo 4"></td>
    <td><img src="https://github.com/user-attachments/assets/ed34c076-76ed-459d-bb78-51b6e39f6045" alt="Pixoo64 demo 5"></td>
  </tr>
  <tr>
    <td><img src="https://github.com/user-attachments/assets/ea74891f-493e-4f10-ae0d-8108d6b371a8" alt="Pixoo64 demo 0"></td>
    <td><img src="https://github.com/user-attachments/assets/d37e2f34-4023-4e46-9358-8ff618f3da99" alt="Pixoo64 demo 1"></td>
    <td><img src="https://github.com/user-attachments/assets/07308c9d-a44b-4978-a7ac-ced42f9e6046" alt="Pixoo64 demo 2"></td>
  </tr>
</table>

---

## 📦 Installation

### Option 1: HACS (Recommended)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=idodov&repository=pixoo64_art&category=integration)

Or add it manually:

1. Open **HACS** from the Home Assistant sidebar.
2. Click the **⋮** menu (top-right) and select **Custom repositories**.
3. Paste the repository URL: `https://github.com/idodov/pixoo64_art`
4. Set the category to **Integration** and click **Add**.
5. Find **Pixoo64 Media Album Art**, click **Download**, and restart Home Assistant.

### Option 2: Manual Installation

1. Download the latest release from the [Releases page](https://github.com/idodov/pixoo64_art/releases).
2. Copy the `pixoo64_art` folder into your Home Assistant config directory:

   ```text
   config/custom_components/pixoo64_art/
   ```

3. Restart Home Assistant.

---

## ⚙️ Initial Configuration (UI Config Flow)

Everything is configured through the Home Assistant UI — no YAML required.

1. Go to **Settings ➔ Devices & Services ➔ Add Integration**.
2. Search for **Pixoo64 Media Album Art**.
3. Complete the setup steps below.

### Step 1 — Device & Media Source

| Option | Key | Description |
| :--- | :--- | :--- |
| **Pixoo IP** | `pixoo_ip` | Select the auto-discovered Pixoo64, or enter its LAN IP manually. |
| **Media Player** | `media_player` | The media player entity to follow (e.g. `media_player.living_room`, Sonos, Apple TV, Cast). |
| **Temperature Sensor** | `temperature_entity` | *Optional.* Any temperature sensor to display room or outdoor temperature. |

### Step 2 — Ambient Lighting & TV Display

| Option | Key | Description |
| :--- | :--- | :--- |
| **Light Entities** | `light_entity` | One or more RGB/RGBW lights that mirror the dominant album colors. |
| **WLED IP** | `wled_ip` | An addressable WLED strip synced with album colors in real time. |
| **Only at Night** | `only_at_night` | Limits ambient lighting sync to after sunset. |
| **TV Mode** | `tv_mode` | Switches to the retro TV icon and test pattern when TV sources, streaming apps, or HDMI-ARC are playing. |

### Step 3 — Metadata APIs, MusicBrainz & AI Art

| Option | Key | Description |
| :--- | :--- | :--- |
| **MusicBrainz** | `musicbrainz_enabled` | Free, open-source Cover Art Archive lookups. |
| **Internet Archive** | `internet_archive_enabled` | Metadata and artwork lookups from archive.org. |
| **Pollinations AI Key** | `pollinations_key` | Enables prompt-based conceptual artwork generation. |
| **AI Model** | `ai_model` | Preferred image model (e.g. `flux.1-schnell`, `turbo`, `vector`). |
| **Spotify Credentials** | `spotify_client_id`, `spotify_client_secret` | High-res artwork lookups and the animated multi-album carousel. |
| **TIDAL Credentials** | `tidal_client_id`, `tidal_client_secret` | TIDAL Developer credentials for catalogue artwork. |
| **Last.fm Key** | `lastfm_key` | Personal API key for album art search. |
| **Discogs Token** | `discogs_token` | Personal access token for vinyl and release artwork. |

> [!TIP]
> Every setting can be changed later via **Settings ➔ Devices & Services ➔ Pixoo64 Media Album Art ➔ Configure**.

---

## 🔔 Smart Notifications Service

The `pixoo64_art.send_notification` action lets automations display animated alerts and play sound effects on the Pixoo64. A notification pauses media rendering, shows a high-contrast black canvas with pixel-art, optionally triggers the hardware buzzer, and then automatically restores your artwork.

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
| :--- | :--- | :---: | :--- | :--- |
| `message` | string | **Yes** | — | Notification text. English, Hebrew, and Arabic are laid out bi-directionally automatically. |
| `type` | string | No | `text` | Visual theme and animation profile (see catalog below). |
| `duration` | int | No | `5` | Seconds to display before returning to media art. |
| `color` | string | No | Theme default | Custom HEX color override (e.g. `#FF0055`). |
| `play_buzzer` | boolean | No | `false` | Trigger the Pixoo64's onboard buzzer. |
| `buzzer_active` | int | No | `500` | Beep length per cycle (ms). |
| `buzzer_off` | int | No | `500` | Silence between beeps (ms). |
| `buzzer_total` | int | No | `3000` | Total buzzer duration (ms). |

### Visual Icon Catalog

| Category | Types |
| :--- | :--- |
| **Alerts & Status** | `text` (text only), `info`, `success`, `warning`, `error`, `v` (checkmark), `x` (cancel), `alert` (animated bell), `attack` (animated rocket) |
| **Smart Home** | `door`, `lock`, `boiler`, `shutter`, `washer`, `car`, `trash`, `mail`, `fire`, `water` |
| **Hardware & Sensors** | `battery`, `wifi` (animated waves), `phone` (animated wiggle), `camera`, `calendar`, `timer` (animated clock hand), `weather` (sun and cloud) |
| **Ambience** | `music`, `sun`, `moon` / `sleep` |

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

---

## ❓ Frequently Asked Questions (FAQ)

### 🔌 Setup, Connectivity & Power Controls

<details>
<summary><strong>🌐 Does this integration require an internet connection?</strong></summary>

<br>

**Not for local playback.** Communication between Home Assistant and the Pixoo64 happens entirely over your local network (LAN HTTP POST).

Internet access is only needed for online providers: Spotify, TIDAL, Discogs, Last.fm, MusicBrainz, TheAudioDB, LRCLIB lyrics, and Pollinations AI.

</details>

<details>
<summary><strong>📡 How do I set a static IP for my Pixoo64?</strong></summary>

<br>

Create a **DHCP reservation** for the Pixoo64 in your router's admin settings so its LAN IP never changes.

</details>

<details>
<summary><strong>🎛️ What is the difference between "Master Control" and "Full Control"?</strong></summary>

<br>

Both toggles affect how the integration behaves, but on different layers:

- **Master Control (software level)** — the integration's main kill switch. When off, it stops fetching artwork, polling lyrics, and sending HTTP payloads. The Pixoo64 stays on and reverts to whatever clock or channel you set in the Divoom app.
- **Full Control (hardware override)** — the integration takes ownership of the screen's power. When music starts, it turns the LED matrix **on**; when playback stops, it turns it **off** (fully black). This bypasses the Divoom app entirely — ideal if you only want the Pixoo active while music is playing.

</details>

<details>
<summary><strong>⚙️ Which settings live on my dashboard vs. in the integration configuration?</strong></summary>

<br>

**1. Dashboard controls (real-time visuals)**

The integration creates several `select` entities you can add to any dashboard. Changes apply to the Pixoo64 **instantly**:

- **Display Mode** — Standard, Vinyl, Cassette, Artist Slide, Spotify Slider, Lyrics, or Force AI.
- **Image Filter** — real-time effects such as Vibrant, Retro Arcade, or Cyberpunk Neon.
- **Crop Mode** — No Crop, Standard Crop, or Extra Crop.
- **Layout Controls** — text position, Clock/Temperature overlays, and their alignment.

**2. Integration settings (core infrastructure)**

Go to **Settings ➔ Devices & Services ➔ Pixoo64 ➔ Configure** to update:

- **API keys & credentials** — Spotify, TIDAL, Last.fm, Discogs, Pollinations AI.
- **Hardware links** — media player, temperature sensor, ambient lights, WLED strips.
- **Engine rules** — TV Mode, Playlist Prefetch range, and OSD timeouts for volume and pause.

</details>

---

### 🔑 APIs, Accounts & Costs

<details>
<summary><strong>💸 Do I need to pay for any API keys or premium subscriptions?</strong></summary>

<br>

**No.** The integration is 100% free out of the box.

- **Built-in open APIs** — MusicBrainz, Internet Archive, and TheAudioDB work with zero configuration and no keys.
- **Free developer keys** — Spotify, TIDAL, Last.fm, Discogs, and Pollinations AI keys unlock higher-resolution artwork and extra modes, and are free to generate.
- **No premium accounts** — you **don't** need Spotify Premium or a paid TIDAL plan to fetch album covers. A free account is enough to access their developer portals.

</details>

<details>
<summary><strong>🔌 Do I have to configure every API? What's recommended?</strong></summary>

<br>

You don't have to configure *any* keys. The "waterfall" engine skips unconfigured services and moves on to the next available one.

| Setup | What to configure | Result |
| :--- | :--- | :--- |
| **Minimalist** | Nothing | Uses your media player's artwork, falling back to MusicBrainz, Internet Archive, and TheAudioDB. |
| **Recommended** | Spotify | Fast, huge high-res library, and unlocks the animated *Spotify Slider* mode. |
| **Never Blank** | Spotify + Discogs / Last.fm + Pollinations AI | Mainstream hits, rare vinyl/B-sides/indie tracks, and AI-generated art when no official cover exists. |

</details>

<details>
<summary><strong>🔗 Where do I get API keys for the supported services?</strong></summary>

<br>

| Service | What you need | Where to get it | How |
| :--- | :--- | :--- | :--- |
| **Spotify** | Client ID & Client Secret | [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) | Create an app, enter a Redirect URI (required by the form, e.g. `http://127.0.0.1:8888/callback`), then copy the Client ID and Secret. |
| **Pollinations AI** | API Key | [Pollinations.ai Dashboard](https://enter.pollinations.ai/) | Sign in and generate an API key. |
| **Discogs** | Personal Access Token | [Discogs Developer Settings](https://www.discogs.com/settings/developers) | Sign in and click **Generate new token**. |
| **Last.fm** | API Key | [Last.fm API Account](https://www.last.fm/api/account/create) | Enter an application name and description to receive your key. |
| **TIDAL** | Client ID & Client Secret | [TIDAL Developer Portal](https://developer.tidal.com/) | Sign in and create client-credentials keys. |
| **TheAudioDB, MusicBrainz, Cover Art Archive** | — | — | **No keys required.** Rate limiting is handled automatically. |

</details>

---

### 🎨 Artwork Engine, Cropping & Visuals

<details>
<summary><strong>🌊 What happens if a track has no official album art? (The Fallback Waterfall)</strong></summary>

<br>

Obscure radio stations, Cast devices, and local files never leave you with an empty display. The integration walks through this recovery sequence:

```text
[Media Player Playing]
         │
         ▼
 1. Local HA artwork? ──────────(Yes)───► Render cover art
         │ (No)
         ▼
 2. Spotify Search API ─────────(Found)─► Render 640×640 art / Spotify Slider
         │ (Missing)
         ▼
 3. Discogs / Last.fm / TIDAL ──(Found)─► Render hi-res match
         │ (Missing)
         ▼
 4. MusicBrainz / Archive ──────(Found)─► Render Cover Art Archive image
         │ (Missing)
         ▼
 5. TheAudioDB API ─────────────(Found)─► Render artist gallery slide
         │ (Missing)
         ▼
 6. Pollinations AI ────────────(Active)► Generate conceptual art
         │ (Disabled / no key)
         ▼
 7. Internal geometric canvas ──────────► Minimalist slate
```

</details>

<details>
<summary><strong>🔀 Why does it sometimes show a different cover than the album I'm playing?</strong></summary>

<br>

This is intentional, to avoid blank screens:

1. **Multiple releases** — a song often appears on a studio album, a single, a compilation, or a soundtrack.
2. **Search priority** — external APIs are queried mainly by **Artist + Track Title**, not by a strict album-name match.
3. **Messy metadata** — local files and streaming services often add tags like *"Deluxe Edition"*, *"Remastered 2023"*, or *"Bonus Track"*. Strict matching would make most lookups fail.

Prioritizing artist and track maximizes the chance of finding high-resolution art — even if it's the single or compilation cover.

</details>

<details>
<summary><strong>🗄️ How does the integration use MusicBrainz & the Cover Art Archive?</strong></summary>

<br>

Built for CD rips, vinyl rips, and purists:

- **Precise querying** — searches releases by artist and track name with strict metadata filtering.
- **Rate-limit compliant** — a built-in governor follows MusicBrainz's policy (1 request/second) to prevent IP throttling.
- **Front-cover priority** — pulls verified 250 px front-cover images directly from the archive.

</details>

<details>
<summary><strong>✂️ How does the Crop Engine (Standard vs. Extra Crop) work?</strong></summary>

<br>

A 64×64 LED canvas needs specialized composition:

- **Standard Crop** — trims black letterboxing, white scanner margins, and pillarbox bars while preserving the full sleeve and typography.
- **Extra Crop (subject isolation)**
  - **Nested container unwrapping** — detects colored bands or card borders (e.g. *Eurythmics – Sweet Dreams*) and extracts the inner photo without border bleed.
  - **Subject clustering** — groups two or more adjacent people (e.g. *Pet Shop Boys*) into one square so duos aren't sliced in half.
  - **Typographic framing** — frames minimalist text covers (e.g. *Charli XCX – Brat*) with balanced negative space instead of zooming into hollow letter shapes.

</details>

<details>
<summary><strong>✨ Can I apply visual effects or filters to the album art?</strong></summary>

<br>

Yes. Downscaling high-res covers to 64×64 can make them look soft, so the **Image Filter Engine** applies Pillow-based pre- and post-scale processing:

| Filter | Effect |
| :--- | :--- |
| **Vibrant** | Boosts saturation, contrast, and sharpness — makes LEDs pop. |
| **Retro Arcade** | Posterizes and reduces bit-depth for a classic 8/16-bit look. |
| **Cyberpunk Neon** | Maximizes contrast, auto-levels, and enhances edges for a glowing look. |
| **Noir B&W** | High-contrast grayscale for a vintage feel. |
| **Crisp & Sharp** | Unsharp mask to recover detail lost during downscaling. |

</details>

---

### 🎛️ Modes & Smart Features

<details>
<summary><strong>🖼️ What's the difference between "Spotify Slider" and "Artist Slide"?</strong></summary>

<br>

Both replace the static cover with an animated carousel, but use different content:

| Mode | Requires | Content |
| :--- | :--- | :--- |
| **Spotify Slider** | Spotify API credentials | **Album covers** from the artist's top releases (singles, EPs, albums). |
| **Artist Slide** | Nothing — free | **Artist fanart, backgrounds, and portraits** from TheAudioDB. Ideal if you'd rather see the band than the covers. |

</details>

<details>
<summary><strong>🤖 What is the "Force AI" display mode?</strong></summary>

<br>

**Force AI** skips traditional artwork sources and sends the current artist and track title as a prompt to Pollinations AI, generating a unique conceptual pop-art image for the song. Great for obscure indie tracks, DJ sets, and live bootlegs without official art.

</details>

<details>
<summary><strong>📺 How does Intelligent TV Mode work?</strong></summary>

<br>

Smart TVs and streaming devices connected via HDMI eARC often report metadata like `"TV"`, `"Audio Return Channel"`, or an app name instead of a music track.

The **TV Mode engine**:

1. **Auto-detects TV inputs** — monitors `media_title`, `media_artist`, `app_name`, `source`, and `media_channel` (HDMI ARC, Netflix, YouTube, Disney+, Apple TV, and more).
2. **Renders the TV visual (`TV_IS_ON_ICON`)** — music features pause and the display shows a **retro television** with a wood-grain cabinet, dual antennas, and SMPTE color bars.

</details>

<details>
<summary><strong>🔊 How does the Volume HUD work?</strong></summary>

<br>

- **Instant feedback** — as soon as the media player's `volume_level` attribute changes (receiver, soundbar, or TV remote), the Pixoo shows a high-visibility volume overlay.
- **Auto-revert** — once you stop adjusting, the display returns to the album art or live lyrics.

</details>

<details>
<summary><strong>⏱️ Live lyrics are slightly out of sync. Can I fix this?</strong></summary>

<br>

Yes. Bluetooth, AirPlay, and Sonos multi-room setups can introduce latency.

Open the integration's **Configure** menu and adjust **Lyrics Sync Offset** (e.g. `1.5` or `-2.0` seconds) until the lyrics match the audio.

</details>

<details>
<summary><strong>💡 How does ambient lighting (WLED/RGB) sync work? Will it turn on my lights during the day?</strong></summary>

<br>

The color analyzer extracts the dominant, vibrant palette from the current artwork and pushes it to your selected Home Assistant lights or WLED strips.

To avoid daytime activation, enable **Only at Night**. The integration then checks `sun.sun` and only syncs lights while the sun is below the horizon.

</details>

---

### ⚡ Performance & Caching

<details>
<summary><strong>🚀 Will high-res downloads and AI generation slow down Home Assistant?</strong></summary>

<br>

No. The integration uses a non-blocking asynchronous **Prefetch Engine**.

With **Playlist Prefetch** enabled, it reads your media player's queue and downloads, crops, and processes upcoming covers *before* the current track ends. Results are held in a lightweight RAM cache (capped at 40 items), so track transitions are instant.

</details>

---

## 🛠️ Diagnostics & Troubleshooting

**Enable debug logging** — add this to `configuration.yaml` and restart Home Assistant:

```yaml
logger:
  default: info
  logs:
    custom_components.pixoo64_art: debug
```

**Network timeouts** — make sure the Pixoo64 is on a stable 2.4 GHz Wi-Fi network and that port `80` isn't blocked between Home Assistant and the device.

**Still stuck?** [Open an issue](https://github.com/idodov/pixoo64_art/issues) and include your debug logs, Home Assistant version, and media player type.

---

## 🤝 Contributing

Contributions, feature requests, and bug reports are welcome!

1. Fork the project.
2. Create a feature branch: `git checkout -b feature/AmazingFeature`
3. Commit your changes: `git commit -m "Add some AmazingFeature"`
4. Push the branch: `git push origin feature/AmazingFeature`
5. Open a Pull Request.

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for details.

---

## 🌟 Acknowledgments

- [Divoom](https://www.divoom.com/) — for the Pixoo64 hardware.
- [LRCLIB](https://lrclib.net/) — for the free, open-source synced lyrics API.
- [TheAudioDB](https://www.theaudiodb.com/) — for the artist fanart API.
- [MusicBrainz](https://musicbrainz.org/) & [Cover Art Archive](https://coverartarchive.org/) — for open music metadata.
- [Pollinations.ai](https://pollinations.ai/) — for accessible generative AI art APIs.
- The [Home Assistant Community](https://community.home-assistant.io/) — for continuous testing and feedback.

<p align="center">
  If this project brightens your Pixoo, consider giving it a ⭐ on GitHub!
</p>
