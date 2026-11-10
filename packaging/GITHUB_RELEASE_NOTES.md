# 🎬 OneBrowser Zen `v3.4.1` — Linux & Bazzite Streaming Edition

**OneBrowser Zen** is a modern Linux desktop browser built on the OneBrowser engine with a **Zen Browser–inspired vertical workspace and tab interface**, designed specifically as a distraction-free **streaming and entertainment environment** on **Bazzite Linux** and modern Wayland/X11 desktops.

---

## 📦 Downloads (Choose Your Format)

| Format | File in Assets Below | Best For |
| :--- | :--- | :--- |
| **Flatpak Bundle (Primary)** | `OneBrowser-x86_64.flatpak` | **Bazzite Linux**, SteamOS, Fedora Atomic, and immutable desktops (includes native GTK3 + WebKit2GTK runtime & desktop integration). |
| **AppImage (Secondary)** | `OneBrowser-x86_64.AppImage` | **Portable 1-file execution** — no installation required; integrates directly with Bazzite's **Gear Lever**. |
| **Checksums** | `SHA256SUMS.txt` | SHA-256 integrity verification hashes. |

---

## 🚀 Option 1: How to Install the Flatpak (Recommended for Bazzite Linux)

Flatpak is the native application format on **Bazzite** and automatically manages all dependencies, desktop icons, Wayland/PipeWire audio, and GPU hardware acceleration.

### Method A — Graphical Install (No Terminal Needed)
1. Download **`OneBrowser-x86_64.flatpak`** from the **Assets** section at the bottom of this release.
2. Open your file manager (**Dolphin** on Bazzite KDE or **Files** on Bazzite GNOME) and **double-click `OneBrowser-x86_64.flatpak`**.
3. It will open in **KDE Discover** / **GNOME Software** / **Bazaar** — click **Install**, then launch **OneBrowser Zen** from your Application Menu!

### Method B — 1-Line Terminal Install
Open a terminal (**Ptyxis** / **Konsole**) and run:

```bash
# 1. Ensure the Flathub GNOME 47 runtime is installed (already present on most Bazzite systems)
flatpak install --user -y flathub org.gnome.Platform//47

# 2. Download & install OneBrowser Zen Flatpak
curl -LO https://github.com/OWNER/REPO/releases/latest/download/OneBrowser-x86_64.flatpak
flatpak install --user -y ./OneBrowser-x86_64.flatpak

# 3. Launch OneBrowser Zen
flatpak run io.github.onebrowser.OneBrowser
```

---

## ⚡ Option 2: How to Run the Standalone AppImage (Zero-Install Portable)

If you want to run OneBrowser immediately from a single file or send it directly to a friend:

### Method A — Using Bazzite's Built-in "Gear Lever" (Graphical)
1. Download **`OneBrowser-x86_64.AppImage`** from the **Assets** section below.
2. Double-click **`OneBrowser-x86_64.AppImage`** in your Downloads folder.
3. Bazzite's **Gear Lever** utility will open automatically:
   * Click **"Unlock & Launch"** to run it immediately, **or**
   * Click **"Move to App Menu"** to pin OneBrowser Zen to your desktop launcher with its icon.

### Method B — 1-Line Terminal Run
Open a terminal and run:

```bash
curl -LO https://github.com/OWNER/REPO/releases/latest/download/OneBrowser-x86_64.AppImage
chmod +x OneBrowser-x86_64.AppImage
./OneBrowser-x86_64.AppImage
```

---

## ✨ Key Features & Keyboard Shortcuts

* **Zen Vertical Sidebar & Workspaces**: Switch effortlessly between `🎬 Streaming`, `🍿 Entertainment`, `🎮 Gaming`, `💬 Social`, and `💼 Work` workspaces with smooth accent transitions and persistent tab restoration.
* **Pinned Streaming Essentials**: Top 2×2 quick-launch grid for **YouTube**, **Twitch**, **Netflix**, and **Disney+**.
* **Immersive Cinema Mode (`F11` or `Ctrl+Shift+I`)**: Collapses all browser toolbars and sidebars for borderless edge-to-edge video playback (`Esc` to exit).
* **Sidebar Media Deck & Picture-in-Picture (`⧉ PiP`)**: Control Play/Pause, Tab Audio Mute (`Ctrl+M`), Volume (`0–100%`), and native Picture-in-Picture directly from the bottom of the sidebar.
* **Dual Split-Screen Tiling (`Ctrl+Shift+S`)**: Watch a live stream on the left while browsing Twitch chat, Reddit, or a game wiki on the right.
* **Built-in 16x ZeroDownloader**: Segmented multi-connection downloader with HLS `.m3u8` and stream extraction support.
* **Linux Hardware Acceleration**: Configured out-of-the-box for VA-API, Vulkan, and Mesa RADV (AMD Radeon / Steam Deck / ROG Ally / Desktop Bazzite).
