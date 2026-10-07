/* Read-only playback of a video assigned in Admin Media.
 *
 * The welcome screen asks /api/design/settings for one public URL field.
 * Nothing here writes a chat, claim, or application record.
 */
(function () {
    'use strict';

    function isPlayableUrl(url) {
        if (!url) return false;
        if (url.indexOf('data:video/') === 0) return true;
        if (url.charAt(0) === '/' && url.charAt(1) !== '/' && url.indexOf('..') === -1) return true;
        return /^https?:\/\//i.test(url);
    }

    function mount(root) {
        const field = root.getAttribute('data-url-field');
        const video = root.querySelector('video');
        if (!field || !video) return;
        fetch('/api/design/settings')
            .then(function (resp) { return resp.ok ? resp.json() : null; })
            .then(function (settings) {
                const url = settings ? String(settings[field] || '').trim() : '';
                if (!isPlayableUrl(url)) return;
                video.addEventListener('error', function () {
                    video.removeAttribute('src');
                    root.hidden = true;
                }, { once: true });
                video.src = url;
                root.hidden = false;
            })
            .catch(function () { /* the chat still starts without the video */ });
    }

    function mountAll() {
        document.querySelectorAll('[data-media-disclaimer]').forEach(mount);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mountAll);
    } else {
        mountAll();
    }
})();
