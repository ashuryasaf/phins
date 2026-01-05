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
          
          // Store session object for ALL users (admin, customer, etc.)
          const sessionObj = {
            customer_id: data.customer_id || null,
            username: username,
            role: data.role || 'customer',
            name: data.name || username,
            token: data.token,
            login_time: new Date().toISOString()
          };
          localStorage.setItem('session', JSON.stringify(sessionObj));
          sessionStorage.setItem('user_role', data.role || 'customer');
          
          console.log('Session stored:', { username, role: data.role });
          
          // Store customer_id in ALL expected locations for data isolation (customers only)
          if (data.customer_id) {
            // Primary storage locations
            localStorage.setItem('customer_id', data.customer_id);
            sessionStorage.setItem('customer_id', data.customer_id);
            localStorage.setItem('phins_customer_id', data.customer_id);
            
            console.log('Customer session stored:', data.customer_id);
          }
          
          // Redirect based on user role
          setTimeout(() => {
            const role = data.role || '';
            
            if (role === 'admin') {
              window.location.href = '/admin-portal.html';
            } else if (role === 'actuary') {
              window.location.href = '/actuary-dashboard.html';
            } else if (role === 'supplier') {
              window.location.href = '/supplier-dashboard.html';
            } else if (role === 'customer') {
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
