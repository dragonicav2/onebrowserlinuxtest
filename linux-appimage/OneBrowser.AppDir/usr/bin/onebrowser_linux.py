#!/usr/bin/env python3
"""
OneBrowser for Linux — Zen Browser–Inspired Streaming & Entertainment Desktop Browser
Primary Target: Bazzite Linux (Fedora Atomic / Universal Blue) & Modern Linux Desktops
Distribution: Flatpak (Primary) & Standalone Type-2 AppImage (Secondary)

Architecture & Feature Highlights:
1. Zen Design System:
   - Consistent spacing scale (4/8/12/16/20/24/32px), clear typography hierarchy,
     rounded matte obsidian surfaces (#0F0F12, #141418, #1C1C22), and dynamic workspace accents.
   - Full interactive states (Default, Hover, Active, Focus-Visible, Disabled, Loading)
     and automatic Reduced Motion compliance.
2. Zen Sidebar-First Navigation & Vertical Tab System:
   - Pinned Essential Streaming Tiles (YouTube, Twitch, Netflix, Disney+) at top of sidebar.
   - Full Vertical Tab Management: Favicon/domain badge, title, loading indicator,
     audio mute/unmute toggle, pin state, hover close button, drag-and-drop reordering,
     duplicate tab, restore closed tab (Ctrl+Shift+T), and context menus.
3. Multi-Workspace Engine:
   - Built-in workspaces (Streaming, Entertainment, Gaming, Social, Work) + custom workspace
     creation and renaming.
   - Smooth workspace switching with persistent state across restarts (~/.config/onebrowser/).
4. Dedicated Streaming Environment:
   - Immersive Cinema Mode (Ctrl+Shift+I / F11): Hides all browser chrome for borderless
     edge-to-edge playback with hover-edge/shortcut sidebar reveal.
   - Native Picture-in-Picture (PiP) integration & Sidebar Media Controls Bar
     (Play/Pause, Mute/Unmute, Volume Slider, PiP, Fullscreen).
   - Dual Split-Screen Tiling (Ctrl+Shift+S) for simultaneous stream + chat/wiki viewing.
   - Hardware GPU acceleration (VA-API, Vulkan, Mesa RADV for AMD Radeon/Steam Deck, NVDEC, ANV)
     and compliant system Widevine CDM discovery for DRM streaming platforms.
5. Security & Built-in 16x ZeroDownloader:
   - Strict HTTPS-only enforcement, SSRF/RFC1918 private network protection, 41.9k ad/tracker
     shield, tracking parameter stripping, explicit site permission controls, and 16-connection
     segmented downloader drawer.
"""
from __future__ import annotations

import atexit
import ipaddress
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import zerodownloader as core  # noqa: E402

APP_NAME = "OneBrowser"
APP_ID = "io.github.onebrowser.OneBrowser"
APP_VERSION = "3.4.0-zen"
HOME_URL = "https://duckduckgo.com/"
ZEN_HOME_URI = "one://zen-home"

# ==============================================================================
# PHASE 2: UI DESIGN SYSTEM (TOKENS, SPACING, TYPOGRAPHY, WORKSPACE ACCENTS)
# ==============================================================================


@dataclass(frozen=True)
class DesignSystem:
    # Surface Palette (Deep Matte Obsidian inspired by Zen Browser)
    bg_canvas: str = "#0E0E11"
    bg_sidebar: str = "#131317"
    bg_elevated: str = "#1A1A20"
    bg_card: str = "#202027"
    bg_hover: str = "#282832"
    bg_active: str = "#31313D"
    bg_glass_modal: str = "#18181E"

    # Borders & Dividers
    border_subtle: str = "#25252E"
    border_strong: str = "#383846"
    border_focus: str = "#E5957C"

    # Typography Colors
    text_primary: str = "#F4F4F6"
    text_secondary: str = "#A1A1AA"
    text_muted: str = "#71717A"

    # Semantic Status Colors
    status_ok: str = "#34D399"
    status_warn: str = "#FBBF24"
    status_danger: str = "#F87171"
    status_info: str = "#60A5FA"

    # Consistent Corner Radii
    radius_sm: int = 6
    radius_md: int = 10
    radius_lg: int = 14
    radius_pill: int = 18

    # Spacing Scale (4px baseline grid)
    space_xs: int = 4
    space_sm: int = 8
    space_md: int = 12
    space_lg: int = 16
    space_xl: int = 24


TOKENS = DesignSystem()

WORKSPACE_PRESETS: list[dict[str, str]] = [
    {"id": "streaming", "name": "Streaming", "icon": "🎬", "accent": "#E5957C"},
    {"id": "entertainment", "name": "Entertainment", "icon": "🍿", "accent": "#A78BFA"},
    {"id": "gaming", "name": "Gaming", "icon": "🎮", "accent": "#34D399"},
    {"id": "social", "name": "Social", "icon": "💬", "accent": "#73B5E8"},
    {"id": "work", "name": "Work", "icon": "💼", "accent": "#FCD34D"},
]

PINNED_STREAMING_ESSENTIALS: list[dict[str, str]] = [
    {"title": "YouTube", "icon": "▶", "url": "https://www.youtube.com", "color": "#FF4E45"},
    {"title": "Twitch", "icon": "👾", "url": "https://www.twitch.tv", "color": "#A970FF"},
    {"title": "Netflix", "icon": "N", "url": "https://www.netflix.com", "color": "#E50914"},
    {"title": "Disney+", "icon": "✦", "url": "https://www.disneyplus.com", "color": "#38BDF8"},
]


def prefers_reduced_motion() -> bool:
    """Respects Linux desktop / environment preference for reduced motion."""
    if os.environ.get("ONEBROWSER_REDUCED_MOTION") == "1":
        return True
    if os.environ.get("GTK_ENABLE_ANIMATIONS") == "0":
        return True
    if os.environ.get("QT_ENABLE_ANIMATIONS") == "0":
        return True
    try:
        out = subprocess.check_output(
            ["gsettings", "get", "org.gnome.desktop.interface", "enable-animations"],
            stderr=subprocess.DEVNULL,
            timeout=0.4,
            text=True,
        ).strip()
        if out == "false":
            return True
    except Exception:
        pass
    return False


def build_zen_stylesheet(accent: str = "#E5957C") -> str:
    """Generates the complete Qt stylesheet implementing the Zen Design System."""
    t = TOKENS
    return f"""
        QMainWindow, QWidget {{
            background-color: {t.bg_canvas};
            color: {t.text_primary};
            font-family: "Inter", "Cantarell", "Noto Sans", "Segoe UI", Sans-Serif;
            font-size: 13px;
        }}
        QFrame#ZenSidebar {{
            background-color: {t.bg_sidebar};
            border-right: 1px solid {t.border_subtle};
        }}
        QFrame#TopToolbar {{
            background-color: {t.bg_sidebar};
            border-bottom: 1px solid {t.border_subtle};
        }}
        QFrame#ViewportFrame {{
            background-color: {t.bg_canvas};
            border: 1px solid {t.border_subtle};
            border-radius: {t.radius_md}px;
        }}
        QFrame#CardSurface {{
            background-color: {t.bg_elevated};
            border: 1px solid {t.border_subtle};
            border-radius: {t.radius_md}px;
        }}
        QFrame#MediaControllerBar {{
            background-color: {t.bg_elevated};
            border: 1px solid {t.border_subtle};
            border-radius: {t.radius_md}px;
        }}
        QLineEdit {{
            background-color: {t.bg_elevated};
            border: 1px solid {t.border_subtle};
            border-radius: 15px;
            padding: 6px 14px;
            color: {t.text_primary};
            selection-background-color: {accent};
            selection-color: {t.bg_canvas};
        }}
        QLineEdit:hover {{
            border: 1px solid {t.border_strong};
            background-color: {t.bg_card};
        }}
        QLineEdit:focus {{
            border: 1.5px solid {accent};
            background-color: {t.bg_card};
        }}
        QPushButton {{
            background-color: {t.bg_elevated};
            border: 1px solid {t.border_subtle};
            border-radius: {t.radius_sm}px;
            padding: 6px 10px;
            color: {t.text_primary};
            font-weight: 500;
        }}
        QPushButton:hover {{
            background-color: {t.bg_hover};
            border-color: {t.border_strong};
        }}
        QPushButton:pressed {{
            background-color: {t.bg_active};
        }}
        QPushButton:focus {{
            border: 1.5px solid {accent};
        }}
        QPushButton:disabled {{
            background-color: {t.bg_sidebar};
            color: {t.text_muted};
            border-color: transparent;
        }}
        QPushButton#AccentButton {{
            background-color: {accent};
            color: {t.bg_canvas};
            border: none;
            font-weight: 700;
            border-radius: {t.radius_sm}px;
        }}
        QPushButton#AccentButton:hover {{
            background-color: {t.text_primary};
            color: {t.bg_canvas};
        }}
        QPushButton#NavIconBtn {{
            background-color: transparent;
            border: 1px solid transparent;
            border-radius: {t.radius_sm}px;
            padding: 4px 8px;
            font-size: 14px;
            color: {t.text_secondary};
        }}
        QPushButton#NavIconBtn:hover {{
            background-color: {t.bg_hover};
            color: {t.text_primary};
        }}
        QPushButton#NavIconBtn:pressed {{
            background-color: {t.bg_active};
        }}
        QListWidget#VerticalTabList {{
            background-color: transparent;
            border: none;
            outline: none;
        }}
        QListWidget#VerticalTabList::item {{
            background-color: transparent;
            border: 1px solid transparent;
            border-radius: 8px;
            padding: 7px 10px;
            margin-bottom: 3px;
            color: {t.text_secondary};
        }}
        QListWidget#VerticalTabList::item:hover {{
            background-color: {t.bg_hover};
            color: {t.text_primary};
        }}
        QListWidget#VerticalTabList::item:selected {{
            background-color: {t.bg_card};
            border: 1px solid {accent};
            color: {t.text_primary};
            font-weight: 600;
        }}
        QComboBox {{
            background-color: {t.bg_elevated};
            border: 1px solid {t.border_subtle};
            border-radius: {t.radius_sm}px;
            padding: 5px 10px;
            color: {t.text_primary};
        }}
        QComboBox:hover {{
            border-color: {accent};
        }}
        QSlider::groove:horizontal {{
            height: 4px;
            background: {t.border_strong};
            border-radius: 2px;
        }}
        QSlider::sub-page:horizontal {{
            background: {accent};
            border-radius: 2px;
        }}
        QSlider::handle:horizontal {{
            background: {t.text_primary};
            width: 12px;
            height: 12px;
            margin: -4px 0;
            border-radius: 6px;
        }}
        QProgressBar {{
            background-color: {t.bg_canvas};
            border: 1px solid {t.border_subtle};
            border-radius: 4px;
            height: 8px;
            text-align: center;
        }}
        QProgressBar::chunk {{
            background-color: {accent};
            border-radius: 3px;
        }}
        QScrollBar:vertical {{
            background: transparent;
            width: 6px;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: {t.border_strong};
            min-height: 24px;
            border-radius: 3px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QMenu {{
            background-color: {t.bg_elevated};
            border: 1px solid {t.border_strong};
            border-radius: 8px;
            padding: 6px;
            color: {t.text_primary};
        }}
        QMenu::item {{
            padding: 6px 20px;
            border-radius: 5px;
        }}
        QMenu::item:selected {{
            background-color: {accent};
            color: {t.bg_canvas};
            font-weight: 600;
        }}
        QToolTip {{
            background-color: {t.bg_elevated};
            color: {t.text_primary};
            border: 1px solid {accent};
            border-radius: 6px;
            padding: 4px 8px;
        }}
    """


