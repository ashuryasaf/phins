document.addEventListener('DOMContentLoaded', function () {
  const form = document.getElementById('login-form');
  const msg = document.getElementById('login-msg');

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    const username = String(form.username.value || '').trim();
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
          
          // Store token(s) and identity
          const role = String(data.role || '').toLowerCase();
          // Clear any previous tokens to avoid cross-role confusion in the same browser
          localStorage.removeItem('phins_token');
          localStorage.removeItem('phins_admin_token');
          localStorage.setItem('phins_role', role);
          localStorage.setItem('phins_username', username);
          sessionStorage.setItem('username', username);
          if (data.customer_id) localStorage.setItem('phins_customer_id', data.customer_id);

          // Separate customer token from staff/admin token
          const isStaff = ['admin', 'underwriter', 'claims', 'claims_adjuster', 'accountant'].includes(role);
          if (isStaff) {
            localStorage.setItem('phins_admin_token', data.token);
          } else {
            localStorage.setItem('phins_token', data.token);
          }
          
          // Redirect based on user role
          setTimeout(() => {
            const role = String(data.role || '').toLowerCase();
            
            // Legacy routes retained for backward compatibility / older tests:
            // - /admin-portal.html
            // - /client-portal.html
            if (role === 'admin') {
              window.location.href = '/admin.html'; // legacy: '/admin-portal.html'
            } else if (role === 'customer') {
              window.location.href = '/dashboard.html'; // legacy: '/client-portal.html'
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
