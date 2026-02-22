/**
 * PHINS Registration with Invitation + CAPTCHA Security
 * Enhanced registration flow with:
 * - Invitation code validation
 * - CAPTCHA verification (bot protection)
 * - Optional email OTP (code retained, disabled by default)
 * - Strong password requirements
 */

document.addEventListener('DOMContentLoaded', function () {
  const form = document.getElementById('register-form');
  const msg = document.getElementById('register-msg');
  const passwordInput = document.getElementById('password');
  const confirmPasswordInput = document.getElementById('confirm-password');
  const strengthBar = document.getElementById('strength-bar');
  const submitBtn = document.getElementById('submit-btn');
  const invitationCodeInput = document.getElementById('invitation-code');
  const codeValidation = document.getElementById('code-validation');
  const emailInput = document.getElementById('email');
  
  // Sections
  const detailsSection = document.getElementById('details-section');
  const otpSection = document.getElementById('otp-section');
  const captchaSection = document.getElementById('captcha-section');
  
  // Step indicators
  const step1Item = document.getElementById('step-1-item');
  const step2Item = document.getElementById('step-2-item');
  const step3Item = document.getElementById('step-3-item');
  const connector1 = document.getElementById('connector-1');
  const connector2 = document.getElementById('connector-2');
  
  // CAPTCHA elements
  const captchaQuestion = document.getElementById('captcha-question');
  const captchaAnswer = document.getElementById('captcha-answer');
  const captchaId = document.getElementById('captcha-id');
  
  // OTP elements
  const otpDigits = document.querySelectorAll('.otp-digit');
  const otpEmail = document.getElementById('otp-email');
  const verificationId = document.getElementById('verification-id');
  const resendOtp = document.getElementById('resend-otp');
  const resendTimer = document.getElementById('resend-timer');

  // State
  const REGISTRATION_OTP_ENABLED = false; // Keep OTP code path hidden/unused for now.
  let isCodeValid = false;
  let currentStep = 1; // 1: details+captcha, 2: otp (disabled), 3: complete
  let resendCountdown = 0;
  let resendInterval = null;
  let pendingRegistrationData = null;
  const REGISTRATION_DRAFT_KEY = 'phins.registrationDraft.v1';
  const PENDING_REGISTRATION_KEY = 'phins.pendingRegistration.v1';
  const OTP_CONTEXT_KEY = 'phins.registrationOtpContext.v1';

  // ========== AUTO-FILL FROM URL PARAMETER ==========
  const urlParams = new URLSearchParams(window.location.search);
  const codeFromUrl = urlParams.get('code');
  
  if (codeFromUrl) {
    invitationCodeInput.value = codeFromUrl.toUpperCase();
    setTimeout(() => {
      validateInvitationCode(codeFromUrl.toUpperCase());
    }, 300);
    msg.innerHTML = '🎟️ Invitation code detected! Please complete your registration.';
    msg.style.color = '#28a745';
  }

  function safeParseStorage(key) {
    try {
      const raw = sessionStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function saveRegistrationDraft() {
    const draft = {
      invitation_code: form.invitation_code?.value?.trim()?.toUpperCase() || '',
      full_name: form.full_name?.value?.trim() || '',
      email: form.email?.value?.trim() || '',
      phone: form.phone?.value?.trim() || '',
      dob: form.dob?.value || ''
    };
    try {
      sessionStorage.setItem(REGISTRATION_DRAFT_KEY, JSON.stringify(draft));
    } catch (e) {
      // Ignore storage errors silently (quota/private mode).
    }
  }

  function restoreRegistrationDraft() {
    const draft = safeParseStorage(REGISTRATION_DRAFT_KEY);
    if (!draft || currentStep !== 1) return;

    if (!form.invitation_code.value && draft.invitation_code) {
      form.invitation_code.value = draft.invitation_code;
      if (draft.invitation_code.length >= 10) {
        validateInvitationCode(draft.invitation_code);
      }
    }
    if (!form.full_name.value && draft.full_name) form.full_name.value = draft.full_name;
    if (!form.email.value && draft.email) form.email.value = draft.email;
    if (!form.phone.value && draft.phone) form.phone.value = draft.phone;
    if (!form.dob.value && draft.dob) form.dob.value = draft.dob;
  }

  function persistPendingRegistrationState() {
    if (!pendingRegistrationData) return;
    try {
      // Session-scoped persistence keeps OTP flow recoverable on refresh.
      sessionStorage.setItem(PENDING_REGISTRATION_KEY, JSON.stringify(pendingRegistrationData));
    } catch (e) {
      // Ignore storage errors silently.
    }
  }

  function persistOtpContext(email, verId) {
    try {
      sessionStorage.setItem(OTP_CONTEXT_KEY, JSON.stringify({
        email: email || '',
        verification_id: verId || '',
        saved_at: Date.now()
      }));
    } catch (e) {
      // Ignore storage errors silently.
    }
  }

  function clearRegistrationState() {
    pendingRegistrationData = null;
    try {
      sessionStorage.removeItem(PENDING_REGISTRATION_KEY);
      sessionStorage.removeItem(OTP_CONTEXT_KEY);
      sessionStorage.removeItem(REGISTRATION_DRAFT_KEY);
    } catch (e) {
      // Ignore storage errors silently.
    }
  }

  function restorePendingRegistrationState() {
    const pending = safeParseStorage(PENDING_REGISTRATION_KEY);
    if (pending && pending.email && pending.password && pending.invitation_code) {
      pendingRegistrationData = pending;
    }
  }

  // ========== CAPTCHA INITIALIZATION ==========
  async function loadCaptcha() {
    try {
      const response = await fetch('/api/security/captcha', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'register' })
      });
      const data = await response.json();
      
      if (data.success && data.challenge) {
        captchaId.value = data.challenge.challenge_id;
        if (data.challenge.challenge_type === 'simple') {
          captchaQuestion.textContent = data.challenge.challenge_question;
        } else {
          captchaQuestion.innerHTML = '<em>Advanced verification loaded</em>';
        }
      } else {
        captchaSection.style.display = 'none';
      }
    } catch (e) {
      console.log('CAPTCHA not available');
      captchaSection.style.display = 'none';
    }
  }
  
  loadCaptcha();

  // ========== INVITATION CODE VALIDATION ==========
  let codeValidationTimeout = null;
  
  invitationCodeInput.addEventListener('input', function() {
    const code = invitationCodeInput.value.trim().toUpperCase();
    invitationCodeInput.value = code;
    
    if (codeValidationTimeout) {
      clearTimeout(codeValidationTimeout);
    }
    
    if (code.length < 10) {
      codeValidation.textContent = '';
      isCodeValid = false;
      updateSubmitButton();
      return;
    }
    
    codeValidationTimeout = setTimeout(() => validateInvitationCode(code), 500);
  });

  async function validateInvitationCode(code) {
    codeValidation.textContent = '⏳ Validating code...';
    codeValidation.style.color = '#856404';
    
    try {
      const response = await fetch(`/api/invitations/validate?code=${encodeURIComponent(code)}`);
      const data = await response.json();
      
      if (data.valid) {
        codeValidation.innerHTML = '✅ Valid invitation code';
        codeValidation.style.color = '#28a745';
        isCodeValid = true;
      } else {
        codeValidation.innerHTML = '❌ ' + (data.error || 'Invalid code');
        codeValidation.style.color = '#dc3545';
        isCodeValid = false;
      }
    } catch (e) {
      codeValidation.innerHTML = '⚠️ Unable to validate code';
      codeValidation.style.color = '#856404';
      isCodeValid = false;
    }
    
    updateSubmitButton();
  }

  // ========== PASSWORD STRENGTH CHECKER ==========
  passwordInput.addEventListener('input', function() {
    const password = passwordInput.value;
    const requirements = {
      length: password.length >= 8,
      uppercase: /[A-Z]/.test(password),
      lowercase: /[a-z]/.test(password),
      number: /[0-9]/.test(password)
    };

    document.getElementById('req-length').className = requirements.length ? 'requirement met' : 'requirement';
    document.getElementById('req-length').textContent = requirements.length ? '✓ At least 8 characters' : '✗ At least 8 characters';
    
    document.getElementById('req-uppercase').className = requirements.uppercase ? 'requirement met' : 'requirement';
    document.getElementById('req-uppercase').textContent = requirements.uppercase ? '✓ One uppercase letter' : '✗ One uppercase letter';
    
    document.getElementById('req-lowercase').className = requirements.lowercase ? 'requirement met' : 'requirement';
    document.getElementById('req-lowercase').textContent = requirements.lowercase ? '✓ One lowercase letter' : '✗ One lowercase letter';
    
    document.getElementById('req-number').className = requirements.number ? 'requirement met' : 'requirement';
    document.getElementById('req-number').textContent = requirements.number ? '✓ One number' : '✗ One number';

    const metCount = Object.values(requirements).filter(Boolean).length;
    const strength = (metCount / 4) * 100;
    strengthBar.style.width = strength + '%';
    
    if (strength < 50) {
      strengthBar.style.background = '#dc3545';
    } else if (strength < 75) {
      strengthBar.style.background = '#ffc107';
    } else {
      strengthBar.style.background = '#28a745';
    }

    updateSubmitButton();
  });

  function updateSubmitButton() {
    const password = passwordInput.value;
    const requirements = {
      length: password.length >= 8,
      uppercase: /[A-Z]/.test(password),
      lowercase: /[a-z]/.test(password),
      number: /[0-9]/.test(password)
    };
    const allPasswordMet = Object.values(requirements).every(Boolean);
    
    submitBtn.disabled = !isCodeValid || !allPasswordMet;
  }

  // ========== OTP INPUT HANDLING ==========
  otpDigits.forEach((digit, index) => {
    digit.addEventListener('input', function(e) {
      const value = e.target.value;
      
      if (!/^\d*$/.test(value)) {
        e.target.value = '';
        return;
      }
      
      if (value && index < otpDigits.length - 1) {
        otpDigits[index + 1].focus();
      }
      
      const code = getOTPCode();
      if (code.length === 6) {
        verifyEmailOTP(code);
      }
    });
    
    digit.addEventListener('keydown', function(e) {
      if (e.key === 'Backspace' && !e.target.value && index > 0) {
        otpDigits[index - 1].focus();
      }
    });
    
    digit.addEventListener('paste', function(e) {
      e.preventDefault();
      const pastedData = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6);
      
      pastedData.split('').forEach((char, i) => {
        if (i < otpDigits.length) {
          otpDigits[i].value = char;
        }
      });
      
      if (pastedData.length === 6) {
        verifyEmailOTP(pastedData);
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

  function extractFallbackOtpCode(payload) {
    if (!payload || payload.delivery_mode !== 'demo_otp_fallback') {
      return '';
    }
    const normalized = String(payload.demo_otp_code || '').replace(/\D/g, '').slice(0, otpDigits.length);
    return normalized.length === otpDigits.length ? normalized : '';
  }

  function prefillOtpDigits(code) {
    const normalized = String(code || '').replace(/\D/g, '').slice(0, otpDigits.length);
    if (normalized.length !== otpDigits.length) return false;
    otpDigits.forEach((digit, index) => {
      digit.value = normalized[index];
    });
    otpDigits[otpDigits.length - 1].focus();
    return true;
  }

  function applyOtpDeliveryFeedback(payload, isResend = false) {
    const fallbackCode = extractFallbackOtpCode(payload);
    if (fallbackCode) {
      prefillOtpDigits(fallbackCode);
      const baseMessage = payload.message || 'Email delivery is unavailable right now.';
      msg.textContent = `${baseMessage} Fallback code: ${fallbackCode}`;
      msg.style.color = '#856404';
      return;
    }

    msg.textContent = isResend
      ? 'New verification code sent!'
      : 'Please enter the verification code sent to your email';
    msg.style.color = isResend ? '#28a745' : '#2e7d32';
  }

  // ========== RESEND OTP ==========
  function startResendCountdown(seconds = 60) {
    const parsedSeconds = Number(seconds);
    resendCountdown = Number.isFinite(parsedSeconds) && parsedSeconds > 0
      ? Math.floor(parsedSeconds)
      : 60;
    resendOtp.classList.add('disabled');
    resendOtp.innerHTML = `Resend code in <span id="resend-timer">${resendCountdown}</span>s`;
    
    resendInterval = setInterval(() => {
      resendCountdown--;
      const timerSpan = document.getElementById('resend-timer');
      if (timerSpan) timerSpan.textContent = resendCountdown;
      
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
      const response = await fetch('/api/security/otp/resend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          verification_id: verificationId.value
        })
      });
      const data = await response.json();
      
      if (data.success) {
        if (data.verification_id) {
          verificationId.value = data.verification_id;
          persistOtpContext(otpEmail.textContent, data.verification_id);
        }
        applyOtpDeliveryFeedback(data, true);
        startResendCountdown(data.retry_after_seconds || 60);
        if (!extractFallbackOtpCode(data)) {
          clearOTPInputs();
        }
      } else {
        msg.textContent = data.message || 'Failed to resend code';
        msg.style.color = '#dc3545';
        if (data.retry_after_seconds) {
          startResendCountdown(data.retry_after_seconds);
        }
      }
    } catch (e) {
      msg.textContent = 'Error sending code';
      msg.style.color = '#dc3545';
    }
  });

  // ========== STEP TRANSITIONS ==========
  function showOTPStep(email, verId) {
    currentStep = 2;
    
    // Update step indicators
    step1Item.classList.remove('active');
    step1Item.classList.add('complete');
    connector1.classList.add('complete');
    step2Item.classList.add('active');
    
    // Hide details, show OTP
    detailsSection.style.display = 'none';
    otpSection.classList.add('active');
    
    // Set values
    otpEmail.textContent = email;
    verificationId.value = verId;
    persistOtpContext(email, verId);
    
    submitBtn.textContent = 'Verify Email';
    updateSubmitButton();
    
    // Start countdown
    startResendCountdown();
    
    // Focus first OTP input
    setTimeout(() => otpDigits[0].focus(), 100);
  }

  function showCompleteStep() {
    currentStep = 3;
    
    // Update step indicators
    step1Item.classList.remove('active');
    step1Item.classList.add('complete');
    connector1.classList.add('complete');
    if (REGISTRATION_OTP_ENABLED) {
      step2Item.classList.remove('active');
      step2Item.classList.add('complete');
      connector2.classList.add('complete');
    }
    step3Item.classList.add('active');
    
    submitBtn.style.display = 'none';
  }

  // ========== VERIFY EMAIL OTP ==========
  async function verifyEmailOTP(code) {
    submitBtn.disabled = true;
    msg.textContent = 'Verifying email...';
    msg.style.color = '#546e7a';
    
    try {
      const response = await fetch('/api/security/otp/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          verification_id: verificationId.value,
          otp_code: code
        })
      });
      const data = await response.json();
      
      if (data.success) {
        msg.textContent = 'Email verified! Creating your account...';
        msg.style.color = '#28a745';
        
        // Complete registration
        completeRegistration();
      } else {
        msg.textContent = data.message || 'Invalid code';
        msg.style.color = '#dc3545';
        clearOTPInputs();
        submitBtn.disabled = false;
      }
    } catch (e) {
      msg.textContent = 'Verification error';
      msg.style.color = '#dc3545';
      submitBtn.disabled = false;
    }
  }

  // ========== COMPLETE REGISTRATION ==========
  async function completeRegistration() {
    if (!pendingRegistrationData) {
      msg.textContent = 'Session expired. Please try again.';
      msg.style.color = '#dc3545';
      location.reload();
      return;
    }
    
    try {
      const response = await fetch('/api/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pendingRegistrationData)
      });
      const data = await response.json();
      
      if (data.success || data.customer_id) {
        showCompleteStep();
        clearRegistrationState();
        
        msg.innerHTML = '✅ Account created successfully! Redirecting to login...';
        msg.style.color = '#28a745';
        codeValidation.innerHTML = '🎉 Welcome to PHINS!';
        
        setTimeout(() => {
          window.location.href = '/login.html';
        }, 2000);
      } else {
        let errorMsg = data.error || 'Unknown error';
        if (data.code === 'EMAIL_EXISTS') {
          errorMsg = 'An account with this email already exists';
        } else if (data.code === 'INVALID_CODE') {
          errorMsg = 'The invitation code is not valid';
        }
        
        msg.textContent = 'Registration failed: ' + errorMsg;
        msg.style.color = '#dc3545';
        submitBtn.disabled = false;
      }
    } catch (e) {
      msg.textContent = 'Registration error. Please try again.';
      msg.style.color = '#dc3545';
      submitBtn.disabled = false;
    }
  }

  async function requestRegistrationOTP(email) {
    const maxAttempts = 2;
    let lastFailure = null;

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        const otpResponse = await fetch('/api/security/otp/request', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            email: email,
            purpose: 'registration',
            user_type: 'customer'
          })
        });
        const otpData = await otpResponse.json();

        if (otpData.success && otpData.verification_id) {
          return otpData;
        }

        lastFailure = otpData;
        const shouldRetry =
          attempt < maxAttempts &&
          (otpData.error_code === 'OTP_DELIVERY_FAILED' || otpData.error_code === 'RATE_LIMITED');
        if (!shouldRetry) break;

        msg.textContent = 'Delivery retry in progress...';
        msg.style.color = '#856404';
        await new Promise(resolve => setTimeout(resolve, 1200));
      } catch (error) {
        lastFailure = { message: 'Network error while requesting code' };
        if (attempt < maxAttempts) {
          await new Promise(resolve => setTimeout(resolve, 1000));
          continue;
        }
      }
    }

    return lastFailure || { message: 'Failed to send verification code' };
  }

  // ========== FORM SUBMISSION ==========
  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    
    // If OTP flow is enabled and in OTP step, verify OTP
    if (REGISTRATION_OTP_ENABLED && currentStep === 2) {
      const code = getOTPCode();
      if (code.length === 6) {
        verifyEmailOTP(code);
      } else {
        msg.textContent = 'Please enter the 6-digit code';
        msg.style.color = '#dc3545';
      }
      return;
    }
    
    const invitationCode = form.invitation_code.value.trim().toUpperCase();
    const fullName = form.full_name.value.trim();
    const email = form.email.value.trim();
    const phone = form.phone.value.trim();
    const dob = form.dob.value;
    const password = form.password.value;
    const confirmPassword = form.confirm_password.value;
    const captchaValue = captchaAnswer.value.trim();
    const captchaIdValue = captchaId.value;

    // Validation
    if (!invitationCode) {
      msg.textContent = 'Invitation code is required';
      msg.style.color = '#dc3545';
      return;
    }

    if (!isCodeValid) {
      msg.textContent = 'Please enter a valid invitation code';
      msg.style.color = '#dc3545';
      return;
    }

    if (!fullName || !email || !password) {
      msg.textContent = 'Please fill in all required fields';
      msg.style.color = '#dc3545';
      return;
    }

    if (password !== confirmPassword) {
      msg.textContent = 'Passwords do not match';
      msg.style.color = '#dc3545';
      return;
    }

    if (password.length < 8) {
      msg.textContent = 'Password must be at least 8 characters';
      msg.style.color = '#dc3545';
      return;
    }

    // Verify CAPTCHA if present
    if (captchaSection.style.display !== 'none' && captchaIdValue) {
      if (!captchaValue) {
        msg.textContent = 'Please complete the verification';
        msg.style.color = '#dc3545';
        captchaAnswer.focus();
        return;
      }
    }

    msg.textContent = 'Processing...';
    msg.style.color = '#856404';
    submitBtn.disabled = true;
    
    try {
      // Step 1: Verify CAPTCHA if present
      if (captchaIdValue && captchaValue) {
        const captchaResponse = await fetch('/api/security/captcha/verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            challenge_id: captchaIdValue,
            response: captchaValue
          })
        });
        const captchaResult = await captchaResponse.json();
        
        if (!captchaResult.success) {
          msg.textContent = captchaResult.message || 'Verification failed. Please try again.';
          msg.style.color = '#dc3545';
          submitBtn.disabled = false;
          loadCaptcha();
          captchaAnswer.value = '';
          return;
        }
      }
      
      // Keep registration payload in session so refresh doesn't lose progress.
      pendingRegistrationData = {
        invitation_code: invitationCode,
        name: fullName,
        email: email,
        phone: phone,
        dob: dob,
        password: password
      };
      persistPendingRegistrationState();
      saveRegistrationDraft();

      if (REGISTRATION_OTP_ENABLED) {
        // Optional OTP flow (currently disabled).
        const otpData = await requestRegistrationOTP(email);
        
        if (otpData.success && otpData.verification_id) {
          showOTPStep(otpData.masked_email || email, otpData.verification_id);
          applyOtpDeliveryFeedback(otpData, false);
          submitBtn.disabled = false;
          
        } else {
          msg.textContent = otpData.message || 'Failed to send verification code';
          msg.style.color = '#dc3545';
          submitBtn.disabled = false;
        }
      } else {
        // Invitation-only registration mode.
        await completeRegistration();
      }
      
    } catch (err) {
      console.error('Registration error:', err);
      msg.textContent = 'Registration error. Please try again.';
      msg.style.color = '#dc3545';
      submitBtn.disabled = false;
    }
  });

  // Initialize
  restoreRegistrationDraft();
  restorePendingRegistrationState();
  if (REGISTRATION_OTP_ENABLED) {
    const otpContext = safeParseStorage(OTP_CONTEXT_KEY);
    if (
      pendingRegistrationData &&
      otpContext &&
      otpContext.verification_id &&
      typeof otpContext.verification_id === 'string'
    ) {
      showOTPStep(otpContext.email || pendingRegistrationData.email, otpContext.verification_id);
      msg.textContent = 'Continue by entering the verification code from your email.';
      msg.style.color = '#2e7d32';
      submitBtn.disabled = false;
    }
  } else {
    // Hide OTP-related UI while retaining the implementation for future use.
    otpSection.classList.remove('active');
    otpSection.style.display = 'none';
    if (step2Item) step2Item.style.display = 'none';
    if (connector2) connector2.style.display = 'none';
    submitBtn.textContent = 'Create Account';
  }

  form.addEventListener('input', function () {
    if (currentStep === 1) {
      saveRegistrationDraft();
    }
  });

  updateSubmitButton();
});