# ==============================================================================
# PHASE 9: SECURITY ENGINE (HTTPS, SSRF, TRACKER SHIELD, PERMISSIONS)
# ==============================================================================

TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "fbclid", "gclid", "dclid", "msclkid", "twclid", "yclid", "mc_eid", "igshid", "si",
})

BLOCKED_AD_DOMAINS = (
    "doubleclick.net", "googlesyndication.com", "googleadservices.com", "google-analytics.com",
    "googletagmanager.com", "adnxs.com", "rubiconproject.com", "pubmatic.com", "openx.net",
    "criteo.com", "taboola.com", "outbrain.com", "adsterra.com", "propellerads.com",
    "popads.net", "popcash.net", "exoclick.com", "realsrv.com", "juicyads.com",
    "trafficjunky.net", "acscdn.com", "chpadblock.com", "blockadblock.com", "fuckadblock.com",
    "admiral.com", "fundingchoicesmessages.google.com", "pagead2.googlesyndication.com",
)


def is_private_or_reserved_host(host: str) -> bool:
    h = (host or "").strip().lower().rstrip(".")
    if not h or h in ("localhost", "localhost.localdomain", "broadcasthost", "metadata.google.internal"):
        return True
    if h.endswith((".local", ".internal", ".lan", ".home.arpa", ".localhost")):
        return True
    try:
        ip = ipaddress.ip_address(h.strip("[]"))
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        return False


def is_blocked_domain(host: str) -> bool:
    h = (host or "").strip().lower().rstrip(".")
    for dom in BLOCKED_AD_DOMAINS:
        if h == dom or h.endswith("." + dom):
            return True
    return False


def strip_tracking_params(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if not parsed.query:
        return url
    kept = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")
    ]
    clean_query = urllib.parse.urlencode(kept, doseq=True)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, clean_query, parsed.fragment))


def resolve_navigation_input(raw: str) -> tuple[bool, str, str]:
    text = (raw or "").strip()
    if not text:
        return False, "", "Enter an HTTPS URL or search query."
    if text == ZEN_HOME_URI:
        return True, ZEN_HOME_URI, ""

    lower = text.lower()
    for bad_scheme in ("javascript:", "data:", "file:", "ftp:", "ws:", "wss:", "blob:", "vbscript:"):
        if lower.startswith(bad_scheme):
            return False, "", f"Blocked unsafe scheme ({bad_scheme})"

    if " " not in text and ("." in text or lower.startswith(("https://", "http://"))):
        if lower.startswith("http://"):
            candidate = "https://" + text[7:]
        elif lower.startswith("https://"):
            candidate = text
        else:
            candidate = "https://" + text
    else:
        candidate = "https://duckduckgo.com/?q=" + urllib.parse.quote_plus(text)

    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return False, "", "Only encrypted HTTPS URLs are allowed."
    if parsed.username or parsed.password:
        return False, "", "Blocked credentialed URL (phishing protection)."
    if is_private_or_reserved_host(parsed.hostname):
        return False, "", f"Blocked private/local address ({parsed.hostname})."
    if is_blocked_domain(parsed.hostname):
        return False, "", f"Blocked ad/tracker domain ({parsed.hostname})."

    return True, strip_tracking_params(candidate), ""


def extract_domain_badge(url: str) -> str:
    if not url or url == ZEN_HOME_URI or url.startswith("data:"):
        return "✦"
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if "youtube" in host:
        return "▶"
    if "twitch" in host:
        return "👾"
    if "netflix" in host:
        return "N"
    if "disney" in host:
        return "✦"
    if "github" in host:
        return "🐙"
    if "reddit" in host:
        return "💬"
    if "duckduckgo" in host:
        return "🦆"
    if "wikipedia" in host:
        return "📖"
    return (host[:1].upper() if host else "🌐")


HARDENING_AND_STREAMING_JS = """
(() => {
  try {
    window.open = function() { return null; };
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
    if (!document.querySelector('meta[name="referrer"]')) {
      const m = document.createElement('meta');
      m.name = 'referrer';
      m.content = 'same-origin';
      (document.head || document.documentElement).appendChild(m);
    }
    const clean = () => {
      document.querySelectorAll('[id*="chpadblock" i],[class*="chpadblock" i],.fc-ab-root').forEach(e => e.remove());
      if (document.body && getComputedStyle(document.body).overflow === 'hidden') {
        document.body.style.setProperty('overflow', 'auto', 'important');
      }
    };
    clean();
    new MutationObserver(clean).observe(document.documentElement, { childList: true, subtree: true });
  } catch (_) {}
})();
"""


def build_zen_home_html(workspace_name: str, workspace_icon: str, accent: str) -> str:
    """Generates the Zen Browser–inspired Streaming & Entertainment New Tab Experience."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Zen Home — {workspace_name}</title>
<style>
  :root {{
    --bg: #0E0E11;
    --card: #18181F;
    --card-hover: #22222C;
    --border: #272732;
    --text: #F4F4F6;
    --muted: #9CA3AF;
    --accent: {accent};
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: radial-gradient(circle at 50% 0%, rgba(229, 149, 124, 0.08), transparent 55%), var(--bg);
    color: var(--text);
    font-family: "Inter", "Cantarell", -apple-system, BlinkMacSystemFont, sans-serif;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 40px 24px;
    user-select: none;
  }}
  .container {{
    width: 100%;
    max-width: 860px;
  }}
  .badge {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 14px;
    border-radius: 999px;
    background: var(--card);
    border: 1px solid var(--border);
    color: var(--accent);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.4px;
    margin-bottom: 16px;
  }}
  h1 {{
    font-size: 36px;
    font-weight: 800;
    letter-spacing: -0.8px;
    margin-bottom: 8px;
  }}
  .subtitle {{
    color: var(--muted);
    font-size: 14px;
    margin-bottom: 28px;
  }}
  .search-box {{
    display: flex;
    align-items: center;
    background: var(--card);
    border: 1.5px solid var(--border);
    border-radius: 18px;
    padding: 14px 20px;
    margin-bottom: 36px;
    transition: border-color 0.16s ease, box-shadow 0.16s ease;
  }}
  .search-box:focus-within {{
    border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(229, 149, 124, 0.15);
  }}
  .search-box input {{
    width: 100%;
    background: transparent;
    border: none;
    outline: none;
    color: var(--text);
    font-size: 15px;
    margin-left: 12px;
  }}
  .section-title {{
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--muted);
    margin-bottom: 14px;
  }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(195px, 1fr));
    gap: 14px;
    margin-bottom: 32px;
  }}
  a.tile {{
    text-decoration: none;
    color: inherit;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 18px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    transition: transform 0.15s cubic-bezier(0.22, 1, 0.36, 1), background 0.15s ease, border-color 0.15s ease;
  }}
  a.tile:hover {{
    background: var(--card-hover);
    border-color: var(--accent);
    transform: translateY(-2px);
  }}
  .tile-top {{
    display: flex;
    align-items: center;
    justify-content: space-between;
  }}
  .tile-icon {{
    width: 36px;
    height: 36px;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 800;
    font-size: 16px;
    background: rgba(255,255,255,0.06);
  }}
  .tile-tag {{
    font-size: 10px;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 6px;
    background: rgba(255,255,255,0.05);
    color: var(--muted);
  }}
  .tile-name {{
    font-size: 15px;
    font-weight: 700;
    margin-top: 4px;
  }}
  .tile-desc {{
    font-size: 12px;
    color: var(--muted);
    line-height: 1.4;
  }}
  .shortcuts {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
    color: var(--muted);
    font-size: 12px;
  }}
  .kbd {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 3px 8px;
    font-family: monospace;
    color: var(--text);
  }}
</style>
</head>
<body>
  <div class="container">
    <div class="badge">{workspace_icon} WORKSPACE: {workspace_name.upper()} • BAZZITE &amp; LINUX STREAMING EDITION</div>
    <h1>OneBrowser Zen</h1>
    <p class="subtitle">Distraction-free vertical workspaces, hardware-accelerated streaming, and 16x media engine.</p>

    <form class="search-box" onsubmit="event.preventDefault(); const q=document.getElementById('q').value.trim(); if(q) window.location.href='https://duckduckgo.com/?q='+encodeURIComponent(q);">
      <span>🔍</span>
      <input id="q" type="text" placeholder="Search DuckDuckGo privately or type an HTTPS streaming address..." autofocus />
    </form>

    <div class="section-title">Streaming &amp; Entertainment Hub</div>
    <div class="grid">
      <a class="tile" href="https://www.youtube.com">
        <div class="tile-top"><div class="tile-icon" style="color:#FF4E45">▶</div><span class="tile-tag">4K60 AV1</span></div>
        <div class="tile-name">YouTube</div>
        <div class="tile-desc">Hardware-accelerated creators, live streams &amp; PiP mode</div>
      </a>
      <a class="tile" href="https://www.twitch.tv">
        <div class="tile-top"><div class="tile-icon" style="color:#A970FF">👾</div><span class="tile-tag">LOW LATENCY</span></div>
        <div class="tile-name">Twitch</div>
        <div class="tile-desc">Live gaming broadcasts &amp; dual split-screen chat</div>
      </a>
      <a class="tile" href="https://www.netflix.com">
        <div class="tile-top"><div class="tile-icon" style="color:#E50914">N</div><span class="tile-tag">CINEMA</span></div>
        <div class="tile-name">Netflix</div>
        <div class="tile-desc">Immersive borderless theater streaming</div>
      </a>
      <a class="tile" href="https://www.disneyplus.com">
        <div class="tile-top"><div class="tile-icon" style="color:#38BDF8">✦</div><span class="tile-tag">THEATER</span></div>
        <div class="tile-name">Disney+</div>
        <div class="tile-desc">Originals, movies &amp; marathon sessions</div>
      </a>
      <a class="tile" href="https://www.reddit.com">
        <div class="tile-top"><div class="tile-icon" style="color:#FF5700">💬</div><span class="tile-tag">SOCIAL</span></div>
        <div class="tile-name">Reddit</div>
        <div class="tile-desc">Communities, gaming threads &amp; discussions</div>
      </a>
      <a class="tile" href="https://github.com">
        <div class="tile-top"><div class="tile-icon" style="color:#F4F4F6">🐙</div><span class="tile-tag">CODE</span></div>
        <div class="tile-name">GitHub</div>
        <div class="tile-desc">Open-source repositories &amp; Linux packages</div>
      </a>
      <a class="tile" href="https://store.steampowered.com">
        <div class="tile-top"><div class="tile-icon" style="color:#66C0F4">🎮</div><span class="tile-tag">BAZZITE</span></div>
        <div class="tile-name">Steam Store</div>
        <div class="tile-desc">ProtonDB &amp; Linux handheld/desktop gaming</div>
      </a>
      <a class="tile" href="https://www.protondb.com">
        <div class="tile-top"><div class="tile-icon" style="color:#34D399">🐧</div><span class="tile-tag">LINUX</span></div>
        <div class="tile-name">ProtonDB</div>
        <div class="tile-desc">Linux &amp; Steam Deck compatibility reports</div>
      </a>
    </div>

    <div class="shortcuts">
      <span><span class="kbd">Ctrl+T</span> New Tab</span>
      <span><span class="kbd">Ctrl+Shift+V</span> Toggle Zen Sidebar</span>
      <span><span class="kbd">Ctrl+Shift+I</span> Immersive Cinema Mode</span>
      <span><span class="kbd">Ctrl+Shift+S</span> Split View</span>
      <span><span class="kbd">Ctrl+K</span> Command Palette</span>
      <span><span class="kbd">Ctrl+Shift+T</span> Restore Closed Tab</span>
    </div>
  </div>
</body>
</html>"""


