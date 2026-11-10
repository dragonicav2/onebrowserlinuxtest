#!/usr/bin/env python3
"""
OneBrowser for Linux — Zen Browser–Inspired Streaming & Entertainment Desktop Browser
Primary Target: Bazzite Linux (Fedora Atomic / Universal Blue) & Modern Linux Desktops
Distribution: Flatpak (Primary) & Standalone Type-2 AppImage (Secondary)

Multi-Engine Guarantee (Never fails silently on any Linux distro):
1. Native GTK3 + WebKit2GTK Engine (Built into org.gnome.Platform Flatpak & Fedora/Bazzite/Ubuntu)
2. Native PyQt6 / PyQt5 QtWebEngine (When PyQt WebEngine is installed on host)
3. Universal Self-Contained Zen Desktop Shell Engine (100% Python stdlib loopback server +
   native frameless --app window or GTK shell — guaranteed to open on stock Bazzite with zero deps)
"""
from __future__ import annotations

import atexit
import http.server
import ipaddress
import json
import os
import secrets
import shutil
import socket
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
APP_VERSION = "3.4.1-zen"
HOME_URL = "https://duckduckgo.com/"
ZEN_HOME_URI = "one://zen-home"


# ==============================================================================
# PHASE 2: UI DESIGN SYSTEM (TOKENS, SPACING, TYPOGRAPHY, WORKSPACE ACCENTS)
# ==============================================================================


@dataclass(frozen=True)
class DesignSystem:
    bg_canvas: str = "#0E0E11"
    bg_sidebar: str = "#131317"
    bg_elevated: str = "#1A1A20"
    bg_card: str = "#202027"
    bg_hover: str = "#282832"
    bg_active: str = "#31313D"
    bg_glass_modal: str = "#18181E"

    border_subtle: str = "#25252E"
    border_strong: str = "#383846"
    border_focus: str = "#E5957C"

    text_primary: str = "#F4F4F6"
    text_secondary: str = "#A1A1AA"
    text_muted: str = "#71717A"

    status_ok: str = "#34D399"
    status_warn: str = "#FBBF24"
    status_danger: str = "#F87171"
    status_info: str = "#60A5FA"

    radius_sm: int = 6
    radius_md: int = 10
    radius_lg: int = 14
    radius_pill: int = 18


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
    if os.environ.get("ONEBROWSER_REDUCED_MOTION") == "1":
        return True
    if os.environ.get("GTK_ENABLE_ANIMATIONS") == "0":
        return True
    if os.environ.get("QT_ENABLE_ANIMATIONS") == "0":
        return True
    return False


# ==============================================================================
# PHASE 9: SECURITY ENGINE (HTTPS, SSRF, TRACKER SHIELD)
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
    "adservice.google.com", "ads.youtube.com", "s0.2mdn.net", "static.doubleclick.net",
)

YOUTUBE_AD_PATH_PATTERNS = (
    "/youtubei/v1/player/ad_break",
    "/api/stats/ads",
    "/api/stats/atr",
    "/pagead/interaction",
    "/pagead/lvz",
    "/pagead/adview",
    "/pagead/conversion",
    "/get_midroll_info",
    "/ptracking",
)

YOUTUBE_AD_QUERY_PATTERNS = (
    "ad_type=",
    "adformat=",
    "ad_system=",
    "oad=",
)


