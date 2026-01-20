/**
 * PHINS Registration with OTP and CAPTCHA Security
 * Enhanced registration flow with:
 * - Invitation code validation
 * - CAPTCHA verification (bot protection)
 * - Email OTP verification
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
  let isCodeValid = false;
  let currentStep = 1; // 1: details+captcha, 2: otp, 3: complete
  let resendCountdown = 0;
  let resendInterval = null;
  let pendingRegistrationData = null;

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
    if (currentStep === 2) {
      submitBtn.disabled = false;
      return;
    }
    
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

  // ========== RESEND OTP ==========
  function startResendCountdown() {
    resendCountdown = 60;
    resendOtp.classList.add('disabled');
    resendOtp.innerHTML = 'Resend code in <span id="resend-timer">60</span>s';
    
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
        msg.textContent = 'New code sent!';
        msg.style.color = '#28a745';
        startResendCountdown();
        clearOTPInputs();
      } else {
        msg.textContent = data.message || 'Failed to resend code';
        msg.style.color = '#dc3545';
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
    step2Item.classList.remove('active');
    step2Item.classList.add('complete');
    connector2.classList.add('complete');
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
        body: JSON.stringify({
          ...pendingRegistrationData,
          email_verified: true,
          verification_id: verificationId.value
        })
      });
      const data = await response.json();
      
      if (data.success || data.customer_id) {
        showCompleteStep();
        
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
    
    // If in OTP step, verify OTP
    if (currentStep === 2) {
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
      
      // Step 2: Request email verification OTP
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
        // Save registration data for later
        pendingRegistrationData = {
          invitation_code: invitationCode,
          name: fullName,
          email: email,
          phone: phone,
          dob: dob,
          password: password
        };
        
        // Show OTP step
        showOTPStep(otpData.masked_email || email, otpData.verification_id);
        msg.textContent = 'Please enter the verification code sent to your email';
        msg.style.color = '#2e7d32';
        submitBtn.disabled = false;
        
      } else {
        msg.textContent = otpData.message || 'Failed to send verification code';
        msg.style.color = '#dc3545';
        submitBtn.disabled = false;
      }
      
    } catch (err) {
      console.error('Registration error:', err);
      msg.textContent = 'Registration error. Please try again.';
      msg.style.color = '#dc3545';
      submitBtn.disabled = false;
    }
  });

  // Initialize
  updateSubmitButton();
});
