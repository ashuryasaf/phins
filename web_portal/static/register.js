document.addEventListener('DOMContentLoaded', function () {
  const form = document.getElementById('register-form');
  const msg = document.getElementById('register-msg');
  const passwordInput = document.getElementById('password');
  const confirmPasswordInput = document.getElementById('confirm-password');
  const strengthBar = document.getElementById('strength-bar');
  const submitBtn = document.getElementById('submit-btn');

  // Password strength checker
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
    document.getElementById('req-uppercase').className = requirements.uppercase ? 'requirement met' : 'requirement';
    document.getElementById('req-lowercase').className = requirements.lowercase ? 'requirement met' : 'requirement';
    document.getElementById('req-number').className = requirements.number ? 'requirement met' : 'requirement';

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

    // Enable/disable submit button
    const allMet = Object.values(requirements).every(Boolean);
    submitBtn.disabled = !allMet;
  });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    
    const fullName = form.full_name.value.trim();
    const email = form.email.value.trim();
    const phone = form.phone.value.trim();
    const dob = form.dob.value;
    const password = form.password.value;
    const confirmPassword = form.confirm_password.value;

    // Validation
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
    msg.className = 'muted';
    submitBtn.disabled = true;
    
    fetch('/api/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
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
          msg.textContent = 'Account created successfully! Redirecting to login...';
          msg.style.color = '#28a745';
          
          setTimeout(() => {
            window.location.href = '/login.html';
          }, 2000);
        } else {
          msg.textContent = 'Registration failed: ' + (data.error || 'Unknown error');
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
});
