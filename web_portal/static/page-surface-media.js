/**
 * Shared photo / video placement for public surfaces (login, solutions).
 * Same URL rules as the landing hero: only same-origin paths, https URLs,
 * or data: video/image payloads. A missing or rejected file never writes
 * design settings and never leaves a broken player visible.
 */
(function (root) {
  'use strict';

  function isPlayableMediaUrl(url) {
    if (typeof url !== 'string') return false;
    var value = url.trim();
    if (!value) return false;
    if (value.indexOf('data:video/') === 0 || value.indexOf('data:image/') === 0) return true;
    if (value.charAt(0) === '/' && value.charAt(1) !== '/' && value.indexOf('..') === -1) return true;
    return /^https?:\/\//i.test(value);
  }

  function prefersReducedMotion() {
    return !!(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  function applyBackground(target, url, veil) {
    if (!target || !isPlayableMediaUrl(url)) return false;
    var overlay = veil || 'linear-gradient(rgba(4,9,22,0.72), rgba(4,9,22,0.86))';
    target.style.backgroundImage = overlay + ', url(' + JSON.stringify(url) + ')';
    target.style.backgroundSize = 'cover';
    target.style.backgroundPosition = 'center';
    target.classList.add('has-photo');
    return true;
  }

  function applyVideo(section, video, url, poster) {
    if (!section || !video) return false;
    if (!isPlayableMediaUrl(url)) {
      video.removeAttribute('src');
      video.removeAttribute('poster');
      section.hidden = true;
      return false;
    }
    video.addEventListener('error', function () {
      video.removeAttribute('src');
      section.hidden = true;
    }, { once: true });
    if (isPlayableMediaUrl(poster)) video.poster = poster;
    else video.removeAttribute('poster');
    video.src = url;
    if (prefersReducedMotion()) {
      video.removeAttribute('autoplay');
      video.pause();
    }
    section.hidden = false;
    return true;
  }

  function applyBanner(host, url, bannerId) {
    bannerId = bannerId || 'page-promo-banner';
    var existing = document.getElementById(bannerId);
    if (!isPlayableMediaUrl(url)) {
      if (existing) existing.hidden = true;
      return false;
    }
    if (existing) {
      var img = existing.querySelector('img');
      if (img) {
        img.src = url;
        img.onerror = function () { existing.hidden = true; };
      }
      existing.hidden = false;
      return true;
    }
    if (!host) return false;
    var banner = document.createElement('div');
    banner.id = bannerId;
    banner.className = 'page-promo-banner';
    var image = document.createElement('img');
    image.src = url;
    image.alt = 'Promotion';
    image.onerror = function () { banner.hidden = true; };
    banner.appendChild(image);
    host.appendChild(banner);
    return true;
  }

  root.PhinsPageMedia = {
    isPlayableMediaUrl: isPlayableMediaUrl,
    applyBackground: applyBackground,
    applyVideo: applyVideo,
    applyBanner: applyBanner
  };
})(window);