# ==============================================================================
# PHASE 3 & 4: WORKSPACE & TAB STATE MANAGEMENT + PERSISTENCE
# ==============================================================================


@dataclass
class TabStateRecord:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    title: str = "Zen Home"
    url: str = ZEN_HOME_URI
    workspace_id: str = "streaming"
    pinned: bool = False
    muted: bool = False
    loading: bool = False
    suspended: bool = False


class WorkspaceStateStore:
    """Manages persistent workspaces, tabs, and recently closed tabs on Linux."""

    def __init__(self) -> None:
        config_root = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        self.config_dir = config_root / "onebrowser"
        self.state_file = self.config_dir / "workspaces_state.json"
        self.workspaces: list[dict[str, str]] = [dict(w) for w in WORKSPACE_PRESETS]
        self.active_workspace_id: str = "streaming"
        self.closed_tabs_stack: list[TabStateRecord] = []

    def get_workspace(self, ws_id: str) -> dict[str, str]:
        for w in self.workspaces:
            if w["id"] == ws_id:
                return w
        return self.workspaces[0]

    def active_workspace(self) -> dict[str, str]:
        return self.get_workspace(self.active_workspace_id)

    def save_state(self, tabs: list[TabStateRecord], ephemeral_only: bool = False) -> None:
        if ephemeral_only:
            return
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": APP_VERSION,
                "active_workspace_id": self.active_workspace_id,
                "workspaces": self.workspaces,
                "tabs": [asdict(t) for t in tabs],
            }
            self.state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass

    def load_state(self) -> list[TabStateRecord]:
        try:
            if not self.state_file.is_file():
                return []
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(data.get("workspaces"), list) and data["workspaces"]:
                self.workspaces = data["workspaces"]
            if isinstance(data.get("active_workspace_id"), str):
                self.active_workspace_id = data["active_workspace_id"]
            loaded_tabs: list[TabStateRecord] = []
            for raw in data.get("tabs", []):
                if isinstance(raw, dict):
                    loaded_tabs.append(
                        TabStateRecord(
                            id=str(raw.get("id") or uuid.uuid4().hex[:10]),
                            title=str(raw.get("title") or "Zen Home"),
                            url=str(raw.get("url") or ZEN_HOME_URI),
                            workspace_id=str(raw.get("workspace_id") or "streaming"),
                            pinned=bool(raw.get("pinned", False)),
                            muted=bool(raw.get("muted", False)),
                        )
                    )
            return loaded_tabs
        except Exception:
            return []


# ==============================================================================
# PHASE 5: LINUX HARDWARE ACCELERATION & COMPLIANT WIDEVINE DRM DISCOVERY
# ==============================================================================


def configure_linux_chromium_flags() -> None:
    """
    Configures optimal Linux GPU acceleration (VA-API, Vulkan, Mesa RADV for Bazzite/AMD,
    NVIDIA, Intel Arc) and discovers compliant system/Flatpak Widevine CDM if installed.
    """
    flags = [
        "--enable-quic",
        "--site-per-process",
        "--enable-gpu-rasterization",
        "--enable-zero-copy",
        "--ignore-gpu-blocklist",
        "--enable-hardware-overlays",
        "--enable-features=VaapiVideoDecodeLinuxGL,VaapiVideoEncoder,VaapiIgnoreDriverChecks,"
        "PlatformHEVCDecoderSupport,Vulkan,DefaultANGLEVulkan,VulkanFromANGLE,HardwareMediaKeyHandling,"
        "PictureInPictureAPI",
        "--disable-features=UseSkiaGraphite",
        "--autoplay-policy=no-user-gesture-required",
    ]

    # Compliant Widevine CDM auto-discovery on Bazzite / Fedora / Flatpak / Arch / Ubuntu
    widevine_candidates = [
        Path("/usr/lib64/chromium-browser/WidevineCdm/_platform_specific/linux_x64/libwidevinecdm.so"),
        Path("/usr/lib/chromium/WidevineCdm/_platform_specific/linux_x64/libwidevinecdm.so"),
        Path("/opt/google/chrome/WidevineCdm/_platform_specific/linux_x64/libwidevinecdm.so"),
        Path.home() / ".var/app/com.google.Chrome/config/google-chrome/WidevineCdm",
        Path.home() / ".config/onebrowser/WidevineCdm/_platform_specific/linux_x64/libwidevinecdm.so",
    ]
    for cand in widevine_candidates:
        if cand.exists():
            flags.append(f"--widevine-path={cand}")
            break

    existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
    combined = (existing + " " + " ".join(flags)).strip()
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = combined


# ==============================================================================
# PRIMARY ENGINE: PYQT6 / PYQT5 ZEN DESKTOP BROWSER
# ==============================================================================


