/**
 * Shared Cross-Platform YouTube Ad-Block & Stream Guard Engine (v2026.11.11.1)
 * Targets: Linux (WebKit2GTK / QtWebEngine), Windows (WebView2), Android (WebView)
 *
 * Guarantees:
 * - Blocks pre-roll, mid-roll, and post-roll video ads via Innertube JSON pruning + DOM fast-forward
 * - Hides masthead banners, home/search promoted feed tiles, watch-page companion ads, and overlay ads
 * - Neutralizes YouTube anti-adblock enforcement dialogs without breaking login, search, comments, or 4K playback
 */
(() => {
  'use strict';
  if (window.__obYouTubeAdBlockActive) return;
  window.__obYouTubeAdBlockActive = true;

  const host = (location.hostname || '').toLowerCase();
  const isYouTube =
    host === 'youtube.com' ||
    host.endsWith('.youtube.com') ||
    host === 'youtu.be' ||
    host.endsWith('.youtube-nocookie.com');

  if (!isYouTube) return;

  // ---------------------------------------------------------------------------
  // 1. RECURSIVE INNERTUBE PLAYER & FEED AD PRUNER
  // ---------------------------------------------------------------------------
  const AD_PRUNE_KEYS = [
    'adPlacements',
    'playerAds',
    'adSlots',
    'adBreakHeartbeatParams'
  ];

  const pruneYouTubePayload = (obj, depth = 0) => {
    if (!obj || typeof obj !== 'object' || depth > 5) return obj;
    try {
      for (let i = 0; i < AD_PRUNE_KEYS.length; i++) {
        const k = AD_PRUNE_KEYS[i];
        if (k in obj) {
          delete obj[k];
        }
      }
      // Strip anti-adblock enforcement popup renderer from player response
      if (obj.auxiliaryUi && obj.auxiliaryUi.messageRenderers) {
        delete obj.auxiliaryUi.messageRenderers.enforcementMessageViewModel;
        delete obj.auxiliaryUi.messageRenderers.bkaEnforcementMessageViewModel;
      }
      if (obj.playabilityStatus && obj.playabilityStatus.errorScreen) {
        const errScreen = obj.playabilityStatus.errorScreen;
        if (errScreen.playerErrorMessageRenderer || errScreen.EnforcementMessageViewModel) {
          // Preserve normal age/region messages, only strip adblock enforcement
          const rawStr = JSON.stringify(errScreen);
          if (rawStr && rawStr.toLowerCase().includes('ad blocker')) {
            obj.playabilityStatus.status = 'OK';
            delete obj.playabilityStatus.errorScreen;
          }
        }
      }
      if (obj.playerResponse && typeof obj.playerResponse === 'object') {
        pruneYouTubePayload(obj.playerResponse, depth + 1);
      }
      if (Array.isArray(obj.onResponseReceivedEndpoints)) {
        for (let j = 0; j < obj.onResponseReceivedEndpoints.length; j++) {
          pruneYouTubePayload(obj.onResponseReceivedEndpoints[j], depth + 1);
        }
      }
    } catch (_) {}
    return obj;
  };

  // ---------------------------------------------------------------------------
  // 2. TRAP GLOBAL INITIAL PLAYER & DATA OBJECTS BEFORE POLYMER READS THEM
  // ---------------------------------------------------------------------------
  const trapGlobalProperty = (propName) => {
    try {
      let internalVal = window[propName];
      if (internalVal && typeof internalVal === 'object') {
        pruneYouTubePayload(internalVal);
      }
      Object.defineProperty(window, propName, {
        configurable: true,
        enumerable: true,
        get() {
          return internalVal;
        },
        set(newVal) {
          internalVal = pruneYouTubePayload(newVal);
        }
      });
    } catch (_) {}
  };

  trapGlobalProperty('ytInitialPlayerResponse');
  trapGlobalProperty('ytInitialData');

  // ---------------------------------------------------------------------------
  // 3. INTERCEPT JSON.parse, fetch(), AND XMLHttpRequest FOR SPA NAVIGATIONS
  // ---------------------------------------------------------------------------
  const isYouTubeAdEndpoint = (urlStr) => {
    if (!urlStr || typeof urlStr !== 'string') return false;
    const u = urlStr.toLowerCase();
    return (
      u.includes('/youtubei/v1/player/ad_break') ||
      u.includes('/api/stats/ads') ||
      u.includes('/pagead/interaction') ||
      u.includes('/pagead/lvz') ||
      u.includes('/pagead/adview') ||
      u.includes('/get_midroll_info') ||
      u.includes('doubleclick.net') ||
      u.includes('googlesyndication.com') ||
      u.includes('googleadservices.com')
    );
  };

  try {
    const origJsonParse = JSON.parse;
    JSON.parse = function () {
      const parsed = origJsonParse.apply(this, arguments);
      return pruneYouTubePayload(parsed);
    };
  } catch (_) {}

  try {
    if (window.Response && Response.prototype.json) {
      const origResJson = Response.prototype.json;
      Response.prototype.json = function () {
        return origResJson.apply(this, arguments).then((data) => pruneYouTubePayload(data));
      };
    }
  } catch (_) {}

  try {
    if (typeof window.fetch === 'function') {
      const origFetch = window.fetch;
      window.fetch = function (input, init) {
        try {
          const url = typeof input === 'string' ? input : (input && input.url ? input.url : '');
          if (isYouTubeAdEndpoint(url)) {
            return Promise.resolve(
              new Response('{}', {
                status: 200,
                headers: { 'Content-Type': 'application/json' }
              })
            );
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
            setTimeout(() => {
              if (typeof this.onload === 'function') this.onload();
              this.dispatchEvent(new Event('load'));
            }, 1);
            return;
          } catch (_) {}
        }
        return origSend.apply(this, arguments);
      };
    }
  } catch (_) {}

  // ---------------------------------------------------------------------------
  // 4. COSMETIC CSS FILTERING (DESKTOP ytd-* & MOBILE ytm-* SELECTORS)
  // ---------------------------------------------------------------------------
  const COSMETIC_CSS = `
    ytd-ad-slot-renderer,
    ytd-in-feed-ad-layout-renderer,
    ytd-promoted-sparkles-web-renderer,
    ytd-promoted-video-renderer,
    ytd-display-ad-renderer,
    ytd-statement-banner-renderer,
    ytd-banner-promo-renderer,
    ytd-video-masthead-ad-v3-renderer,
    ytd-primetime-promo-renderer,
    ytd-companion-slot-renderer,
    ytd-action-companion-ad-renderer,
    ytd-image-companion-ad-renderer,
    ytd-engagement-panel-section-list-renderer[target-id="engagement-panel-ads"],
    ytd-enforcement-message-view-model,
    ytm-promoted-sparkles-web-renderer,
    ytm-promoted-video-renderer,
    ytm-companion-ad-renderer,
    ytm-statement-banner-renderer,
    #masthead-ad,
    #player-ads,
    #offer-module,
    .ytp-ad-overlay-container,
    .ytp-ad-message-container,
    .ytp-featured-product,
    .ytd-mealbar-promo-renderer,
    tp-yt-paper-dialog:has(ytd-enforcement-message-view-model) {
      display: none !important;
      visibility: hidden !important;
      height: 0 !important;
      min-height: 0 !important;
      max-height: 0 !important;
      margin: 0 !important;
      padding: 0 !important;
      pointer-events: none !important;
      overflow: hidden !important;
    }
  `;

  const injectCosmeticStyles = () => {
    try {
      const root = document.head || document.documentElement;
      if (!root || document.getElementById('ob-yt-adblock-css')) return;
      const style = document.createElement('style');
      style.id = 'ob-yt-adblock-css';
      style.textContent = COSMETIC_CSS;
      root.appendChild(style);
    } catch (_) {}
  };

  // ---------------------------------------------------------------------------
  // 5. INSTANT VIDEO AD SKIPPER & ENFORCEMENT MODAL NEUTRALIZER
  // ---------------------------------------------------------------------------
  const SKIP_SELECTORS = [
    '.ytp-ad-skip-button',
    '.ytp-skip-ad-button',
    '.ytp-ad-skip-button-modern',
    '.ytp-ad-skip-button-slot button',
    '.ytp-ad-overlay-close-button',
    'button.ytp-ad-skip-button-modern'
  ].join(',');

  let wasMutedByAdGuard = false;
  let userPlaybackRate = 1.0;

  const mitigateActiveVideoAds = () => {
    try {
      injectCosmeticStyles();

      // A. Dismiss any anti-adblock enforcement popup & resume video if paused by it
      const enforcementModal = document.querySelector(
        'ytd-enforcement-message-view-model, tp-yt-paper-dialog:has(ytd-enforcement-message-view-model)'
      );
      if (enforcementModal) {
        enforcementModal.remove();
        const backdrop = document.querySelector('tp-yt-iron-overlay-backdrop');
        if (backdrop) backdrop.remove();
        const v = document.querySelector('video.html5-main-video, video');
        if (v && v.paused) {
          v.play().catch(() => {});
        }
      }

      // B. Click any visible skip or overlay-close buttons immediately
      const skipBtns = document.querySelectorAll(SKIP_SELECTORS);
      for (let i = 0; i < skipBtns.length; i++) {
        const btn = skipBtns[i];
        if (btn && typeof btn.click === 'function') {
          btn.click();
        }
      }

      // C. Detect active pre-roll / mid-roll ad state on #movie_player
      const player = document.querySelector(
        '.html5-video-player.ad-showing, .html5-video-player.ad-interrupting, .ad-showing'
      );
      const video = document.querySelector('video.html5-main-video, .html5-video-player video, video');

      if (player && video) {
        if (!wasMutedByAdGuard) {
          wasMutedByAdGuard = true;
          if (video.playbackRate > 0 && video.playbackRate <= 2) {
            userPlaybackRate = video.playbackRate;
          }
        }
        video.muted = true;
        if (Number.isFinite(video.duration) && video.duration > 0.5) {
          video.currentTime = Math.max(0, video.duration - 0.05);
        } else {
          video.playbackRate = 16.0;
        }
        if (video.paused) {
          video.play().catch(() => {});
        }
      } else if (wasMutedByAdGuard && video) {
        // Restore user's normal audio & playback rate immediately after ad ends
        wasMutedByAdGuard = false;
        video.muted = false;
        video.playbackRate = userPlaybackRate || 1.0;
      }
    } catch (_) {}
  };

  injectCosmeticStyles();
  setInterval(mitigateActiveVideoAds, 200);

  const attachPlayerObserver = () => {
    injectCosmeticStyles();
    mitigateActiveVideoAds();
    try {
      const target = document.documentElement || document.body;
      if (!target) return;
      const observer = new MutationObserver(() => {
        mitigateActiveVideoAds();
      });
      observer.observe(target, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['class', 'src']
      });
    } catch (_) {}
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attachPlayerObserver, { once: true });
  } else {
    attachPlayerObserver();
  }
  window.addEventListener('yt-navigate-finish', mitigateActiveVideoAds);
  window.addEventListener('yt-page-data-updated', mitigateActiveVideoAds);
})();
