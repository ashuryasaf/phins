/**
 * PHINS Login with OTP and CAPTCHA Security
 * Enhanced login flow with:
 * - CAPTCHA verification (bot protection)
 * - OTP verification for new devices
 * - Device trust management
 * - Retry logic for transient network failures
 */

document.addEventListener('DOMContentLoaded', function () {
  const form = document.getElementById('login-form');
  const msg = document.getElementById('login-msg');
  const submitBtn = document.getElementById('submit-btn');
  
  // Sections
  const credentialsSection = document.getElementById('credentials-section');
  const otpSection = document.getElementById('otp-section');
  const captchaSection = document.getElementById('captcha-section');
  
  // Step indicators
  const step1 = document.getElementById('step-1');
  const step2 = document.getElementById('step-2');
  const step3 = document.getElementById('step-3');
  
  // CAPTCHA elements
  const captchaQuestion = document.getElementById('captcha-question');
  const captchaAnswer = document.getElementById('captcha-answer');
  const captchaId = document.getElementById('captcha-id');
  const captchaRefreshBtn = document.getElementById('captcha-refresh');
  
  // OTP elements
  const otpDigits = document.querySelectorAll('.otp-digit');
  const otpEmail = document.getElementById('otp-email');
  const verificationId = document.getElementById('verification-id');
  const resendOtp = document.getElementById('resend-otp');
  const resendTimer = document.getElementById('resend-timer');
  const trustDevice = document.getElementById('trust-device');
  
  // State
  var currentStep = 1; // 1: credentials+captcha, 2: otp, 3: complete
  var resendCountdown = 0;
  var resendInterval = null;
  var pendingLoginData = null;
  var localCaptchaAnswer = null;
  var otpVerifyInFlight = false;
  var captchaVerifiedToken = null;
  var captchaExpiryTimer = null;
  var LOCAL_CAPTCHA_FLAG = ['__', 'local', '__'].join('');
  
  function safeStorageSet(storage, key, value) {
    try {
      storage.setItem(key, value);
      return true;
    } catch (err) {
      console.warn('Storage set failed (' + key + '):', err);
      return false;
    }
  }

  function fetchWithTimeout(url, options, timeoutMs) {
    timeoutMs = timeoutMs || 30000;
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, timeoutMs);
    options = options || {};
    options.signal = controller.signal;
    return fetch(url, options).finally(function () { clearTimeout(timer); });
  }

  function fetchWithRetry(url, options, timeoutMs, maxRetries) {
    maxRetries = maxRetries || 2;
    timeoutMs = timeoutMs || 30000;
    var attempt = 0;

    function tryOnce() {
      attempt++;
      return fetchWithTimeout(url, Object.assign({}, options), timeoutMs)
        .then(function (response) {
          if (response.status >= 500 && attempt <= maxRetries) {
            return delay(1000 * attempt).then(tryOnce);
          }
          return response;
        })
        .catch(function (err) {
          if (attempt <= maxRetries && (err.name === 'AbortError' || err.name === 'TypeError')) {
            return delay(1000 * attempt).then(tryOnce);
          }
          throw err;
        });
    }

    return tryOnce();
  }

  function delay(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  function generateLocalCaptchaChallenge() {
    var a = Math.floor(Math.random() * 20) + 10;
    var b = Math.floor(Math.random() * 15) + 5;
    var ops = [
      { symbol: '+', fn: function (x, y) { return x + y; } },
      { symbol: '-', fn: function (x, y) { return x - y; } },
      { symbol: 'x', fn: function (x, y) { return x * y; } }
    ];
    var op = ops[Math.floor(Math.random() * ops.length)];
    if (op.symbol === '-' && b > a) { var tmp = a; a = b; b = tmp; }
    if (op.symbol === 'x') { a = Math.floor(Math.random() * 9) + 2; b = Math.floor(Math.random() * 9) + 2; }
    return {
      question: 'What is ' + a + ' ' + op.symbol + ' ' + b + '?',
      answer: String(op.fn(a, b))
    };
  }

  function showLocalCaptcha(message) {
    var localChallenge = generateLocalCaptchaChallenge();
    localCaptchaAnswer = localChallenge.answer;
    captchaVerifiedToken = null;
    captchaAnswer.value = '';
    captchaId.value = '';
    captchaQuestion.textContent = localChallenge.question;
    captchaQuestion.title = message || 'Using built-in verification';
    captchaSection.style.display = '';
  }
  
  function getDeviceFingerprint() {
    var canvas = document.createElement('canvas');
    var ctx = canvas.getContext('2d');
    ctx.textBaseline = 'top';
    ctx.font = '14px Arial';
    ctx.fillText('PHINS fingerprint', 2, 2);
    var canvasData = canvas.toDataURL();
    
    var data = [
      navigator.userAgent,
      navigator.language,
      screen.width + 'x' + screen.height,
      new Date().getTimezoneOffset(),
      canvasData.substring(0, 50)
    ].join('|');
    
    var hash = 0;
    for (var i = 0; i < data.length; i++) {
      var char = data.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash;
    }
    return Math.abs(hash).toString(16);
  }

  function startCaptchaExpiryTimer(expiresAt) {
    if (captchaExpiryTimer) clearInterval(captchaExpiryTimer);
    if (!expiresAt) return;

    var expiryDate = new Date(expiresAt);
    captchaExpiryTimer = setInterval(function () {
      var remaining = Math.max(0, Math.floor((expiryDate - Date.now()) / 1000));
      if (remaining <= 0) {
        clearInterval(captchaExpiryTimer);
        captchaExpiryTimer = null;
        loadCaptcha();
      }
    }, 10000);
  }
  
  async function loadCaptcha() {
    localCaptchaAnswer = null;
    captchaVerifiedToken = null;
    captchaAnswer.value = '';
    captchaId.value = '';
    captchaQuestion.textContent = 'Loading verification...';
    captchaQuestion.title = '';
    captchaSection.style.display = '';
    if (captchaExpiryTimer) { clearInterval(captchaExpiryTimer); captchaExpiryTimer = null; }

    try {
      var response = await fetchWithRetry('/api/security/captcha', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'login' })
      }, 15000, 2);
      var data = await response.json();
      
      if (response.ok && data.success && data.challenge) {
        captchaId.value = data.challenge.challenge_id;
        if (data.challenge.challenge_type === 'simple') {
          captchaQuestion.textContent = data.challenge.challenge_question;
          captchaQuestion.title = '';
        } else {
          showLocalCaptcha('Advanced CAPTCHA fallback is active');
        }
        if (data.challenge.expires_at) {
          startCaptchaExpiryTimer(data.challenge.expires_at);
        }
      } else {
        showLocalCaptcha('Verification service is temporarily unavailable');
      }
    } catch (e) {
      console.log('CAPTCHA load failed, using local fallback:', e);
      showLocalCaptcha('Verification service could not be reached');
    }
  }

  if (captchaRefreshBtn) {
    captchaRefreshBtn.addEventListener('click', function (e) {
      e.preventDefault();
      loadCaptcha();
    });
  }
  
  loadCaptcha();
  
  // OTP digit input handling
  otpDigits.forEach((digit, index) => {
    digit.addEventListener('input', function(e) {
      const value = e.target.value;
      
      // Only allow numbers
      if (!/^\d*$/.test(value)) {
        e.target.value = '';
        return;
      }
      
      // Move to next input
      if (value && index < otpDigits.length - 1) {
        otpDigits[index + 1].focus();
      }
      
      // Check if all digits are filled
      const code = getOTPCode();
      if (code.length === 6) {
        verifyOTP(code);
      }
    });
    
    digit.addEventListener('keydown', function(e) {
      // Handle backspace
      if (e.key === 'Backspace' && !e.target.value && index > 0) {
        otpDigits[index - 1].focus();
      }
    });
    
    // Handle paste
    digit.addEventListener('paste', function(e) {
      e.preventDefault();
      const pastedData = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6);
      
      pastedData.split('').forEach((char, i) => {
        if (i < otpDigits.length) {
          otpDigits[i].value = char;
        }
      });
      
      if (pastedData.length === 6) {
        verifyOTP(pastedData);
      }
    });
  });
  
  function getOTPCode() {
    return Array.from(otpDigits).map(d => d.value).join('');
  }
  
  function clearOTPInputs() {
    otpDigits.forEach(d => d.value = '');
    otpDigits[0].focus();
  }
  
  // Resend OTP handling
  function startResendCountdown() {
    resendCountdown = 60;
    resendOtp.classList.add('disabled');
    
    resendInterval = setInterval(() => {
      resendCountdown--;
      resendTimer.textContent = resendCountdown;
      
      if (resendCountdown <= 0) {
        clearInterval(resendInterval);
        resendOtp.classList.remove('disabled');
        resendOtp.textContent = 'Resend code';
      }
    }, 1000);
  }
  
  resendOtp.addEventListener('click', async function(e) {
    e.preventDefault();
    if (resendOtp.classList.contains('disabled')) return;
    
    try {
      var response = await fetchWithRetry('/api/security/otp/resend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          verification_id: verificationId.value
        })
      }, 15000, 1);
      var data = await response.json();
      
      if (data.success) {
        msg.textContent = 'New code sent!';
        msg.style.color = '#28a745';
        startResendCountdown();
        clearOTPInputs();
      } else {
        msg.textContent = data.message || 'Failed to resend code';
        msg.style.color = '#dc3545';
      }
    } catch (resendErr) {
      msg.textContent = 'Error sending code. Please try again.';
      msg.style.color = '#dc3545';
    }
  });
  
  // Switch to OTP step
  function showOTPStep(email, verId) {
    currentStep = 2;
    
    // Update UI
    step1.classList.remove('active');
    step1.classList.add('complete');
    step2.classList.add('active');
    
    credentialsSection.style.display = 'none';
    otpSection.classList.add('active');
    
    // Set values
    otpEmail.textContent = email;
    verificationId.value = verId;
    
    submitBtn.textContent = 'Verify & Sign In';
    
    // Start countdown
    startResendCountdown();
    
    // Focus first OTP input
    setTimeout(() => otpDigits[0].focus(), 100);
  }
  
  async function verifyOTP(code) {
    if (otpVerifyInFlight) return;
    otpVerifyInFlight = true;
    submitBtn.disabled = true;
    msg.textContent = 'Verifying...';
    msg.style.color = '#546e7a';
    
    try {
      var response = await fetchWithRetry('/api/security/otp/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          verification_id: verificationId.value,
          otp_code: code,
          trust_device: trustDevice.checked,
          device_fingerprint: getDeviceFingerprint()
        })
      }, 20000, 1);
      var data = await response.json();
      
      if (data.success) {
        msg.textContent = 'Verified! Completing login...';
        msg.style.color = '#28a745';
        completeLogin();
      } else {
        msg.textContent = data.message || 'Invalid code';
        msg.style.color = '#dc3545';
        clearOTPInputs();
        submitBtn.disabled = false;
        otpVerifyInFlight = false;
      }
    } catch (e) {
      msg.textContent = e.name === 'AbortError' ? 'Verification timed out. Please try again.' : 'Verification error. Please try again.';
      msg.style.color = '#dc3545';
      submitBtn.disabled = false;
      otpVerifyInFlight = false;
    }
  }
  
  async function completeLogin() {
    if (!pendingLoginData) {
      msg.textContent = 'Session expired. Please try again.';
      msg.style.color = '#dc3545';
      location.reload();
      return;
    }
    
    step2.classList.remove('active');
    step2.classList.add('complete');
    step3.classList.add('active');
    
    try {
      var loginPayload = Object.assign({}, pendingLoginData, {
        verified: true,
        verification_id: verificationId.value
      });

      var response = await fetchWithRetry('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(loginPayload)
      }, 30000, 2);
      var data = await response.json();
      
      if (data.token) {
        handleLoginSuccess(data, pendingLoginData.username);
      } else {
        msg.textContent = 'Login failed: ' + (data.error || 'Unknown error');
        msg.style.color = '#dc3545';
        submitBtn.disabled = false;
      }
    } catch (e) {
      msg.textContent = e.name === 'AbortError' ? 'The server is taking longer than usual. Please try again.' : 'Login error. Please try again.';
      msg.style.color = '#dc3545';
      submitBtn.disabled = false;
    }
  }
  
  function getDashboardUrl(role) {
    switch (role) {
      case 'admin': return '/admin-portal.html';
      case 'media': return '/admin-media.html';
      case 'actuary': return '/actuary-dashboard.html';
      case 'supplier': return '/supplier-dashboard.html';
      case 'underwriter': return '/underwriter-dashboard.html';
      case 'claims':
      case 'claims_adjuster': return '/claims-adjuster-dashboard.html';
      case 'accountant': return '/accountant-dashboard.html';
      case 'customer':
      default: return '/dashboard.html';
    }
  }

  // Handle successful login
  function handleLoginSuccess(data, username) {
    msg.textContent = 'Login successful! Redirecting...';
    msg.style.color = '#28a745';
    submitBtn.disabled = true;

    const targetUrl = getDashboardUrl(data.role || '');

    try {
      safeStorageSet(localStorage, 'phins_token', data.token);
      safeStorageSet(sessionStorage, 'phins_token', data.token);
      safeStorageSet(sessionStorage, 'username', username);

      const sessionObj = {
        customer_id: data.customer_id || null,
        username: username,
        role: data.role || 'customer',
        name: data.name || username,
        token: data.token,
        login_time: new Date().toISOString()
      };
      safeStorageSet(localStorage, 'session', JSON.stringify(sessionObj));
      safeStorageSet(sessionStorage, 'user_role', data.role || 'customer');

      if (data.customer_id) {
        safeStorageSet(localStorage, 'customer_id', data.customer_id);
        safeStorageSet(sessionStorage, 'customer_id', data.customer_id);
        safeStorageSet(localStorage, 'phins_customer_id', data.customer_id);
      } else if (data.role === 'customer') {
        console.warn('Customer login successful but no customer_id in response:', data);
      }

      safeStorageSet(localStorage, 'phins_device_fp', getDeviceFingerprint());
    } catch (storageErr) {
      console.warn('Non-critical: failed to persist session data', storageErr);
    }

    console.log('Session stored:', { username, role: data.role });

    setTimeout(() => { window.location.href = targetUrl; }, 400);

    setTimeout(() => {
      if (submitBtn.disabled) {
        submitBtn.disabled = false;
        msg.textContent = 'Redirect may have been blocked. Click here to continue.';
        msg.style.color = '#1565c0';
        msg.style.cursor = 'pointer';
        msg.onclick = () => { window.location.href = targetUrl; };
      }
    }, 5000);
  }
  
  // Main form submission
  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    
    if (currentStep === 2) {
      var code = getOTPCode();
      if (code.length === 6) {
        verifyOTP(code);
      } else {
        msg.textContent = 'Please enter the 6-digit code';
        msg.style.color = '#dc3545';
      }
      return;
    }
    
    var username = form.username.value.trim();
    var password = form.password.value;
    var captchaValue = captchaAnswer.value.trim();
    var captchaIdValue = captchaId.value;
    
    if (!username || !password) {
      msg.textContent = 'Please enter username and password';
      msg.style.color = '#dc3545';
      return;
    }
    
    if (captchaSection.style.display !== 'none') {
      if (!captchaValue) {
        msg.textContent = 'Please complete the verification';
        msg.style.color = '#dc3545';
        captchaAnswer.focus();
        return;
      }
    }
    
    msg.textContent = 'Signing in...';
    msg.style.color = '#546e7a';
    submitBtn.disabled = true;
    
    try {
      var verifiedCaptchaToken = captchaVerifiedToken;

      if (!verifiedCaptchaToken) {
        if (captchaIdValue && captchaValue) {
          var captchaResponse = await fetchWithRetry('/api/security/captcha/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              challenge_id: captchaIdValue,
              response: captchaValue
            })
          }, 15000, 1);
          var captchaResult = await captchaResponse.json();
          
          if (!captchaResult.success) {
            msg.textContent = captchaResult.message || 'Verification failed. Please try again.';
            msg.style.color = '#dc3545';
            submitBtn.disabled = false;
            loadCaptcha();
            captchaAnswer.value = '';
            return;
          }
          verifiedCaptchaToken = captchaIdValue;
          captchaVerifiedToken = captchaIdValue;
        } else if (localCaptchaAnswer) {
          if (captchaValue.toLowerCase().trim() !== localCaptchaAnswer.toLowerCase().trim()) {
            msg.textContent = 'Verification failed. Please try again.';
            msg.style.color = '#dc3545';
            submitBtn.disabled = false;
            loadCaptcha();
            captchaAnswer.value = '';
            return;
          }
          verifiedCaptchaToken = LOCAL_CAPTCHA_FLAG;
        }
      }
      
      var loginData = {
        username: username,
        password: password,
        device_fingerprint: getDeviceFingerprint(),
        user_agent: navigator.userAgent
      };

      if (verifiedCaptchaToken && verifiedCaptchaToken !== LOCAL_CAPTCHA_FLAG) {
        loginData.captcha_token = verifiedCaptchaToken;
      }
      
      var response = await fetchWithRetry('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(loginData)
      }, 30000, 2);
      var data = await response.json();
      
      if (data.requires_otp) {
        pendingLoginData = loginData;
        showOTPStep(data.masked_email || '***@***.com', data.verification_id);
        msg.textContent = 'Please enter the verification code sent to your email';
        msg.style.color = '#e65100';
        submitBtn.disabled = false;
        
      } else if (data.token) {
        handleLoginSuccess(data, username);
        
      } else {
        msg.textContent = 'Login failed: ' + (data.error || 'Invalid credentials');
        msg.style.color = '#dc3545';
        submitBtn.disabled = false;
        captchaVerifiedToken = null;
        loadCaptcha();
        captchaAnswer.value = '';
      }
      
    } catch (err) {
      console.error('Login error:', err);
      if (err.name === 'AbortError') {
        msg.textContent = 'The server is taking longer than usual. Please try again.';
      } else if (!navigator.onLine) {
        msg.textContent = 'You appear to be offline. Please check your connection.';
      } else {
        msg.textContent = 'Connection error. Please try again.';
      }
      msg.style.color = '#dc3545';
      submitBtn.disabled = false;
      captchaVerifiedToken = null;
      loadCaptcha();
    }
  });
});