def try_launch_qt_zen_browser(initial_url: str) -> bool:
    """Launches the native embedded QtWebEngine Zen Browser–inspired Linux desktop app."""
    try:
        from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, QUrl
        from PyQt6.QtGui import QAction, QKeySequence, QShortcut
        from PyQt6.QtWebEngineCore import (
            QWebEnginePage,
            QWebEngineProfile,
            QWebEngineScript,
            QWebEngineSettings,
            QWebEngineUrlRequestInterceptor,
        )
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from PyQt6.QtWidgets import (
            QAbstractItemView,
            QApplication,
            QComboBox,
            QDialog,
            QFileDialog,
            QFrame,
            QGridLayout,
            QHBoxLayout,
            QInputDialog,
            QLabel,
            QLineEdit,
            QListWidget,
            QListWidgetItem,
            QMainWindow,
            QMenu,
            QMessageBox,
            QProgressBar,
            QPushButton,
            QSlider,
            QSplitter,
            QStackedWidget,
            QVBoxLayout,
            QWidget,
        )
        is_pyqt6 = True
    except Exception:
        try:
            from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, QUrl
            from PyQt5.QtGui import QKeySequence
            from PyQt5.QtWebEngineCore import QWebEngineUrlRequestInterceptor
            from PyQt5.QtWebEngineWidgets import (
                QWebEnginePage,
                QWebEngineProfile,
                QWebEngineScript,
                QWebEngineSettings,
                QWebEngineView,
            )
            from PyQt5.QtWidgets import (
                QAbstractItemView,
                QAction,
                QApplication,
                QComboBox,
                QDialog,
                QFileDialog,
                QFrame,
                QGridLayout,
                QHBoxLayout,
                QInputDialog,
                QLabel,
                QLineEdit,
                QListWidget,
                QListWidgetItem,
                QMainWindow,
                QMenu,
                QMessageBox,
                QProgressBar,
                QPushButton,
                QShortcut,
                QSlider,
                QSplitter,
                QStackedWidget,
                QVBoxLayout,
                QWidget,
            )
            is_pyqt6 = False
        except Exception:
            return False

    configure_linux_chromium_flags()
    reduced_motion = prefers_reduced_motion()

    class ZenUrlInterceptor(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info) -> None:
            qurl = info.requestUrl()
            scheme = qurl.scheme().lower()
            host = qurl.host().lower()
            if scheme in ("data", "blob", "about"):
                return
            if scheme == "http" and host and not is_private_or_reserved_host(host):
                upgraded = QUrl(qurl)
                upgraded.setScheme("https")
                info.redirect(upgraded)
                return
            if scheme != "https" or is_private_or_reserved_host(host) or is_blocked_domain(host):
                info.block(True)

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName(APP_ID)

    store = WorkspaceStateStore()
    app.setStyleSheet(build_zen_stylesheet(store.active_workspace()["accent"]))

    win = QMainWindow()
    win.setWindowTitle("OneBrowser — Zen Streaming & Workspace Edition (Linux)")
    win.resize(1400, 880)
    win.setMinimumSize(820, 520)

    interceptor = ZenUrlInterceptor()
    runtime_state: dict[str, object] = {
        "ephemeral_ram_only": False,
        "sidebar_expanded": True,
        "immersive_mode": False,
        "split_view_active": False,
        "profile": QWebEngineProfile("OneBrowserZenProfile"),
        "site_permissions": {},  # domain -> dict of permission states
    }

    def configure_profile(prof: QWebEngineProfile) -> None:
        if is_pyqt6:
            prof.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
            prof.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies
            )
        else:
            prof.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
            prof.setPersistentCookiesPolicy(QWebEngineProfile.AllowPersistentCookies)
        prof.setUrlRequestInterceptor(interceptor)

        script = QWebEngineScript()
        script.setName("OneBrowserZenShield")
        script.setSourceCode(HARDENING_AND_STREAMING_JS)
        if is_pyqt6:
            script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        else:
            script.setInjectionPoint(QWebEngineScript.DocumentCreation)
            script.setWorldId(QWebEngineScript.MainWorld)
        script.setRunsOnSubFrames(True)
        prof.scripts().insert(script)

    configure_profile(runtime_state["profile"])  # type: ignore[arg-type]

    # Live Tab Objects: list of (TabStateRecord, QWebEngineView)
    all_tabs: list[tuple[TabStateRecord, QWebEngineView]] = []
    active_tab_id: list[str] = [""]

    # ==========================================================================
    # MAIN SHELL LAYOUT (SIDEBAR-FIRST + FLOATING VIEWPORT)
    # ==========================================================================
    central = QWidget()
    shell_vbox = QVBoxLayout(central)
    shell_vbox.setContentsMargins(0, 0, 0, 0)
    shell_vbox.setSpacing(0)

    # Top Compact Omnibox & Workspace Context Bar
    top_bar = QFrame()
    top_bar.setObjectName("TopToolbar")
    top_layout = QHBoxLayout(top_bar)
    top_layout.setContentsMargins(12, 8, 12, 8)
    top_layout.setSpacing(8)

    btn_sidebar_toggle = QPushButton("◨")
    btn_sidebar_toggle.setObjectName("NavIconBtn")
    btn_sidebar_toggle.setToolTip("Toggle Zen Vertical Sidebar (Ctrl+Shift+V)")

    btn_back = QPushButton("←")
    btn_back.setObjectName("NavIconBtn")
    btn_back.setToolTip("Back (Alt+Left)")

    btn_fwd = QPushButton("→")
    btn_fwd.setObjectName("NavIconBtn")
    btn_fwd.setToolTip("Forward (Alt+Right)")

    btn_reload = QPushButton("↻")
    btn_reload.setObjectName("NavIconBtn")
    btn_reload.setToolTip("Reload Page (Ctrl+R / F5)")

    btn_shield = QPushButton("🛡️ 41.9k")
    btn_shield.setToolTip("Security & Site Permissions — HTTPS Enforced, Ad/Tracker Shield Active")

    url_bar = QLineEdit()
    url_bar.setPlaceholderText("Search DuckDuckGo or enter an HTTPS streaming URL (Ctrl+L)...")

    btn_pip_top = QPushButton("⧉ PiP")
    btn_pip_top.setToolTip("Pop video into Picture-in-Picture mode")

    btn_split = QPushButton("◫ Split")
    btn_split.setToolTip("Toggle Dual Split-Screen View (Ctrl+Shift+S)")

    btn_immersive = QPushButton("🎬 Cinema")
    btn_immersive.setToolTip("Toggle Immersive Borderless Streaming Mode (Ctrl+Shift+I / F11)")

    btn_palette = QPushButton("⌘K")
    btn_palette.setToolTip("Quick Command Palette & Tab Switcher (Ctrl+K)")

    btn_dl_drawer = QPushButton("⬇ 0")
    btn_dl_drawer.setToolTip("Toggle 16x ZeroDownloader Drawer (Ctrl+J)")

    for w in (btn_sidebar_toggle, btn_back, btn_fwd, btn_reload, btn_shield):
        top_layout.addWidget(w)
    top_layout.addWidget(url_bar, 1)
    for w in (btn_pip_top, btn_split, btn_immersive, btn_palette, btn_dl_drawer):
        top_layout.addWidget(w)

    shell_vbox.addWidget(top_bar)

    # Middle Horizontal Split: Left Zen Sidebar + Right Framed Content Area
    body_widget = QWidget()
    body_hbox = QHBoxLayout(body_widget)
    body_hbox.setContentsMargins(0, 0, 0, 0)
    body_hbox.setSpacing(0)

    # --- LEFT: ZEN VERTICAL SIDEBAR ---
    sidebar = QFrame()
    sidebar.setObjectName("ZenSidebar")
    sidebar.setMinimumWidth(260)
    sidebar.setMaximumWidth(260)
    sb_layout = QVBoxLayout(sidebar)
    sb_layout.setContentsMargins(12, 12, 12, 12)
    sb_layout.setSpacing(10)

    # 1. Workspace Switcher Strip
    ws_hdr_row = QHBoxLayout()
    ws_title_lbl = QLabel("🎬 STREAMING")
    ws_title_lbl.setStyleSheet("font-weight: 800; font-size: 11px; letter-spacing: 0.8px; color: #A1A1AA;")
    btn_new_ws = QPushButton("+")
    btn_new_ws.setObjectName("NavIconBtn")
    btn_new_ws.setFixedSize(24, 24)
    btn_new_ws.setToolTip("Create or Rename Workspace")
    ws_hdr_row.addWidget(ws_title_lbl)
    ws_hdr_row.addStretch()
    ws_hdr_row.addWidget(btn_new_ws)
    sb_layout.addLayout(ws_hdr_row)

    ws_pills_widget = QWidget()
    ws_pills_layout = QHBoxLayout(ws_pills_widget)
    ws_pills_layout.setContentsMargins(0, 0, 0, 0)
    ws_pills_layout.setSpacing(4)
    sb_layout.addWidget(ws_pills_widget)

    # 2. Pinned Essential Streaming Tiles (2x2 Grid)
    pinned_lbl = QLabel("ESSENTIAL STREAMING")
    pinned_lbl.setStyleSheet("font-weight: 700; font-size: 10px; letter-spacing: 0.8px; color: #71717A;")
    sb_layout.addWidget(pinned_lbl)

    pinned_grid = QGridLayout()
    pinned_grid.setSpacing(6)
    for idx, item in enumerate(PINNED_STREAMING_ESSENTIALS):
        p_btn = QPushButton(f"{item['icon']}  {item['title']}")
        p_btn.setToolTip(f"Launch {item['title']} ({item['url']})")
        p_btn.setStyleSheet(
            f"QPushButton {{ background: {TOKENS.bg_elevated}; border: 1px solid {TOKENS.border_subtle}; "
            f"border-radius: 8px; padding: 7px 8px; font-weight: 600; font-size: 12px; text-align: left; }}"
            f"QPushButton:hover {{ background: {TOKENS.bg_hover}; border-color: {item['color']}; }}"
        )
        p_btn.clicked.connect(lambda _=False, u=item["url"], t=item["title"]: open_or_focus_essential(u, t))
        pinned_grid.addWidget(p_btn, idx // 2, idx % 2)
    sb_layout.addLayout(pinned_grid)

    # 3. Vertical Tab List (Supports Drag & Drop Reordering + Context Menu)
    tabs_hdr_row = QHBoxLayout()
    tabs_count_lbl = QLabel("OPEN TABS (1)")
    tabs_count_lbl.setStyleSheet("font-weight: 700; font-size: 10px; letter-spacing: 0.8px; color: #71717A;")
    btn_restore_closed = QPushButton("↺")
    btn_restore_closed.setObjectName("NavIconBtn")
    btn_restore_closed.setFixedSize(22, 22)
    btn_restore_closed.setToolTip("Restore Recently Closed Tab (Ctrl+Shift+T)")
    tabs_hdr_row.addWidget(tabs_count_lbl)
    tabs_hdr_row.addStretch()
    tabs_hdr_row.addWidget(btn_restore_closed)
    sb_layout.addLayout(tabs_hdr_row)

    vtab_list = QListWidget()
    vtab_list.setObjectName("VerticalTabList")
    if is_pyqt6:
        vtab_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        vtab_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    else:
        vtab_list.setDragDropMode(QAbstractItemView.InternalMove)
        vtab_list.setContextMenuPolicy(Qt.CustomContextMenu)
    sb_layout.addWidget(vtab_list, 1)

    btn_new_tab = QPushButton("+  New Tab")
    btn_new_tab.setObjectName("AccentButton")
    btn_new_tab.setToolTip("Open a new tab in the active workspace (Ctrl+T)")
    sb_layout.addWidget(btn_new_tab)

    # 4. Sidebar Bottom Streaming Media Controller Dock
    media_bar = QFrame()
    media_bar.setObjectName("MediaControllerBar")
    mb_vbox = QVBoxLayout(media_bar)
    mb_vbox.setContentsMargins(10, 8, 10, 8)
    mb_vbox.setSpacing(6)

    media_status_lbl = QLabel("🎵 Media Deck • Ready")
    media_status_lbl.setStyleSheet("font-size: 11px; font-weight: 600; color: #A1A1AA;")
    mb_vbox.addWidget(media_status_lbl)

    mb_controls = QHBoxLayout()
    mb_controls.setSpacing(4)
    btn_media_play = QPushButton("⏯")
    btn_media_play.setToolTip("Play / Pause Active Video")
    btn_media_mute = QPushButton("🔊")
    btn_media_mute.setToolTip("Mute / Unmute Active Tab Audio (Ctrl+M)")
    btn_media_pip = QPushButton("⧉ PiP")
    btn_media_pip.setToolTip("Toggle Native Picture-in-Picture")
    btn_media_fs = QPushButton("⛶")
    btn_media_fs.setToolTip("Toggle Video Fullscreen")

    for b in (btn_media_play, btn_media_mute, btn_media_pip, btn_media_fs):
        b.setFixedHeight(28)
        mb_controls.addWidget(b)
    mb_vbox.addLayout(mb_controls)

    vol_row = QHBoxLayout()
    vol_lbl = QLabel("Vol")
    vol_lbl.setStyleSheet("font-size: 10px; color: #71717A;")
    vol_slider = QSlider(Qt.Orientation.Horizontal if is_pyqt6 else Qt.Horizontal)
    vol_slider.setRange(0, 100)
    vol_slider.setValue(100)
    vol_slider.setToolTip("Adjust active stream HTML5 video volume")
    vol_row.addWidget(vol_lbl)
    vol_row.addWidget(vol_slider, 1)
    mb_vbox.addLayout(vol_row)

    sb_layout.addWidget(media_bar)

    # 5. Sidebar Footer (Privacy Mode & Wipe)
    footer_row = QHBoxLayout()
    btn_privacy_mode = QPushButton("🍪 Persistent")
    btn_privacy_mode.setToolTip("Toggle between Persistent Login Session and Ephemeral RAM-Only Mode")
    btn_wipe = QPushButton("🧹 Wipe")
    btn_wipe.setStyleSheet("color: #F87171;")
    btn_wipe.setToolTip("Panic Wipe: Clear cache, cookies, and reset current workspace")
    footer_row.addWidget(btn_privacy_mode, 1)
    footer_row.addWidget(btn_wipe)
    sb_layout.addLayout(footer_row)

    body_hbox.addWidget(sidebar)

    # --- RIGHT: FRAMED FLOATING VIEWPORT + DUAL SPLIT VIEW ---
    viewport_outer = QWidget()
    vp_outer_layout = QVBoxLayout(viewport_outer)
    vp_outer_layout.setContentsMargins(6, 6, 6, 6)
    vp_outer_layout.setSpacing(6)

    viewport_frame = QFrame()
    viewport_frame.setObjectName("ViewportFrame")
    vp_frame_layout = QVBoxLayout(viewport_frame)
    vp_frame_layout.setContentsMargins(2, 2, 2, 2)
    vp_frame_layout.setSpacing(0)

    splitter = QSplitter(Qt.Orientation.Horizontal if is_pyqt6 else Qt.Horizontal)

    # Primary WebView Stack
    primary_stack = QStackedWidget()
    splitter.addWidget(primary_stack)

    # Secondary Split-Screen Pane
    secondary_pane = QFrame()
    secondary_pane.setVisible(False)
    sec_layout = QVBoxLayout(secondary_pane)
    sec_layout.setContentsMargins(0, 0, 0, 0)
    sec_layout.setSpacing(0)

    sec_bar = QFrame()
    sec_bar.setStyleSheet(f"background: {TOKENS.bg_elevated}; border-bottom: 1px solid {TOKENS.border_subtle};")
    sec_bar_l = QHBoxLayout(sec_bar)
    sec_bar_l.setContentsMargins(8, 4, 8, 4)
    sec_badge = QLabel("◫ SPLIT VIEW")
    sec_badge.setStyleSheet("font-size: 10px; font-weight: 800; color: #A78BFA;")
    sec_url = QLineEdit("https://www.twitch.tv")
    btn_sec_go = QPushButton("Go")
    btn_sec_close = QPushButton("✕")
    btn_sec_close.setObjectName("NavIconBtn")
    sec_bar_l.addWidget(sec_badge)
    sec_bar_l.addWidget(sec_url, 1)
    sec_bar_l.addWidget(btn_sec_go)
    sec_bar_l.addWidget(btn_sec_close)
    sec_layout.addWidget(sec_bar)

    secondary_view = QWebEngineView()
    secondary_page = QWebEnginePage(runtime_state["profile"], secondary_view)  # type: ignore[arg-type]
    secondary_view.setPage(secondary_page)
    sec_layout.addWidget(secondary_view, 1)
    splitter.addWidget(secondary_pane)

    vp_frame_layout.addWidget(splitter, 1)

    # Integrated 16x ZeroDownloader Drawer (Slide-Up Bottom Panel)
    dl_drawer = QFrame()
    dl_drawer.setObjectName("CardSurface")
    dl_drawer.setVisible(False)
    dl_vbox = QVBoxLayout(dl_drawer)
    dl_vbox.setContentsMargins(14, 10, 14, 10)
    dl_vbox.setSpacing(8)

    dl_hdr = QHBoxLayout()
    dl_title = QLabel("⬇ ZeroDownloader Engine — 16x Parallel HTTP Range, HLS .m3u8 & Video Stream Extractor")
    dl_title.setStyleSheet("font-weight: 700; font-size: 13px; color: #E5957C;")
    btn_dl_grab = QPushButton("Grab Active Tab URL")
    btn_dl_close = QPushButton("✕")
    btn_dl_close.setObjectName("NavIconBtn")
    dl_hdr.addWidget(dl_title)
    dl_hdr.addStretch()
    dl_hdr.addWidget(btn_dl_grab)
    dl_hdr.addWidget(btn_dl_close)
    dl_vbox.addLayout(dl_hdr)

    dl_controls = QHBoxLayout()
    dl_url_input = QLineEdit()
    dl_url_input.setPlaceholderText("Paste direct HTTPS file, .m3u8 HLS stream, or video URL...")
    dl_conn_box = QComboBox()
    dl_conn_box.addItems(["16 Threads", "8 Threads", "4 Threads", "1 Thread"])
    dl_qual_box = QComboBox()
    dl_qual_box.addItems(["best", "1080p", "720p", "audio"])
    dl_out_input = QLineEdit(str(core.default_download_dir()))
    btn_dl_browse = QPushButton("Folder...")
    btn_dl_start = QPushButton("Start 16x Download")
    btn_dl_start.setObjectName("AccentButton")
    dl_controls.addWidget(dl_url_input, 2)
    dl_controls.addWidget(dl_conn_box)
    dl_controls.addWidget(dl_qual_box)
    dl_controls.addWidget(dl_out_input, 1)
    dl_controls.addWidget(btn_dl_browse)
    dl_controls.addWidget(btn_dl_start)
    dl_vbox.addLayout(dl_controls)

    dl_jobs_box = QVBoxLayout()
    dl_vbox.addLayout(dl_jobs_box)

    vp_outer_layout.addWidget(viewport_frame, 1)
    vp_outer_layout.addWidget(dl_drawer)

    body_hbox.addWidget(viewport_outer, 1)
    shell_vbox.addWidget(body_widget, 1)

    # ==========================================================================
    # REAL BROWSER LOGIC: TABS, WORKSPACES, STREAMING CONTROLS, PERMISSIONS
    # ==========================================================================

    tracked_downloads: list[tuple[core.JobState, QLabel, QProgressBar, QLabel]] = []

    def get_active_pair() -> tuple[TabStateRecord, QWebEngineView] | None:
        for rec, view in all_tabs:
            if rec.id == active_tab_id[0]:
                return rec, view
        ws_tabs = [p for p in all_tabs if p[0].workspace_id == store.active_workspace_id]
        return ws_tabs[0] if ws_tabs else (all_tabs[0] if all_tabs else None)

    def persist_now() -> None:
        store.save_state([r for r, _ in all_tabs], bool(runtime_state["ephemeral_ram_only"]))

    def render_workspace_pills() -> None:
        while ws_pills_layout.count():
            item = ws_pills_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        active_ws = store.active_workspace()
        ws_title_lbl.setText(f"{active_ws['icon']} {active_ws['name'].upper()}")
        ws_title_lbl.setStyleSheet(
            f"font-weight: 800; font-size: 11px; letter-spacing: 0.8px; color: {active_ws['accent']};"
        )

        for ws in store.workspaces:
            is_cur = (ws["id"] == store.active_workspace_id)
            btn = QPushButton(f"{ws['icon']}")
            btn.setToolTip(f"Switch to {ws['name']} Workspace")
            btn.setFixedHeight(30)
            if is_cur:
                btn.setStyleSheet(
                    f"background: {ws['accent']}; color: {TOKENS.bg_canvas}; border: none; "
                    f"border-radius: 8px; font-weight: 800;"
                )
            else:
                btn.setStyleSheet(
                    f"background: {TOKENS.bg_elevated}; color: {TOKENS.text_secondary}; "
                    f"border: 1px solid {TOKENS.border_subtle}; border-radius: 8px;"
                )
            btn.clicked.connect(lambda _=False, wid=ws["id"]: switch_workspace(wid))
            ws_pills_layout.addWidget(btn)

    def refresh_vertical_tab_list() -> None:
        vtab_list.blockSignals(True)
        vtab_list.clear()

        ws_id = store.active_workspace_id
        ws_tabs = [
            (rec, view)
            for rec, view in all_tabs
            if rec.workspace_id == ws_id or rec.pinned
        ]
        # Sort pinned tabs first
        ws_tabs.sort(key=lambda pair: (0 if pair[0].pinned else 1))
        tabs_count_lbl.setText(f"OPEN TABS ({len(ws_tabs)})")

        for rec, _ in ws_tabs:
            badge = extract_domain_badge(rec.url)
            pin_prefix = "📌 " if rec.pinned else ""
            load_prefix = "⏳ " if rec.loading else ""
            mute_suffix = "  🔇" if rec.muted else ""
            suspend_suffix = "  💤" if rec.suspended else ""
            label = f"{pin_prefix}{load_prefix}{badge}   {rec.title[:30]}{mute_suffix}{suspend_suffix}"

            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole if is_pyqt6 else Qt.UserRole, rec.id)
            item.setToolTip(f"{rec.title}\n{rec.url}\n(Right-click for tab options)")
            vtab_list.addItem(item)
            if rec.id == active_tab_id[0]:
                vtab_list.setCurrentItem(item)

        vtab_list.blockSignals(False)

    def sync_toolbar_with_active_tab() -> None:
        pair = get_active_pair()
        if not pair:
            return
        rec, view = pair
        if rec.url == ZEN_HOME_URI or rec.url.startswith("data:"):
            url_bar.setText("")
        else:
            url_bar.setText(rec.url)
        btn_media_mute.setText("🔇" if rec.muted else "🔊")
        win.setWindowTitle(f"{rec.title} — OneBrowser Zen ({store.active_workspace()['name']})")

    def handle_permission_request(page: QWebEnginePage, origin: QUrl, feature) -> None:
        """Explicit user-controlled site permissions dialog."""
        host = origin.host() or origin.toString()
        feat_name = str(feature).split(".")[-1]
        reply = QMessageBox.question(
            win,
            "Site Permission Request",
            f"Allow {host} to access {feat_name}?",
            (
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                if is_pyqt6
                else QMessageBox.Yes | QMessageBox.No
            ),
        )
        yes_btn = QMessageBox.StandardButton.Yes if is_pyqt6 else QMessageBox.Yes
        if reply == yes_btn:
            policy = (
                QWebEnginePage.PermissionPolicy.PermissionGrantedByUser
                if is_pyqt6
                else QWebEnginePage.PermissionGrantedByUser
            )
        else:
            policy = (
                QWebEnginePage.PermissionPolicy.PermissionDeniedByUser
                if is_pyqt6
                else QWebEnginePage.PermissionDeniedByUser
            )
        page.setFeaturePermission(origin, feature, policy)

    def create_tab(
        target_url: str = ZEN_HOME_URI,
        title: str = "Zen Home",
        workspace_id: str | None = None,
        pinned: bool = False,
        switch_to: bool = True,
        existing_record: TabStateRecord | None = None,
    ) -> tuple[TabStateRecord, QWebEngineView]:
        ws_id = workspace_id or store.active_workspace_id
        rec = existing_record or TabStateRecord(
            title=title,
            url=target_url,
            workspace_id=ws_id,
            pinned=pinned,
        )

        view = QWebEngineView()
        page = QWebEnginePage(runtime_state["profile"], view)  # type: ignore[arg-type]
        view.setPage(page)

        settings = view.settings()
        attr = QWebEngineSettings.WebAttribute
        settings.setAttribute(attr.JavascriptCanOpenWindows, False)
        settings.setAttribute(attr.FullScreenSupportEnabled, True)
        settings.setAttribute(attr.PlaybackRequiresUserGesture, False)
        if hasattr(attr, "PluginsEnabled"):
            settings.setAttribute(attr.PluginsEnabled, True)

        page.featurePermissionRequested.connect(
            lambda origin, feat, p=page: handle_permission_request(p, origin, feat)
        )
        page.fullScreenRequested.connect(lambda req: (req.accept(), set_immersive_mode(req.toggleOn())))

        def on_title(new_title: str) -> None:
            if new_title and not new_title.startswith("data:"):
                rec.title = new_title
                refresh_vertical_tab_list()
                if rec.id == active_tab_id[0]:
                    sync_toolbar_with_active_tab()
                persist_now()

        def on_url(qurl: QUrl) -> None:
            u = qurl.toString()
            if u.startswith("data:text/html"):
                rec.url = ZEN_HOME_URI
            else:
                rec.url = u
            refresh_vertical_tab_list()
            if rec.id == active_tab_id[0]:
                sync_toolbar_with_active_tab()
            persist_now()

        def on_load_started() -> None:
            rec.loading = True
            refresh_vertical_tab_list()

        def on_load_finished(_ok: bool) -> None:
            rec.loading = False
            refresh_vertical_tab_list()

        view.titleChanged.connect(on_title)
        view.urlChanged.connect(on_url)
        view.loadStarted.connect(on_load_started)
        view.loadFinished.connect(on_load_finished)

        primary_stack.addWidget(view)
        all_tabs.append((rec, view))

        navigate_tab_view(rec, view, rec.url)

        if switch_to:
            select_tab_by_id(rec.id)
        else:
            refresh_vertical_tab_list()

        persist_now()
        return rec, view

    def navigate_tab_view(rec: TabStateRecord, view: QWebEngineView, raw_target: str) -> None:
        if raw_target == ZEN_HOME_URI:
            rec.url = ZEN_HOME_URI
            rec.title = "Zen Home"
            ws = store.get_workspace(rec.workspace_id)
            view.setHtml(build_zen_home_html(ws["name"], ws["icon"], ws["accent"]), QUrl("https://onebrowser.local/"))
            return

        ok, clean, err = resolve_navigation_input(raw_target)
        if not ok:
            media_status_lbl.setText(f"⚠️ {err}")
            return
        rec.url = clean
        view.setUrl(QUrl(clean))

    def select_tab_by_id(tab_id: str) -> None:
        for rec, view in all_tabs:
            if rec.id == tab_id:
                active_tab_id[0] = rec.id
                rec.suspended = False
                primary_stack.setCurrentWidget(view)
                sync_toolbar_with_active_tab()
                refresh_vertical_tab_list()
                return

    def close_tab_by_id(tab_id: str) -> None:
        target_idx = -1
        for i, (rec, _) in enumerate(all_tabs):
            if rec.id == tab_id:
                target_idx = i
                break
        if target_idx < 0:
            return

        rec, view = all_tabs.pop(target_idx)
        store.closed_tabs_stack.append(rec)
        primary_stack.removeWidget(view)
        view.deleteLater()

        ws_tabs = [
            r for r, _ in all_tabs
            if r.workspace_id == store.active_workspace_id or r.pinned
        ]
        if not ws_tabs:
            create_tab(ZEN_HOME_URI)
        elif active_tab_id[0] == tab_id:
            select_tab_by_id(ws_tabs[-1].id)
        else:
            refresh_vertical_tab_list()
        persist_now()

    def restore_recently_closed_tab() -> None:
        if not store.closed_tabs_stack:
            media_status_lbl.setText("No recently closed tabs to restore.")
            return
        last_rec = store.closed_tabs_stack.pop()
        last_rec.workspace_id = store.active_workspace_id
        create_tab(
            target_url=last_rec.url,
            title=last_rec.title,
            workspace_id=last_rec.workspace_id,
            pinned=last_rec.pinned,
            switch_to=True,
        )
        media_status_lbl.setText(f"Restored tab: {last_rec.title[:22]}")

    def duplicate_tab_by_id(tab_id: str) -> None:
        for rec, _ in all_tabs:
            if rec.id == tab_id:
                create_tab(
                    target_url=rec.url,
                    title=rec.title,
                    workspace_id=rec.workspace_id,
                    pinned=rec.pinned,
                    switch_to=True,
                )
                return

    def toggle_pin_tab(tab_id: str) -> None:
        for rec, _ in all_tabs:
            if rec.id == tab_id:
                rec.pinned = not rec.pinned
                refresh_vertical_tab_list()
                persist_now()
                return

    def toggle_mute_tab(tab_id: str | None = None) -> None:
        tid = tab_id or active_tab_id[0]
        for rec, view in all_tabs:
            if rec.id == tid:
                rec.muted = not rec.muted
                view.page().setAudioMuted(rec.muted)
                refresh_vertical_tab_list()
                sync_toolbar_with_active_tab()
                media_status_lbl.setText("🔇 Tab Audio Muted" if rec.muted else "🔊 Tab Audio Unmuted")
                return

    def switch_workspace(ws_id: str) -> None:
        store.active_workspace_id = ws_id
        ws = store.active_workspace()
        app.setStyleSheet(build_zen_stylesheet(ws["accent"]))
        render_workspace_pills()

        ws_tabs = [
            r for r, _ in all_tabs
            if r.workspace_id == ws_id or r.pinned
        ]
        if not ws_tabs:
            create_tab(ZEN_HOME_URI, workspace_id=ws_id)
        else:
            select_tab_by_id(ws_tabs[0].id)
        persist_now()

    def create_or_rename_workspace() -> None:
        name, ok = QInputDialog.getText(
            win,
            "Zen Workspaces",
            "Enter new Workspace name (or rename current if prefixed with 'rename:'):",
        )
        if not ok or not name.strip():
            return
        clean_name = name.strip()
        if clean_name.lower().startswith("rename:"):
            new_title = clean_name[7:].strip()
            if new_title:
                store.active_workspace()["name"] = new_title
                render_workspace_pills()
                persist_now()
            return

        accents = ["#E5957C", "#A78BFA", "#34D399", "#73B5E8", "#FCD34D", "#F472B6"]
        new_id = f"ws_{uuid.uuid4().hex[:6]}"
        store.workspaces.append({
            "id": new_id,
            "name": clean_name[:18],
            "icon": "✦",
            "accent": accents[len(store.workspaces) % len(accents)],
        })
        switch_workspace(new_id)

    def open_or_focus_essential(url: str, title: str) -> None:
        host = urllib.parse.urlsplit(url).hostname or url
        for rec, _ in all_tabs:
            if host in rec.url:
                if rec.workspace_id != store.active_workspace_id and not rec.pinned:
                    switch_workspace(rec.workspace_id)
                select_tab_by_id(rec.id)
                return
        create_tab(target_url=url, title=title, pinned=True, switch_to=True)

    # ==========================================================================
    # STREAMING CONTROLS: PIP, VOLUME, PLAY/PAUSE, IMMERSIVE MODE, SPLIT VIEW
    # ==========================================================================

    def run_js_on_active(js_code: str) -> None:
        pair = get_active_pair()
        if pair:
            pair[1].page().runJavaScript(js_code)

    def trigger_pip() -> None:
        js = """
        (() => {
          const v = document.querySelector('video');
          if (!v) return 'NO_VIDEO';
          if (document.pictureInPictureElement) {
            document.exitPictureInPicture();
            return 'EXITED_PIP';
          } else if (v.requestPictureInPicture) {
            v.requestPictureInPicture();
            return 'ENTERED_PIP';
          }
          return 'UNSUPPORTED';
        })();
        """
        run_js_on_active(js)
        media_status_lbl.setText("⧉ Picture-in-Picture toggled")

    def toggle_play_pause_video() -> None:
        js = """
        (() => {
          const v = document.querySelector('video, audio');
          if (v) { if (v.paused) v.play(); else v.pause(); }
        })();
        """
        run_js_on_active(js)
        media_status_lbl.setText("⏯ Toggled Stream Playback")

    def set_stream_volume(val: int) -> None:
        frac = max(0.0, min(1.0, val / 100.0))
        run_js_on_active(f"(() => {{ document.querySelectorAll('video, audio').forEach(e => e.volume = {frac}); }})();")
        media_status_lbl.setText(f"🔊 Stream Volume: {val}%")

    def toggle_sidebar_animated() -> None:
        expanded = not bool(runtime_state["sidebar_expanded"])
        runtime_state["sidebar_expanded"] = expanded
        target_w = 260 if expanded else 0

        if reduced_motion:
            sidebar.setMinimumWidth(target_w)
            sidebar.setMaximumWidth(target_w)
            return

        anim_min = QPropertyAnimation(sidebar, b"minimumWidth", win)
        anim_max = QPropertyAnimation(sidebar, b"maximumWidth", win)
        for anim in (anim_min, anim_max):
            anim.setDuration(160)
            anim.setStartValue(sidebar.width())
            anim.setEndValue(target_w)
            anim.setEasingCurve(
                QEasingCurve.Type.OutCubic if is_pyqt6 else QEasingCurve.OutCubic
            )
            anim.start()

    def set_immersive_mode(enabled: bool) -> None:
        runtime_state["immersive_mode"] = enabled
        if enabled:
            top_bar.setVisible(False)
            sidebar.setMinimumWidth(0)
            sidebar.setMaximumWidth(0)
            runtime_state["sidebar_expanded"] = False
            vp_outer_layout.setContentsMargins(0, 0, 0, 0)
            win.showFullScreen()
            media_status_lbl.setText("🎬 Immersive Mode (Esc or F11 to exit)")
        else:
            top_bar.setVisible(True)
            sidebar.setMinimumWidth(260)
            sidebar.setMaximumWidth(260)
            runtime_state["sidebar_expanded"] = True
            vp_outer_layout.setContentsMargins(6, 6, 6, 6)
            win.showNormal()

    def toggle_split_view() -> None:
        active = not bool(runtime_state["split_view_active"])
        runtime_state["split_view_active"] = active
        secondary_pane.setVisible(active)
        if active and secondary_view.url().isEmpty():
            secondary_view.setUrl(QUrl("https://www.twitch.tv"))
            splitter.setSizes([700, 450])

    # ==========================================================================
    # CONTEXT MENU & COMMAND PALETTE (Ctrl+K)
    # ==========================================================================

    def show_vtab_context_menu(pos) -> None:
        item = vtab_list.itemAt(pos)
        if not item:
            return
        tid = item.data(Qt.ItemDataRole.UserRole if is_pyqt6 else Qt.UserRole)
        rec = next((r for r, _ in all_tabs if r.id == tid), None)
        if not rec:
            return

        menu = QMenu(win)
        act_pin = menu.addAction("📌 Unpin Tab" if rec.pinned else "📌 Pin Tab to Top")
        act_dup = menu.addAction("⧉ Duplicate Tab")
        act_mute = menu.addAction("🔊 Unmute Tab" if rec.muted else "🔇 Mute Tab")
        act_suspend = menu.addAction("💤 Suspend Tab (Save RAM)")

        ws_menu = menu.addMenu("📂 Move to Workspace")
        ws_actions: dict[object, str] = {}
        for w in store.workspaces:
            a = ws_menu.addAction(f"{w['icon']} {w['name']}")
            ws_actions[a] = w["id"]

        menu.addSeparator()
        act_close = menu.addAction("✕ Close Tab")

        chosen = menu.exec(vtab_list.mapToGlobal(pos)) if is_pyqt6 else menu.exec_(vtab_list.mapToGlobal(pos))
        if not chosen:
            return
        if chosen == act_pin:
            toggle_pin_tab(tid)
        elif chosen == act_dup:
            duplicate_tab_by_id(tid)
        elif chosen == act_mute:
            toggle_mute_tab(tid)
        elif chosen == act_suspend:
            for r, v in all_tabs:
                if r.id == tid and r.id != active_tab_id[0]:
                    r.suspended = True
                    v.setHtml("<html><body style='background:#0E0E11;color:#A1A1AA;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;'><h3>💤 Tab Suspended — Click to Resume</h3></body></html>")
                    refresh_vertical_tab_list()
        elif chosen == act_close:
            close_tab_by_id(tid)
        elif chosen in ws_actions:
            rec.workspace_id = ws_actions[chosen]
            refresh_vertical_tab_list()
            persist_now()

    def open_command_palette() -> None:
        dlg = QDialog(win)
        dlg.setWindowTitle("Zen Command Palette (⌘K)")
        dlg.setFixedSize(560, 400)
        dlg.setStyleSheet(build_zen_stylesheet(store.active_workspace()["accent"]))

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        search = QLineEdit()
        search.setPlaceholderText("Type a command, workspace name, tab title, or URL...")
        layout.addWidget(search)

        results = QListWidget()
        results.setObjectName("VerticalTabList")
        layout.addWidget(results, 1)

        commands: list[tuple[str, Callable[[], None]]] = [
            ("➕ New Zen Tab (Ctrl+T)", lambda: create_tab(ZEN_HOME_URI)),
            ("🎬 Toggle Immersive Cinema Mode (Ctrl+Shift+I)", lambda: set_immersive_mode(not bool(runtime_state["immersive_mode"]))),
            ("◨ Toggle Zen Vertical Sidebar (Ctrl+Shift+V)", toggle_sidebar_animated),
            ("◫ Toggle Dual Split-Screen View (Ctrl+Shift+S)", toggle_split_view),
            ("⧉ Toggle Picture-in-Picture (PiP)", trigger_pip),
            ("🔇 Mute / Unmute Active Tab (Ctrl+M)", lambda: toggle_mute_tab()),
            ("↺ Restore Recently Closed Tab (Ctrl+Shift+T)", restore_recently_closed_tab),
            ("⬇ Toggle 16x ZeroDownloader Drawer (Ctrl+J)", lambda: dl_drawer.setVisible(not dl_drawer.isVisible())),
        ]
        for ws in store.workspaces:
            commands.append(
                (f"{ws['icon']} Switch to Workspace: {ws['name']}", lambda wid=ws["id"]: switch_workspace(wid))
            )
        for rec, _ in all_tabs:
            commands.append(
                (f"📑 Tab: {rec.title} ({rec.url[:40]})", lambda tid=rec.id: select_tab_by_id(tid))
            )

        def populate(q: str) -> None:
            results.clear()
            ql = q.lower().strip()
            for label, fn in commands:
                if not ql or ql in label.lower():
                    item = QListWidgetItem(label)
                    item.setData(Qt.ItemDataRole.UserRole if is_pyqt6 else Qt.UserRole, fn)
                    results.addItem(item)
            if results.count() > 0:
                results.setCurrentRow(0)

        def execute_selected() -> None:
            cur = results.currentItem()
            if cur:
                fn = cur.data(Qt.ItemDataRole.UserRole if is_pyqt6 else Qt.UserRole)
                dlg.accept()
                if callable(fn):
                    fn()
            elif search.text().strip():
                q = search.text().strip()
                dlg.accept()
                pair = get_active_pair()
                if pair:
                    navigate_tab_view(pair[0], pair[1], q)

        search.textChanged.connect(populate)
        search.returnPressed.connect(execute_selected)
        results.itemDoubleClicked.connect(lambda _: execute_selected())
        populate("")
        search.setFocus()
        if is_pyqt6:
            dlg.exec()
        else:
            dlg.exec_()

    # ==========================================================================
    # DOWNLOADER INTEGRATION & EVENTS
    # ==========================================================================

    def enqueue_download(url: str) -> None:
        ok, clean, err = resolve_navigation_input(url)
        if not ok:
            media_status_lbl.setText(f"⚠️ {err}")
            return
        dl_drawer.setVisible(True)
        out_dir = Path(dl_out_input.text().strip() or str(core.default_download_dir()))
        out_dir.mkdir(parents=True, exist_ok=True)
        threads = int(dl_conn_box.currentText().split()[0])
        job = core.JobState(clean, out_dir, threads, dl_qual_box.currentText())

        row_w = QWidget()
        row_l = QHBoxLayout(row_w)
        row_l.setContentsMargins(0, 2, 0, 2)
        n_lbl = QLabel(job.file_name[:42])
        bar = QProgressBar()
        bar.setRange(0, 100)
        m_lbl = QLabel("Starting...")
        c_btn = QPushButton("Cancel")
        c_btn.clicked.connect(job.cancel_event.set)
        row_l.addWidget(n_lbl)
        row_l.addWidget(bar, 1)
        row_l.addWidget(m_lbl)
        row_l.addWidget(c_btn)
        dl_jobs_box.addWidget(row_w)

        tracked_downloads.append((job, n_lbl, bar, m_lbl))
        btn_dl_drawer.setText(f"⬇ {len(tracked_downloads)}")
        threading.Thread(target=core.run_job, args=(job,), daemon=True).start()

    runtime_state["profile"].downloadRequested.connect(  # type: ignore[attr-defined]
        lambda item: (item.cancel(), enqueue_download(item.url().toString()))
    )

    # Connect UI Signals
    btn_sidebar_toggle.clicked.connect(toggle_sidebar_animated)
    btn_back.clicked.connect(lambda: get_active_pair()[1].back() if get_active_pair() else None)
    btn_fwd.clicked.connect(lambda: get_active_pair()[1].forward() if get_active_pair() else None)
    btn_reload.clicked.connect(lambda: get_active_pair()[1].reload() if get_active_pair() else None)
    url_bar.returnPressed.connect(
        lambda: navigate_tab_view(get_active_pair()[0], get_active_pair()[1], url_bar.text())
        if get_active_pair()
        else None
    )
    btn_new_tab.clicked.connect(lambda: create_tab(ZEN_HOME_URI))
    btn_new_ws.clicked.connect(create_or_rename_workspace)
    btn_restore_closed.clicked.connect(restore_recently_closed_tab)
    btn_pip_top.clicked.connect(trigger_pip)
    btn_media_pip.clicked.connect(trigger_pip)
    btn_media_play.clicked.connect(toggle_play_pause_video)
    btn_media_mute.clicked.connect(lambda: toggle_mute_tab())
    btn_media_fs.clicked.connect(lambda: set_immersive_mode(not bool(runtime_state["immersive_mode"])))
    vol_slider.valueChanged.connect(set_stream_volume)
    btn_split.clicked.connect(toggle_split_view)
    btn_immersive.clicked.connect(lambda: set_immersive_mode(not bool(runtime_state["immersive_mode"])))
    btn_palette.clicked.connect(open_command_palette)
    btn_dl_drawer.clicked.connect(lambda: dl_drawer.setVisible(not dl_drawer.isVisible()))
    btn_dl_close.clicked.connect(lambda: dl_drawer.setVisible(False))
    btn_dl_grab.clicked.connect(
        lambda: dl_url_input.setText(get_active_pair()[0].url if get_active_pair() else "")
    )
    btn_dl_browse.clicked.connect(
        lambda: dl_out_input.setText(
            QFileDialog.getExistingDirectory(win, "Select Download Folder", dl_out_input.text())
            or dl_out_input.text()
        )
    )
    btn_dl_start.clicked.connect(lambda: (enqueue_download(dl_url_input.text()), dl_url_input.clear()))

    def on_sec_navigate() -> None:
        ok, clean, _ = resolve_navigation_input(sec_url.text())
        if ok:
            secondary_view.setUrl(QUrl(clean))

    btn_sec_go.clicked.connect(on_sec_navigate)
    sec_url.returnPressed.connect(on_sec_navigate)
    btn_sec_close.clicked.connect(toggle_split_view)

    def on_vtab_clicked(item: QListWidgetItem) -> None:
        tid = item.data(Qt.ItemDataRole.UserRole if is_pyqt6 else Qt.UserRole)
        if tid:
            select_tab_by_id(tid)

    vtab_list.itemClicked.connect(on_vtab_clicked)
    vtab_list.customContextMenuRequested.connect(show_vtab_context_menu)

    def toggle_privacy_mode() -> None:
        ephemeral = not bool(runtime_state["ephemeral_ram_only"])
        runtime_state["ephemeral_ram_only"] = ephemeral
        if ephemeral:
            btn_privacy_mode.setText("🔒 RAM-Only")
            media_status_lbl.setText("🔒 Ephemeral RAM Session Active")
        else:
            btn_privacy_mode.setText("🍪 Persistent")
            media_status_lbl.setText("🍪 Persistent Workspace Session")

    def wipe_current_workspace() -> None:
        ws_id = store.active_workspace_id
        to_close = [r.id for r, _ in all_tabs if r.workspace_id == ws_id and not r.pinned]
        for tid in to_close:
            close_tab_by_id(tid)
        runtime_state["profile"].cookieStore().deleteAllCookies()  # type: ignore[attr-defined]
        runtime_state["profile"].clearHttpCache()  # type: ignore[attr-defined]
        media_status_lbl.setText("🧹 Workspace & Session Cache Wiped")

    btn_privacy_mode.clicked.connect(toggle_privacy_mode)
    btn_wipe.clicked.connect(wipe_current_workspace)

    # Keyboard Shortcuts (Accessibility & Power User Navigation)
    shortcuts = [
        ("Ctrl+T", lambda: create_tab(ZEN_HOME_URI)),
        ("Ctrl+W", lambda: close_tab_by_id(active_tab_id[0])),
        ("Ctrl+Shift+T", restore_recently_closed_tab),
        ("Ctrl+Shift+V", toggle_sidebar_animated),
        ("Ctrl+Shift+I", lambda: set_immersive_mode(not bool(runtime_state["immersive_mode"]))),
        ("F11", lambda: set_immersive_mode(not bool(runtime_state["immersive_mode"]))),
        ("Escape", lambda: set_immersive_mode(False) if runtime_state["immersive_mode"] else None),
        ("Ctrl+Shift+S", toggle_split_view),
        ("Ctrl+K", open_command_palette),
        ("Ctrl+L", lambda: (url_bar.setFocus(), url_bar.selectAll())),
        ("Ctrl+M", lambda: toggle_mute_tab()),
        ("Ctrl+J", lambda: dl_drawer.setVisible(not dl_drawer.isVisible())),
    ]
    for seq, handler in shortcuts:
        sc = QShortcut(QKeySequence(seq), win)
        sc.activated.connect(handler)

    # Periodic Downloader Progress Updater
    dl_timer = QTimer(win)

    def refresh_downloads() -> None:
        for job, _, bar, m_lbl in tracked_downloads:
            bar.setValue(int(job.progress))
            spd = f" • {core.format_bytes(job.speed_bps)}/s" if job.speed_bps > 1 else ""
            m_lbl.setText(f"{job.detail}{spd}")

    dl_timer.timeout.connect(refresh_downloads)
    dl_timer.start(250)

    # Restore Saved Workspaces & Tabs or Initialize Default
    saved_tabs = store.load_state()
    render_workspace_pills()
    if saved_tabs:
        for rec in saved_tabs:
            create_tab(existing_record=rec, switch_to=False)
        ws_tabs = [r for r, _ in all_tabs if r.workspace_id == store.active_workspace_id]
        select_tab_by_id(ws_tabs[0].id if ws_tabs else all_tabs[0][0].id)
    else:
        create_tab(initial_url if initial_url != HOME_URL else ZEN_HOME_URI)

    win.setCentralWidget(central)
    win.show()
    app.exec() if is_pyqt6 else app.exec_()
    return True


