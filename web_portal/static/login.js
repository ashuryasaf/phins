/**
 * PHINS Login with OTP and CAPTCHA Security
 * Enhanced login flow with:
 * - CAPTCHA verification (bot protection)
 * - OTP verification for new devices
 * - Device trust management
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
  
  // OTP elements
  const otpDigits = document.querySelectorAll('.otp-digit');
  const otpEmail = document.getElementById('otp-email');
  const verificationId = document.getElementById('verification-id');
  const resendOtp = document.getElementById('resend-otp');
  const resendTimer = document.getElementById('resend-timer');
  const trustDevice = document.getElementById('trust-device');
  
  // State
  let currentStep = 1; // 1: credentials+captcha, 2: otp, 3: complete
  let resendCountdown = 0;
  let resendInterval = null;
  let pendingLoginData = null;
  
  function safeStorageSet(storage, key, value) {
    try {
      storage.setItem(key, value);
      return true;
    } catch (err) {
      console.warn(`Storage set failed (${key}):`, err);
      return false;
    }
  }
  
  // Generate device fingerprint
  function getDeviceFingerprint() {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    ctx.textBaseline = 'top';
    ctx.font = '14px Arial';
    ctx.fillText('PHINS fingerprint', 2, 2);
    const canvasData = canvas.toDataURL();
    
    const data = [
      navigator.userAgent,
      navigator.language,
      screen.width + 'x' + screen.height,
      new Date().getTimezoneOffset(),
      canvasData.substring(0, 50)
    ].join('|');
    
    // Simple hash
    let hash = 0;
    for (let i = 0; i < data.length; i++) {
      const char = data.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash;
    }
    return Math.abs(hash).toString(16);
  }
  
  // Initialize CAPTCHA
  async function loadCaptcha() {
    try {
      const response = await fetch('/api/security/captcha', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'login' })
      });
      
      let data;
      try {
        data = await response.json();
      } catch (parseErr) {
        console.log('CAPTCHA response parse error, proceeding without:', parseErr);
        captchaSection.style.display = 'none';
        return;
      }
      
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
      console.log('CAPTCHA not available, proceeding without');
      captchaSection.style.display = 'none';
    }
  }
  
  // Load CAPTCHA on page load
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
      const response = await fetch('/api/security/otp/resend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          verification_id: verificationId.value
        })
      });
      
      let data;
      try {
        data = await response.json();
      } catch (parseErr) {
        console.error('Failed to parse OTP resend response:', parseErr);
        msg.textContent = 'Server error. Please try again.';
        msg.style.color = '#dc3545';
        return;
      }
      
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
      console.error('OTP resend network error:', e);
      msg.textContent = 'Connection error. Please try again.';
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
  
  // Verify OTP
  async function verifyOTP(code) {
    submitBtn.disabled = true;
    msg.textContent = 'Verifying...';
    msg.style.color = '#546e7a';
    
    try {
      const response = await fetch('/api/security/otp/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          verification_id: verificationId.value,
          otp_code: code,
          trust_device: trustDevice.checked,
          device_fingerprint: getDeviceFingerprint()
        })
      });
      
      let data;
      try {
        data = await response.json();
      } catch (parseErr) {
        console.error('Failed to parse OTP verify response:', parseErr, 'status:', response.status);
        msg.textContent = 'Server error during verification. Please try again.';
        msg.style.color = '#dc3545';
        clearOTPInputs();
        submitBtn.disabled = false;
        return;
      }
      
      if (data.success) {
        msg.textContent = 'Verified! Completing login...';
        msg.style.color = '#28a745';
        
        // Complete login
        completeLogin();
      } else {
        msg.textContent = data.message || 'Invalid code';
        msg.style.color = '#dc3545';
        clearOTPInputs();
        submitBtn.disabled = false;
      }
    } catch (e) {
      console.error('OTP verification network error:', e);
      msg.textContent = 'Connection error during verification. Please try again.';
      msg.style.color = '#dc3545';
      submitBtn.disabled = false;
    }
  }
  
  // Complete login after verification
  async function completeLogin() {
    if (!pendingLoginData) {
      msg.textContent = 'Session expired. Please try again.';
      msg.style.color = '#dc3545';
      location.reload();
      return;
    }
    
    // Update steps
    step2.classList.remove('active');
    step2.classList.add('complete');
    step3.classList.add('active');
    
    // Final login call with verified flag
    try {
      const response = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...pendingLoginData,
          verified: true,
          verification_id: verificationId.value
        })
      });
      
      let data;
      try {
        data = await response.json();
      } catch (parseErr) {
        console.error('Failed to parse login response:', parseErr, 'status:', response.status);
        msg.textContent = 'Server error (status ' + response.status + '). Please try again.';
        msg.style.color = '#dc3545';
        return;
      }
      
      if (data.token) {
        handleLoginSuccess(data, pendingLoginData.username);
      } else {
        msg.textContent = 'Login failed: ' + (data.error || 'Unknown error');
        msg.style.color = '#dc3545';
      }
    } catch (e) {
      console.error('Login network error:', e);
      msg.textContent = 'Connection error. Please check your network and try again.';
      msg.style.color = '#dc3545';
    }
  }
  
  // Handle successful login
  function handleLoginSuccess(data, username) {
    msg.textContent = 'Login successful! Redirecting...';
    msg.style.color = '#28a745';
    
    // Store token and username
    localStorage.setItem('phins_token', data.token);
    sessionStorage.setItem('phins_token', data.token);
    sessionStorage.setItem('username', username);
    safeStorageSet(localStorage, 'phins_token', data.token);
    safeStorageSet(sessionStorage, 'phins_token', data.token);
    safeStorageSet(sessionStorage, 'username', username);
    
    // Store session object for ALL users (admin, customer, etc.)
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
    
    console.log('Session stored:', { username, role: data.role });
    
    // Store customer_id in ALL expected locations for data isolation (customers only)
    if (data.customer_id) {
      safeStorageSet(localStorage, 'customer_id', data.customer_id);
      safeStorageSet(sessionStorage, 'customer_id', data.customer_id);
      safeStorageSet(localStorage, 'phins_customer_id', data.customer_id);
      console.log('Customer session stored:', data.customer_id);
    } else if (data.role === 'customer') {
      // Warning: customer logged in but no customer_id returned
      console.warn('Customer login successful but no customer_id in response:', data);
    }
    
    // Store device fingerprint for future logins
    safeStorageSet(localStorage, 'phins_device_fp', getDeviceFingerprint());
    
    // Redirect based on user role
    setTimeout(() => {
      const role = data.role || '';
      
      if (role === 'admin') {
        window.location.href = '/admin-portal.html';
      } else if (role === 'media') {
        window.location.href = '/admin-media.html';
      } else if (role === 'actuary') {
        window.location.href = '/actuary-dashboard.html';
      } else if (role === 'supplier') {
        window.location.href = '/supplier-dashboard.html';
      } else if (role === 'customer') {
        // Direct redirect to dashboard.html for customers (no double redirect)
        window.location.href = '/dashboard.html';
      } else if (role === 'underwriter') {
        window.location.href = '/underwriter-dashboard.html';
      } else if (role === 'claims' || role === 'claims_adjuster') {
        window.location.href = '/claims-adjuster-dashboard.html';
      } else if (role === 'accountant') {
        window.location.href = '/accountant-dashboard.html';
      } else {
        window.location.href = '/dashboard.html';
      }
    }, 500);
  }
  
  // Main form submission
  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    
    // If in OTP step, verify OTP
    if (currentStep === 2) {
      const code = getOTPCode();
      if (code.length === 6) {
        verifyOTP(code);
      } else {
        msg.textContent = 'Please enter the 6-digit code';
        msg.style.color = '#dc3545';
      }
      return;
    }
    
    const username = form.username.value.trim();
    const password = form.password.value;
    const captchaValue = captchaAnswer.value.trim();
    const captchaIdValue = captchaId.value;
    
    // Validate
    if (!username || !password) {
      msg.textContent = 'Please enter username and password';
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
    
    msg.textContent = 'Signing in...';
    msg.style.color = '#546e7a';
    submitBtn.disabled = true;
    
    // Step 1: Verify CAPTCHA if present (separate error handling)
    if (captchaIdValue && captchaValue) {
      try {
        const captchaResponse = await fetch('/api/security/captcha/verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            challenge_id: captchaIdValue,
            response: captchaValue
          })
        });
        
        let captchaResult;
        try {
          captchaResult = await captchaResponse.json();
        } catch (parseErr) {
          console.warn('CAPTCHA verify response parse error, failing CAPTCHA verification:', parseErr);
          captchaResult = {
            success: false,
            message: 'Verification unavailable. Please try again.'
          };
        }
        
        if (!captchaResult.success) {
          msg.textContent = captchaResult.message || 'Verification failed. Please try again.';
          msg.style.color = '#dc3545';
          submitBtn.disabled = false;
          loadCaptcha();
          captchaAnswer.value = '';
          return;
        }
      } catch (captchaErr) {
        console.warn('CAPTCHA verification unavailable, proceeding with login:', captchaErr);
      }
    }
    
    // Step 2: Attempt login (separate error handling)
    try {
      const loginData = {
        username,
        password,
        device_fingerprint: getDeviceFingerprint(),
        user_agent: navigator.userAgent
      };
      
      const response = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(loginData)
      });
      
      let data;
      try {
        data = await response.json();
      } catch (parseErr) {
        console.error('Failed to parse login response:', parseErr, 'status:', response.status);
        msg.textContent = 'Server error (status ' + response.status + '). Please try again later.';
        msg.style.color = '#dc3545';
        submitBtn.disabled = false;
        loadCaptcha();
        return;
      }
      
      if (data.requires_otp) {
        // OTP required - show OTP step
        pendingLoginData = loginData;
        showOTPStep(data.masked_email || '***@***.com', data.verification_id);
        msg.textContent = 'Please enter the verification code sent to your email';
        msg.style.color = '#e65100';
        submitBtn.disabled = false;
        
      } else if (data.token) {
        // Direct login success (trusted device)
        handleLoginSuccess(data, username);
        
      } else {
        // Login failed
        msg.textContent = 'Login failed: ' + (data.error || 'Invalid credentials');
        msg.style.color = '#dc3545';
        submitBtn.disabled = false;
        
        // Reload CAPTCHA on failure
        loadCaptcha();
        captchaAnswer.value = '';
      }
      
    } catch (err) {
      console.error('Login network error:', err);
      msg.textContent = 'Connection error. Please check your network and try again.';
      msg.style.color = '#dc3545';
      submitBtn.disabled = false;
      loadCaptcha();
    }
  });
});
