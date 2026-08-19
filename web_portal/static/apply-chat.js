/* PHINS Chat Application ("Phin" flow)
 *
 * Conversational new-policy application client. The server
 * (/api/chat-application/*) owns the conversation state machine; this client
 * renders bot messages, morphs the input dock per step type, records
 * voice/video, uploads documents, handles the OTP gate and pause/resume, and
 * finalizes through the existing policy-creation backbone.
 */

(function () {
    'use strict';

    const API = '/api/chat-application';
    const STORE_KEY = 'phins.chatApplication.v1';

    const state = {
        appId: null,
        resumeCode: null,
        email: null,
        step: null,          // current step descriptor from the API
        otp: null,           // {verification_id}
        otpRestoreTranscript: false, // replay transcript after OTP only on a fresh-page resume
        busy: false,
        mediaCount: 0,
        submitted: false,
    };

    // ---- DOM ----------------------------------------------------------
    const $ = (id) => document.getElementById(id);
    const chatScroll = () => $('chat-scroll');
    const dock = () => $('chat-dock');

    // ---- utils --------------------------------------------------------

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = String(text == null ? '' : text);
        return div.innerHTML;
    }

    function richText(text) {
        // bot copy uses **bold** emphasis only
        return escapeHtml(text).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    }

    function fmtMoney(v, decimals = 2) {
        return new Intl.NumberFormat('en-US', {
            style: 'currency', currency: 'USD',
            minimumFractionDigits: decimals, maximumFractionDigits: decimals,
        }).format(v || 0);
    }

    async function api(method, path, body) {
        const resp = await fetch(API + path, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: body === undefined ? undefined : JSON.stringify(body),
        });
        let data = {};
        try { data = await resp.json(); } catch (e) { /* empty body */ }
        return { status: resp.status, data };
    }

    function saveLocal() {
        try {
            localStorage.setItem(STORE_KEY, JSON.stringify({
                appId: state.appId, resumeCode: state.resumeCode, email: state.email,
            }));
        } catch (e) { /* private mode */ }
    }

    function clearLocal() {
        try { localStorage.removeItem(STORE_KEY); } catch (e) { /* noop */ }
    }

    function loadLocal() {
        try { return JSON.parse(localStorage.getItem(STORE_KEY) || 'null'); }
        catch (e) { return null; }
    }

    function scrollClearance(el) {
        // >10% of page length (matches .chat-scroll::after spacer at 15vh).
        return Math.round((window.innerHeight || el.clientHeight || 800) * 0.15);
    }

    function lastChatContent(el) {
        const nodes = el.querySelectorAll('.msg-row, .chat-card');
        return nodes.length ? nodes[nodes.length - 1] : null;
    }

    // Stick-to-bottom through the whole chat (including after OTP → signature).
    // Programmatic scrolls keep the flag true; only intentional user scroll-up
    // pauses auto-follow until they return near the bottom.
    let stickToBottom = true;
    let scrollProgrammatic = false;
    let layoutScrollTimers = [];

    function nearBottom(el) {
        const clearance = scrollClearance(el);
        return (el.scrollHeight - el.scrollTop - el.clientHeight) <= clearance + 24;
    }

    function scrollDown(force) {
        const el = chatScroll();
        if (!el) return;
        if (force) stickToBottom = true;
        if (!stickToBottom) return;
        // Keep the latest Q&A visible above the dock: scroll the last content
        // into view (scroll-margin-bottom: 15vh preserves the gap), then pin to
        // the true bottom so the permanent spacer stays in place.
        const prev = el.style.scrollBehavior;
        el.style.scrollBehavior = 'auto';
        scrollProgrammatic = true;
        const run = () => {
            const last = lastChatContent(el);
            if (last && typeof last.scrollIntoView === 'function') {
                try {
                    last.scrollIntoView({ behavior: 'auto', block: 'end', inline: 'nearest' });
                } catch (e) { /* fall through to scrollTop */ }
            }
            el.scrollTop = el.scrollHeight + scrollClearance(el);
            requestAnimationFrame(() => {
                el.scrollTop = el.scrollHeight + scrollClearance(el);
                el.style.scrollBehavior = prev || '';
                // Allow the browser to settle before re-enabling user-scroll detection.
                setTimeout(() => { scrollProgrammatic = false; }, 80);
            });
        };
        requestAnimationFrame(run);
    }

    function afterLayoutScroll(opts) {
        // Re-run after dock widgets paint and after multi-bubble OTP follow-ups
        // (typing delays can stretch past 1s).
        const force = !(opts && opts.soft);
        layoutScrollTimers.forEach((id) => clearTimeout(id));
        layoutScrollTimers = [];
        const delays = [0, 50, 150, 350, 600, 1000, 1600, 2400];
        requestAnimationFrame(() => scrollDown(force));
        delays.slice(1).forEach((ms) => {
            layoutScrollTimers.push(setTimeout(() => scrollDown(force), ms));
        });
    }

    function focusWithoutScroll(el) {
        if (!el) return;
        try {
            el.focus({ preventScroll: true });
        } catch (e) {
            el.focus();
        }
        // Focusing dock controls can still nudge layout; re-pin the transcript.
        afterLayoutScroll({ soft: true });
    }

    // When the input dock grows/shrinks (OTP, signature, cards), keep the
    // latest Q&A scrolled into the visible gap above it. Also observe the
    // transcript itself so post-OTP cards/messages keep following to the end.
    let dockResizeObserver = null;
    let chatMutationObserver = null;
    function watchChatScrollFollow() {
        const el = chatScroll();
        const dockEl = dock();
        if (!el) return;

        if (!el.dataset.scrollFollowBound) {
            el.dataset.scrollFollowBound = '1';
            el.addEventListener('scroll', () => {
                if (scrollProgrammatic) return;
                stickToBottom = nearBottom(el);
            }, { passive: true });
        }

        if (typeof ResizeObserver !== 'undefined') {
            if (dockResizeObserver) dockResizeObserver.disconnect();
            dockResizeObserver = new ResizeObserver(() => {
                if (stickToBottom) scrollDown(false);
            });
            if (dockEl) dockResizeObserver.observe(dockEl);
            dockResizeObserver.observe(el);
        }

        if (typeof MutationObserver !== 'undefined') {
            if (chatMutationObserver) chatMutationObserver.disconnect();
            chatMutationObserver = new MutationObserver(() => {
                if (stickToBottom) scrollDown(false);
            });
            chatMutationObserver.observe(el, { childList: true, subtree: true });
        }
    }

    function watchDockResize() {
        // Back-compat alias used by switchToChat — wires full follow behavior.
        watchChatScrollFollow();
    }

    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

    function currentLanguage() {
        try {
            if (window.PhinsI18n && window.PhinsI18n.lang) return window.PhinsI18n.lang;
            return localStorage.getItem('phins_language') || 'en';
        } catch (e) { return 'en'; }
    }

    // ---- message rendering ---------------------------------------------

    function addBubble(role, html, extraClass) {
        const row = document.createElement('div');
        row.className = 'msg-row ' + role;
        if (role === 'bot') {
            row.innerHTML = '<div class="msg-avatar"><img src="/phins-logo.svg" alt=""></div>' +
                `<div class="msg-bubble ${extraClass || ''}">${html}</div>`;
        } else {
            row.innerHTML = `<div class="msg-bubble">${html}</div>`;
        }
        chatScroll().appendChild(row);
        scrollDown(true);
        return row;
    }

    function addTyping() {
        const row = document.createElement('div');
        row.className = 'msg-row bot typing-row';
        row.innerHTML = '<div class="msg-avatar"><img src="/phins-logo.svg" alt=""></div>' +
            '<div class="msg-bubble typing"><i></i><i></i><i></i></div>';
        chatScroll().appendChild(row);
        scrollDown(true);
        return row;
    }

    function addCard(html) {
        const card = document.createElement('div');
        card.className = 'chat-card';
        card.innerHTML = html;
        chatScroll().appendChild(card);
        scrollDown(true);
        return card;
    }

    function renderQuoteCard(quote) {
        const src = quote.pricing_source === 'pricing_kernel'
            ? 'Actuarial Pricing Kernel' : 'Standard Rate Card';
        const meta = quote.pricing_source === 'pricing_kernel'
            ? `Tables ${escapeHtml(quote.tables_version || '')} · Config ${escapeHtml(quote.config_version || '')}` +
              (quote.integrity_hash ? ` · Sealed <code>${escapeHtml(String(quote.integrity_hash).slice(0, 12))}</code>` : '')
            : 'Final premium confirmed at underwriting';
        addCard(`
            <h4>Your Personalized Quote <span class="card-badge">${escapeHtml(src)}</span></h4>
            <div class="quote-tiles">
                <div class="quote-tile">
                    <div class="quote-tile-label">Monthly</div>
                    <div class="quote-tile-value">${fmtMoney(quote.monthly)}</div>
                </div>
                <div class="quote-tile">
                    <div class="quote-tile-label">Quarterly</div>
                    <div class="quote-tile-value">${fmtMoney(quote.quarterly)}</div>
                    <div class="quote-tile-save">Save 3%</div>
                </div>
                <div class="quote-tile featured">
                    <div class="quote-tile-label">Annual</div>
                    <div class="quote-tile-value">${fmtMoney(quote.annual)}</div>
                    <div class="quote-tile-save">Save 10%</div>
                </div>
            </div>
            <div class="quote-meta">${fmtMoney(quote.coverage_amount, 0)} coverage · ${escapeHtml(String(quote.coverage_years || 20))} years · ${meta}</div>
        `);
    }

    function renderAssessmentCard(a) {
        const conf = Math.round((a.confidence || 0.8) * 100);
        addCard(`
            <h4>Broker Risk Assessment <span class="card-badge">Live AI Engine</span></h4>
            <div class="assess-grid">
                <div class="assess-line"><span>Risk profile</span><span class="val">${escapeHtml(String(a.risk_category || '').replace(/_/g, ' '))}</span></div>
                <div class="assess-line"><span>Recommendation</span><span class="val">${escapeHtml(String(a.recommendation_type || '').replace(/_/g, ' '))}</span></div>
                ${a.bmi ? `<div class="assess-line"><span>BMI</span><span class="val">${escapeHtml(String(a.bmi))}</span></div>` : ''}
                <div class="assess-line"><span>Confidence</span><span class="val">${conf}%</span></div>
                <div class="confidence-track"><div class="confidence-fill" style="width:${conf}%"></div></div>
            </div>
        `);
    }

    async function playMessages(messages, opts) {
        const options = opts || {};
        for (const msg of (messages || [])) {
            if (msg.role !== 'bot') {
                addBubble('user', richText(msg.text));
                continue;
            }
            if (!options.instant) {
                const t = addTyping();
                await sleep(Math.min(1400, 350 + (msg.text || '').length * 6));
                t.remove();
            }
            const cls = msg.kind === 'resume_code' ? 'resume-note'
                : (msg.kind === 'uw_decision' ? 'uw-decision' : '');
            let html = richText(msg.text);
            if (msg.kind === 'resume_code' && msg.meta && msg.meta.resume_code) {
                // Keep resume code ASCII / untranslated for tracking integrity.
                html = html.replace(escapeHtml(msg.meta.resume_code),
                    `<code data-no-i18n translate="no">${escapeHtml(msg.meta.resume_code)}</code>`);
            }
            addBubble('bot', html, cls);
            if (msg.kind === 'assessment' && msg.meta && msg.meta.assessment) {
                renderAssessmentCard(Object.assign({}, msg.meta.assessment));
            }
            if (msg.kind === 'quote' && msg.meta && msg.meta.quote) {
                renderQuoteCard(msg.meta.quote);
            }
        }
        afterLayoutScroll();
    }

    function setProgress(progress) {
        if (!progress) return;
        $('progress-wrap').hidden = false;
        $('progress-fill').style.width = progress.percent + '%';
        $('progress-label').textContent = progress.percent + '%';
    }

    function showHeaderTools() {
        if (state.resumeCode) {
            $('resume-pill').hidden = false;
            $('resume-pill-code').textContent = state.resumeCode;
        }
        $('pause-btn').hidden = false;
    }

    // ---- input dock ------------------------------------------------------

    function dockHtml(inner) {
        dock().innerHTML = `<div class="dock-inner">${inner}<div class="dock-error" id="dock-error" hidden></div></div>`;
    }

    function dockError(text) {
        const el = $('dock-error');
        if (el) { el.hidden = !text; el.textContent = text || ''; }
    }

    function clearDock() { dock().innerHTML = ''; }

    function renderStep(step) {
        state.step = step;
        dockError('');
        if (!step) { clearDock(); afterLayoutScroll(); return; }
        const input = step.input || { type: 'text' };
        switch (input.type) {
            case 'text':
            case 'email':
            case 'phone':
            case 'date':
            case 'number':
                renderTextInput(input);
                break;
            case 'choice':
                renderChoices(input);
                break;
            case 'multi_choice':
                renderMultiChoice(input);
                break;
            case 'slider':
                renderSlider(input);
                break;
            case 'media':
                renderMediaDock(input);
                break;
            case 'card':
                renderCardForm();
                break;
            case 'consent':
                renderConsent();
                break;
            case 'signature':
                renderSignature(input);
                break;
            default:
                renderTextInput({ type: 'text', placeholder: input.placeholder });
        }
        afterLayoutScroll();
    }

    function renderTextInput(input) {
        const typeMap = { text: 'text', email: 'email', phone: 'tel', date: 'date', number: 'number' };
        const htmlType = typeMap[input.type] || 'text';
        const attrs = [
            `type="${htmlType}"`,
            input.placeholder ? `placeholder="${escapeHtml(input.placeholder)}"` : '',
            input.min !== undefined ? `min="${input.min}"` : '',
            input.max !== undefined ? `max="${input.max}"` : '',
            'autocomplete="off"',
        ].join(' ');
        dockHtml(`
            <div class="dock-row">
                <input class="dock-input" id="dock-field" ${attrs}>
                <button class="send-btn" id="dock-send" title="Send">&#10148;</button>
            </div>
            ${input.suffix ? `<div class="dock-hint">${escapeHtml(input.suffix)}</div>` : ''}
        `);
        const field = $('dock-field');
        focusWithoutScroll(field);
        const send = () => {
            const value = field.value.trim();
            if (!value) return;
            submitAnswer(input.type === 'number' ? Number(value) : value, value);
        };
        $('dock-send').addEventListener('click', send);
        field.addEventListener('keydown', (e) => { if (e.key === 'Enter') send(); });
    }

    function renderChoices(input) {
        const labels = input.labels || {};
        const chips = (input.options || []).map((o) =>
            `<button class="chip" data-value="${escapeHtml(o)}">${escapeHtml(labels[o] || cap(o))}${input.suffix ? ' ' + escapeHtml(input.suffix) : ''}</button>`
        ).join('');
        dockHtml(`<div class="chips-wrap">${chips}</div>`);
        dock().querySelectorAll('.chip').forEach((chip) => {
            chip.addEventListener('click', () => {
                const v = chip.dataset.value;
                submitAnswer(v, (input.labels || {})[v] || cap(v));
            });
        });
    }

    function renderMultiChoice(input) {
        const chips = (input.options || []).map((o) =>
            `<button class="chip" data-value="${escapeHtml(o)}">${escapeHtml(cap(o))}</button>`
        ).join('');
        dockHtml(`
            <div class="dock-label">Pick all that apply, then confirm</div>
            <div class="chips-wrap" id="multi-chips">${chips}</div>
            <div class="dock-row" style="margin-top:10px; justify-content:flex-end;">
                <button class="chip chip-go" id="multi-confirm">Confirm</button>
            </div>
        `);
        const selected = new Set();
        dock().querySelectorAll('#multi-chips .chip').forEach((chip) => {
            chip.addEventListener('click', () => {
                const v = chip.dataset.value;
                if (v === 'none') {
                    selected.clear(); selected.add('none');
                    dock().querySelectorAll('#multi-chips .chip').forEach((c) => c.classList.remove('selected'));
                    chip.classList.add('selected');
                    return;
                }
                selected.delete('none');
                dock().querySelector('#multi-chips .chip[data-value="none"]')?.classList.remove('selected');
                if (selected.has(v)) { selected.delete(v); chip.classList.remove('selected'); }
                else { selected.add(v); chip.classList.add('selected'); }
            });
        });
        $('multi-confirm').addEventListener('click', () => {
            const values = selected.size ? Array.from(selected) : ['none'];
            submitAnswer(values, values.map(cap).join(', '));
        });
    }

    function renderSlider(input) {
        const min = input.min || 0, max = input.max || 100, step = input.step || 1;
        const start = input.default || min;
        dockHtml(`
            <div class="slider-value" id="slider-value"></div>
            <input type="range" class="dock-slider" id="dock-slider"
                   min="${min}" max="${max}" step="${step}" value="${start}">
            <div class="dock-row" style="justify-content:center;">
                <button class="chip chip-go" id="slider-confirm">Lock it in</button>
            </div>
        `);
        const slider = $('dock-slider');
        const label = $('slider-value');
        const paint = () => {
            label.textContent = input.format === 'currency'
                ? fmtMoney(Number(slider.value), 0) : slider.value;
        };
        paint();
        slider.addEventListener('input', paint);
        $('slider-confirm').addEventListener('click', () => {
            submitAnswer(Number(slider.value),
                input.format === 'currency' ? fmtMoney(Number(slider.value), 0) : slider.value);
        });
    }

    function renderCardForm() {
        dockHtml(`
            <div class="card-grid">
                <input class="dock-input full" id="cc-number" placeholder="Card number" inputmode="numeric" autocomplete="cc-number" maxlength="23">
                <input class="dock-input full" id="cc-name" placeholder="Cardholder name" autocomplete="cc-name" style="text-transform:uppercase;">
            </div>
            <div class="card-grid-3" style="margin-top:10px;">
                <input class="dock-input" id="cc-month" placeholder="MM" inputmode="numeric" maxlength="2" autocomplete="cc-exp-month">
                <input class="dock-input" id="cc-year" placeholder="YYYY" inputmode="numeric" maxlength="4" autocomplete="cc-exp-year">
                <input class="dock-input" id="cc-cvv" placeholder="CVV" type="password" inputmode="numeric" maxlength="4" autocomplete="cc-csc">
            </div>
            <div class="dock-row" style="margin-top:12px; justify-content:flex-end;">
                <button class="chip chip-go" id="cc-submit">Secure my card</button>
            </div>
            <div class="dock-hint">PCI-DSS: encrypted and tokenized - we never store the full number.</div>
        `);
        $('cc-number').addEventListener('input', (e) => {
            const digits = e.target.value.replace(/\D/g, '').slice(0, 19);
            e.target.value = (digits.match(/.{1,4}/g) || []).join(' ');
        });
        $('cc-submit').addEventListener('click', () => {
            const digits = $('cc-number').value.replace(/\D/g, '');
            submitAnswer({
                card_number: digits,
                cardholder_name: $('cc-name').value.trim(),
                expiry_month: $('cc-month').value.trim(),
                expiry_year: $('cc-year').value.trim(),
                cvv: $('cc-cvv').value.trim(),
            }, `Card ending in ${digits.slice(-4) || '????'}`);
        });
    }

    function renderConsent() {
        dockHtml(`
            <div class="consent-list">
                <label class="consent-item"><input type="checkbox" id="c-terms">
                    <span>I agree to the <a href="/terms-of-use.html" target="_blank">Terms of Use</a> and <a href="/privacy-policy.html" target="_blank">Privacy Policy</a>.</span></label>
                <label class="consent-item"><input type="checkbox" id="c-accuracy">
                    <span>Everything I told Phin is accurate and complete to the best of my knowledge.</span></label>
                <label class="consent-item"><input type="checkbox" id="c-billing">
                    <span>I authorize PHINS to charge my payment method for premiums and approved expenses.</span></label>
            </div>
            <div class="dock-row" style="justify-content:flex-end;">
                <button class="chip chip-go" id="consent-submit" disabled>I agree - continue to signature</button>
            </div>
        `);
        const boxes = ['c-terms', 'c-accuracy', 'c-billing'].map($);
        const btn = $('consent-submit');
        const refresh = () => { btn.disabled = !boxes.every((b) => b.checked); };
        boxes.forEach((b) => b.addEventListener('change', refresh));
        btn.addEventListener('click', () => submitAnswer('agree', 'I agree - all three confirmations'));
    }

    function renderSignature(input) {
        const namePh = escapeHtml(input.placeholder || 'Full legal name');
        const idPh = escapeHtml(input.id_placeholder || 'National ID / Teudat Zehut');
        dockHtml(`
            <div class="dock-label">Electronic signature (mandatory)</div>
            <div class="sig-fields">
                <input class="dock-input" id="dock-field" type="text"
                       placeholder="${namePh}" autocomplete="name">
                <input class="dock-input" id="dock-id-number" type="text"
                       placeholder="${idPh}" inputmode="numeric" autocomplete="off"
                       data-no-i18n>
            </div>
            <div class="sig-pad-wrap">
                <canvas class="sig-pad" id="sig-pad" width="520" height="140"
                        aria-label="Draw your signature"></canvas>
                <div class="sig-pad-actions">
                    <button type="button" class="link-btn" id="sig-clear">Clear signature</button>
                    <span class="dock-hint" id="sig-hint">Draw your signature above</span>
                </div>
            </div>
            <div class="dock-row" style="justify-content:flex-end; margin-top:10px;">
                <button class="chip chip-go" id="sign-submit">Sign &amp; seal</button>
            </div>
            <div class="dock-hint">Name must match this application. ID is sealed with your drawn signature for underwriting integrity.</div>
        `);
        afterLayoutScroll();

        const canvas = $('sig-pad');
        const ctx = canvas.getContext('2d');
        let drawing = false;
        let hasInk = false;
        const pos = (e) => {
            const r = canvas.getBoundingClientRect();
            const src = e.touches ? e.touches[0] : e;
            return {
                x: (src.clientX - r.left) * (canvas.width / r.width),
                y: (src.clientY - r.top) * (canvas.height / r.height),
            };
        };
        const start = (e) => {
            e.preventDefault();
            drawing = true;
            const p = pos(e);
            ctx.beginPath();
            ctx.moveTo(p.x, p.y);
        };
        const move = (e) => {
            if (!drawing) return;
            e.preventDefault();
            const p = pos(e);
            ctx.lineWidth = 2.2;
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';
            ctx.strokeStyle = '#0d2a5c';
            ctx.lineTo(p.x, p.y);
            ctx.stroke();
            hasInk = true;
            $('sig-hint').textContent = 'Signature captured';
        };
        const end = () => { drawing = false; };
        canvas.addEventListener('mousedown', start);
        canvas.addEventListener('mousemove', move);
        canvas.addEventListener('mouseup', end);
        canvas.addEventListener('mouseleave', end);
        canvas.addEventListener('touchstart', start, { passive: false });
        canvas.addEventListener('touchmove', move, { passive: false });
        canvas.addEventListener('touchend', end);
        $('sig-clear').addEventListener('click', () => {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            hasInk = false;
            $('sig-hint').textContent = 'Draw your signature above';
        });

        const field = $('dock-field');
        focusWithoutScroll(field);
        const send = () => {
            const name = field.value.trim();
            const idNumber = ($('dock-id-number').value || '').trim();
            if (!name) { dockError('Please type your full legal name.'); return; }
            if (!idNumber) { dockError('Please enter your ID number.'); return; }
            if (!hasInk) { dockError('Please draw your signature in the panel.'); return; }
            const signatureData = canvas.toDataURL('image/png');
            submitAnswer({
                name,
                id_number: idNumber,
                signature_data: signatureData,
                method: 'drawn_canvas',
            }, `Signed: ${name}`);
        };
        $('sign-submit').addEventListener('click', send);
        field.addEventListener('keydown', (e) => { if (e.key === 'Enter') send(); });
    }

    function cap(text) {
        const s = String(text);
        return s.charAt(0).toUpperCase() + s.slice(1);
    }

    // ---- media dock ------------------------------------------------------

    let voiceRecorder = null;
    let videoRecorder = null;
    let videoStream = null;

    function renderMediaDock(input) {
        dockHtml(`
            <div class="media-btns">
                <button class="media-btn" id="mb-voice"><span class="mb-icon">MIC</span><span>Voice note</span></button>
                <button class="media-btn" id="mb-video"><span class="mb-icon">CAM</span><span>Video message</span></button>
                <button class="media-btn" id="mb-doc"><span class="mb-icon">DOC</span><span>Upload files</span></button>
            </div>
            <div class="chips-wrap" style="justify-content:flex-end;">
                <button class="chip" data-value="skip">Skip for now</button>
                <button class="chip chip-go" data-value="done">Done - continue</button>
            </div>
            <div class="dock-hint">Voice, video and documents are hash-sealed into your application file (max 4MB each).</div>
        `);
        $('mb-voice').addEventListener('click', toggleVoiceRecording);
        $('mb-video').addEventListener('click', openVideoModal);
        $('mb-doc').addEventListener('click', () => $('doc-file-input').click());
        dock().querySelectorAll('.chip[data-value]').forEach((chip) => {
            chip.addEventListener('click', () => {
                stopVoiceRecorder();
                submitAnswer(chip.dataset.value,
                    chip.dataset.value === 'done' ? 'Done - continue' : 'Skip for now');
            });
        });
    }

    function stopVoiceRecorder() {
        if (voiceRecorder && voiceRecorder.state === 'recording') voiceRecorder.stop();
    }

    async function toggleVoiceRecording() {
        const btn = $('mb-voice');
        if (voiceRecorder && voiceRecorder.state === 'recording') {
            voiceRecorder.stop();
            return;
        }
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const chunks = [];
            voiceRecorder = new MediaRecorder(stream);
            voiceRecorder.ondataavailable = (e) => chunks.push(e.data);
            voiceRecorder.onstop = async () => {
                stream.getTracks().forEach((t) => t.stop());
                btn.classList.remove('recording');
                btn.querySelector('span:last-child').textContent = 'Voice note';
                const blob = new Blob(chunks, { type: voiceRecorder.mimeType || 'audio/webm' });
                await uploadMedia('voice', `voice-note-${Date.now()}.webm`, blob);
                voiceRecorder = null;
            };
            voiceRecorder.start();
            btn.classList.add('recording');
            btn.querySelector('span:last-child').textContent = 'Stop recording';
        } catch (err) {
            dockError('Microphone unavailable: ' + (err.message || 'permission denied'));
        }
    }

    async function openVideoModal() {
        const modal = $('video-modal');
        try {
            videoStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
        } catch (err) {
            dockError('Camera unavailable: ' + (err.message || 'permission denied'));
            return;
        }
        modal.hidden = false;
        $('video-preview').srcObject = videoStream;
        const recordBtn = $('video-record-btn');
        recordBtn.textContent = 'Start recording';
        recordBtn.onclick = () => {
            if (videoRecorder && videoRecorder.state === 'recording') {
                videoRecorder.stop();
                return;
            }
            const chunks = [];
            videoRecorder = new MediaRecorder(videoStream);
            videoRecorder.ondataavailable = (e) => chunks.push(e.data);
            videoRecorder.onstop = async () => {
                closeVideoModal();
                const blob = new Blob(chunks, { type: videoRecorder.mimeType || 'video/webm' });
                await uploadMedia('video', `video-message-${Date.now()}.webm`, blob);
                videoRecorder = null;
            };
            videoRecorder.start();
            recordBtn.textContent = 'Stop & send';
            // auto-stop after 30s to respect size budget
            setTimeout(() => {
                if (videoRecorder && videoRecorder.state === 'recording') videoRecorder.stop();
            }, 30000);
        };
        $('video-cancel-btn').onclick = closeVideoModal;
    }

    function closeVideoModal() {
        $('video-modal').hidden = true;
        if (videoStream) {
            videoStream.getTracks().forEach((t) => t.stop());
            videoStream = null;
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        $('doc-file-input').addEventListener('change', async (e) => {
            for (const file of Array.from(e.target.files || [])) {
                const kind = file.type.startsWith('image/') ? 'image' : 'document';
                await uploadMedia(kind, file.name, file);
            }
            e.target.value = '';
        });
    });

    async function uploadMedia(kind, name, blob) {
        if (blob.size > 4 * 1024 * 1024) {
            dockError(`"${name}" is over the 4MB limit.`);
            return;
        }
        const b64 = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result).split(',')[1]);
            reader.onerror = reject;
            reader.readAsDataURL(blob);
        });
        addBubble('user',
            `<span class="media-chip"><span class="kind-tag">${escapeHtml(kind.toUpperCase())}</span>${escapeHtml(name)}</span>`);
        const { status, data } = await api('POST', `/${state.appId}/media`, {
            kind, name, mime_type: blob.type || 'application/octet-stream', data_b64: b64,
            resume_code: state.resumeCode,
        });
        if (status !== 200) {
            dockError(data.error || 'Upload failed');
            return;
        }
        state.mediaCount += 1;
        await playMessages(data.messages);
    }

    // ---- OTP ------------------------------------------------------------

    async function requestOtp() {
        const { status, data } = await api('POST', `/${state.appId}/otp/request`, { resume_code: state.resumeCode });
        if (status !== 200) {
            addBubble('bot', richText(data.error || 'I could not send the code - give it a moment and try again.'));
            renderOtpDock(true);
            return;
        }
        state.otp = { verification_id: data.verification_id };
        if (data.demo_otp_code) {
            addBubble('bot',
                `<strong>Demo environment:</strong> your verification code is <code>${escapeHtml(data.demo_otp_code)}</code>.`,
                'resume-note');
        }
        renderOtpDock();
    }

    function renderOtpDock(retryOnly) {
        const boxes = Array.from({ length: 6 }, (_, i) =>
            `<input class="otp-box" maxlength="1" inputmode="numeric" data-i="${i}">`).join('');
        dockHtml(`
            ${retryOnly ? '' : `<div class="dock-label" style="text-align:center;">Enter the 6-digit code</div><div class="otp-row">${boxes}</div>`}
            <div class="otp-actions">
                ${retryOnly ? '' : '<button class="chip chip-go" id="otp-submit">Verify</button>'}
                <button class="link-btn" id="otp-resend" style="margin:0;">${retryOnly ? 'Send code again' : 'Resend code'}</button>
            </div>
        `);
        const inputs = Array.from(dock().querySelectorAll('.otp-box'));
        inputs.forEach((box, i) => {
            box.addEventListener('input', () => {
                box.value = box.value.replace(/\D/g, '');
                if (box.value && i < 5) focusWithoutScroll(inputs[i + 1]);
                if (inputs.every((b) => b.value)) verifyOtp(inputs.map((b) => b.value).join(''));
            });
            box.addEventListener('keydown', (e) => {
                if (e.key === 'Backspace' && !box.value && i > 0) focusWithoutScroll(inputs[i - 1]);
            });
            box.addEventListener('paste', (e) => {
                const text = (e.clipboardData.getData('text') || '').replace(/\D/g, '').slice(0, 6);
                if (text.length === 6) {
                    e.preventDefault();
                    inputs.forEach((b, j) => { b.value = text[j] || ''; });
                    verifyOtp(text);
                }
            });
        });
        if (inputs.length) focusWithoutScroll(inputs[0]);
        const submitBtn = $('otp-submit');
        if (submitBtn) submitBtn.addEventListener('click', () =>
            verifyOtp(inputs.map((b) => b.value).join('')));
        $('otp-resend').addEventListener('click', requestOtp);
        afterLayoutScroll();
    }

    async function verifyOtp(code) {
        if (!code || code.length !== 6) { dockError('Please enter all 6 digits.'); return; }
        dockError('');
        stickToBottom = true;
        addBubble('user', escapeHtml('\u2022'.repeat(6)));
        const { status, data } = await api('POST', `/${state.appId}/otp/verify`, {
            verification_id: state.otp && state.otp.verification_id,
            otp_code: code,
            resume_code: state.resumeCode,
        });
        if (status !== 200) {
            const t = addTyping(); await sleep(500); t.remove();
            addBubble('bot', richText(data.error || 'That code is not right - try again.'));
            renderOtpDock();
            afterLayoutScroll();
            return;
        }
        state.otp = null;
        setProgress(data.progress);
        // On a secure fresh-page resume the server returns the prior
        // conversation only after the fresh OTP passes - replay it so the chat
        // is restored. Skip it on the same-tab continue path where the live
        // conversation is already rendered, to avoid duplicating history.
        stickToBottom = true;
        if (state.otpRestoreTranscript && data.transcript && data.transcript.length) {
            await playMessages(data.transcript, { instant: true });
        }
        state.otpRestoreTranscript = false;
        await playMessages(data.messages);
        renderStep(data.step);
        // Keep following through the rest of the application after OTP.
        stickToBottom = true;
        afterLayoutScroll();
    }

    // ---- conversation ----------------------------------------------------

    async function submitAnswer(value, displayText) {
        if (state.busy) return;
        state.busy = true;
        stickToBottom = true;
        clearDock();
        addBubble('user', richText(displayText !== undefined ? displayText : String(value)));
        try {
            const { status, data } = await api('POST', `/${state.appId}/message`, { value, resume_code: state.resumeCode });
            setProgress(data.progress);
            await playMessages(data.messages);
            if (status >= 400 && !data.messages) {
                addBubble('bot', richText(data.error || 'Something went wrong - try again.'));
            }
            if (data.otp_required) {
                await requestOtp();
                stickToBottom = true;
                afterLayoutScroll();
            } else if (data.ready_to_finalize) {
                await finalize();
            } else if (status >= 400) {
                renderStep(data.step || state.step);
                afterLayoutScroll();
            } else {
                if (state.step && state.step.id === 'email' && status < 400) {
                    state.email = String(value).toLowerCase();
                    saveLocal();
                }
                renderStep(data.step);
                afterLayoutScroll();
            }
        } catch (err) {
            addBubble('bot', 'Connection hiccup - your progress is saved. Try that again.');
            renderStep(state.step);
            afterLayoutScroll();
        } finally {
            state.busy = false;
        }
    }

    async function finalize() {
        const t = addTyping();
        stickToBottom = true;
        const { status, data } = await api('POST', `/${state.appId}/finalize`, { resume_code: state.resumeCode });
        t.remove();
        if (status !== 201) {
            addBubble('bot', richText(data.error || 'Submission failed - let me try that again in a moment.'));
            dockHtml('<div class="dock-row" style="justify-content:center;"><button class="chip chip-go" id="retry-finalize">Retry submission</button></div>');
            $('retry-finalize').addEventListener('click', finalize);
            afterLayoutScroll();
            return;
        }
        state.submitted = true;
        clearLocal();
        await playMessages(data.messages);
        const login = data.provisioned_login || {};
        const claim = data.claim || {};
        // With a claim code the applicant finishes account setup by choosing
        // their own password, so we never print a temporary one on screen.
        const trackUrl = claim.track_url || '/track-application.html';
        addCard(`
            <div class="success-card">
                <div class="big-check">&#10003;</div>
                <h4 style="justify-content:center;">Application Submitted</h4>
                <div class="success-ids">
                    <div><span>Policy</span><code>${escapeHtml(data.policy.id || '')}</code></div>
                    <div><span>Underwriting</span><code>${escapeHtml(data.underwriting.id || '')}</code></div>
                    <div><span>Ledger checksum</span><code>${escapeHtml(String(data.payload_checksum || '').slice(0, 16))}&hellip;</code></div>
                    ${claim.claim_code ? `<div><span>Claim code</span><code>${escapeHtml(claim.claim_code)}</code></div>` : ''}
                    ${!claim.claim_code && login.username ? `<div><span>Portal username</span><code>${escapeHtml(login.username)}</code></div>` : ''}
                    ${!claim.claim_code && login.password ? `<div><span>Temporary password</span><code>${escapeHtml(login.password)}</code></div>` : ''}
                    ${login.existing_account ? '<div><span>Account</span><code>Use your existing login</code></div>' : ''}
                </div>
                ${claim.claim_code ? `<p class="success-note">Keep this claim code. Open <strong>Track my application</strong> and it will carry everything across from your application &mdash; all you choose is a password.</p>` : ''}
                <div class="success-actions">
                    <a class="btn-gold" href="${escapeHtml(trackUrl)}">Track my application</a>
                    <a class="btn-ghost" href="/">Back to home</a>
                </div>
            </div>
        `);
        clearDock();
        $('pause-btn').hidden = true;
        stickToBottom = true;
        afterLayoutScroll();
        startUwDecisionWatch();
    }

    // ---- UW decision auto-answer watch (post-submit) ----------------------

    let uwWatchTimer = null;
    let uwLastSeq = 0;

    function startUwDecisionWatch() {
        if (uwWatchTimer) clearInterval(uwWatchTimer);
        uwLastSeq = 0;
        const tick = async () => {
            if (!state.appId || !state.resumeCode || !state.submitted) return;
            try {
                const { status, data } = await api(
                    'GET',
                    `/${state.appId}?resume_code=${encodeURIComponent(state.resumeCode)}`
                );
                if (status !== 200) return;
                const msgs = (data.transcript || []).filter((m) => m.kind === 'uw_decision');
                for (const msg of msgs) {
                    if (msg.seq <= uwLastSeq) continue;
                    uwLastSeq = Math.max(uwLastSeq, msg.seq);
                    stickToBottom = true;
                    await playMessages([msg]);
                    afterLayoutScroll();
                }
                if (data.uw_decision && data.uw_decision.decision) {
                    // Decision delivered — keep watching briefly then stop.
                    clearInterval(uwWatchTimer);
                    uwWatchTimer = null;
                }
            } catch (e) { /* ignore transient */ }
        };
        tick();
        uwWatchTimer = setInterval(tick, 6000);
    }

    // ---- start / pause / resume -------------------------------------------

    function inviteCodeFromUrl() {
        const params = new URLSearchParams(window.location.search);
        return params.get('ref') || params.get('invite') || params.get('code') || '';
    }

    async function startApplication() {
        $('start-btn').disabled = true;
        const body = { channel: 'web_chat', language: currentLanguage() };
        const invite = inviteCodeFromUrl();
        if (invite) body.invite_code = invite;
        const { status, data } = await api('POST', '/start', body);
        if (status !== 201) {
            $('start-btn').disabled = false;
            alert(data.error || 'Could not start the application - please try again.');
            return;
        }
        state.appId = data.application_id;
        state.resumeCode = data.resume_code;
        saveLocal();
        switchToChat();
        setProgress(data.progress);
        await playMessages(data.messages);
        renderStep(data.step);
        afterLayoutScroll();
    }

    async function resumeApplication(code, email) {
        const { status, data } = await api('POST', '/resume', {
            resume_code: code, email,
        });
        if (status !== 200) {
            const err = $('resume-error');
            err.hidden = false;
            err.textContent = data.error || 'We could not match that code and email.';
            return;
        }
        state.appId = data.application_id;
        state.resumeCode = code.toUpperCase();
        state.email = email.toLowerCase();
        saveLocal();
        switchToChat();

        if (data.status === 'submitted') {
            addBubble('bot', richText(
                `Welcome back! This application was already submitted - policy **${(data.submission || {}).policy_id || ''}** is in processing. You can track it from the portal.`));
            clearDock();
            return;
        }
        if (data.otp_required) {
            // Only rebuild history from the transcript when it is not already
            // on screen (fresh-page resume). The same-tab continue path still
            // shows the live conversation, so replaying would duplicate it.
            state.otpRestoreTranscript = chatScroll().childElementCount === 0;
            addBubble('bot', richText(
                `Welcome back! Since your session is verified, I sent a fresh security code to **${data.masked_email || 'your email'}** - enter it and we'll continue.`));
            state.otp = { verification_id: (data.otp || {}).verification_id };
            if ((data.otp || {}).demo_otp_code) {
                addBubble('bot',
                    `<strong>Demo environment:</strong> your verification code is <code>${escapeHtml(data.otp.demo_otp_code)}</code>.`,
                    'resume-note');
            }
            renderOtpDock();
            return;
        }
        // replay transcript for context
        await playMessages(data.transcript || [], { instant: true });
        await playMessages(data.messages || []);
        setProgress(data.progress);
        renderStep(data.step);
        afterLayoutScroll();
    }

    async function pauseApplication() {
        if (!state.appId || state.submitted) return;
        const { status, data } = await api('POST', `/${state.appId}/pause`, { resume_code: state.resumeCode });
        if (status === 200) {
            await playMessages(data.messages);
            clearDock();
            dockHtml(`<div class="dock-row" style="justify-content:center;">
                <button class="chip chip-go" id="resume-now">Actually, let's continue</button>
            </div>`);
            $('resume-now').addEventListener('click', async () => {
                await resumeApplication(state.resumeCode, state.email || '');
            });
            afterLayoutScroll();
        }
    }

    function switchToChat() {
        $('welcome-screen').hidden = true;
        $('chat-screen').hidden = false;
        showHeaderTools();
        watchDockResize();
        afterLayoutScroll();
    }

    // ---- boot -------------------------------------------------------------

    document.addEventListener('DOMContentLoaded', async () => {
        $('start-btn').addEventListener('click', startApplication);
        $('show-resume-btn').addEventListener('click', () => {
            const form = $('resume-form');
            form.hidden = !form.hidden;
        });
        $('resume-form').addEventListener('submit', (e) => {
            e.preventDefault();
            resumeApplication($('resume-code-input').value.trim(),
                $('resume-email-input').value.trim());
        });
        $('pause-btn').addEventListener('click', pauseApplication);
        $('resume-pill').addEventListener('click', () => {
            navigator.clipboard?.writeText(state.resumeCode || '');
            $('resume-pill-code').textContent = 'Copied!';
            setTimeout(() => { $('resume-pill-code').textContent = state.resumeCode; }, 1200);
        });

        // referral banner
        const invite = inviteCodeFromUrl();
        if (invite) {
            const banner = $('welcome-invite');
            banner.hidden = false;
            banner.textContent = `Invitation ${invite} detected - your referrer will be credited.`;
        }

        // offer to continue a locally saved session
        const saved = loadLocal();
        if (saved && saved.resumeCode && saved.email) {
            $('show-resume-btn').click();
            $('resume-code-input').value = saved.resumeCode;
            $('resume-email-input').value = saved.email;
        }
    });
})();