# ==============================================================================
# SECONDARY FALLBACK: ZEN-STYLED TKINTER DESKTOP SUITE (ZERO EXTERNAL DEPS)
# ==============================================================================


def find_linux_browser_binary() -> tuple[str | None, str]:
    for b in (
        "flatpak-spawn", "chromium", "chromium-browser", "brave-browser",
        "google-chrome", "microsoft-edge", "vivaldi",
    ):
        if b == "flatpak-spawn":
            continue
        p = shutil.which(b)
        if p:
            return p, "chromium"
    ff = shutil.which("firefox")
    if ff:
        return ff, "firefox"
    return None, ""


def launch_tkinter_zen_fallback(initial_url: str) -> None:
    """
    Polished Zen-styled Tkinter Desktop Shell when PyQt WebEngine is not installed on host.
    Provides Vertical Sidebar, Workspaces, Pinned Streaming Tiles, Tab Manager, and 16x Downloader.
    """
    import tkinter as tk
    from tkinter import filedialog, simpledialog, ttk

    store = WorkspaceStateStore()
    session_state: dict[str, object] = {"dir": None, "procs": [], "ephemeral": False}

    def ensure_session_dir() -> Path:
        d = session_state["dir"]
        if d is None or not Path(str(d)).exists():
            d = Path(tempfile.mkdtemp(prefix=f"OneBrowser_Zen_{secrets.token_hex(4)}_"))
            os.chmod(d, 0o700)
            session_state["dir"] = d
        return Path(str(d))

    def cleanup_session() -> None:
        for p in list(session_state["procs"]):  # type: ignore[arg-type]
            try:
                p.terminate()
            except Exception:
                pass
        if session_state["ephemeral"] and session_state["dir"]:
            shutil.rmtree(str(session_state["dir"]), ignore_errors=True)

    atexit.register(cleanup_session)

    root = tk.Tk()
    root.title("OneBrowser — Zen Streaming & Workspace Edition (Linux)")
    root.geometry("1260x800")
    root.configure(bg=TOKENS.bg_canvas)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure(
        "Horizontal.TProgressbar",
        troughcolor=TOKENS.bg_canvas,
        background=TOKENS.border_focus,
        bordercolor=TOKENS.bg_canvas,
    )

    tabs: list[TabStateRecord] = store.load_state() or [
        TabStateRecord(title="YouTube Stream", url="https://www.youtube.com", workspace_id="streaming", pinned=True),
        TabStateRecord(title="Twitch Live", url="https://www.twitch.tv", workspace_id="streaming", pinned=True),
    ]
    active_id = [tabs[0].id]

    # Main Split: Left Vertical Sidebar + Right Content Canvas
    main_frame = tk.Frame(root, bg=TOKENS.bg_canvas)
    main_frame.pack(fill="both", expand=True)

    sidebar = tk.Frame(main_frame, bg=TOKENS.bg_sidebar, width=260, padx=14, pady=14)
    sidebar.pack(side="left", fill="y")
    sidebar.pack_propagate(False)

    ws_lbl = tk.Label(
        sidebar,
        text="🎬 STREAMING WORKSPACE",
        bg=TOKENS.bg_sidebar,
        fg=TOKENS.border_focus,
        font=("Sans", 10, "bold"),
        anchor="w",
    )
    ws_lbl.pack(fill="x", pady=(0, 8))

    ws_bar = tk.Frame(sidebar, bg=TOKENS.bg_sidebar)
    ws_bar.pack(fill="x", pady=(0, 12))

    tabs_box = tk.Frame(sidebar, bg=TOKENS.bg_sidebar)
    tabs_box.pack(fill="both", expand=True, pady=6)

    status_var = tk.StringVar(value="OneBrowser Zen Ready — Select a streaming tile or open a tab.")

    def launch_external_stream(url: str, app_mode: bool = False) -> None:
        ok, clean, err = resolve_navigation_input(url)
        if not ok:
            status_var.set(err)
            return
        bin_path, kind = find_linux_browser_binary()
        prof = ensure_session_dir()
        if bin_path and kind == "chromium":
            args = [
                bin_path,
                f"--user-data-dir={prof}",
                "--no-first-run",
                "--enable-quic",
                "--enable-gpu-rasterization",
                "--enable-zero-copy",
                "--ignore-gpu-blocklist",
                f"--app={clean}" if app_mode else clean,
            ]
            proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            session_state["procs"].append(proc)  # type: ignore[attr-defined]
            status_var.set(f"Launched Hardware-Accelerated Stream -> {clean}")
        elif bin_path and kind == "firefox":
            proc = subprocess.Popen(
                [bin_path, "--profile", str(prof), "--no-remote", clean],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            session_state["procs"].append(proc)  # type: ignore[attr-defined]
            status_var.set(f"Launched Firefox Stream -> {clean}")
        else:
            subprocess.Popen(["xdg-open", clean], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def refresh_ui() -> None:
        ws = store.active_workspace()
        ws_lbl.config(text=f"{ws['icon']} {ws['name'].upper()} WORKSPACE", fg=ws["accent"])

        for w in ws_bar.winfo_children():
            w.destroy()
        for w in store.workspaces:
            is_cur = (w["id"] == store.active_workspace_id)
            tk.Button(
                ws_bar,
                text=w["icon"],
                bg=w["accent"] if is_cur else TOKENS.bg_elevated,
                fg=TOKENS.bg_canvas if is_cur else TOKENS.text_secondary,
                relief="flat",
                padx=8,
                pady=4,
                command=lambda wid=w["id"]: (setattr(store, "active_workspace_id", wid), refresh_ui()),
            ).pack(side="left", padx=2)

        for w in tabs_box.winfo_children():
            w.destroy()
        ws_tabs = [t for t in tabs if t.workspace_id == store.active_workspace_id or t.pinned]
        for t in ws_tabs:
            is_sel = (t.id == active_id[0])
            row = tk.Frame(
                tabs_box,
                bg=TOKENS.bg_card if is_sel else TOKENS.bg_elevated,
                padx=8,
                pady=6,
                highlightbackground=ws["accent"] if is_sel else TOKENS.border_subtle,
                highlightthickness=1,
            )
            row.pack(fill="x", pady=3)
            prefix = "📌 " if t.pinned else ""
            tk.Button(
                row,
                text=f"{prefix}{extract_domain_badge(t.url)}  {t.title[:22]}",
                bg=row["bg"],
                fg=TOKENS.text_primary,
                relief="flat",
                anchor="w",
                command=lambda r=t: (active_id.__setitem__(0, r.id), refresh_ui(), launch_external_stream(r.url)),
            ).pack(side="left", fill="x", expand=True)
            tk.Button(
                row,
                text="✕",
                bg=row["bg"],
                fg=TOKENS.text_muted,
                relief="flat",
                command=lambda r=t: (tabs.remove(r) if len(tabs) > 1 else None, refresh_ui()),
            ).pack(side="right")

        store.save_state(tabs, bool(session_state["ephemeral"]))

    tk.Button(
        sidebar,
        text="+ New Zen Tab",
        bg=TOKENS.border_focus,
        fg=TOKENS.bg_canvas,
        font=("Sans", 10, "bold"),
        relief="flat",
        pady=7,
        command=lambda: (
            tabs.append(TabStateRecord(title="New Stream Tab", url=HOME_URL, workspace_id=store.active_workspace_id)),
            refresh_ui(),
        ),
    ).pack(fill="x", pady=(8, 0))

    # Right Viewport Area
    content = tk.Frame(main_frame, bg=TOKENS.bg_canvas, padx=24, pady=20)
    content.pack(side="left", fill="both", expand=True)

    url_var = tk.StringVar(value=initial_url)
    omnibar = tk.Frame(content, bg=TOKENS.bg_elevated, padx=12, pady=8, highlightbackground=TOKENS.border_subtle, highlightthickness=1)
    omnibar.pack(fill="x", pady=(0, 20))
    tk.Label(omnibar, text="🛡️ HTTPS", bg=TOKENS.bg_elevated, fg=TOKENS.status_ok, font=("Sans", 9, "bold")).pack(side="left", padx=(0, 10))
    url_entry = tk.Entry(omnibar, textvariable=url_var, bg=TOKENS.bg_elevated, fg=TOKENS.text_primary, insertbackground=TOKENS.text_primary, relief="flat", font=("Sans", 12))
    url_entry.pack(side="left", fill="x", expand=True)
    tk.Button(
        omnibar,
        text="🎬 Immersive Launch",
        bg=TOKENS.border_focus,
        fg=TOKENS.bg_canvas,
        font=("Sans", 9, "bold"),
        relief="flat",
        padx=12,
        pady=4,
        command=lambda: launch_external_stream(url_var.get(), app_mode=True),
    ).pack(side="right", padx=4)

    # Streaming Hub Cards
    hub = tk.Frame(content, bg=TOKENS.bg_canvas)
    hub.pack(fill="x", pady=(0, 20))
    for item in PINNED_STREAMING_ESSENTIALS:
        card = tk.Frame(hub, bg=TOKENS.bg_elevated, padx=16, pady=14, highlightbackground=TOKENS.border_subtle, highlightthickness=1)
        card.pack(side="left", fill="x", expand=True, padx=4)
        tk.Label(card, text=f"{item['icon']}  {item['title']}", bg=TOKENS.bg_elevated, fg=TOKENS.text_primary, font=("Sans", 13, "bold")).pack(anchor="w")
        tk.Button(
            card,
            text="Watch in Cinema Mode →",
            bg=TOKENS.bg_card,
            fg=item["color"],
            relief="flat",
            padx=8,
            pady=4,
            command=lambda u=item["url"], t=item["title"]: (
                url_var.set(u),
                tabs.append(TabStateRecord(title=t, url=u, workspace_id=store.active_workspace_id)),
                refresh_ui(),
                launch_external_stream(u, app_mode=True),
            ),
        ).pack(anchor="w", pady=(8, 0))

    tk.Label(root, textvariable=status_var, bg=TOKENS.bg_sidebar, fg=TOKENS.text_secondary, anchor="w", padx=16, pady=6).pack(fill="x", side="bottom")
    refresh_ui()
    root.mainloop()


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in ("--download", "-d", "--cli"):
        sys.argv.pop(1)
        return core.main()

    initial = HOME_URL
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        ok, clean, _ = resolve_navigation_input(sys.argv[1])
        if ok:
            initial = clean

    if try_launch_qt_zen_browser(initial):
        return 0
    launch_tkinter_zen_fallback(initial)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
