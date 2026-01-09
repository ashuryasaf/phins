document.addEventListener('DOMContentLoaded', function () {
  const form = document.getElementById('register-form');
  const msg = document.getElementById('register-msg');
  const passwordInput = document.getElementById('password');
  const confirmPasswordInput = document.getElementById('confirm-password');
  const strengthBar = document.getElementById('strength-bar');
  const submitBtn = document.getElementById('submit-btn');
  const invitationCodeInput = document.getElementById('invitation-code');
  const codeValidation = document.getElementById('code-validation');

  let isCodeValid = false;

  // ========== INVITATION CODE VALIDATION ==========
  let codeValidationTimeout = null;
  
  invitationCodeInput.addEventListener('input', function() {
    const code = invitationCodeInput.value.trim().toUpperCase();
    invitationCodeInput.value = code; // Force uppercase
    
    // Clear previous timeout
    if (codeValidationTimeout) {
      clearTimeout(codeValidationTimeout);
    }
    
    if (code.length < 10) {
      codeValidation.textContent = '';
      isCodeValid = false;
      updateSubmitButton();
      return;
    }
    
    // Debounce validation
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

    // Update requirement indicators
    document.getElementById('req-length').className = requirements.length ? 'requirement met' : 'requirement';
    document.getElementById('req-length').textContent = requirements.length ? '✓ At least 8 characters' : '✗ At least 8 characters';
    
    document.getElementById('req-uppercase').className = requirements.uppercase ? 'requirement met' : 'requirement';
    document.getElementById('req-uppercase').textContent = requirements.uppercase ? '✓ One uppercase letter' : '✗ One uppercase letter';
    
    document.getElementById('req-lowercase').className = requirements.lowercase ? 'requirement met' : 'requirement';
    document.getElementById('req-lowercase').textContent = requirements.lowercase ? '✓ One lowercase letter' : '✗ One lowercase letter';
    
    document.getElementById('req-number').className = requirements.number ? 'requirement met' : 'requirement';
    document.getElementById('req-number').textContent = requirements.number ? '✓ One number' : '✗ One number';

    // Update strength bar
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
    
    // Submit only enabled if code is valid AND password requirements are met
    submitBtn.disabled = !isCodeValid || !allPasswordMet;
  }

  // ========== FORM SUBMISSION ==========
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    
    const invitationCode = form.invitation_code.value.trim().toUpperCase();
    const fullName = form.full_name.value.trim();
    const email = form.email.value.trim();
    const phone = form.phone.value.trim();
    const dob = form.dob.value;
    const password = form.password.value;
    const confirmPassword = form.confirm_password.value;

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

    msg.textContent = 'Creating account...';
    msg.style.color = '#856404';
    submitBtn.disabled = true;
    
    fetch('/api/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        invitation_code: invitationCode,
        name: fullName,
        email: email,
        phone: phone,
        dob: dob,
        password: password
      })
    })
      .then(r => r.json())
      .then(data => {
        if (data.success || data.customer_id) {
          msg.innerHTML = '✅ Account created successfully! Redirecting to login...';
          msg.style.color = '#28a745';
          
          // Show success message
          codeValidation.innerHTML = '🎉 Welcome to PHINS!';
          
          setTimeout(() => {
            window.location.href = '/login.html';
          }, 2000);
        } else {
          let errorMsg = data.error || 'Unknown error';
          if (data.code === 'INVITATION_REQUIRED') {
            errorMsg = 'Invitation code is required for registration';
          } else if (data.code === 'INVALID_CODE') {
            errorMsg = 'The invitation code is not valid';
          } else if (data.code === 'CODE_EXPIRED') {
            errorMsg = 'The invitation code has expired';
          } else if (data.code === 'CODE_USED') {
            errorMsg = 'The invitation code has already been used';
          }
          
          msg.textContent = 'Registration failed: ' + errorMsg;
          msg.style.color = '#dc3545';
          submitBtn.disabled = false;
        }
      })
      .catch(err => {
        msg.textContent = 'Registration error. Please try again.';
        msg.style.color = '#dc3545';
        submitBtn.disabled = false;
      });
  });

  // Initialize button state
  updateSubmitButton();
});
