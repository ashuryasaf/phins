document.addEventListener('DOMContentLoaded', function () {
  const form = document.getElementById('login-form');
  const msg = document.getElementById('login-msg');

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    const username = form.username.value;
    const password = form.password.value;
    msg.textContent = 'Signing in...';
    msg.className = 'muted';
    
    fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    })
      .then(r => r.json())
      .then(data => {
        if (data.token) {
          msg.textContent = 'Login successful! Redirecting...';
          msg.style.color = '#28a745';
          
          // Store token and username
          localStorage.setItem('phins_token', data.token);
          sessionStorage.setItem('username', username);
          if (data.customer_id) {
            localStorage.setItem('phins_customer_id', data.customer_id);
          }
          
          // Redirect based on user role
          setTimeout(() => {
            const role = data.role || '';
            
            if (role === 'admin') {
              window.location.href = '/admin-portal.html';
            } else if (role === 'customer') {
              // Primary customer portal page
              window.location.href = '/client-portal.html';
            } else if (role === 'underwriter') {
              window.location.href = '/underwriter-dashboard.html';
            } else if (role === 'claims' || role === 'claims_adjuster') {
              window.location.href = '/claims-adjuster-dashboard.html';
            } else if (role === 'accountant') {
              window.location.href = '/accountant-dashboard.html';
            } else {
              // Default fallback
              window.location.href = '/dashboard.html';
            }
          }, 500);
        } else {
          msg.textContent = 'Login failed: ' + (data.error || 'Invalid credentials');
          msg.style.color = '#dc3545';
        }
      })
      .catch(err => {
        msg.textContent = 'Login error. Please try again.';
        msg.style.color = '#dc3545';
      });
  });
});
