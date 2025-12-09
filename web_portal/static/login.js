document.addEventListener('DOMContentLoaded', function () {
  const form = document.getElementById('login-form');
  const msg = document.getElementById('login-msg');

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    const username = form.username.value;
    const password = form.password.value;
    msg.textContent = 'Signing in...';
    fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    })
      .then(r => r.json())
      .then(data => {
        if (data.token) {
          msg.textContent = 'Login successful!';
          // Store token and redirect (demo)
          localStorage.setItem('phins_token', data.token);
          window.location.href = '/index.html';
        } else {
          msg.textContent = 'Login failed: ' + (data.error || 'Invalid credentials');
        }
      })
      .catch(err => {
        msg.textContent = 'Login error.';
      });
  });
});
