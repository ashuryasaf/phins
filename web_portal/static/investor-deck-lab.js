/* Investor deck film.
   One 15-second scene per deck paragraph. The stream plays only the clips
   whose spoken line still matches the current plan. A missing clip is not
   a gap: the next stored scene follows. Charts and the founder portrait
   come from the plan, not from the generated frame. */
(function () {
    var STYLE_ID = 'investor-deck-lab-style';
    var mountedEditClicks = new WeakMap();

    function token() {
        try {
            return localStorage.getItem('phins_auth_token') ||
                localStorage.getItem('phins_token') ||
                sessionStorage.getItem('phins_token') || '';
        } catch (e) {
            return '';
        }
    }

    function esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function ensureStyle() {
        if (document.getElementById(STYLE_ID)) return;
        var style = document.createElement('style');
        style.id = STYLE_ID;
        style.textContent = [
            '.idl { color: inherit; font-family: Inter, "Segoe UI", sans-serif; }',
            '.idl-stage { margin: 0 0 14px; padding: 12px; border-radius: 14px; border: 1px solid rgba(227,191,111,0.45); background: rgba(6,13,31,0.35); }',
            '.idl-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 10px; }',
            '.idl-btn { appearance: none; border: 1px solid rgba(227,191,111,0.7); background: linear-gradient(180deg,#f7e2a0,#e3bf6f); color: #071022; font-weight: 700; border-radius: 8px; padding: 7px 12px; cursor: pointer; }',
            '.idl-btn.secondary { background: transparent; color: inherit; font-weight: 600; }',
            '.idl-note { font-size: 12.5px; opacity: 0.88; margin: 0 0 8px; line-height: 1.45; }',
            '.idl-status { font-size: 12.5px; min-height: 1.2em; margin: 6px 0 0; }',
            '.idl-clips { display: grid; gap: 12px; }',
            '.idl-clip { display: grid; grid-template-columns: minmax(220px, 1.4fr) minmax(180px, 0.8fr); gap: 10px; padding: 10px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.14); background: rgba(255,255,255,0.04); }',
            '.idl-clip.is-current { border-color: #e3bf6f; box-shadow: 0 0 0 1px rgba(227,191,111,0.45); }',
            '.idl-clip video { width: 100%; border-radius: 8px; background: #000; max-height: 280px; }',
            '.idl-side { display: flex; flex-direction: column; gap: 8px; min-width: 0; }',
            '.idl-side svg { width: 100%; height: auto; background: #fff; border-radius: 8px; }',
            '.idl-side img { width: 100%; max-height: 160px; object-fit: cover; border-radius: 8px; background: #0b1733; }',
            '.idl-caption { font-size: 12.5px; line-height: 1.4; grid-column: 1 / -1; }',
            '.idl-caption strong { font-family: "Space Grotesk", Inter, sans-serif; }',
            '.idl-slides { display: flex; flex-direction: column; gap: 14px; margin-top: 8px; }',
            '.idl-slide { padding: 12px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.12); }',
            '.idl-slide h3 { margin: 0 0 4px; font-size: 15px; font-family: "Space Grotesk", Inter, sans-serif; }',
            '.idl-kicker { font-size: 12px; opacity: 0.8; margin: 0 0 8px; }',
            '.idl-paragraph { margin: 0 0 10px; padding-bottom: 10px; border-bottom: 1px solid rgba(255,255,255,0.08); }',
            '.idl-paragraph p { margin: 4px 0; font-size: 13px; line-height: 1.45; }',
            '.idl-paragraph label { display: block; font-size: 11px; letter-spacing: 0.04em; text-transform: uppercase; opacity: 0.75; margin-top: 6px; }',
            '.idl-paragraph input, .idl-paragraph select, .idl select { width: 100%; max-width: 520px; margin-top: 3px; }',
            '@media (max-width: 720px) { .idl-clip { grid-template-columns: 1fr; } }'
        ].join('\n');
        document.head.appendChild(style);
    }

    function authHeaders(json) {
        var headers = { 'Authorization': 'Bearer ' + token() };
        if (json) headers['Content-Type'] = 'application/json';
        return headers;
    }

    function chartSvg(data, chartId) {
        if (!chartId || !data.charts || !data.charts[chartId]) return '';
        var svg = String(data.charts[chartId].svg || '');
        if (svg.indexOf('<svg') !== 0 && svg.indexOf('<svg') === -1) return '';
        return svg;
    }

    function armClip(video) {
        if (!video || video.dataset.armed === '1') return;
        // A later scene starts from the previous clip's ended event, which is
        // not a user gesture. play() during the click clears that restriction
        // on this element; pause before a frame so the film does not overlap.
        video.muted = true;
        try {
            var pending = video.play();
            video.pause();
            try { video.currentTime = 0; } catch (e) { /* metadata not in yet */ }
            video.muted = false;
            video.dataset.armed = '1';
            if (pending && pending.catch) pending.catch(function () {});
        } catch (e) {
            video.muted = false;
        }
    }

    function armOtherClips(state, currentIndex) {
        state.clips.forEach(function (clip, index) {
            if (index === currentIndex) return;
            armClip(clip.querySelector('video'));
        });
    }

    function renderStream(root, data, state) {
        var host = root.querySelector('[data-idl-stream]');
        if (!host) return;
        var stream = Array.isArray(data.stream) ? data.stream : [];
        if (!stream.length) {
            host.innerHTML = '<p class="idl-note">No filmed scenes for this plan yet. A paragraph joins the film only after its 15-second clip is stored and its spoken line still matches the plan. A paragraph without a clip is skipped.</p>';
            state.clips = [];
            return;
        }
        host.innerHTML = stream.map(function (scene, index) {
            var chart = chartSvg(data, scene.chart_id);
            var photo = scene.photo_url ? '<img alt="Founder portrait" src="' + esc(scene.photo_url) + '" data-idl-photo>' : '';
            var reference = scene.reference_url ? '<img alt="Scene photo" src="' + esc(scene.reference_url) + '">' : '';
            var aside = chart || photo || reference
                ? '<div class="idl-side">' + chart + photo + reference + '</div>'
                : '';
            return '<article class="idl-clip" data-stream-index="' + index + '">' +
                '<video playsinline webkit-playsinline preload="' + (index === 0 ? 'auto' : 'metadata') + '" src="' + esc(scene.playback_url) + '"></video>' +
                aside +
                '<div class="idl-caption"><strong>Slide ' + esc(scene.slide_no) + ' · ' + esc(scene.slide_title) +
                '</strong><br>Paragraph ' + esc(scene.paragraph_no) + ' of ' + esc(scene.paragraph_count) +
                ' · 15 seconds' +
                (scene.presenter_label ? '<br>Presenter · ' + esc(scene.presenter_label) : '') +
                '<br>' + esc(scene.narration) + '</div></article>';
        }).join('');
        host.querySelectorAll('[data-idl-photo]').forEach(function (img) {
            img.addEventListener('error', function () { img.remove(); });
        });
        state.clips = Array.prototype.slice.call(host.querySelectorAll('.idl-clip'));
        state.clips.forEach(function (clip, index) {
            var video = clip.querySelector('video');
            video.addEventListener('ended', function () {
                if (state.cursor === index && index + 1 < state.clips.length) playAt(state, index + 1);
            });
            video.addEventListener('error', function () {
                if (state.cursor === index && index + 1 < state.clips.length) playAt(state, index + 1);
            });
        });
    }

    function playAt(state, index) {
        if (!state.clips.length || index < 0 || index >= state.clips.length) return;
        state.cursor = index;
        state.blocked = false;
        state.clips.forEach(function (clip, clipIndex) {
            clip.classList.toggle('is-current', clipIndex === index);
            var node = clip.querySelector('video');
            if (!node) return;
            if (clipIndex !== index && !node.paused) node.pause();
        });
        var current = state.clips[index];
        var video = current.querySelector('video');
        if (!video) return;
        var upcoming = state.clips[index + 1];
        if (upcoming) {
            var nextVideo = upcoming.querySelector('video');
            if (nextVideo) nextVideo.preload = 'auto';
        }
        if (current.scrollIntoView) current.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        video.muted = false;
        var generation = (state.generation || 0) + 1;
        state.generation = generation;
        var played = video.play();
        if (played && played.catch) {
            played.catch(function (err) {
                if (state.generation !== generation) return;
                if (err && err.name === 'AbortError') return;
                state.blocked = true;
                if (state.root) setStatus(state.root, 'The film stopped. Press Play the film to continue.');
            });
        }
    }

    function groupSlides(scenes) {
        var slides = [];
        var index = {};
        (scenes || []).forEach(function (scene) {
            var key = String(scene.slide_no);
            if (!index[key]) {
                index[key] = {
                    slide_no: scene.slide_no,
                    slide_title: scene.slide_title,
                    kicker: scene.kicker,
                    chart_id: scene.chart_id,
                    photo_url: scene.photo_url,
                    paragraphs: []
                };
                slides.push(index[key]);
            }
            index[key].paragraphs.push(scene);
        });
        return slides;
    }

    function imageOptions(images, selected) {
        var list = [];
        try { list = (typeof images === 'function' ? images() : images) || []; } catch (e) { list = []; }
        var html = '<option value="">No library photo</option>';
        list.filter(function (asset) { return asset && asset.type === 'image'; }).forEach(function (asset) {
            var id = String(asset.id || '');
            html += '<option value="' + esc(id) + '"' + (id === selected ? ' selected' : '') + '>' +
                esc(asset.name || id) + '</option>';
        });
        if (selected && html.indexOf('value="' + esc(selected) + '"') === -1) {
            html += '<option value="' + esc(selected) + '" selected>Missing image ' + esc(selected) + '</option>';
        }
        return html;
    }

    function syncImages(target, images) {
        if (!target || !target.querySelectorAll) return;
        target.querySelectorAll('select[data-idl-photo-select]').forEach(function (select) {
            select.innerHTML = imageOptions(images, select.value);
        });
    }

    function renderEditor(root, data, images) {
        var host = root.querySelector('[data-idl-editor]');
        if (!host) return;
        var engines = Array.isArray(data.engines) ? data.engines : [];
        var engineHtml = engines.length
            ? '<label>Engine <select data-idl-engine>' + engines.map(function (engine) {
                return '<option value="' + esc(engine.id) + '">' + esc(engine.label) + ' · 15s</option>';
            }).join('') + '</select></label>'
            : '<p class="idl-note">No connected engine can hold a 15-second scene.</p>';
        var slides = groupSlides(data.scenes).map(function (slide) {
            var chart = chartSvg(data, slide.chart_id);
            var photo = slide.photo_url ? '<img alt="Founder portrait" src="' + esc(slide.photo_url) + '" data-idl-photo>' : '';
            var paragraphs = slide.paragraphs.map(function (scene) {
                var state = !scene.integrity_ok
                    ? 'Checksum mismatch. Reset this paragraph before sending.'
                    : scene.in_stream
                        ? 'In the film.'
                        : scene.last_asset_id
                            ? 'A clip is stored for an earlier plan and is not in the film.'
                            : 'Not filmed.';
                return '<div class="idl-paragraph" data-scene="' + esc(scene.scene_key) + '">' +
                    '<p><strong>Paragraph ' + esc(scene.paragraph_no) + '</strong> · ' + esc(state) +
                    (scene.presenter_label ? ' · ' + esc(scene.presenter_label) : '') + '</p>' +
                    '<p>' + esc(scene.narration) + '</p>' +
                    '<label>Theme <input data-idl-theme maxlength="240" value="' + esc(scene.theme) + '" placeholder="Optional setting, unspoken"></label>' +
                    '<label>Library photo <select data-idl-photo-select>' + imageOptions(images, scene.reference_image_asset_id) + '</select></label>' +
                    '<div class="idl-row">' +
                    '<button type="button" class="idl-btn" data-idl-send="' + esc(scene.scene_key) + '">Film 15s</button>' +
                    '<button type="button" class="idl-btn secondary" data-idl-reassign="' + esc(scene.scene_key) + '">New presenter</button>' +
                    '<button type="button" class="idl-btn secondary" data-idl-reset="' + esc(scene.scene_key) + '">Reset</button>' +
                    '</div></div>';
            }).join('');
            return '<section class="idl-slide"><h3>Slide ' + esc(slide.slide_no) + ' · ' + esc(slide.slide_title) +
                ' · ' + slide.paragraphs.length + ' paragraph' + (slide.paragraphs.length === 1 ? '' : 's') + '</h3>' +
                (slide.kicker ? '<p class="idl-kicker">' + esc(slide.kicker) + '</p>' : '') +
                (chart || photo ? '<div class="idl-side">' + chart + photo + '</div>' : '') +
                paragraphs + '</section>';
        }).join('');
        host.innerHTML = engineHtml + '<div class="idl-slides">' + slides + '</div>';
        host.querySelectorAll('[data-idl-photo]').forEach(function (img) {
            img.addEventListener('error', function () { img.remove(); });
        });
    }

    function setStatus(root, text) {
        var node = root.querySelector('[data-idl-status]');
        if (node) node.textContent = text || '';
    }

    function selectedEngine(root, data) {
        var select = root.querySelector('[data-idl-engine]');
        var id = select ? select.value : '';
        var engines = Array.isArray(data.engines) ? data.engines : [];
        for (var i = 0; i < engines.length; i += 1) {
            if (engines[i].id === id) return engines[i];
        }
        return engines[0] || null;
    }

    function sceneFields(root, sceneKey) {
        var block = root.querySelector('[data-scene="' + sceneKey + '"]');
        return {
            theme: block ? (block.querySelector('[data-idl-theme]') || {}).value || '' : '',
            reference_image_asset_id: block ? (block.querySelector('[data-idl-photo-select]') || {}).value || '' : ''
        };
    }

    async function refresh(root, mode, images, state) {
        var response = await fetch('/api/admin/media/investor-deck', { headers: authHeaders(false) });
        var data = await response.json();
        if (!response.ok) throw new Error(data.error || 'The investor deck could not be loaded');
        state.data = data;
        var hash = data.plan && data.plan.content_hash ? String(data.plan.content_hash).slice(0, 12) : '';
        setStatus(root,
            (data.stream_count || 0) + ' scene' + ((data.stream_count === 1) ? '' : 's') +
            ' in the film · ' + (data.scene_count || 0) + ' paragraphs · plan ' +
            (data.plan && data.plan.factors_source ? data.plan.factors_source : '') +
            (hash ? ' · ' + hash : '')
        );
        renderStream(root, data, state);
        if (mode === 'edit') renderEditor(root, data, images);
        return data;
    }

    async function postScene(root, mode, images, state, path, sceneKey, extra) {
        var fields = sceneFields(root, sceneKey);
        var body = Object.assign({
            scene_key: sceneKey,
            theme: fields.theme,
            reference_image_asset_id: fields.reference_image_asset_id,
            poll_mode: 'poll',
            auto_publish_to_hero: false
        }, extra || {});
        if (path.indexOf('/send') !== -1) {
            var engine = selectedEngine(root, state.data || {});
            if (!engine) throw new Error('Choose a 15-second engine');
            body.engine_id = engine.id;
            body.provider = engine.provider;
            body.provider_model = engine.model;
        }
        setStatus(root, path.indexOf('/send') !== -1 ? 'Sending the paragraph…' : 'Saving…');
        var response = await fetch(path, {
            method: 'POST',
            headers: authHeaders(true),
            body: JSON.stringify(body)
        });
        var data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Request failed');
        await refresh(root, mode, images, state);
        return data;
    }

    function mount(target, options) {
        if (!target) return;
        ensureStyle();
        var priorClick = mountedEditClicks.get(target);
        if (priorClick) {
            target.removeEventListener('click', priorClick);
            mountedEditClicks.delete(target);
        }
        var mode = options && options.mode === 'edit' ? 'edit' : 'watch';
        var images = options && options.images;
        var state = { clips: [], cursor: 0, data: null, root: target, blocked: false };
        target.innerHTML = '<div class="idl">' +
            '<div class="idl-stage">' +
            '<p class="idl-note">Part II, one 15-second scene per paragraph. The film plays the scenes that exist, in order, and skips the rest. Charts and the founder portrait are the plan’s own, shown beside the clip. The spoken line is the paragraph as the plan fills it.</p>' +
            '<div class="idl-row"><button type="button" class="idl-btn" data-idl-play>Play the film</button>' +
            '<a class="idl-btn secondary" href="' + (mode === 'edit' ? '/investor-deck.html?edit=1' : '/investor-deck.html') + '">Present the 13 slides</a>' +
            (mode === 'watch' ? '<a class="idl-btn secondary" href="/admin-media.html#investor-deck">Open the investor deck lab</a>' : '') +
            '</div><div data-idl-stream></div><p class="idl-status" data-idl-status>Loading the deck…</p></div>' +
            (mode === 'edit' ? '<div data-idl-editor></div>' : '') +
            '</div>';
        var play = target.querySelector('[data-idl-play]');
        if (play) play.addEventListener('click', function () {
            var index = state.blocked ? state.cursor : 0;
            armOtherClips(state, index);
            playAt(state, index);
        });
        if (mode === 'edit') {
            var onEditClick = function (event) {
                var send = event.target && event.target.getAttribute && event.target.getAttribute('data-idl-send');
                var reassign = event.target && event.target.getAttribute && event.target.getAttribute('data-idl-reassign');
                var reset = event.target && event.target.getAttribute && event.target.getAttribute('data-idl-reset');
                var sceneKey = send || reassign || reset;
                if (!sceneKey) return;
                var path = reset ? '/api/admin/media/investor-deck' : '/api/admin/media/investor-deck/send';
                var extra = reset ? { reset: true } : (reassign ? { reassign_presenter: true } : {});
                postScene(target, mode, images, state, path, sceneKey, extra).then(function (data) {
                    setStatus(target, data.message || 'Saved.');
                }).catch(function (err) {
                    setStatus(target, err.message || 'Request failed');
                });
            };
            mountedEditClicks.set(target, onEditClick);
            target.addEventListener('click', onEditClick);
        }
        refresh(target, mode, images, state).catch(function (err) {
            setStatus(target, err.message || 'The investor deck could not be loaded');
        });
    }

    window.InvestorDeckLab = { mount: mount, syncImages: syncImages };
})();
