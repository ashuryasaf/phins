/* PHINS Claims Chat ("Phin" as claims agent).
 * Server owns the steps (/api/claims-chat). This client renders them with the
 * same dock, OTP, media, and signature methods as apply-chat.js.
 */
(function () {
    'use strict';

    const API = '/api/claims-chat';
    const STORE_KEY = 'phins.claimsChat.v1';
    const state = {
        appId: null, resumeCode: null, email: null, step: null,
        otp: null, otpChannel: null, busy: false, submitted: false,
    };

    const $ = (id) => document.getElementById(id);
    const chatScroll = () => $('chat-scroll');
    const dock = () => $('chat-dock');

    function token() {
        try { return localStorage.getItem('phins_token') || ''; }
        catch (e) { return ''; }
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = String(text == null ? '' : text);
        return div.innerHTML;
    }

    function richText(text) {
        return escapeHtml(text).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    }

    function fmtMoney(v) {
        return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(v || 0);
    }

    async function api(method, path, body) {
        const headers = { 'Content-Type': 'application/json' };
        if (token()) headers.Authorization = 'Bearer ' + token();
        const resp = await fetch(API + path, {
            method,
            headers,
            body: body === undefined ? undefined : JSON.stringify(body),
        });
        let data = {};
        try { data = await resp.json(); } catch (e) { /* empty */ }
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

    function scrollDown() {
        const el = chatScroll();
        if (el) el.scrollTop = el.scrollHeight;
    }

    function addBubble(role, html, cls) {
        const row = document.createElement('div');
        row.className = 'msg-row ' + (role === 'user' ? 'user' : 'bot') + (cls ? ' ' + cls : '');
        row.innerHTML = '<div class="msg-avatar">' + (role === 'user' ? 'You' : 'Ph') + '</div>'
            + '<div class="msg-bubble">' + html + '</div>';
        chatScroll().appendChild(row);
        scrollDown();
        return row;
    }

    function addCard(html) {
        const card = document.createElement('div');
        card.className = 'chat-card';
        card.innerHTML = html;
        chatScroll().appendChild(card);
        scrollDown();
        return card;
    }

    function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

    async function playMessages(messages, opts) {
        const instant = opts && opts.instant;
        for (const msg of messages || []) {
            if (!instant) {
                const t = addBubble('bot', '<span class="typing">···</span>');
                await sleep(280);
                t.remove();
            }
            addBubble(msg.role === 'user' ? 'user' : 'bot', richText(msg.text || ''), msg.kind || '');
        }
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

    function dockHtml(inner) {
        dock().innerHTML = '<div class="dock-inner">' + inner + '<div class="dock-error" id="dock-error" hidden></div></div>';
    }

    function dockError(text) {
        const el = $('dock-error');
        if (el) { el.hidden = !text; el.textContent = text || ''; }
    }

    function withCode(body) {
        const payload = body || {};
        if (state.resumeCode) payload.resume_code = state.resumeCode;
        return payload;
    }

    function renderStep(step) {
        state.step = step;
        dockError('');
        if (!step) { dock().innerHTML = ''; return; }
        const input = step.input || { type: 'text' };
        switch (input.type) {
            case 'profile': renderProfile(input); break;
            case 'choice': renderChoices(input); break;
            case 'media': renderMediaDock(); break;
            case 'consent': renderConsent(); break;
            case 'signature': renderSignature(input); break;
            default: renderTextInput(input);
        }
        scrollDown();
    }

    function renderTextInput(input) {
        const typeMap = { text: 'text', email: 'email', phone: 'tel', date: 'date', number: 'number' };
        const htmlType = typeMap[input.type] || 'text';
        dockHtml(
            '<div class="dock-row"><input class="dock-input" id="dock-field" type="' + htmlType + '" placeholder="'
            + escapeHtml(input.placeholder || '') + '"'
            + (input.min !== undefined ? ' min="' + input.min + '"' : '')
            + (input.max !== undefined ? ' max="' + input.max + '"' : '')
            + ' autocomplete="off"><button class="send-btn" id="dock-send">&#10148;</button></div>'
            + (input.suffix ? '<div class="dock-hint">' + escapeHtml(input.suffix) + '</div>' : '')
        );
        const field = $('dock-field');
        const send = () => {
            const raw = field.value.trim();
            if (!raw) return;
            submitAnswer(input.type === 'number' ? Number(raw) : raw, raw);
        };
        $('dock-send').addEventListener('click', send);
        field.addEventListener('keydown', (e) => { if (e.key === 'Enter') send(); });
        field.focus();
    }

    function renderProfile(input) {
        const pre = input.prefill || {};
        dockHtml(
            '<div class="dock-label">' + (input.from_account
                ? 'From your PHINS account — edit anything that changed'
                : 'Confirm the account on file — edit anything that changed') + '</div>'
            + '<div class="profile-grid">'
            + '<input class="dock-input" id="pf-name" placeholder="Full name" value="' + escapeHtml(pre.name || '') + '">'
            + '<input class="dock-input" id="pf-email" type="email" placeholder="Email" value="' + escapeHtml(pre.email || '') + '">'
            + '<input class="dock-input" id="pf-phone" type="tel" placeholder="Mobile" value="' + escapeHtml(pre.phone || '') + '">'
            + '</div>'
            + '<div class="dock-row" style="justify-content:flex-end;margin-top:10px;">'
            + '<button class="chip chip-go" id="pf-confirm">Confirm details</button></div>'
        );
        $('pf-confirm').addEventListener('click', () => {
            const name = $('pf-name').value.trim();
            const email = $('pf-email').value.trim();
            const phone = $('pf-phone').value.trim();
            if (!name || !email || !phone) { dockError('Name, email, and mobile are all required.'); return; }
            state.email = email.toLowerCase();
            saveLocal();
            submitAnswer({ name, email, phone, confirm: true }, 'Confirmed: ' + name);
        });
    }

    function renderChoices(input) {
        const labels = input.labels || {};
        const chips = (input.options || []).map((o) =>
            '<button class="chip" data-value="' + escapeHtml(o) + '">' + escapeHtml(labels[o] || o) + '</button>'
        ).join('');
        dockHtml('<div class="chips-wrap">' + (chips || '<div class="dock-hint">No active policy is on file.</div>') + '</div>');
        dock().querySelectorAll('.chip').forEach((chip) => {
            chip.addEventListener('click', () => {
                const v = chip.dataset.value;
                submitAnswer(v, (input.labels || {})[v] || v);
            });
        });
    }

    function renderConsent() {
        dockHtml(
            '<div class="consent-list">'
            + '<label class="consent-item"><input type="checkbox" id="c-terms"><span>I agree to the <a href="/terms-of-use.html" target="_blank">Terms of Use</a> and <a href="/privacy-policy.html" target="_blank">Privacy Policy</a>.</span></label>'
            + '<label class="consent-item"><input type="checkbox" id="c-accuracy"><span>This account of the loss is accurate and complete.</span></label>'
            + '<label class="consent-item"><input type="checkbox" id="c-review"><span>PHINS may review the evidence and contact me about this claim.</span></label>'
            + '</div><div class="dock-row" style="justify-content:flex-end;">'
            + '<button class="chip chip-go" id="consent-submit" disabled>I agree — continue to signature</button></div>'
        );
        const boxes = ['c-terms', 'c-accuracy', 'c-review'].map($);
        const btn = $('consent-submit');
        const refresh = () => { btn.disabled = !boxes.every((b) => b.checked); };
        boxes.forEach((b) => b.addEventListener('change', refresh));
        btn.addEventListener('click', () => submitAnswer('agree', 'I agree — all three confirmations'));
    }

    function renderSignature(input) {
        dockHtml(
            '<div class="dock-label">Electronic signature (mandatory)</div>'
            + '<div class="sig-fields">'
            + '<input class="dock-input" id="dock-field" type="text" placeholder="Full legal name" autocomplete="name">'
            + '<input class="dock-input" id="dock-nationality" type="text" placeholder="Nationality (e.g. Israel)">'
            + '<input class="dock-input" id="dock-id-number" type="text" placeholder="'
            + escapeHtml(input.id_placeholder || 'National ID') + '" autocomplete="off">'
            + '</div>'
            + '<div class="sig-pad-wrap"><canvas class="sig-pad" id="sig-pad" width="520" height="140" aria-label="Draw your signature"></canvas>'
            + '<div class="sig-pad-actions"><button type="button" class="link-btn" id="sig-clear">Clear signature</button>'
            + '<span class="dock-hint" id="sig-hint">Draw your signature above</span></div></div>'
            + '<div class="dock-row" style="justify-content:flex-end;margin-top:10px;">'
            + '<button class="chip chip-go" id="sign-submit">Sign &amp; file</button></div>'
            + '<div class="dock-hint">Name must match the name you confirmed. The ID is stored in the identity vault, not on the claim.</div>'
        );
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
        const start = (e) => { e.preventDefault(); drawing = true; const p = pos(e); ctx.beginPath(); ctx.moveTo(p.x, p.y); };
        const move = (e) => {
            if (!drawing) return;
            e.preventDefault();
            const p = pos(e);
            ctx.lineWidth = 2.2; ctx.lineCap = 'round'; ctx.strokeStyle = '#0d2a5c';
            ctx.lineTo(p.x, p.y); ctx.stroke(); hasInk = true;
            $('sig-hint').textContent = 'Signature captured';
        };
        canvas.addEventListener('mousedown', start);
        canvas.addEventListener('mousemove', move);
        window.addEventListener('mouseup', () => { drawing = false; });
        canvas.addEventListener('touchstart', start, { passive: false });
        canvas.addEventListener('touchmove', move, { passive: false });
        $('sig-clear').addEventListener('click', () => {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            hasInk = false;
            $('sig-hint').textContent = 'Draw your signature above';
        });
        if (input.name_default) $('dock-field').value = input.name_default;
        const nationality = $('dock-nationality');
        if (window.PhinsApplySuggest) window.PhinsApplySuggest.attach(nationality, { kind: 'country', limit: 8 });
        $('sign-submit').addEventListener('click', () => {
            const name = $('dock-field').value.trim();
            const nat = nationality.value.trim();
            const idNumber = $('dock-id-number').value.trim();
            if (!name || !nat || !idNumber) { dockError('Name, nationality, and ID are required.'); return; }
            if (!hasInk) { dockError('Please draw your signature.'); return; }
            submitAnswer({
                name, nationality: nat, id_number: idNumber,
                signature_data: canvas.toDataURL('image/png'), method: 'drawn_canvas',
            }, 'Signed: ' + name);
        });
    }

    let voiceRecorder = null;

    function renderMediaDock() {
        dockHtml(
            '<div class="media-btns">'
            + '<button class="media-btn" id="mb-voice" type="button"><span class="mb-icon">MIC</span><span>Voice note</span></button>'
            + '<button class="media-btn" id="mb-video" type="button"><span class="mb-icon">CAM</span><span>Video</span></button>'
            + '<button class="media-btn" id="mb-doc" type="button"><span class="mb-icon">DOC</span><span>Documents</span></button>'
            + '</div>'
            + '<div class="chips-wrap" style="justify-content:flex-end;">'
            + '<button class="chip" id="mb-audio-file" type="button">Upload audio</button>'
            + '<button class="chip" id="mb-video-file" type="button">Upload video</button>'
            + '<button class="chip chip-go" id="mb-done" type="button">Done — continue</button></div>'
            + '<div class="dock-hint">At least one file. Each upload is hash-sealed (max 4MB).</div>'
        );
        $('mb-voice').addEventListener('click', toggleVoice);
        $('mb-video').addEventListener('click', openVideoModal);
        $('mb-doc').addEventListener('click', () => $('doc-file-input').click());
        $('mb-audio-file').addEventListener('click', () => $('audio-file-input').click());
        $('mb-video-file').addEventListener('click', () => $('video-file-input').click());
        $('mb-done').addEventListener('click', () => submitAnswer('done', 'Evidence attached'));
    }

    async function toggleVoice() {
        const btn = $('mb-voice');
        if (!btn) return;
        if (voiceRecorder && voiceRecorder.state === 'recording') { voiceRecorder.stop(); return; }
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const chunks = [];
            voiceRecorder = new MediaRecorder(stream);
            voiceRecorder.ondataavailable = (e) => chunks.push(e.data);
            voiceRecorder.onstop = async () => {
                stream.getTracks().forEach((t) => t.stop());
                const blob = new Blob(chunks, { type: voiceRecorder.mimeType || 'audio/webm' });
                await uploadMedia('voice', 'voice-note-' + Date.now() + '.webm', blob);
            };
            voiceRecorder.start();
            btn.querySelector('span:last-child').textContent = 'Stop';
        } catch (e) {
            dockError('Microphone unavailable — upload an audio file instead.');
        }
    }

    async function openVideoModal() {
        const modal = $('video-modal');
        modal.hidden = false;
        let stream = null;
        let recorder = null;
        const chunks = [];
        try {
            stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
            $('video-preview').srcObject = stream;
        } catch (e) {
            modal.hidden = true;
            dockError('Camera unavailable — upload a video file instead.');
            return;
        }
        $('video-record-btn').onclick = () => {
            if (recorder && recorder.state === 'recording') { recorder.stop(); return; }
            recorder = new MediaRecorder(stream);
            recorder.ondataavailable = (e) => chunks.push(e.data);
            recorder.onstop = async () => {
                stream.getTracks().forEach((t) => t.stop());
                modal.hidden = true;
                const blob = new Blob(chunks, { type: recorder.mimeType || 'video/webm' });
                await uploadMedia('video', 'loss-video-' + Date.now() + '.webm', blob);
            };
            recorder.start();
            $('video-record-btn').textContent = 'Stop & attach';
            setTimeout(() => { if (recorder && recorder.state === 'recording') recorder.stop(); }, 30000);
        };
        $('video-cancel-btn').onclick = () => {
            stream.getTracks().forEach((t) => t.stop());
            modal.hidden = true;
        };
    }

    function readFile(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result || '').split(',')[1] || '');
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    async function uploadMedia(kind, name, blobOrFile) {
        const file = blobOrFile;
        const data = await readFile(file);
        const mime = file.type || 'application/octet-stream';
        addBubble('user', escapeHtml(kind.toUpperCase() + ' · ' + name));
        const { status, data: body } = await api('POST', '/' + state.appId + '/media', withCode({
            kind, name, mime_type: mime, data_b64: data,
        }));
        if (status !== 200) {
            addBubble('bot', richText((body && body.error) || 'Upload failed.'));
            return;
        }
        await playMessages(body.messages);
        const sha = body.media && body.media.sha256;
        if (sha) addBubble('bot', 'Sealed fingerprint <code>' + escapeHtml(sha.slice(0, 16)) + '</code>');
    }

    function bindFileInput(id, kind) {
        $(id).addEventListener('change', async (e) => {
            const files = Array.from(e.target.files || []);
            e.target.value = '';
            for (const file of files) {
                const useKind = kind || (file.type.startsWith('image/') ? 'image' : 'document');
                await uploadMedia(useKind, file.name, file);
            }
        });
    }

    function renderOtp(data) {
        state.otp = {
            verification_id: data.verification_id,
            maskedEmail: data.masked_email,
            maskedPhone: data.masked_phone,
        };
        state.otpChannel = data.delivery_channel || state.otpChannel || 'email';
        const boxes = [0, 1, 2, 3, 4, 5].map(() => '<input class="otp-box" inputmode="numeric" maxlength="1">').join('');
        dockHtml(
            '<div class="dock-label">Verification code</div>'
            + '<div class="chips-wrap otp-channel-wrap">'
            + '<button class="chip" data-channel="email" type="button">Email</button>'
            + '<button class="chip" data-channel="sms" type="button">SMS</button>'
            + '<button class="chip" data-channel="whatsapp" type="button">WhatsApp</button>'
            + '</div><div class="otp-boxes">' + boxes + '</div>'
            + '<div class="dock-row" style="justify-content:space-between;">'
            + '<button class="link-btn" id="otp-resend" type="button">Resend</button>'
            + '<button class="chip chip-go" id="otp-submit" type="button">Verify</button></div>'
        );
        const inputs = Array.from(dock().querySelectorAll('.otp-box'));
        inputs.forEach((box, i) => {
            box.addEventListener('input', () => {
                if (box.value && inputs[i + 1]) inputs[i + 1].focus();
                if (inputs.every((b) => b.value)) verifyOtp(inputs.map((b) => b.value).join(''));
            });
        });
        dock().querySelectorAll('[data-channel]').forEach((chip) => {
            chip.addEventListener('click', () => requestOtp(chip.dataset.channel));
        });
        $('otp-submit').addEventListener('click', () => verifyOtp(inputs.map((b) => b.value).join('')));
        $('otp-resend').addEventListener('click', () => requestOtp(state.otpChannel));
        if (inputs[0]) inputs[0].focus();
    }

    async function requestOtp(channel) {
        state.otpChannel = channel || 'email';
        const { status, data } = await api('POST', '/' + state.appId + '/otp/request', withCode({
            delivery_channel: state.otpChannel,
        }));
        if (status !== 200) {
            addBubble('bot', richText(data.error || 'Could not send a code.'));
            return;
        }
        if (data.demo_otp_code) {
            addBubble('bot', 'Demo environment: your verification code is <code>' + escapeHtml(data.demo_otp_code) + '</code>.');
        }
        renderOtp(data);
    }

    async function verifyOtp(code) {
        if (!code || code.length < 6) { dockError('Enter the 6-digit code.'); return; }
        addBubble('user', '••••••');
        const { status, data } = await api('POST', '/' + state.appId + '/otp/verify', withCode({
            verification_id: state.otp && state.otp.verification_id,
            otp_code: code,
        }));
        if (status !== 200) {
            addBubble('bot', richText(data.error || 'That code is not right.'));
            renderOtp(state.otp || {});
            return;
        }
        setProgress(data.progress);
        await playMessages(data.messages);
        renderStep(data.step);
    }

    async function submitAnswer(value, displayText) {
        if (state.busy) return;
        state.busy = true;
        dock().innerHTML = '';
        addBubble('user', richText(displayText !== undefined ? displayText : String(value)));
        try {
            const { status, data } = await api('POST', '/' + state.appId + '/message', withCode({ value }));
            setProgress(data.progress);
            await playMessages(data.messages);
            if (data.otp_required) {
                await requestOtp('email');
            } else if (data.ready_to_finalize) {
                await finalize();
            } else {
                if (status >= 400 && !data.messages) addBubble('bot', richText(data.error || 'Try that again.'));
                renderStep(data.step || state.step);
            }
        } catch (err) {
            addBubble('bot', 'Connection hiccup — your progress is saved. Try that again.');
            renderStep(state.step);
        } finally {
            state.busy = false;
            scrollDown();
        }
    }

    function showDocuments(data) {
        const claim = data.claim || {};
        const integrity = data.integrity || {};
        const processing = data.processing || {};
        const pipeline = processing.pipeline || {};
        addCard(
            '<h4>Claim filed</h4>'
            + '<div class="success-ids">'
            + '<div><span>Claim</span><code>' + escapeHtml(claim.id || '') + '</code></div>'
            + '<div><span>Status</span><code>' + escapeHtml(claim.status || 'pending') + '</code></div>'
            + '<div><span>Policy</span><code>' + escapeHtml(claim.policy_id || '') + '</code></div>'
            + '<div><span>Amount</span><code>' + escapeHtml(fmtMoney(claim.claimed_amount)) + '</code></div>'
            + '<div><span>Checksum</span><code>' + escapeHtml(String(integrity.payload_sha256 || '').slice(0, 16)) + '…</code></div>'
            + '<div><span>Notification</span><code>' + escapeHtml(processing.notification_id || processing.notification_status || '') + '</code></div>'
            + '<div><span>Claims bot</span><code>' + escapeHtml(pipeline.recommendation || pipeline.status || '') + '</code></div>'
            + '</div>'
            + '<p class="integrity-line">Identity ' + escapeHtml(integrity.identity_outcome || '')
            + ' · fraud probability ' + escapeHtml(pipeline.fraud_probability == null ? '' : String(pipeline.fraud_probability))
            + ' · advisory only, the filed amount is unchanged.</p>'
            + '<h4 style="margin-top:16px;">Notice of loss</h4>'
            + '<iframe class="claim-doc-frame" id="fnol-frame" sandbox="" title="Claim notice of loss"></iframe>'
            + '<h4 style="margin-top:16px;">Processing record</h4>'
            + '<iframe class="claim-doc-frame" id="proc-frame" sandbox="" title="Claim processing record"></iframe>'
            + '<div class="claim-doc-actions">'
            + '<button class="btn-gold" id="download-fnol" type="button">Download notice</button>'
            + '<button class="btn-ghost" id="download-proc" type="button">Download processing record</button>'
            + '<a class="btn-ghost" href="/claims-adjuster-dashboard.html">Back to claims</a>'
            + '</div>'
        );
        const fnol = $('fnol-frame');
        const proc = $('proc-frame');
        if (fnol) fnol.srcdoc = data.document_html || '';
        if (proc) proc.srcdoc = data.processing_html || '';
        const saveHtml = (filename, html) => {
            const blob = new Blob([html || ''], { type: 'text/html' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            a.click();
            URL.revokeObjectURL(url);
        };
        const btn = $('download-fnol');
        if (btn) btn.addEventListener('click', () => {
            saveHtml((claim.id || 'claim') + '-notice-of-loss.html', data.document_html);
        });
        const procBtn = $('download-proc');
        if (procBtn) procBtn.addEventListener('click', () => {
            saveHtml((claim.id || 'claim') + '-processing-record.html', data.processing_html);
        });
    }

    async function finalize() {
        const hold = addBubble('bot', 'Sealing the notice and filing the claim…');
        const { status, data } = await api('POST', '/' + state.appId + '/finalize', withCode({}));
        hold.remove();
        if (status !== 201 && status !== 200) {
            addBubble('bot', richText(data.error || 'Filing failed.'));
            dockHtml('<div class="dock-row" style="justify-content:center;"><button class="chip chip-go" id="retry-finalize">Retry filing</button></div>');
            $('retry-finalize').addEventListener('click', finalize);
            return;
        }
        state.submitted = true;
        clearLocal();
        await playMessages(data.messages);
        showDocuments(data);
        $('pause-btn').hidden = true;
        dock().innerHTML = '';
        scrollDown();
    }

    function switchToChat() {
        $('welcome-screen').hidden = true;
        $('chat-screen').hidden = false;
        showHeaderTools();
        scrollDown();
    }

    async function startClaim() {
        if (!token()) {
            window.location.href = '/login.html';
            return;
        }
        $('start-btn').disabled = true;
        const { status, data } = await api('POST', '/start', { channel: 'web_chat' });
        if (status !== 201) {
            $('start-btn').disabled = false;
            alert(data.error || 'Could not start the claim.');
            return;
        }
        state.appId = data.application_id;
        state.resumeCode = data.resume_code;
        saveLocal();
        switchToChat();
        setProgress(data.progress);
        await playMessages(data.messages);
        renderStep(data.step);
    }

    async function resumeClaim(code, email) {
        const { status, data } = await api('POST', '/resume', { resume_code: code, email });
        if (status !== 200) {
            $('resume-error').hidden = false;
            $('resume-error').textContent = data.error || 'We could not match that code and email.';
            return;
        }
        state.appId = data.application_id;
        state.resumeCode = code.toUpperCase();
        state.email = email.toLowerCase();
        saveLocal();
        switchToChat();
        if (data.status === 'submitted') {
            addBubble('bot', 'This claim was already filed.');
            showDocuments({
                claim: { id: (data.submission || {}).claim_id, policy_id: (data.submission || {}).policy_id },
                document_html: data.document_html,
                processing: data.processing,
                integrity: { payload_sha256: (data.submission || {}).payload_checksum },
            });
            return;
        }
        if (data.otp_required) {
            addBubble('bot', 'Welcome back. Enter the fresh verification code to continue.');
            if (data.otp) renderOtp(data.otp);
            if (data.otp && data.otp.demo_otp_code) {
                addBubble('bot', 'Demo environment: your verification code is <code>' + escapeHtml(data.otp.demo_otp_code) + '</code>.');
            }
            return;
        }
        await playMessages(data.transcript, { instant: true });
        setProgress(data.progress);
        renderStep(data.step);
    }

    async function pauseClaim() {
        if (!state.appId || state.submitted) return;
        const { status, data } = await api('POST', '/' + state.appId + '/pause', withCode({}));
        if (status === 200) await playMessages(data.messages);
    }

    document.addEventListener('DOMContentLoaded', () => {
        const note = $('auth-note');
        if (!token()) {
            note.textContent = 'Sign in with your PHINS account so I can use the details we already have.';
            $('start-btn').textContent = 'Sign in to file a claim';
        } else {
            note.textContent = 'Signed in. If this is your account, I will prefill your details for you to confirm or edit.';
        }
        $('start-btn').addEventListener('click', startClaim);
        $('show-resume-btn').addEventListener('click', () => {
            $('resume-form').hidden = !$('resume-form').hidden;
        });
        $('resume-form').addEventListener('submit', (e) => {
            e.preventDefault();
            resumeClaim($('resume-code-input').value.trim(), $('resume-email-input').value.trim());
        });
        $('pause-btn').addEventListener('click', pauseClaim);
        $('resume-pill').addEventListener('click', () => {
            navigator.clipboard?.writeText(state.resumeCode || '');
        });
        bindFileInput('doc-file-input');
        bindFileInput('audio-file-input', 'voice');
        bindFileInput('video-file-input', 'video');
        const params = new URLSearchParams(window.location.search);
        if (params.get('start') === '1' && token()) startClaim();
    });
})();
