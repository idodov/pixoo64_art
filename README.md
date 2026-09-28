# ALPHA VERSION

# 🎨 Pixoo64 Media Album Art for Home Assistant

Transform your Divoom Pixoo64 into a dynamic, smart media display for Home Assistant. This native custom component displays real-time album art, synced lyrics, progress bars, and smart home data directly on your Pixoo64.

Built entirely for Home Assistant (no AppDaemon required), it offers a plug-and-play UI configuration and advanced dashboard entities to control every pixel of your display.

## ✨ Key Features

* 🎵 **Smart Media Tracking:** Automatically fetches and displays high-quality album art from your active HA media player.
* 🎤 **Live Synced Lyrics:** Displays scrolling lyrics for the currently playing song, with an adjustable sync offset.
* 🧠 **Smart Fallback Matrix:** Never see a blank screen. Uses Spotify API, MusicBrainz, and Pollinations AI to find or generate cover art.
* 🎛️ **Dashboard UI Controls:** Toggle the clock, temperature, text layout, and progress bar dynamically using auto-generated Home Assistant switches and selects.
* 💡 **Ambient Lighting Sync:** Extracts dominant colors from the album cover and syncs them automatically with WLED or any Home Assistant RGB light.
* 🔔 **Custom Notifications:** Send text or animated icon notifications directly to the screen using the built-in HA service.

---

## 📦 Installation

### HACS (Recommended)
1. Open **HACS** in your Home Assistant instance.
2. Click the 3-dots menu in the top right corner and select **Custom repositories**.
3. Add the repository URL: `https://github.com/idodov/pixoo64_art`
4. Select **Integration** as the category and click **Add**.
5. Search for "Pixoo64 Media Album Art" in HACS, click **Download**, and restart Home Assistant.

### Manual Installation
1. Download the latest release.
2. Copy the `custom_components/pixoo64_art` directory into your Home Assistant `custom_components` directory.
3. Restart Home Assistant.

---

## ⚙️ Configuration

This integration supports **Config Flow** — no YAML required!

1. Navigate to **Settings** > **Devices & Services** in Home Assistant.
2. Click **+ Add Integration** and search for **Pixoo64**.
3. **Step 1 (Basic Setup):** Enter your Pixoo64's local IP address and select the Media Player entity you want to track.
4. **Step 2 (Advanced APIs):** Configure optional (but highly recommended) features:
   * **Spotify API:** For perfect cover matching and smooth slider animations.
   * **Temperature Sensor:** Select a sensor to display local room/outdoor temperature on the screen.
   * **Ambient Lights:** Select a Home Assistant light entity or enter a WLED IP to sync room colors with the album art.
   * **Pollinations AI:** For AI-generated conceptual art when no cover is available.

---

## 🎛️ Dashboard Entities

Once configured, the integration automatically creates a Device with the following entities for your dashboard:

### Switches (Toggles)
* **Master Control:** Turn the screen integration on/off.
* **Show Lyrics:** Overrides the display to show synced lyrics.
* **Show Clock / Temperature / Text:** Toggle individual data layers.
* **Text Background:** Adds a clean, dark gradient behind text for readability.
* **Progress Bar:** Shows track progress at the bottom of the screen.
* **Spotify Slider Mode:** Enables the animated Spotify album gallery effect.

### Selects (Layout & Positioning)
* **Text Position:** `Top` / `Bottom`
* **Clock & Temp Position:** `Opposite to Text` / `Top` / `Bottom`
* **Clock Alignment:** `Right` / `Left`
* **Crop Mode:** `Default` / `No Crop` / `Crop` / `Extra Crop`

### Sensors
* **Media Status:** Displays the current track, extracted colors, active mode, and image source (Original/Spotify/AI).

---

## 🔔 Sending Notifications

The integration registers a custom service `pixoo64_art.send_notification`. You can use this in your automations to interrupt the album art and show a message.

**Example YAML:**
```yaml
service: pixoo64_art.send_notification
data:
  message: "Someone is at the front door!"
  type: alert
  duration: 8
