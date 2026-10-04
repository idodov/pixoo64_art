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

This project is a **100% native Home Assistant custom integration**:
* **Native Performance:** Runs directly within Home Assistant’s native asynchronous event loop.
* **100% UI Configured:** Automatic LAN device discovery and full interactive setup through the Home Assistant UI (Config Flow & Options Flow).
* **Direct LAN Communication:** Communicates directly with the Pixoo64 over local HTTP REST—instant, reliable, and completely cloud-independent for core playback.
* **Multi-Purpose Visual Hub:** Displays high-contrast album art, dynamic artist slideshows, real-time volume feedback, retro TV mode, synchronized lyrics, ambient room light mirroring, and animated visual notifications with hardware buzzer support.

---

## ✨ Features at a Glance

| Feature | Description |
| :--- | :--- |
| 🖼️ **Adaptive Crop Engine** | **Standard Crop** trims margins while keeping typography; **Extra Crop** unwraps nested stripes, unites multi-person subjects, and frames minimalist text. |
| 🧑‍🎤 **Dynamic Artist Gallery** | Dedicated **Artist Slide** mode (and fallback layer) that intelligently parses artist names and fetches high-quality fanart from TheAudioDB to render dynamic slideshows. |
| 🌊 **Multi-Tier Fallback** | When artwork is missing, queries: **Local HA ➔ Spotify ➔ Discogs / Last.fm / TIDAL / MusicBrainz ➔ TheAudioDB ➔ Pollinations AI ➔ Minimalist Slate**. |
| 🔊 **Real-Time Volume HUD** | Detects volume changes on your AVR, soundbar, or media player and temporarily renders an instant, high-visibility volume level indicator. |
| 📺 **Intelligent TV Mode** | Detects HDMI-ARC, streaming apps, and live TV sources, displaying a handcrafted retro pixel-art television with antennas and SMPTE test bars. |
| 🎤 **Live Synced Lyrics** | Live `.lrc` lyrics via LRCLIB with event-driven timing, smart line wrapping, millisecond calibration, and native BiDi (Hebrew/Arabic RTL) layout. |
| 💡 **Ambient Lighting Sync** | Extracts primary album colors in real time and synchronizes **Home Assistant RGB lights** and **WLED fixtures** (with night-only filters). |
| 🔔 **Animated Visual Alerts** | 30+ animated pixel icons (doorbell, laundry, climate, security) with onboard **Pixoo hardware buzzer** chime integration. |

---

## 📦 Installation

### Option 1: Via HACS (Recommended)

1. Open **HACS** in your Home Assistant sidebar.
2. Click the **three dots** in the top right corner and select **Custom repositories**.
3. Paste repository: `https://github.com/idodov/pixoo64_art`
4. Choose Category: **Integration**.
5. Click **Add**, locate **Pixoo64 Media Album Art**, click **Download**, and restart Home Assistant.

### Option 2: Manual Installation