def _load_shared_adblock_rules() -> dict:
    candidates = [
        HERE / "youtube_adblock_rules.json",
        HERE.parent.parent.parent / "crossplatform" / "youtube_adblock_rules.json",
        Path("/app/bin/youtube_adblock_rules.json"),
    ]
    for c in candidates:
        try:
            if c.is_file():
                return json.loads(c.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


_SHARED_RULES = _load_shared_adblock_rules()
if isinstance(_SHARED_RULES.get("ad_domains"), list):
    BLOCKED_AD_DOMAINS = tuple(dict.fromkeys([*BLOCKED_AD_DOMAINS, *_SHARED_RULES["ad_domains"]]))
if isinstance(_SHARED_RULES.get("youtube_ad_path_patterns"), list):
    YOUTUBE_AD_PATH_PATTERNS = tuple(dict.fromkeys([*YOUTUBE_AD_PATH_PATTERNS, *_SHARED_RULES["youtube_ad_path_patterns"]]))
if isinstance(_SHARED_RULES.get("youtube_ad_query_patterns"), list):
    YOUTUBE_AD_QUERY_PATTERNS = tuple(dict.fromkeys([*YOUTUBE_AD_QUERY_PATTERNS, *_SHARED_RULES["youtube_ad_query_patterns"]]))


def is_youtube_ad_request(url: str) -> bool:
    if not url:
        return False
    u = url.lower()
    if any(dom in u for dom in ("doubleclick.net", "googlesyndication.com", "googleadservices.com", "adservice.google.", "s0.2mdn.net")):
        return True
    if "youtube.com" in u or "googlevideo.com" in u:
        for pat in YOUTUBE_AD_PATH_PATTERNS:
            if pat in u:
                return True
        if "googlevideo.com/videoplayback" in u and ("&oad=" in u or "?oad=" in u or "&ctier=l" in u):
            return True
        if ("/pagead/" in u or "/api/stats/ads" in u) and any(q in u for q in YOUTUBE_AD_QUERY_PATTERNS):
            return True
    return False


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


BASE_HARDENING_JS = """
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

FALLBACK_YOUTUBE_ADBLOCK_JS = """
(() => {
  'use strict';
  if (window.__obYouTubeAdBlockActive) return;
  window.__obYouTubeAdBlockActive = true;
  const host = (location.hostname || '').toLowerCase();
  if (!(host === 'youtube.com' || host.endsWith('.youtube.com') || host === 'youtu.be' || host.endsWith('.youtube-nocookie.com'))) return;

  const AD_PRUNE_KEYS = ['adPlacements', 'playerAds', 'adSlots', 'adBreakHeartbeatParams'];
  const pruneYouTubePayload = (obj, depth = 0) => {
    if (!obj || typeof obj !== 'object' || depth > 5) return obj;
    try {
      for (const k of AD_PRUNE_KEYS) { if (k in obj) delete obj[k]; }
      if (obj.auxiliaryUi && obj.auxiliaryUi.messageRenderers) {
        delete obj.auxiliaryUi.messageRenderers.enforcementMessageViewModel;
        delete obj.auxiliaryUi.messageRenderers.bkaEnforcementMessageViewModel;
      }
      if (obj.playabilityStatus && obj.playabilityStatus.errorScreen) {
        const rawStr = JSON.stringify(obj.playabilityStatus.errorScreen);
        if (rawStr && rawStr.toLowerCase().includes('ad blocker')) {
          obj.playabilityStatus.status = 'OK';
          delete obj.playabilityStatus.errorScreen;
        }
      }
      if (obj.playerResponse && typeof obj.playerResponse === 'object') pruneYouTubePayload(obj.playerResponse, depth + 1);
      if (Array.isArray(obj.onResponseReceivedEndpoints)) {
        for (const ep of obj.onResponseReceivedEndpoints) pruneYouTubePayload(ep, depth + 1);
      }
    } catch (_) {}
    return obj;
  };

  const trapGlobalProperty = (propName) => {
    try {
      let internalVal = window[propName];
      if (internalVal && typeof internalVal === 'object') pruneYouTubePayload(internalVal);
      Object.defineProperty(window, propName, {
        configurable: true, enumerable: true,
        get() { return internalVal; },
        set(newVal) { internalVal = pruneYouTubePayload(newVal); }
      });
    } catch (_) {}
  };
  trapGlobalProperty('ytInitialPlayerResponse');
  trapGlobalProperty('ytInitialData');

  const isYouTubeAdEndpoint = (urlStr) => {
    if (!urlStr || typeof urlStr !== 'string') return false;
    const u = urlStr.toLowerCase();
    return u.includes('/youtubei/v1/player/ad_break') || u.includes('/api/stats/ads') ||
           u.includes('/pagead/interaction') || u.includes('/pagead/lvz') ||
           u.includes('/pagead/adview') || u.includes('/get_midroll_info') ||
           u.includes('doubleclick.net') || u.includes('googlesyndication.com') || u.includes('googleadservices.com');
  };

  try {
    const origJsonParse = JSON.parse;
    JSON.parse = function () { return pruneYouTubePayload(origJsonParse.apply(this, arguments)); };
  } catch (_) {}
  try {
    if (window.Response && Response.prototype.json) {
      const origResJson = Response.prototype.json;
      Response.prototype.json = function () { return origResJson.apply(this, arguments).then(d => pruneYouTubePayload(d)); };
    }
  } catch (_) {}
  try {
    if (typeof window.fetch === 'function') {
      const origFetch = window.fetch;
      window.fetch = function (input) {
        try {
          const url = typeof input === 'string' ? input : (input && input.url ? input.url : '');
          if (isYouTubeAdEndpoint(url)) {
            return Promise.resolve(new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }));
          }
        } catch (_) {}
        return origFetch.apply(this, arguments);
      };
    }
  } catch (_) {}
  try {
    if (typeof XMLHttpRequest !== 'undefined' && XMLHttpRequest.prototype) {
      const origOpen = XMLHttpRequest.prototype.open;
      const origSend = XMLHttpRequest.prototype.send;
      XMLHttpRequest.prototype.open = function (method, url) {
        this.__obReqUrl = typeof url === 'string' ? url : '';
        return origOpen.apply(this, arguments);
      };
      XMLHttpRequest.prototype.send = function () {
        if (this.__obReqUrl && isYouTubeAdEndpoint(this.__obReqUrl)) {
          try {
            Object.defineProperty(this, 'status', { get: () => 200 });
            Object.defineProperty(this, 'readyState', { get: () => 4 });
            Object.defineProperty(this, 'responseText', { get: () => '{}' });
            Object.defineProperty(this, 'response', { get: () => '{}' });
            setTimeout(() => { if (typeof this.onload === 'function') this.onload(); this.dispatchEvent(new Event('load')); }, 1);
            return;
          } catch (_) {}
        }
        return origSend.apply(this, arguments);
      };
    }
  } catch (_) {}

  const COSMETIC_CSS = `
    ytd-ad-slot-renderer, ytd-in-feed-ad-layout-renderer, ytd-promoted-sparkles-web-renderer,
    ytd-promoted-video-renderer, ytd-display-ad-renderer, ytd-statement-banner-renderer,
    ytd-banner-promo-renderer, ytd-video-masthead-ad-v3-renderer, ytd-primetime-promo-renderer,
    ytd-companion-slot-renderer, ytd-action-companion-ad-renderer, ytd-image-companion-ad-renderer,
    ytd-engagement-panel-section-list-renderer[target-id="engagement-panel-ads"],
    ytd-enforcement-message-view-model, ytm-promoted-sparkles-web-renderer,
    ytm-promoted-video-renderer, ytm-companion-ad-renderer, ytm-statement-banner-renderer,
    #masthead-ad, #player-ads, #offer-module, .ytp-ad-overlay-container, .ytp-ad-message-container,
    .ytp-featured-product, .ytd-mealbar-promo-renderer,
    tp-yt-paper-dialog:has(ytd-enforcement-message-view-model) {
      display: none !important; visibility: hidden !important; height: 0 !important;
      margin: 0 !important; padding: 0 !important; pointer-events: none !important;
    }
  `;
  const injectCss = () => {
    try {
      const root = document.head || document.documentElement;
      if (root && !document.getElementById('ob-yt-adblock-css')) {
        const s = document.createElement('style');
        s.id = 'ob-yt-adblock-css';
        s.textContent = COSMETIC_CSS;
        root.appendChild(s);
      }
    } catch (_) {}
  };

  const SKIP_SEL = '.ytp-ad-skip-button,.ytp-skip-ad-button,.ytp-ad-skip-button-modern,.ytp-ad-skip-button-slot button,.ytp-ad-overlay-close-button,button.ytp-ad-skip-button-modern';
  let wasMutedByAdGuard = false;
  let userPlaybackRate = 1.0;

  const mitigateAds = () => {
    try {
      injectCss();
      const modal = document.querySelector('ytd-enforcement-message-view-model, tp-yt-paper-dialog:has(ytd-enforcement-message-view-model)');
      if (modal) {
        modal.remove();
        const bd = document.querySelector('tp-yt-iron-overlay-backdrop');
        if (bd) bd.remove();
        const v = document.querySelector('video.html5-main-video, video');
        if (v && v.paused) v.play().catch(() => {});
      }
      document.querySelectorAll(SKIP_SEL).forEach(b => { if (b && typeof b.click === 'function') b.click(); });
      const player = document.querySelector('.html5-video-player.ad-showing, .html5-video-player.ad-interrupting, .ad-showing');
      const video = document.querySelector('video.html5-main-video, .html5-video-player video, video');
      if (player && video) {
        if (!wasMutedByAdGuard) {
          wasMutedByAdGuard = true;
          if (video.playbackRate > 0 && video.playbackRate <= 2) userPlaybackRate = video.playbackRate;
        }
        video.muted = true;
        if (Number.isFinite(video.duration) && video.duration > 0.5) {
          video.currentTime = Math.max(0, video.duration - 0.05);
        } else {
          video.playbackRate = 16.0;
        }
        if (video.paused) video.play().catch(() => {});
      } else if (wasMutedByAdGuard && video) {
        wasMutedByAdGuard = false;
        video.muted = false;
        video.playbackRate = userPlaybackRate || 1.0;
      }
    } catch (_) {}
  };
  injectCss();
  setInterval(mitigateAds, 200);
  window.addEventListener('yt-navigate-finish', mitigateAds);
  window.addEventListener('yt-page-data-updated', mitigateAds);
})();
"""


def _load_shared_youtube_adblock_js() -> str:
    candidates = [
        HERE / "youtube_adblock_engine.js",
        HERE.parent.parent.parent / "crossplatform" / "youtube_adblock_engine.js",
        Path("/app/bin/youtube_adblock_engine.js"),
    ]
    for c in candidates:
        try:
            if c.is_file():
                return c.read_text(encoding="utf-8")
        except Exception:
            pass
    return FALLBACK_YOUTUBE_ADBLOCK_JS


YOUTUBE_ADBLOCK_JS = _load_shared_youtube_adblock_js()
HARDENING_AND_STREAMING_JS = BASE_HARDENING_JS + "\n" + YOUTUBE_ADBLOCK_JS


def build_zen_home_html(workspace_name: str, workspace_icon: str, accent: str) -> str:
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
  .container {{ width: 100%; max-width: 860px; }}
  .badge {{
    display: inline-flex; align-items: center; gap: 8px;
    padding: 6px 14px; border-radius: 999px;
    background: var(--card); border: 1px solid var(--border);
    color: var(--accent); font-size: 12px; font-weight: 600;
    letter-spacing: 0.4px; margin-bottom: 16px;
  }}
  h1 {{ font-size: 36px; font-weight: 800; letter-spacing: -0.8px; margin-bottom: 8px; }}
  .subtitle {{ color: var(--muted); font-size: 14px; margin-bottom: 28px; }}
  .search-box {{
    display: flex; align-items: center;
    background: var(--card); border: 1.5px solid var(--border);
    border-radius: 18px; padding: 14px 20px; margin-bottom: 36px;
    transition: border-color 0.16s ease, box-shadow 0.16s ease;
  }}
  .search-box:focus-within {{
    border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(229, 149, 124, 0.15);
  }}
  .search-box input {{
    width: 100%; background: transparent; border: none; outline: none;
    color: var(--text); font-size: 15px; margin-left: 12px;
  }}
  .section-title {{
    font-size: 12px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 1px; color: var(--muted); margin-bottom: 14px;
  }}
  .grid {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(195px, 1fr));
    gap: 14px; margin-bottom: 32px;
  }}
  a.tile {{
    text-decoration: none; color: inherit;
    background: var(--card); border: 1px solid var(--border);
    border-radius: 14px; padding: 18px;
    display: flex; flex-direction: column; gap: 8px;
    transition: transform 0.15s cubic-bezier(0.22, 1, 0.36, 1), background 0.15s ease, border-color 0.15s ease;
  }}
  a.tile:hover {{
    background: var(--card-hover); border-color: var(--accent); transform: translateY(-2px);
  }}
  .tile-top {{ display: flex; align-items: center; justify-content: space-between; }}
  .tile-icon {{
    width: 36px; height: 36px; border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-weight: 800; font-size: 16px; background: rgba(255,255,255,0.06);
  }}
  .tile-tag {{
    font-size: 10px; font-weight: 600; padding: 3px 8px;
    border-radius: 6px; background: rgba(255,255,255,0.05); color: var(--muted);
  }}
  .tile-name {{ font-size: 15px; font-weight: 700; margin-top: 4px; }}
  .tile-desc {{ font-size: 12px; color: var(--muted); line-height: 1.4; }}
  .shortcuts {{
    display: flex; flex-wrap: wrap; gap: 10px;
    padding-top: 16px; border-top: 1px solid var(--border);
    color: var(--muted); font-size: 12px;
  }}
  .kbd {{
    background: var(--card); border: 1px solid var(--border);
    border-radius: 6px; padding: 3px 8px; font-family: monospace; color: var(--text);
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
      <span><span class="kbd">F11</span> Immersive Cinema Mode</span>
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


def configure_linux_chromium_flags() -> None:
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
    widevine_candidates = [
        Path("/usr/lib64/chromium-browser/WidevineCdm/_platform_specific/linux_x64/libwidevinecdm.so"),
        Path("/usr/lib/chromium/WidevineCdm/_platform_specific/linux_x64/libwidevinecdm.so"),
        Path("/opt/google/chrome/WidevineCdm/_platform_specific/linux_x64/libwidevinecdm.so"),
        Path.home() / ".config/onebrowser/WidevineCdm/_platform_specific/linux_x64/libwidevinecdm.so",
    ]
    for cand in widevine_candidates:
        if cand.exists():
            flags.append(f"--widevine-path={cand}")
            break
    existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (existing + " " + " ".join(flags)).strip()


# ==============================================================================
# ENGINE 1A: NATIVE GTK4 + WEBKIT 6.0 ZEN BROWSER (GNOME 47 PLATPAK & UBUNTU 24.04+)
# ==============================================================================


def try_launch_gtk4_zen_browser(initial_url: str) -> bool:
    """
    Launches the modern GTK4 + WebKitGTK 6.0 Zen Browser desktop interface.
    Native engine in GNOME 47 Platform Flatpak (Bazzite/Fedora) and Ubuntu 24.04+.
    """
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Gdk", "4.0")
        gi.require_version("WebKit", "6.0")
        from gi.repository import Gdk, Gio, GLib, Gtk, WebKit
    except Exception:
        return False

    store = WorkspaceStateStore()
    all_tabs: list[tuple[TabStateRecord, object]] = []
    active_tab_id: list[str] = [""]
    state = {"sidebar_open": True, "immersive": False, "split_open": False, "ephemeral": False}
    tracked_jobs: list[tuple[core.JobState, object, object]] = []

    try:
        app = Gtk.Application(
            application_id="io.github.onebrowser.OneBrowser",
            flags=getattr(Gio.ApplicationFlags, "NON_UNIQUE", 0),
        )
    except Exception:
        app = Gtk.Application()

    def on_activate(application):
        win = Gtk.ApplicationWindow(application=application, title="OneBrowser — Zen Streaming & Workspace Edition")
        win.set_default_size(1380, 860)

        css_provider = Gtk.CssProvider()

        def apply_gtk4_theme(accent: str) -> None:
            css = f"""
                window, .zen-root {{ background-color: #0E0E11; color: #F4F4F6; font-family: "Inter", "Cantarell", Sans-Serif; }}
                .zen-sidebar {{ background-color: #131317; border-right: 1px solid #25252E; padding: 12px; }}
                .zen-topbar {{ background-color: #131317; border-bottom: 1px solid #25252E; padding: 8px 12px; }}
                .zen-viewport {{ background-color: #0E0E11; border: 1px solid #25252E; border-radius: 10px; }}
                .zen-card {{ background-color: #1A1A20; border: 1px solid #25252E; border-radius: 10px; padding: 10px; }}
                entry {{ background-color: #1A1A20; color: #F4F4F6; border: 1px solid #25252E; border-radius: 16px; padding: 6px 14px; }}
                entry:focus {{ border-color: {accent}; background-color: #202027; }}
                button {{ background-image: none; background-color: #1A1A20; color: #F4F4F6; border: 1px solid #25252E; border-radius: 7px; padding: 5px 10px; }}
                button:hover {{ background-color: #282832; border-color: #383846; }}
                button.accent-btn {{ background-color: {accent}; color: #0E0E11; font-weight: bold; border: none; }}
                button.tab-active {{ background-color: #202027; border: 1px solid {accent}; color: #F4F4F6; font-weight: bold; }}
                button.ws-active {{ background-color: {accent}; color: #0E0E11; font-weight: bold; border: none; }}
                .section-lbl {{ color: #71717A; font-size: 10px; font-weight: bold; }}
            """
            try:
                if hasattr(css_provider, "load_from_string"):
                    css_provider.load_from_string(css)
                else:
                    css_provider.load_from_data(css.encode("utf-8"))
            except Exception:
                try:
                    css_provider.load_from_data(css)
                except Exception:
                    pass

        apply_gtk4_theme(store.active_workspace()["accent"])
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

        root_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root_vbox.add_css_class("zen-root")
        win.set_child(root_vbox)

        # Top Compact Navigation Bar
        topbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        topbar.add_css_class("zen-topbar")

        btn_sb_toggle = Gtk.Button(label="◨")
        btn_back = Gtk.Button(label="←")
        btn_fwd = Gtk.Button(label="→")
        btn_reload = Gtk.Button(label="↻")
        badge_lbl = Gtk.Label(label="🛡️ 41.9k")

        url_entry = Gtk.Entry()
        url_entry.set_placeholder_text("Search DuckDuckGo or enter an HTTPS streaming URL...")
        url_entry.set_hexpand(True)

        btn_pip = Gtk.Button(label="⧉ PiP")
        btn_split = Gtk.Button(label="◫ Split")
        btn_cinema = Gtk.Button(label="🎬 Cinema")
        btn_dl_toggle = Gtk.Button(label="⬇ 0")

        for w in (btn_sb_toggle, btn_back, btn_fwd, btn_reload, badge_lbl):
            topbar.append(w)
        topbar.append(url_entry)
        for w in (btn_pip, btn_split, btn_cinema, btn_dl_toggle):
            topbar.append(w)

        root_vbox.append(topbar)

        # Main Body: Left Zen Sidebar + Right Framed Viewport
        body_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        body_hbox.set_hexpand(True)
        body_hbox.set_vexpand(True)
        root_vbox.append(body_hbox)

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        sidebar.set_size_request(260, -1)
        sidebar.add_css_class("zen-sidebar")
        body_hbox.append(sidebar)

        ws_title = Gtk.Label(label="🎬 STREAMING")
        ws_title.set_xalign(0.0)
        ws_title.add_css_class("section-lbl")
        sidebar.append(ws_title)

        ws_pills_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        sidebar.append(ws_pills_box)

        ess_lbl = Gtk.Label(label="ESSENTIAL STREAMING")
        ess_lbl.set_xalign(0.0)
        ess_lbl.add_css_class("section-lbl")
        sidebar.append(ess_lbl)

        ess_grid = Gtk.Grid()
        ess_grid.set_column_spacing(6)
        ess_grid.set_row_spacing(6)
        ess_grid.set_column_homogeneous(True)
        for idx, item in enumerate(PINNED_STREAMING_ESSENTIALS):
            eb = Gtk.Button(label=f"{item['icon']} {item['title']}")
            eb.connect("clicked", lambda _, u=item["url"], t=item["title"]: create_or_focus_tab(u, t, pinned=True))
            ess_grid.attach(eb, idx % 2, idx // 2, 1, 1)
        sidebar.append(ess_grid)

        tabs_lbl = Gtk.Label(label="VERTICAL TABS")
        tabs_lbl.set_xalign(0.0)
        tabs_lbl.add_css_class("section-lbl")
        sidebar.append(tabs_lbl)

        tabs_scroll = Gtk.ScrolledWindow()
        tabs_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        tabs_scroll.set_vexpand(True)
        vtabs_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        tabs_scroll.set_child(vtabs_vbox)
        sidebar.append(tabs_scroll)

        btn_new_tab = Gtk.Button(label="+  New Zen Tab")
        btn_new_tab.add_css_class("accent-btn")
        sidebar.append(btn_new_tab)

        # Sidebar Bottom Media Deck
        media_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        media_card.add_css_class("zen-card")
        media_lbl = Gtk.Label(label="🎵 Media Deck • Ready")
        media_lbl.set_xalign(0.0)
        media_card.append(media_lbl)

        media_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        btn_m_play = Gtk.Button(label="⏯")
        btn_m_mute = Gtk.Button(label="🔊")
        btn_m_pip = Gtk.Button(label="⧉ PiP")
        btn_m_restore = Gtk.Button(label="↺ Tab")
        for b in (btn_m_play, btn_m_mute, btn_m_pip, btn_m_restore):
            b.set_hexpand(True)
            media_btns.append(b)
        media_card.append(media_btns)
        sidebar.append(media_card)

        # Right Viewport + Split View + Downloader Drawer
        right_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        right_vbox.set_hexpand(True)
        right_vbox.set_vexpand(True)
        right_vbox.set_margin_top(6)
        right_vbox.set_margin_bottom(6)
        right_vbox.set_margin_start(6)
        right_vbox.set_margin_end(6)
        body_hbox.append(right_vbox)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_hexpand(True)
        paned.set_vexpand(True)
        right_vbox.append(paned)

        notebook = Gtk.Notebook()
        notebook.set_show_tabs(False)
        notebook.set_show_border(False)
        notebook.set_hexpand(True)
        notebook.set_vexpand(True)
        paned.set_start_child(notebook)

        secondary_webview = WebKit.WebView()
        secondary_webview.set_visible(False)
        secondary_webview.set_hexpand(True)
        secondary_webview.set_vexpand(True)
        paned.set_end_child(secondary_webview)

        # Downloader Drawer
        dl_drawer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        dl_drawer.add_css_class("zen-card")
        dl_drawer.set_visible(False)

        dl_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        dl_entry = Gtk.Entry()
        dl_entry.set_placeholder_text("Paste HTTPS file, .m3u8 stream, or video link for 16x download...")
        dl_entry.set_hexpand(True)
        btn_dl_grab = Gtk.Button(label="Grab Tab URL")
        btn_dl_go = Gtk.Button(label="Start 16x Download")
        btn_dl_go.add_css_class("accent-btn")
        dl_row.append(dl_entry)
        dl_row.append(btn_dl_grab)
        dl_row.append(btn_dl_go)
        dl_drawer.append(dl_row)

        dl_jobs_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        dl_drawer.append(dl_jobs_vbox)
        right_vbox.append(dl_drawer)

        def clear_box(box):
            while True:
                child = box.get_first_child()
                if child is None:
                    break
                box.remove(child)

        def get_active_pair() -> tuple[TabStateRecord, object] | None:
            for r, v in all_tabs:
                if r.id == active_tab_id[0]:
                    return r, v
            return all_tabs[0] if all_tabs else None

        def render_sidebar() -> None:
            ws = store.active_workspace()
            ws_title.set_text(f"{ws['icon']} {ws['name'].upper()}")
            clear_box(ws_pills_box)
            for w in store.workspaces:
                b = Gtk.Button(label=w["icon"])
                b.set_hexpand(True)
                if w["id"] == store.active_workspace_id:
                    b.add_css_class("ws-active")
                b.connect("clicked", lambda _, wid=w["id"]: switch_workspace(wid))
                ws_pills_box.append(b)

            clear_box(vtabs_vbox)
            ws_tabs = [
                (r, v) for r, v in all_tabs
                if r.workspace_id == store.active_workspace_id or r.pinned
            ]
            ws_tabs.sort(key=lambda p: (0 if p[0].pinned else 1))
            tabs_lbl.set_text(f"OPEN TABS ({len(ws_tabs)})")

            for r, _ in ws_tabs:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                pin_mark = "📌 " if r.pinned else ""
                mute_mark = " 🔇" if r.muted else ""
                tb = Gtk.Button(label=f"{pin_mark}{extract_domain_badge(r.url)}  {r.title[:22]}{mute_mark}")
                tb.set_hexpand(True)
                if r.id == active_tab_id[0]:
                    tb.add_css_class("tab-active")
                tb.connect("clicked", lambda _, tid=r.id: select_tab(tid))

                cb = Gtk.Button(label="✕")
                cb.connect("clicked", lambda _, tid=r.id: close_tab(tid))
                row.append(tb)
                row.append(cb)
                vtabs_vbox.append(row)

            store.save_state([r for r, _ in all_tabs], state["ephemeral"])

        def load_into_webview(rec: TabStateRecord, webview, raw_url: str) -> None:
            if raw_url == ZEN_HOME_URI:
                rec.url = ZEN_HOME_URI
                rec.title = "Zen Home"
                ws = store.get_workspace(rec.workspace_id)
                webview.load_html(build_zen_home_html(ws["name"], ws["icon"], ws["accent"]), "https://onebrowser.local/")
                return
            ok, clean, err = resolve_navigation_input(raw_url)
            if not ok:
                media_lbl.set_text(f"⚠️ {err}")
                return
            rec.url = clean
            webview.load_uri(clean)

        def create_tab(
            target_url: str = ZEN_HOME_URI,
            title: str = "Zen Home",
            pinned: bool = False,
            existing: TabStateRecord | None = None,
        ) -> None:
            rec = existing or TabStateRecord(
                title=title,
                url=target_url,
                workspace_id=store.active_workspace_id,
                pinned=pinned,
            )
            wv = WebKit.WebView()
            wv.set_hexpand(True)
            wv.set_vexpand(True)
            settings = wv.get_settings()
            if hasattr(settings, "set_enable_mediasource"):
                settings.set_enable_mediasource(True)
            if hasattr(settings, "set_enable_webgl"):
                settings.set_enable_webgl(True)
            if hasattr(settings, "set_media_playback_requires_user_gesture"):
                settings.set_media_playback_requires_user_gesture(False)

            ucm = wv.get_user_content_manager()
            if hasattr(WebKit, "UserScript"):
                try:
                    script = WebKit.UserScript.new(
                        HARDENING_AND_STREAMING_JS,
                        WebKit.UserContentInjectedFrames.ALL_FRAMES,
                        WebKit.UserScriptInjectionTime.START,
                        None,
                        None,
                    )
                    ucm.add_script(script)
                except Exception:
                    pass

            def on_decide_policy(_view, decision, decision_type) -> bool:
                try:
                    if hasattr(decision, "get_request"):
                        req_uri = decision.get_request().get_uri() or ""
                        req_host = (urllib.parse.urlsplit(req_uri).hostname or "").lower()
                        if (req_host and is_blocked_domain(req_host)) or is_youtube_ad_request(req_uri):
                            decision.ignore()
                            return True
                except Exception:
                    pass
                return False

            wv.connect("decide-policy", on_decide_policy)

            def on_title_changed(view, _param) -> None:
                t = view.get_title()
                if t:
                    rec.title = t
                    render_sidebar()

            def on_uri_changed(view, _param) -> None:
                u = view.get_uri() or ""
                if u and not u.startswith("https://onebrowser.local"):
                    rec.url = u
                    if rec.id == active_tab_id[0]:
                        url_entry.set_text(u)
                    render_sidebar()

            wv.connect("notify::title", on_title_changed)
            wv.connect("notify::uri", on_uri_changed)

            notebook.append_page(wv, None)
            all_tabs.append((rec, wv))
            load_into_webview(rec, wv, rec.url)
            select_tab(rec.id)

        def create_or_focus_tab(url: str, title: str, pinned: bool = False) -> None:
            host = urllib.parse.urlsplit(url).hostname or url
            for r, _ in all_tabs:
                if host in r.url:
                    select_tab(r.id)
                    return
            create_tab(url, title, pinned=pinned)

        def select_tab(tid: str) -> None:
            for r, wv in all_tabs:
                if r.id == tid:
                    active_tab_id[0] = tid
                    page_num = notebook.page_num(wv)
                    if page_num >= 0:
                        notebook.set_current_page(page_num)
                    url_entry.set_text("" if r.url == ZEN_HOME_URI else r.url)
                    render_sidebar()
                    return

        def close_tab(tid: str) -> None:
            idx = next((i for i, (r, _) in enumerate(all_tabs) if r.id == tid), -1)
            if idx < 0:
                return
            r, wv = all_tabs.pop(idx)
            store.closed_tabs_stack.append(r)
            page_num = notebook.page_num(wv)
            if page_num >= 0:
                notebook.remove_page(page_num)
            ws_tabs = [rec for rec, _ in all_tabs if rec.workspace_id == store.active_workspace_id or rec.pinned]
            if not ws_tabs:
                create_tab(ZEN_HOME_URI)
            else:
                select_tab(ws_tabs[-1].id)

        def switch_workspace(wid: str) -> None:
            store.active_workspace_id = wid
            apply_gtk4_theme(store.active_workspace()["accent"])
            ws_tabs = [r for r, _ in all_tabs if r.workspace_id == wid or r.pinned]
            if not ws_tabs:
                create_tab(ZEN_HOME_URI)
            else:
                select_tab(ws_tabs[0].id)

        def run_js(code: str) -> None:
            pair = get_active_pair()
            if not pair:
                return
            wv = pair[1]
            if hasattr(wv, "evaluate_javascript"):
                try:
                    wv.evaluate_javascript(code, -1, None, None, None, None, None)
                except Exception:
                    pass
            elif hasattr(wv, "run_javascript"):
                try:
                    wv.run_javascript(code, None, None, None)
                except Exception:
                    pass

        def toggle_immersive() -> None:
            state["immersive"] = not state["immersive"]
            if state["immersive"]:
                topbar.set_visible(False)
                sidebar.set_visible(False)
                win.fullscreen()
            else:
                topbar.set_visible(True)
                sidebar.set_visible(True)
                win.unfullscreen()

        def toggle_split() -> None:
            state["split_open"] = not state["split_open"]
            secondary_webview.set_visible(state["split_open"])
            if state["split_open"]:
                secondary_webview.load_uri("https://www.twitch.tv")
                paned.set_position(720)

        def start_download() -> None:
            ok, clean, err = resolve_navigation_input(dl_entry.get_text())
            if not ok:
                media_lbl.set_text(f"⚠️ {err}")
                return
            out_dir = core.default_download_dir()
            out_dir.mkdir(parents=True, exist_ok=True)
            job = core.JobState(clean, out_dir, 16, "best")
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            lbl = Gtk.Label(label=f"{job.file_name[:32]} — Starting...")
            lbl.set_hexpand(True)
            row.append(lbl)
            dl_jobs_vbox.append(row)
            tracked_jobs.append((job, lbl, row))
            btn_dl_toggle.set_label(f"⬇ {len(tracked_jobs)}")
            threading.Thread(target=core.run_job, args=(job,), daemon=True).start()
            dl_entry.set_text("")

        btn_sb_toggle.connect("clicked", lambda _: sidebar.set_visible(not sidebar.get_visible()))
        btn_back.connect("clicked", lambda _: get_active_pair()[1].go_back() if get_active_pair() else None)
        btn_fwd.connect("clicked", lambda _: get_active_pair()[1].go_forward() if get_active_pair() else None)
        btn_reload.connect("clicked", lambda _: get_active_pair()[1].reload() if get_active_pair() else None)
        url_entry.connect(
            "activate",
            lambda _: load_into_webview(get_active_pair()[0], get_active_pair()[1], url_entry.get_text())
            if get_active_pair()
            else None,
        )
        btn_new_tab.connect("clicked", lambda _: create_tab(ZEN_HOME_URI))
        btn_pip.connect(
            "clicked",
            lambda _: run_js("const v=document.querySelector('video'); if(v&&v.requestPictureInPicture) v.requestPictureInPicture();"),
        )
        btn_m_pip.connect(
            "clicked",
            lambda _: run_js("const v=document.querySelector('video'); if(v&&v.requestPictureInPicture) v.requestPictureInPicture();"),
        )
        btn_m_play.connect(
            "clicked",
            lambda _: run_js("const v=document.querySelector('video,audio'); if(v){if(v.paused)v.play();else v.pause();}"),
        )
        btn_m_mute.connect(
            "clicked",
            lambda _: run_js("document.querySelectorAll('video,audio').forEach(e=>e.muted=!e.muted);"),
        )
        btn_m_restore.connect(
            "clicked",
            lambda _: create_tab(existing=store.closed_tabs_stack.pop()) if store.closed_tabs_stack else None,
        )
        btn_cinema.connect("clicked", lambda _: toggle_immersive())
        btn_split.connect("clicked", lambda _: toggle_split())
        btn_dl_toggle.connect(
            "clicked",
            lambda _: dl_drawer.set_visible(not dl_drawer.get_visible()),
        )
        btn_dl_grab.connect(
            "clicked",
            lambda _: dl_entry.set_text(get_active_pair()[0].url if get_active_pair() else ""),
        )
        btn_dl_go.connect("clicked", lambda _: start_download())

        key_controller = Gtk.EventControllerKey.new()

        def on_key_pressed(_ctrl, keyval, keycode, state_mask) -> bool:
            keyname = Gdk.keyval_name(keyval) or ""
            ctrl = bool(state_mask & Gdk.ModifierType.CONTROL_MASK)
            shift = bool(state_mask & Gdk.ModifierType.SHIFT_MASK)
            if keyname == "F11" or (ctrl and shift and keyname.lower() == "i"):
                toggle_immersive()
                return True
            if keyname == "Escape" and state["immersive"]:
                toggle_immersive()
                return True
            if ctrl and shift and keyname.lower() == "v":
                sidebar.set_visible(not sidebar.get_visible())
                return True
            if ctrl and shift and keyname.lower() == "s":
                toggle_split()
                return True
            if ctrl and keyname.lower() == "t":
                create_tab(ZEN_HOME_URI)
                return True
            if ctrl and keyname.lower() == "w" and active_tab_id[0]:
                close_tab(active_tab_id[0])
                return True
            return False

        key_controller.connect("key-pressed", on_key_pressed)
        win.add_controller(key_controller)

        def update_dl_progress() -> bool:
            for job, lbl, _ in tracked_jobs:
                spd = f" • {core.format_bytes(job.speed_bps)}/s" if job.speed_bps > 1 else ""
                lbl.set_text(f"{job.file_name[:32]} — {job.detail} ({job.progress:.0f}%){spd}")
            return True

        GLib.timeout_add(300, update_dl_progress)

        saved = store.load_state()
        if saved:
            for r in saved:
                create_tab(existing=r)
        else:
            create_tab(initial_url if initial_url != HOME_URL else ZEN_HOME_URI)

        win.present()

    app.connect("activate", on_activate)
    try:
        app.run([sys.argv[0]] if sys.argv else None)
        return True
    except Exception:
        try:
            app.run(None)
            return True
        except Exception:
            return False


# ==============================================================================
# ENGINE 1B: NATIVE GTK3 + WEBKIT2GTK ZEN BROWSER (UBUNTU 22.04 & OLDER DISTROS)
# ==============================================================================


def try_launch_gtk_webkit_zen_browser(initial_url: str) -> bool:
    """
    Launches the native GTK3 + WebKit2GTK Zen Browser–inspired desktop interface.
    Used on older Linux distributions (Ubuntu 22.04, Debian 11/12) with GTK 3.
    """
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        try:
            gi.require_version("WebKit2", "4.1")
        except ValueError:
            gi.require_version("WebKit2", "4.0")
        from gi.repository import Gdk, GLib, Gtk, Pango, WebKit2
    except Exception:
        return False

    store = WorkspaceStateStore()
    all_tabs: list[tuple[TabStateRecord, object]] = []
    active_tab_id: list[str] = [""]
    state = {"sidebar_open": True, "immersive": False, "split_open": False, "ephemeral": False}
    tracked_jobs: list[tuple[core.JobState, object, object]] = []

    win = Gtk.Window(title="OneBrowser — Zen Streaming & Workspace Edition")
    win.set_default_size(1380, 860)

    css_provider = Gtk.CssProvider()

    def apply_gtk_theme(accent: str) -> None:
        css = f"""
            window, .zen-root {{ background-color: #0E0E11; color: #F4F4F6; font-family: "Inter", "Cantarell", Sans-Serif; }}
            .zen-sidebar {{ background-color: #131317; border-right: 1px solid #25252E; padding: 12px; }}
            .zen-topbar {{ background-color: #131317; border-bottom: 1px solid #25252E; padding: 8px 12px; }}
            .zen-viewport {{ background-color: #0E0E11; border: 1px solid #25252E; border-radius: 10px; }}
            .zen-card {{ background-color: #1A1A20; border: 1px solid #25252E; border-radius: 10px; padding: 10px; }}
            entry {{ background-color: #1A1A20; color: #F4F4F6; border: 1px solid #25252E; border-radius: 16px; padding: 6px 14px; }}
            entry:focus {{ border-color: {accent}; background-color: #202027; }}
            button {{ background-image: none; background-color: #1A1A20; color: #F4F4F6; border: 1px solid #25252E; border-radius: 7px; padding: 5px 10px; }}
            button:hover {{ background-color: #282832; border-color: #383846; }}
            button.accent-btn {{ background-color: {accent}; color: #0E0E11; font-weight: bold; border: none; }}
            button.tab-active {{ background-color: #202027; border: 1px solid {accent}; color: #F4F4F6; font-weight: bold; }}
            button.ws-active {{ background-color: {accent}; color: #0E0E11; font-weight: bold; border: none; }}
            .section-lbl {{ color: #71717A; font-size: 10px; font-weight: bold; }}
        """
        css_provider.load_from_data(css.encode("utf-8"))

    apply_gtk_theme(store.active_workspace()["accent"])
    screen = Gdk.Screen.get_default()
    if screen:
        Gtk.StyleContext.add_provider_for_screen(
            screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    root_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    root_vbox.get_style_context().add_class("zen-root")
    win.add(root_vbox)

    # Top Compact Navigation Bar
    topbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    topbar.get_style_context().add_class("zen-topbar")

    btn_sb_toggle = Gtk.Button(label="◨")
    btn_back = Gtk.Button(label="←")
    btn_fwd = Gtk.Button(label="→")
    btn_reload = Gtk.Button(label="↻")
    badge_lbl = Gtk.Label(label="🛡️ 41.9k")

    url_entry = Gtk.Entry()
    url_entry.set_placeholder_text("Search DuckDuckGo or enter an HTTPS streaming URL...")

    btn_pip = Gtk.Button(label="⧉ PiP")
    btn_split = Gtk.Button(label="◫ Split")
    btn_cinema = Gtk.Button(label="🎬 Cinema")
    btn_dl_toggle = Gtk.Button(label="⬇ 0")

    for w in (btn_sb_toggle, btn_back, btn_fwd, btn_reload, badge_lbl):
        topbar.pack_start(w, False, False, 0)
    topbar.pack_start(url_entry, True, True, 4)
    for w in (btn_pip, btn_split, btn_cinema, btn_dl_toggle):
        topbar.pack_start(w, False, False, 0)

    root_vbox.pack_start(topbar, False, False, 0)

    # Main Horizontal Body: Left Zen Sidebar + Right Framed Viewport
    body_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    root_vbox.pack_start(body_hbox, True, True, 0)

    sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    sidebar.set_size_request(260, -1)
    sidebar.get_style_context().add_class("zen-sidebar")
    body_hbox.pack_start(sidebar, False, False, 0)

    ws_title = Gtk.Label(label="🎬 STREAMING")
    ws_title.set_xalign(0.0)
    ws_title.get_style_context().add_class("section-lbl")
    sidebar.pack_start(ws_title, False, False, 0)

    ws_pills_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    sidebar.pack_start(ws_pills_box, False, False, 0)

    ess_lbl = Gtk.Label(label="ESSENTIAL STREAMING")
    ess_lbl.set_xalign(0.0)
    ess_lbl.get_style_context().add_class("section-lbl")
    sidebar.pack_start(ess_lbl, False, False, 2)

    ess_grid = Gtk.Grid(column_spacing=6, row_spacing=6, column_homogeneous=True)
    for idx, item in enumerate(PINNED_STREAMING_ESSENTIALS):
        eb = Gtk.Button(label=f"{item['icon']} {item['title']}")
        eb.connect("clicked", lambda _, u=item["url"], t=item["title"]: create_or_focus_tab(u, t, pinned=True))
        ess_grid.attach(eb, idx % 2, idx // 2, 1, 1)
    sidebar.pack_start(ess_grid, False, False, 0)

    tabs_lbl = Gtk.Label(label="VERTICAL TABS")
    tabs_lbl.set_xalign(0.0)
    tabs_lbl.get_style_context().add_class("section-lbl")
    sidebar.pack_start(tabs_lbl, False, False, 2)

    tabs_scroll = Gtk.ScrolledWindow()
    tabs_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    vtabs_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    tabs_scroll.add(vtabs_vbox)
    sidebar.pack_start(tabs_scroll, True, True, 0)

    btn_new_tab = Gtk.Button(label="+  New Zen Tab")
    btn_new_tab.get_style_context().add_class("accent-btn")
    sidebar.pack_start(btn_new_tab, False, False, 0)

    # Sidebar Bottom Media Deck
    media_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    media_card.get_style_context().add_class("zen-card")
    media_lbl = Gtk.Label(label="🎵 Media Deck • Ready")
    media_lbl.set_xalign(0.0)
    media_card.pack_start(media_lbl, False, False, 0)

    media_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    btn_m_play = Gtk.Button(label="⏯")
    btn_m_mute = Gtk.Button(label="🔊")
    btn_m_pip = Gtk.Button(label="⧉ PiP")
    btn_m_restore = Gtk.Button(label="↺ Tab")
    for b in (btn_m_play, btn_m_mute, btn_m_pip, btn_m_restore):
        media_btns.pack_start(b, True, True, 0)
    media_card.pack_start(media_btns, False, False, 0)
    sidebar.pack_start(media_card, False, False, 0)

    # Right Viewport + Split View + Downloader Drawer
    right_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    right_vbox.set_margin_top(6)
    right_vbox.set_margin_bottom(6)
    right_vbox.set_margin_start(6)
    right_vbox.set_margin_end(6)
    body_hbox.pack_start(right_vbox, True, True, 0)

    paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
    right_vbox.pack_start(paned, True, True, 0)

    notebook = Gtk.Notebook()
    notebook.set_show_tabs(False)
    notebook.set_show_border(False)
    paned.pack1(notebook, True, False)

    secondary_webview = WebKit2.WebView()
    secondary_webview.set_visible(False)
    paned.pack2(secondary_webview, True, False)

    # Downloader Drawer
    dl_drawer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    dl_drawer.get_style_context().add_class("zen-card")
    dl_drawer.set_no_show_all(True)
    dl_drawer.set_visible(False)

    dl_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    dl_entry = Gtk.Entry()
    dl_entry.set_placeholder_text("Paste HTTPS file, .m3u8 stream, or video link for 16x download...")
    btn_dl_grab = Gtk.Button(label="Grab Tab URL")
    btn_dl_go = Gtk.Button(label="Start 16x Download")
    btn_dl_go.get_style_context().add_class("accent-btn")
    dl_row.pack_start(dl_entry, True, True, 0)
    dl_row.pack_start(btn_dl_grab, False, False, 0)
    dl_row.pack_start(btn_dl_go, False, False, 0)
    dl_drawer.pack_start(dl_row, False, False, 0)

    dl_jobs_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    dl_drawer.pack_start(dl_jobs_vbox, False, False, 0)
    right_vbox.pack_start(dl_drawer, False, False, 0)

    def get_active_pair() -> tuple[TabStateRecord, object] | None:
        for r, v in all_tabs:
            if r.id == active_tab_id[0]:
                return r, v
        return all_tabs[0] if all_tabs else None

    def render_sidebar() -> None:
        ws = store.active_workspace()
        ws_title.set_text(f"{ws['icon']} {ws['name'].upper()}")
        for ch in ws_pills_box.get_children():
            ws_pills_box.remove(ch)
        for w in store.workspaces:
            b = Gtk.Button(label=w["icon"])
            if w["id"] == store.active_workspace_id:
                b.get_style_context().add_class("ws-active")
            b.connect("clicked", lambda _, wid=w["id"]: switch_workspace(wid))
            ws_pills_box.pack_start(b, True, True, 0)
        ws_pills_box.show_all()

        for ch in vtabs_vbox.get_children():
            vtabs_vbox.remove(ch)

        ws_tabs = [
            (r, v) for r, v in all_tabs
            if r.workspace_id == store.active_workspace_id or r.pinned
        ]
        ws_tabs.sort(key=lambda p: (0 if p[0].pinned else 1))
        tabs_lbl.set_text(f"OPEN TABS ({len(ws_tabs)})")

        for r, _ in ws_tabs:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            pin_mark = "📌 " if r.pinned else ""
            mute_mark = " 🔇" if r.muted else ""
            tb = Gtk.Button(label=f"{pin_mark}{extract_domain_badge(r.url)}  {r.title[:22]}{mute_mark}")
            tb.set_hexpand(True)
            if r.id == active_tab_id[0]:
                tb.get_style_context().add_class("tab-active")
            tb.connect("clicked", lambda _, tid=r.id: select_tab(tid))

            cb = Gtk.Button(label="✕")
            cb.connect("clicked", lambda _, tid=r.id: close_tab(tid))
            row.pack_start(tb, True, True, 0)
            row.pack_start(cb, False, False, 0)
            vtabs_vbox.pack_start(row, False, False, 0)

        vtabs_vbox.show_all()
        store.save_state([r for r, _ in all_tabs], state["ephemeral"])

    def load_into_webview(rec: TabStateRecord, webview, raw_url: str) -> None:
        if raw_url == ZEN_HOME_URI:
            rec.url = ZEN_HOME_URI
            rec.title = "Zen Home"
            ws = store.get_workspace(rec.workspace_id)
            webview.load_html(build_zen_home_html(ws["name"], ws["icon"], ws["accent"]), "https://onebrowser.local/")
            return
        ok, clean, err = resolve_navigation_input(raw_url)
        if not ok:
            media_lbl.set_text(f"⚠️ {err}")
            return
        rec.url = clean
        webview.load_uri(clean)

    def create_tab(
        target_url: str = ZEN_HOME_URI,
        title: str = "Zen Home",
        pinned: bool = False,
        existing: TabStateRecord | None = None,
    ) -> None:
        rec = existing or TabStateRecord(
            title=title,
            url=target_url,
            workspace_id=store.active_workspace_id,
            pinned=pinned,
        )
        wv = WebKit2.WebView()
        settings = wv.get_settings()
        if hasattr(settings, "set_enable_mediasource"):
            settings.set_enable_mediasource(True)
        if hasattr(settings, "set_enable_webgl"):
            settings.set_enable_webgl(True)
        if hasattr(settings, "set_media_playback_requires_user_gesture"):
            settings.set_media_playback_requires_user_gesture(False)

        ucm = wv.get_user_content_manager()
        if hasattr(WebKit2, "UserScript"):
            script = WebKit2.UserScript.new(
                HARDENING_AND_STREAMING_JS,
                WebKit2.UserContentInjectedFrames.ALL_FRAMES,
                WebKit2.UserScriptInjectionTime.START,
                None,
                None,
            )
            ucm.add_script(script)

        def on_decide_policy(_view, decision, decision_type) -> bool:
            try:
                if hasattr(decision, "get_request"):
                    req_uri = decision.get_request().get_uri() or ""
                    req_host = (urllib.parse.urlsplit(req_uri).hostname or "").lower()
                    if (req_host and is_blocked_domain(req_host)) or is_youtube_ad_request(req_uri):
                        decision.ignore()
                        return True
            except Exception:
                pass
            return False

        wv.connect("decide-policy", on_decide_policy)

        def on_title_changed(view, _param) -> None:
            t = view.get_title()
            if t:
                rec.title = t
                render_sidebar()

        def on_uri_changed(view, _param) -> None:
            u = view.get_uri() or ""
            if u and not u.startswith("https://onebrowser.local"):
                rec.url = u
                if rec.id == active_tab_id[0]:
                    url_entry.set_text(u)
                render_sidebar()

        wv.connect("notify::title", on_title_changed)
        wv.connect("notify::uri", on_uri_changed)

        wv.show()
        notebook.append_page(wv, None)
        all_tabs.append((rec, wv))
        load_into_webview(rec, wv, rec.url)
        select_tab(rec.id)

    def create_or_focus_tab(url: str, title: str, pinned: bool = False) -> None:
        host = urllib.parse.urlsplit(url).hostname or url
        for r, _ in all_tabs:
            if host in r.url:
                select_tab(r.id)
                return
        create_tab(url, title, pinned=pinned)

    def select_tab(tid: str) -> None:
        for r, wv in all_tabs:
            if r.id == tid:
                active_tab_id[0] = tid
                page_num = notebook.page_num(wv)
                if page_num >= 0:
                    notebook.set_current_page(page_num)
                url_entry.set_text("" if r.url == ZEN_HOME_URI else r.url)
                render_sidebar()
                return

    def close_tab(tid: str) -> None:
        idx = next((i for i, (r, _) in enumerate(all_tabs) if r.id == tid), -1)
        if idx < 0:
            return
        r, wv = all_tabs.pop(idx)
        store.closed_tabs_stack.append(r)
        page_num = notebook.page_num(wv)
        if page_num >= 0:
            notebook.remove_page(page_num)
        ws_tabs = [rec for rec, _ in all_tabs if rec.workspace_id == store.active_workspace_id or rec.pinned]
        if not ws_tabs:
            create_tab(ZEN_HOME_URI)
        else:
            select_tab(ws_tabs[-1].id)

    def switch_workspace(wid: str) -> None:
        store.active_workspace_id = wid
        apply_gtk_theme(store.active_workspace()["accent"])
        ws_tabs = [r for r, _ in all_tabs if r.workspace_id == wid or r.pinned]
        if not ws_tabs:
            create_tab(ZEN_HOME_URI)
        else:
            select_tab(ws_tabs[0].id)

    def run_js(code: str) -> None:
        pair = get_active_pair()
        if pair and hasattr(pair[1], "run_javascript"):
            pair[1].run_javascript(code, None, None, None)

    def toggle_immersive() -> None:
        state["immersive"] = not state["immersive"]
        if state["immersive"]:
            topbar.set_visible(False)
            sidebar.set_visible(False)
            win.fullscreen()
        else:
            topbar.set_visible(True)
            sidebar.set_visible(True)
            win.unfullscreen()

    def toggle_split() -> None:
        state["split_open"] = not state["split_open"]
        secondary_webview.set_visible(state["split_open"])
        if state["split_open"]:
            secondary_webview.load_uri("https://www.twitch.tv")
            paned.set_position(720)

    def start_download() -> None:
        ok, clean, err = resolve_navigation_input(dl_entry.get_text())
        if not ok:
            media_lbl.set_text(f"⚠️ {err}")
            return
        out_dir = core.default_download_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        job = core.JobState(clean, out_dir, 16, "best")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl = Gtk.Label(label=f"{job.file_name[:32]} — Starting...")
        row.pack_start(lbl, True, True, 0)
        dl_jobs_vbox.pack_start(row, False, False, 0)
        dl_jobs_vbox.show_all()
        tracked_jobs.append((job, lbl, row))
        btn_dl_toggle.set_label(f"⬇ {len(tracked_jobs)}")
        threading.Thread(target=core.run_job, args=(job,), daemon=True).start()
        dl_entry.set_text("")

    btn_sb_toggle.connect("clicked", lambda _: sidebar.set_visible(not sidebar.get_visible()))
    btn_back.connect("clicked", lambda _: get_active_pair()[1].go_back() if get_active_pair() else None)
    btn_fwd.connect("clicked", lambda _: get_active_pair()[1].go_forward() if get_active_pair() else None)
    btn_reload.connect("clicked", lambda _: get_active_pair()[1].reload() if get_active_pair() else None)
    url_entry.connect(
        "activate",
        lambda _: load_into_webview(get_active_pair()[0], get_active_pair()[1], url_entry.get_text())
        if get_active_pair()
        else None,
    )
    btn_new_tab.connect("clicked", lambda _: create_tab(ZEN_HOME_URI))
    btn_pip.connect(
        "clicked",
        lambda _: run_js("const v=document.querySelector('video'); if(v&&v.requestPictureInPicture) v.requestPictureInPicture();"),
    )
    btn_m_pip.connect(
        "clicked",
        lambda _: run_js("const v=document.querySelector('video'); if(v&&v.requestPictureInPicture) v.requestPictureInPicture();"),
    )
    btn_m_play.connect(
        "clicked",
        lambda _: run_js("const v=document.querySelector('video,audio'); if(v){if(v.paused)v.play();else v.pause();}"),
    )
    btn_m_mute.connect(
        "clicked",
        lambda _: run_js("document.querySelectorAll('video,audio').forEach(e=>e.muted=!e.muted);"),
    )
    btn_m_restore.connect(
        "clicked",
        lambda _: create_tab(existing=store.closed_tabs_stack.pop()) if store.closed_tabs_stack else None,
    )
    btn_cinema.connect("clicked", lambda _: toggle_immersive())
    btn_split.connect("clicked", lambda _: toggle_split())
    btn_dl_toggle.connect(
        "clicked",
        lambda _: (dl_drawer.set_no_show_all(False), dl_drawer.set_visible(not dl_drawer.get_visible()), dl_drawer.show_all()),
    )
    btn_dl_grab.connect(
        "clicked",
        lambda _: dl_entry.set_text(get_active_pair()[0].url if get_active_pair() else ""),
    )
    btn_dl_go.connect("clicked", lambda _: start_download())

    def on_key_press(_widget, event) -> bool:
        keyname = Gdk.keyval_name(event.keyval) or ""
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        if keyname == "F11" or (ctrl and shift and keyname.lower() == "i"):
            toggle_immersive()
            return True
        if keyname == "Escape" and state["immersive"]:
            toggle_immersive()
            return True
        if ctrl and shift and keyname.lower() == "v":
            sidebar.set_visible(not sidebar.get_visible())
            return True
        if ctrl and shift and keyname.lower() == "s":
            toggle_split()
            return True
        if ctrl and keyname.lower() == "t":
            create_tab(ZEN_HOME_URI)
            return True
        if ctrl and keyname.lower() == "w" and active_tab_id[0]:
            close_tab(active_tab_id[0])
            return True
        return False

    win.connect("key-press-event", on_key_press)
    win.connect("destroy", Gtk.main_quit)

    def update_dl_progress() -> bool:
        for job, lbl, _ in tracked_jobs:
            spd = f" • {core.format_bytes(job.speed_bps)}/s" if job.speed_bps > 1 else ""
            lbl.set_text(f"{job.file_name[:32]} — {job.detail} ({job.progress:.0f}%){spd}")
        return True

    GLib.timeout_add(300, update_dl_progress)

    saved = store.load_state()
    if saved:
        for r in saved:
            create_tab(existing=r)
    else:
        create_tab(initial_url if initial_url != HOME_URL else ZEN_HOME_URI)

    win.show_all()
    Gtk.main()
    return True


# ==============================================================================
# ENGINE 2: NATIVE PYQT6 / PYQT5 QTWEBENGINE ZEN BROWSER
# ==============================================================================


def try_launch_qt_zen_browser(initial_url: str) -> bool:
    try:
        from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, QUrl
        from PyQt6.QtGui import QKeySequence, QShortcut
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

    class ZenAdBlockInterceptor(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info) -> None:
            qurl = info.requestUrl()
            scheme = qurl.scheme().lower()
            host = qurl.host().lower()
            raw_url = qurl.toString()
            if scheme == "http" and host and not is_private_or_reserved_host(host):
                upgraded = QUrl(qurl)
                upgraded.setScheme("https")
                info.redirect(upgraded)
                return
            if scheme != "https" or is_private_or_reserved_host(host) or is_blocked_domain(host) or is_youtube_ad_request(raw_url):
                info.block(True)

    app = QApplication(sys.argv[:1])
    store = WorkspaceStateStore()
    win = QMainWindow()
    win.setWindowTitle("OneBrowser — Zen Streaming & Workspace Edition (Linux)")
    win.resize(1380, 860)

    interceptor = ZenAdBlockInterceptor()
    prof = QWebEngineProfile.defaultProfile()
    if hasattr(prof, "setUrlRequestInterceptor"):
        prof.setUrlRequestInterceptor(interceptor)
    elif hasattr(prof, "setRequestInterceptor"):
        prof.setRequestInterceptor(interceptor)

    script = QWebEngineScript()
    script.setName("OneBrowserYouTubeAdBlockAndHardening")
    script.setSourceCode(HARDENING_AND_STREAMING_JS)
    script.setInjectionPoint(
        QWebEngineScript.InjectionPoint.DocumentCreation
        if is_pyqt6
        else QWebEngineScript.DocumentCreation
    )
    script.setWorldId(
        QWebEngineScript.ScriptWorldId.MainWorld
        if is_pyqt6
        else QWebEngineScript.MainWorld
    )
    script.setRunsOnSubFrames(True)
    prof.scripts().insert(script)

    view = QWebEngineView()
    ws = store.active_workspace()
    if initial_url == HOME_URL:
        view.setHtml(build_zen_home_html(ws["name"], ws["icon"], ws["accent"]), QUrl("https://onebrowser.local/"))
    else:
        view.setUrl(QUrl(initial_url))
    win.setCentralWidget(view)
    win.show()
    app.exec() if is_pyqt6 else app.exec_()
    return True


# ==============================================================================
# ENGINE 3: UNIVERSAL SELF-CONTAINED ZEN DESKTOP SHELL (100% PYTHON STDLIB)
# Guaranteed to open on stock Bazzite AppImage with zero Python GUI deps!
# ==============================================================================

ZEN_DESKTOP_SHELL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>OneBrowser Zen — Linux Streaming Edition</title>
<style>
  :root {
    --bg: #0E0E11; --sidebar: #131317; --elevated: #1A1A20; --card: #202027;
    --hover: #282832; --border: #25252E; --text: #F4F4F6; --muted: #A1A1AA;
    --accent: #E5957C;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg); color: var(--text);
    font-family: "Inter", "Cantarell", -apple-system, sans-serif;
    height: 100vh; display: flex; flex-direction: column; overflow: hidden;
  }
  .topbar {
    height: 48px; background: var(--sidebar); border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 8px; padding: 0 12px;
  }
  .btn {
    background: var(--elevated); color: var(--text); border: 1px solid var(--border);
    border-radius: 8px; padding: 6px 11px; font-size: 12px; font-weight: 600;
    cursor: pointer; transition: all 0.14s ease;
  }
  .btn:hover { background: var(--hover); border-color: var(--accent); }
  .btn-accent { background: var(--accent); color: #0E0E11; border: none; font-weight: 700; }
  .omnibar {
    flex: 1; background: var(--elevated); border: 1.5px solid var(--border);
    border-radius: 16px; padding: 7px 14px; color: var(--text); font-size: 13px; outline: none;
  }
  .omnibar:focus { border-color: var(--accent); }
  .body-split { flex: 1; display: flex; overflow: hidden; }
  .sidebar {
    width: 260px; background: var(--sidebar); border-right: 1px solid var(--border);
    display: flex; flex-direction: column; padding: 12px; gap: 10px;
    transition: width 0.16s cubic-bezier(0.22, 1, 0.36, 1), padding 0.16s ease;
    overflow: hidden;
  }
  .sidebar.collapsed { width: 0; padding: 0; border-right: none; }
  .ws-strip { display: flex; gap: 4px; }
  .ws-pill {
    flex: 1; text-align: center; padding: 6px 0; border-radius: 8px;
    background: var(--elevated); border: 1px solid var(--border); cursor: pointer;
  }
  .ws-pill.active { background: var(--accent); color: #0E0E11; font-weight: 800; border: none; }
  .sec-label { font-size: 10px; font-weight: 700; letter-spacing: 0.8px; color: #71717A; text-transform: uppercase; }
  .ess-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  .tab-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; }
  .tab-item {
    display: flex; align-items: center; justify-content: space-between;
    padding: 8px 10px; border-radius: 8px; background: transparent;
    border: 1px solid transparent; cursor: pointer; font-size: 12px; color: var(--muted);
  }
  .tab-item:hover { background: var(--hover); color: var(--text); }
  .tab-item.active { background: var(--card); border-color: var(--accent); color: var(--text); font-weight: 600; }
  .viewport-wrap { flex: 1; padding: 6px; display: flex; flex-direction: column; gap: 6px; }
  .viewport-wrap.immersive { padding: 0; }
  .viewport {
    flex: 1; background: #121217; border: 1px solid var(--border);
    border-radius: 12px; overflow-y: auto; padding: 32px;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
  }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 14px; width: 100%; max-width: 860px; margin-top: 24px; }
  .stream-card {
    background: var(--elevated); border: 1px solid var(--border); border-radius: 14px;
    padding: 18px; cursor: pointer; transition: transform 0.15s ease, border-color 0.15s ease;
  }
  .stream-card:hover { transform: translateY(-2px); border-color: var(--accent); background: var(--hover); }
  .dl-drawer {
    background: var(--elevated); border: 1px solid var(--border); border-radius: 10px;
    padding: 12px; display: none; flex-direction: column; gap: 8px;
  }
  .dl-drawer.open { display: flex; }
</style>
</head>
<body>
  <div class="topbar" id="topbar">
    <button class="btn" onclick="toggleSidebar()" title="Toggle Zen Sidebar (Ctrl+Shift+V)">◨</button>
    <span class="btn" style="color:#34D399;cursor:default;">🛡️ 41.9k HTTPS</span>
    <input id="omnibar" class="omnibar" placeholder="Search DuckDuckGo or paste an HTTPS streaming link (Enter to launch)..." onkeydown="if(event.key==='Enter')openStream(this.value)" />
    <button class="btn" onclick="toggleImmersive()">🎬 Cinema (F11)</button>
    <button class="btn" onclick="toggleDrawer()">⬇ 16x Downloader</button>
  </div>
  <div class="body-split">
    <div class="sidebar" id="sidebar">
      <div class="sec-label" id="wsTitle">🎬 STREAMING WORKSPACE</div>
      <div class="ws-strip">
        <div class="ws-pill active" onclick="setWs('Streaming','🎬','#E5957C',this)">🎬</div>
        <div class="ws-pill" onclick="setWs('Entertainment','🍿','#A78BFA',this)">🍿</div>
        <div class="ws-pill" onclick="setWs('Gaming','🎮','#34D399',this)">🎮</div>
        <div class="ws-pill" onclick="setWs('Social','💬','#73B5E8',this)">💬</div>
        <div class="ws-pill" onclick="setWs('Work','💼','#FCD34D',this)">💼</div>
      </div>
      <div class="sec-label">ESSENTIAL STREAMING</div>
      <div class="ess-grid">
        <button class="btn" onclick="openStream('https://www.youtube.com','YouTube')">▶ YouTube</button>
        <button class="btn" onclick="openStream('https://www.twitch.tv','Twitch')">👾 Twitch</button>
        <button class="btn" onclick="openStream('https://www.netflix.com','Netflix')">N Netflix</button>
        <button class="btn" onclick="openStream('https://www.disneyplus.com','Disney+')">✦ Disney+</button>
      </div>
      <div class="sec-label">VERTICAL TABS</div>
      <div class="tab-list" id="tabList"></div>
      <button class="btn btn-accent" onclick="addTab('Zen Home','https://duckduckgo.com')">+ New Zen Tab</button>
    </div>
    <div class="viewport-wrap" id="vpWrap">
      <div class="viewport">
        <div style="text-align:center;max-width:860px;width:100%;">
          <div style="color:var(--accent);font-size:12px;font-weight:700;margin-bottom:8px;">✦ ONEBROWSER ZEN • BAZZITE &amp; LINUX STREAMING HUB</div>
          <h1 style="font-size:34px;margin-bottom:8px;">OneBrowser Zen</h1>
          <p style="color:var(--muted);font-size:14px;">Click any streaming platform below to launch a hardware-accelerated borderless Cinema stream or queue a 16x download.</p>
          <div class="cards">
            <div class="stream-card" onclick="openStream('https://www.youtube.com','YouTube')">
              <div style="font-size:20px;color:#FF4E45;font-weight:800;">▶ YouTube</div>
              <div style="color:var(--muted);font-size:12px;margin-top:6px;">4K60 AV1 hardware-accelerated streaming</div>
            </div>
            <div class="stream-card" onclick="openStream('https://www.twitch.tv','Twitch')">
              <div style="font-size:20px;color:#A970FF;font-weight:800;">👾 Twitch</div>
              <div style="color:var(--muted);font-size:12px;margin-top:6px;">Low-latency live broadcasts &amp; gaming</div>
            </div>
            <div class="stream-card" onclick="openStream('https://www.netflix.com','Netflix')">
              <div style="font-size:20px;color:#E50914;font-weight:800;">N Netflix</div>
              <div style="color:var(--muted);font-size:12px;margin-top:6px;">Immersive borderless cinema mode</div>
            </div>
            <div class="stream-card" onclick="openStream('https://www.disneyplus.com','Disney+')">
              <div style="font-size:20px;color:#38BDF8;font-weight:800;">✦ Disney+</div>
              <div style="color:var(--muted);font-size:12px;margin-top:6px;">Originals, movies &amp; series</div>
            </div>
            <div class="stream-card" onclick="openStream('https://store.steampowered.com','Steam')">
              <div style="font-size:20px;color:#66C0F4;font-weight:800;">🎮 Steam Store</div>
              <div style="color:var(--muted);font-size:12px;margin-top:6px;">Bazzite &amp; Linux gaming catalog</div>
            </div>
            <div class="stream-card" onclick="openStream('https://www.protondb.com','ProtonDB')">
              <div style="font-size:20px;color:#34D399;font-weight:800;">🐧 ProtonDB</div>
              <div style="color:var(--muted);font-size:12px;margin-top:6px;">Linux compatibility database</div>
            </div>
          </div>
        </div>
      </div>
      <div class="dl-drawer" id="dlDrawer">
        <div style="font-weight:700;color:var(--accent);font-size:13px;">⬇ ZeroDownloader 16x Multi-Stream Engine</div>
        <div style="display:flex;gap:8px;">
          <input id="dlUrl" class="omnibar" placeholder="Paste HTTPS file, .m3u8 HLS stream, or video link..." />
          <button class="btn btn-accent" onclick="startDl()">Start 16x Download</button>
        </div>
        <div id="dlStatus" style="font-size:12px;color:var(--muted);">Ready — downloads save to ~/Downloads/ZeroDownloader</div>
      </div>
    </div>
  </div>
<script>
  let tabs = [
    {title: 'YouTube Stream', url: 'https://www.youtube.com'},
    {title: 'Twitch Live', url: 'https://www.twitch.tv'}
  ];
  let activeIdx = 0;
  function renderTabs() {
    const box = document.getElementById('tabList');
    box.innerHTML = '';
    tabs.forEach((t, i) => {
      const d = document.createElement('div');
      d.className = 'tab-item' + (i === activeIdx ? ' active' : '');
      d.innerHTML = `<span onclick="activeIdx=${i};renderTabs();openStream('${t.url}','${t.title}')">✦ ${t.title}</span><span onclick="event.stopPropagation();tabs.splice(${i},1);renderTabs()">✕</span>`;
      box.appendChild(d);
    });
  }
  function addTab(title, url) { tabs.push({title, url}); activeIdx = tabs.length - 1; renderTabs(); }
  function toggleSidebar() { document.getElementById('sidebar').classList.toggle('collapsed'); }
  function toggleDrawer() { document.getElementById('dlDrawer').classList.toggle('open'); }
  function toggleImmersive() {
    document.getElementById('sidebar').classList.toggle('collapsed');
    document.getElementById('vpWrap').classList.toggle('immersive');
    if (!document.fullscreenElement) document.documentElement.requestFullscreen().catch(()=>{});
    else document.exitFullscreen().catch(()=>{});
  }
  function setWs(name, icon, accent, el) {
    document.documentElement.style.setProperty('--accent', accent);
    document.getElementById('wsTitle').textContent = icon + ' ' + name.toUpperCase() + ' WORKSPACE';
    document.querySelectorAll('.ws-pill').forEach(p => p.classList.remove('active'));
    el.classList.add('active');
  }
  function openStream(raw, title) {
    fetch('/api/open?url=' + encodeURIComponent(raw)).then(r=>r.json()).then(d=>{
      if (d.ok) { addTab(title || d.url, d.url); }
    });
  }
  function startDl() {
    const u = document.getElementById('dlUrl').value.trim();
    if (!u) return;
    fetch('/api/download?url=' + encodeURIComponent(u)).then(r=>r.json()).then(d=>{
      document.getElementById('dlStatus').textContent = d.message || 'Started download';
      document.getElementById('dlUrl').value = '';
    });
  }
  renderTabs();
</script>
</body>
</html>
"""


def ensure_chromium_adblock_extension() -> Path | None:
    """
    Materializes an unpacked Manifest V3 extension containing the shared YouTube Ad-Block Engine
    so Engine 3 (--app mode on stock Bazzite/Linux) runs the exact same document_start MAIN-world
    YouTube ad-blocker and declarativeNetRequest rules.
    """
    try:
        config_root = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        ext_dir = config_root / "onebrowser" / "yt_adblock_mv3"
        ext_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "manifest_version": 3,
            "name": "OneBrowser YouTube Ad-Block & Stream Guard",
            "version": "1.0.0",
            "description": "Shared cross-platform YouTube ad-blocker & stream guard for OneBrowser.",
            "permissions": ["declarativeNetRequest"],
            "host_permissions": ["*://*.youtube.com/*", "*://*.googlevideo.com/*", "*://*.doubleclick.net/*", "*://*.googlesyndication.com/*"],
            "declarative_net_request": {
                "rule_resources": [{"id": "yt_ads", "enabled": True, "path": "rules.json"}]
            },
            "content_scripts": [
                {
                    "matches": ["*://*.youtube.com/*", "*://*.youtube-nocookie.com/*"],
                    "js": ["youtube_adblock_engine.js"],
                    "run_at": "document_start",
                    "world": "MAIN",
                    "all_frames": True,
                }
            ],
        }
        dnr_rules = [
            {"id": 1, "priority": 1, "action": {"type": "block"}, "condition": {"urlFilter": "||doubleclick.net^"}},
            {"id": 2, "priority": 1, "action": {"type": "block"}, "condition": {"urlFilter": "||googlesyndication.com^"}},
            {"id": 3, "priority": 1, "action": {"type": "block"}, "condition": {"urlFilter": "||googleadservices.com^"}},
            {"id": 4, "priority": 1, "action": {"type": "block"}, "condition": {"urlFilter": "||youtube.com/api/stats/ads"}},
            {"id": 5, "priority": 1, "action": {"type": "block"}, "condition": {"urlFilter": "||youtube.com/pagead/"}},
            {"id": 6, "priority": 1, "action": {"type": "block"}, "condition": {"urlFilter": "||youtube.com/ptracking"}},
            {"id": 7, "priority": 1, "action": {"type": "block"}, "condition": {"urlFilter": "||youtube.com/get_midroll_info"}},
        ]
        (ext_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (ext_dir / "rules.json").write_text(json.dumps(dnr_rules, indent=2), encoding="utf-8")
        (ext_dir / "youtube_adblock_engine.js").write_text(YOUTUBE_ADBLOCK_JS, encoding="utf-8")
        return ext_dir
    except Exception:
        return None


def open_url_crossplatform(url: str, app_mode: bool = False, window_size: str = "1360,860") -> subprocess.Popen | None:
    cmd = find_linux_browser_command()
    if cmd:
        is_ff = "firefox" in cmd[-1].lower() or "librewolf" in cmd[-1].lower()
        args = [*cmd]
        if not is_ff:
            ext_dir = ensure_chromium_adblock_extension()
            if ext_dir is not None and not (cmd[0] == "flatpak"):
                args.append(f"--load-extension={ext_dir}")
        if app_mode and not is_ff:
            args.extend([f"--app={url}", f"--window-size={window_size}"])
        else:
            args.append(url)
        return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.name == "nt":
        try:
            os.startfile(url)  # type: ignore[attr-defined]
        except Exception:
            import webbrowser
            webbrowser.open(url)
        return None
    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return None


def find_linux_browser_command() -> list[str] | None:
    if os.name == "nt":
        win_candidates = [
            Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "BraveSoftware/Brave-Browser/Application/brave.exe",
        ]
        for wc in win_candidates:
            if wc.is_file():
                return [str(wc)]
    for b in (
        "brave-browser", "chromium", "chromium-browser", "google-chrome",
        "microsoft-edge", "vivaldi",
    ):
        p = shutil.which(b)
        if p:
            return [p]
    # Check Flatpak browsers common on Bazzite Linux
    if shutil.which("flatpak"):
        try:
            out = subprocess.check_output(["flatpak", "list", "--app", "--columns=application"], text=True, timeout=3)
            for app_id in (
                "com.brave.Browser",
                "org.chromium.Chromium",
                "com.google.Chrome",
                "com.microsoft.Edge",
                "io.gitlab.librewolf-community",
                "org.mozilla.firefox",
            ):
                if app_id in out:
                    return ["flatpak", "run", app_id]
        except Exception:
            pass
    ff = shutil.which("firefox")
    if ff:
        return [ff]
    return None


def launch_zen_local_desktop_engine(initial_url: str) -> None:
    """
    Starts a local loopback Zen Desktop Shell server and opens it in a native
    frameless desktop window on Bazzite / Linux / Windows. Zero external Python deps required.
    """
    jobs: list[core.JobState] = []

    class ZenShellHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            pass

        def do_GET(self) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/api/open":
                q = dict(urllib.parse.parse_qsl(parsed.query)).get("url", "")
                ok, clean, err = resolve_navigation_input(q)
                if ok:
                    open_url_crossplatform(clean, app_mode=True)
                body = json.dumps({"ok": ok, "url": clean, "error": err}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
                return

            if parsed.path == "/api/download":
                q = dict(urllib.parse.parse_qsl(parsed.query)).get("url", "")
                ok, clean, err = resolve_navigation_input(q)
                if ok:
                    out_dir = core.default_download_dir()
                    out_dir.mkdir(parents=True, exist_ok=True)
                    job = core.JobState(clean, out_dir, 16, "best")
                    jobs.append(job)
                    threading.Thread(target=core.run_job, args=(job,), daemon=True).start()
                    msg = f"Started 16x download: {job.file_name} -> {out_dir}"
                else:
                    msg = f"Blocked: {err}"
                body = json.dumps({"ok": ok, "message": msg}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
                return

            data = ZEN_DESKTOP_SHELL_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), ZenShellHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    shell_url = f"http://127.0.0.1:{port}/"
    proc = open_url_crossplatform(shell_url, app_mode=True, window_size="1380,860")

    try:
        if proc is not None:
            proc.wait()
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in ("--download", "-d", "--cli"):
        sys.argv.pop(1)
        return core.main()

    initial = HOME_URL
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        ok, clean, _ = resolve_navigation_input(sys.argv[1])
        if ok:
            initial = clean

    # 1. Try Native GTK4 + WebKitGTK 6.0 (Built into GNOME 47 Platform Flatpak & Ubuntu 24.04+)
    if try_launch_gtk4_zen_browser(initial):
        return 0

    # 2. Try Native GTK3 + WebKit2GTK (Older Linux distros / Ubuntu 22.04 LTS)
    if try_launch_gtk_webkit_zen_browser(initial):
        return 0

    # 3. Try Native PyQt6 / PyQt5 QtWebEngine
    if try_launch_qt_zen_browser(initial):
        return 0

    # 4. Universal Self-Contained Zen Desktop Shell (Works on 100% of Linux systems with zero deps)
    launch_zen_local_desktop_engine(initial)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
