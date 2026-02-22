/**
 * PHINS Registration with invitation code + CAPTCHA
 * Enhanced registration flow with:
 * - Invitation code validation
 * - CAPTCHA verification (bot protection)
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
  
  // State
  let isCodeValid = false;
  let currentStep = 1; // 1: details+captcha, 3: complete
  let pendingRegistrationData = null;
  const REGISTRATION_DRAFT_KEY = 'phins.registrationDraft.v1';
  const PENDING_REGISTRATION_KEY = 'phins.pendingRegistration.v1';

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
      sessionStorage.setItem(PENDING_REGISTRATION_KEY, JSON.stringify(pendingRegistrationData));
    } catch (e) {
      // Ignore storage errors silently.
    }
  }

  function clearRegistrationState() {
    pendingRegistrationData = null;
    try {
      sessionStorage.removeItem(PENDING_REGISTRATION_KEY);
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

  // ========== STEP TRANSITIONS ==========
  function showCompleteStep() {
    currentStep = 3;
    
    // Hide the registration form
    detailsSection.style.display = 'none';
    
    // Update step indicators
    step1Item.classList.remove('active');
    step1Item.classList.add('complete');
    connector1.classList.add('complete');
    step2Item.classList.remove('active');
    step2Item.classList.add('complete');
    connector2.classList.add('complete');
    step3Item.classList.add('active');
    
    submitBtn.style.display = 'none';
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

  // ========== FORM SUBMISSION ==========
  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    
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
      await completeRegistration();
      
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

  form.addEventListener('input', function () {
    if (currentStep === 1) {
      saveRegistrationDraft();
    }
  });

  updateSubmitButton();
});
