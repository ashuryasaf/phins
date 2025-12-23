document.addEventListener('DOMContentLoaded', () => {
  const statusSummary = document.getElementById('status-summary');
  const statusDetails = document.getElementById('status-details');
  const policyList = document.getElementById('policy-list');
  const uwList = document.getElementById('uw-list');

  const token = localStorage.getItem('phins_token');

  if (!token) {
    statusSummary.textContent = 'Please log in to view your status.';
    statusSummary.className = 'warn';
    return;
  }

  fetch(`/api/customer/status`, {
    headers: { 'Authorization': `Bearer ${token}` }
  })
    .then(r => r.json())
    .then(data => {
      const overall = data.overall_status || 'unknown';
      statusSummary.textContent = `Overall status: ${overall}`;
      statusSummary.className = overall === 'active_policy' ? 'success' : 'muted';

      // Customer details
      const cust = data.customer || {};
      statusDetails.innerHTML = `
        <div class="card">
          <strong>Name:</strong> ${cust.name || ''}<br>
          <strong>Email:</strong> ${cust.email || ''}<br>
          <strong>ID:</strong> ${cust.id || ''}
        </div>
      `;

      // Policies
      policyList.innerHTML = '';
      (data.policies || []).forEach(p => {
        const li = document.createElement('li');
        li.textContent = `${p.id} – ${p.type} – ${p.status}`;
        policyList.appendChild(li);
      });

      // Underwriting apps
      uwList.innerHTML = '';
      (data.underwriting_applications || []).forEach(u => {
        const li = document.createElement('li');
        li.textContent = `${u.id} – ${u.status} – risk: ${u.risk_assessment}`;
        uwList.appendChild(li);
      });
    })
    .catch(err => {
      statusSummary.textContent = 'Failed to load status.';
      statusSummary.className = 'error';
    });
});