1. Download the latest release `.zip` from the [Releases Page](https://github.com/idodov/pixoo64_art/releases).
2. Extract the folder into your Home Assistant directory:
```text
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

* **MusicBrainz (`musicbrainz_enabled`):** Enable or disable free open-source Cover Art Archive lookups.
* **Internet Archive (`internet_archive_enabled`):** Enable metadata and art lookups from archive.org.
* **Pollinations AI Key (`pollinations_key`):** Enter your API key to generate prompt-based conceptual artwork.
* **AI Model (`ai_model`):** Select your preferred generative image model (e.g. `flux.1-schnell`, `turbo`, `vector`).
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
| --- | --- | --- | --- | --- |
| `message` | string | **Yes** | — | Notification body (supports automatic English, Hebrew, and Arabic bi-directional layout). |
| `type` | string | No | `text` | The visual theme and animation profile (see catalog below). |
| `duration` | int | No | `5` | Display duration in seconds before returning to media art. |
| `color` | string | No | Theme Default | Custom HEX color override (e.g., `#FF0055`). |
| `play_buzzer` | boolean | No | `false` | Trigger the Pixoo64 onboard acoustic buzzer. |
| `buzzer_active` | int | No | `500` | Beep duration in milliseconds per cycle. |
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


## ❓ Frequently Asked Questions (FAQ)

<details>
<summary><strong>🎛️ Q: What is the difference between "Master Control" and "Full Control"?</strong></summary>

> Both of these toggles dictate how the integration behaves, but they act on entirely different layers of the hardware:
> 
> * **Master Control (Software Level):** This acts as the integration's main "Kill Switch". If toggled off, the integration simply stops fetching album art, polling lyrics, and pushing HTTP payloads. The Pixoo64 remains turned on, but it will revert to whatever default clock or custom channel you have set in the Divoom App.
> * **Full Control (Hardware Override):** When enabled, the integration takes complete ownership of the Pixoo64's screen power. When music plays, it sends an explicit command to power the LED matrix **ON**. The moment playback stops, it sends a command to power the LED matrix **OFF** (completely black). This bypasses the Divoom App entirely and is perfect if you only want the Pixoo active when music is playing.

</details>

<details>
<summary><strong>🔑 Q: Where do I get API keys for all the supported services?</strong></summary>

> Here are the direct links to obtain developer credentials for every supported metadata provider:
> 
> * **Spotify (Client ID & Client Secret):**  
>   👉 [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)  
>   *Log in with your Spotify account, click "Create an App", set the Redirect URI to `https://localhost`, and copy your Client ID and Client Secret.*
> 
> * **Pollinations AI (API Key):**  
>   👉 [Pollinations.ai Dashboard](https://enter.pollinations.ai/)  
>   *Sign in to generate your API key for prompt-based conceptual artwork generation.*
> 
> * **Discogs (Personal Access Token):**  
>   👉 [Discogs Developer Settings](https://www.discogs.com/settings/developers)  
>   *Sign in, scroll to "User Tokens", and click "Generate new token".*
> 
> * **Last.fm (API Key):**  
>   👉 [Last.fm API Account Creation](https://www.last.fm/api/account/create)  
>   *Fill in an application name and description to receive an instant 32-character API key.*
> 
> * **TIDAL (Client ID & Client Secret):**  
>   👉 [TIDAL Developer Portal](https://developer.tidal.com/)  
>   *Log in with your TIDAL account to access your developer dashboard and create client-credentials keys.*
> 
> * **TheAudioDB, MusicBrainz & Cover Art Archive:**  
>   * **No keys or tokens required!** These platforms are completely free and open-source. The integration automatically handles compliant rate-limiting for them.

</details>
<details>
<summary><strong>🔌 Q: Do I have to configure all these APIs? Can I use just one or two, and what is recommended?</strong></summary>

> You are not required to configure *any* API keys if you don't want to! You can pick and choose exactly which services you want to enable. The integration uses a smart "Waterfall" engine—it will simply skip any service you haven't configured and seamlessly move to the next available one.
> 
> Here are a few ways you can set it up:
> * **The Minimalist (Zero Setup):** Don't enter any keys. The integration will rely on your local Home Assistant media player's artwork and automatically fall back to the built-in free databases (MusicBrainz, TheAudioDB, Internet Archive).
> * **The Recommended "Sweet Spot":** We highly recommend generating a free **Spotify** API key. It is incredibly fast, holds the largest high-resolution library, and unlocks the animated *Spotify Slider* mode.
> * **The "Never Blank" Setup (Best Experience):** Add **Spotify** (for mainstream hits), **Discogs / Last.fm** (for rare vinyls, B-sides, and indie tracks), and **Pollinations AI** (to dynamically generate stunning conceptual art when a song truly has no official cover). 

</details>
<details>
<summary><strong>💸 Q: Do I need to pay for any API keys or premium subscriptions to use this?</strong></summary>

> **Absolutely not.** The integration is designed to be 100% free out-of-the-box.
> 
> * **Built-in Open APIs:** Services like MusicBrainz, Internet Archive, and TheAudioDB are completely open to the public and require zero configuration or keys to function. The integration uses them automatically.
> * **Free Developer Keys:** While you *can* plug in API keys to unlock higher-resolution artwork or specific animated modes (like Spotify, TIDAL, Last.fm, Discogs, and Pollinations AI), generating these developer keys is completely free. 
> * **No Premium Accounts Needed:** You **do not** need a Spotify Premium or TIDAL Hi-Fi subscription to use their APIs to fetch album covers. A standard free account is all you need to access their developer portals and generate a Client ID.

</details>
<details>
<summary><strong>🌊 Q: What happens if my music doesn't have official album art? (The Fallback Waterfall)</strong></summary>

> Never face an empty display when listening to obscure radio stations, Cast devices, or local files. The integration features an intelligent "waterfall" recovery sequence to ensure something beautiful is always rendered on your screen:
> 
> ```text
> [Media Player Playing]
>          │
>          ▼
>  1. Local HA Art Present? ─────(Yes)───► [Render Cover Art]
>          │ (No)
>          ▼
>  2. Spotify Search API ────────(Found)─► [Render 640x640 Art / Spotify Slider]
>          │ (Missing)
>          ▼
>  3. Discogs / Last.fm / TIDAL ─(Found)─► [Render Hi-Res Match]
>          │ (Missing)
>          ▼
>  4. MusicBrainz / Archive ─────(Found)─► [Render CoverArtArchive]
>          │ (Missing)
>          ▼
>  5. TheAudioDB API ────────────(Found)─► [Render Dynamic Artist Gallery Slide]
>          │ (Missing)
>          ▼
>  6. Pollinations AI ───────────(Active)► [Generate Conceptual Art]
>          │ (Disabled / No Key)
>          ▼
>  7. Internal Geometric Canvas ─────────► [Minimalist Burned Slate]
> ```

</details>
<details>
<summary><strong>🎛️ Q: What settings can I change from my dashboard vs. the integration configuration?</strong></summary>

> The integration is designed to give you maximum flexibility, dividing settings into two logical areas:
> 
> **1. Dashboard UI Controls (Real-Time Visuals):**
> Once installed, the integration automatically generates several `Select` entities that you can place directly on your Home Assistant dashboard. Changing these updates the Pixoo64 **instantly**:
> * **Display Mode:** Switch live between Standard, Vinyl, Cassette, Artist Slide, Spotify Slider, Lyrics, or Force AI.
> * **Image Filter:** Apply real-time processing effects (e.g., Vibrant, Retro Arcade, Cyberpunk Neon).
> * **Crop Mode:** Toggle between No Crop, Standard Crop, or Extra Crop.
> * **Layout Controls:** Adjust the typography position, toggle the Clock/Temperature overlays, and change their alignment on the fly.
> 
> **2. Integration Settings (Core Infrastructure):**
> For deeper structural changes, navigate to **Settings > Devices & Services > Pixoo64 > Configure**. Here you can safely update:
> * **API Keys & Credentials:** Add or remove tokens for Spotify, TIDAL, Last.fm, Discogs, or Pollinations AI.
> * **Hardware Links:** Change the targeted Media Player, Temperature Sensor, or your synchronized Ambient Lights / WLED strips.
> * **Background Engine Rules:** Enable/Disable TV Mode, adjust Playlist Prefetch ranges, and modify OSD (On-Screen Display) timeout durations for volume and pausing.

</details>
<details>
<summary><strong>📺 Q: How does the Intelligent TV Mode work?</strong></summary>

> Streaming devices and modern smart TVs connected via HDMI eARC often populate media players with metadata like `"TV"`, `"Audio Return Channel"`, or streaming app names rather than music tracks. 
> 
> The integration includes an intelligent **TV Mode engine**:
> 1. **Automatic TV Detection:** Monitors `media_title`, `media_artist`, `app_name`, `source`, and `media_channel`. It immediately recognizes inputs such as HDMI ARC, Netflix, YouTube, Disney+, Prime Video, Apple TV, and Live TV.
> 2. **Dedicated Visual Display (`TV_IS_ON_ICON`):** When TV Mode is active, music-specific features are automatically suspended. Instead, the screen renders an authentic **Retro Color-Bar Television** with a classic wood-grain cabinet, dual antennas, and a SMPTE rainbow test screen.

</details>

<details>
<summary><strong>🔊 Q: How does the Dynamic Volume HUD Effect work?</strong></summary>

> When you adjust the volume on your receiver, soundbar, or TV remote, looking at a small receiver display across the room can be difficult. 
> 
> The integration tracks volume changes in real time:
> * **Instant Visual Feedback:** The moment the `volume_level` attribute changes on your tracked media player, the Pixoo temporarily displays a high-visibility volume level HUD overlay.
> * **Auto-Revert:** Once volume adjustment stops, the display smoothly returns to the current album artwork or live lyrics without skipping a beat.

</details>

<details>
<summary><strong>🗄️ Q: How does the integration use MusicBrainz & Cover Art Archive?</strong></summary>

> For music purists, offline CD rips, and vinyl collectors, the integration includes native integration with **MusicBrainz** and the **Internet Archive's Cover Art Archive**:
> * **Intelligent Querying:** Queries releases by exact artist and track name using strict metadata filtering.
> * **Rate-Limit Resilient:** Features a built-in rate-limiting governor compliant with MusicBrainz API policies (1 request per second) to prevent IP throttling.
> * **Front Cover Priority:** Automatically pulls verified `250px` high-quality front cover art directly from the archive.

</details>

<details>
<summary><strong>✂️ Q: How does the Crop Engine (Standard vs. Extra Crop) work?</strong></summary>

> Pixoo's 64×64 LED resolution requires specialized image composition. The integration offers two intelligent cropping algorithms:
> 
> * **Standard Crop:** Trims outer black letterboxing, white scanner margins, and pillarbox bars while preserving full album sleeves and typography.
> * **Extra Crop (Subject Isolation):**
>   * **Nested Container Unwrapping:** Detects when an album has a colored vertical band or card (e.g. *Eurythmics - Sweet Dreams*) and extracts the inner photo without border bleed.
>   * **Subject Clustering:** Detects two or more adjacent subjects (e.g. *Pet Shop Boys*) and groups them together into a unified square, preventing two-person shots from being sliced in half.
>   * **Typographic Framing:** Automatically detects minimalist covers (e.g. *Charli XCX - Brat*) and frames the text with balanced negative space rather than collapsing on hollow letter loops.

</details>

<details>
<summary><strong>🌍 Q: Why are Hebrew or Arabic lyrics/text displayed correctly without reversing?</strong></summary>

> The integration includes an internal Bidirectional (BiDi) layout algorithm. Text containing Hebrew or Arabic characters is parsed and formatted for Right-to-Left (RTL) reading order before rendering to the Pixoo LED matrix.

</details>

<details>
<summary><strong>🌐 Q: Does this integration require an internet connection?</strong></summary>

> **No, for local playback.** Communication between Home Assistant and the Pixoo64 happens entirely over your local area network (LAN HTTP POST). 
> Internet access is only required if you use online fallback providers (Spotify, TheAudioDB, MusicBrainz, TIDAL, LRCLIB lyrics, or Pollinations AI).

</details>

<details>
<summary><strong>📡 Q: How do I set a static IP for my Pixoo64?</strong></summary>

> It is strongly recommended to assign a permanent **DHCP Reservation** for your Pixoo64 within your home router's admin settings to ensure its LAN IP address never changes.

</details>

<details>
<summary><strong>🖼️ Q: What is the difference between "Spotify Slider" and "Artist Slide" modes?</strong></summary>

> Both modes replace the static album cover with a dynamic, animated slideshow, but they use different sources and display different content:
> 
> * **Spotify Slider:** Requires your personal Spotify API keys. It searches Spotify for the currently playing artist and builds an animated carousel using the **Album Covers** of their top releases (Singles, EPs, and Albums). 
> * **Artist Slide:** Requires **NO API keys** (completely free). It uses TheAudioDB to fetch high-quality **Artist Fanart, Backgrounds, and Portraits**. This is perfect if you want to see the actual band/singer on your screen instead of album squares, or if you don't use Spotify at all.

</details>

<details>
<summary><strong>⏱️ Q: The live lyrics are slightly out of sync with the music. Can I fix this?</strong></summary>

> Yes! Depending on your setup (Bluetooth speakers, AirPlay, or Sonos multi-room), there is often an inherent audio delay. 
> 
> You can easily calibrate this by going to the integration's **Configure** menu and adjusting the **Lyrics Sync Offset**. You can add or subtract seconds (e.g., `1.5` or `-0.8`) to perfectly match the text rendering on the Pixoo64 with the audio hitting your ears.

</details>
<details>
<summary><strong>✨ Q: Can I apply visual effects or filters to the album art?</strong></summary>

> Yes! Scaling high-resolution album covers down to a 64x64 pixel grid can sometimes make them look soft or slightly washed out. To fix this, the integration includes a dedicated **Image Filter Engine** that applies professional pre-scale and post-scale processing using Python's Pillow library.
> 
> You can select from several curated styles directly from the Home Assistant UI:
> * **Vibrant:** Boosts color saturation, contrast, and sharpness. (Highly recommended to make the LEDs truly pop).
> * **Retro Arcade:** Posterizes the image and reduces the color bit-depth for a classic 8-bit / 16-bit video game vibe.
> * **Cyberpunk Neon:** Maximizes contrast, auto-levels, and applies edge enhancement for a glowing, neon-drenched look.
> * **Noir B&W:** Converts the artwork to high-contrast grayscale for a moody, vintage aesthetic.
> * **Crisp & Sharp:** Applies an unsharp mask to recover fine details and lines that are usually lost during the extreme downscaling process.

</details>
<details>
<summary><strong>💡 Q: How does the ambient lighting (WLED/RGB) sync work? Will it turn on my lights during the day?</strong></summary>

> The integration features a built-in Color Science analyzer that extracts the most prominent and vibrant color palette from the currently playing album art. It then pushes these colors to your selected Home Assistant light entities or WLED strips.
> 
> To prevent wasting energy, you can enable the **Only at Night** toggle in the configuration. When enabled, the integration checks the native `sun.sun` state in Home Assistant and will only synchronize your room lights if the sun is below the horizon.

</details>

<details>
<summary><strong>🚀 Q: Won't downloading high-res images and running AI models slow down my Home Assistant?</strong></summary>

> Not at all. The integration uses a highly optimized, asynchronous **Prefetch Engine**. 
> 
> If you enable the **Playlist Prefetch** option, the integration looks ahead into your media player's queue and downloads, crops, and processes the upcoming album art *before* the current song finishes. Everything is stored in a strict, lightweight RAM cache (capped at 40 items), ensuring that the moment the next track starts, the Pixoo transitions instantly with zero delay or loading screens.

</details>

<details>
<summary><strong>🤖 Q: What is the "Force AI" display mode?</strong></summary>

> **Force AI** intentionally bypasses all traditional album art databases (Spotify, Apple Music, Local Files). Instead, it takes the current "Artist" and "Track Title" and sends them as a prompt to the Pollinations AI generative model. 
> 
> The AI dynamically generates a unique, vibrant, conceptual pop-art representation of the song. This is highly recommended for users who listen to a lot of obscure indie music, live bootlegs, or DJ sets that typically don't have official cover art.

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

Distributed under the **MIT License**. See [`LICENSE`](https://www.google.com/search?q=LICENSE) for more information.

---

## 🌟 Acknowledgments

* [Divoom](https://www.divoom.com/) for building the Pixoo64 hardware.
* [LRCLIB](https://lrclib.net/) for providing a free, open-source synced lyrics API.
* [TheAudioDB](https://www.theaudiodb.com/) for the dynamic artist fanart API.
* [MusicBrainz](https://musicbrainz.org/) & [Cover Art Archive](https://coverartarchive.org/) for open metadata.
* [Pollinations.ai](https://pollinations.ai/) for accessible generative AI art APIs.
* The [Home Assistant Community](https://community.home-assistant.io/) for continuous testing and feedback.
