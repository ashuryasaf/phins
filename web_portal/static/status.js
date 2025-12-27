document.addEventListener('DOMContentLoaded', () => {
  const statusSummary = document.getElementById('status-summary');
  const statusDetails = document.getElementById('status-details');
  const policyList = document.getElementById('policy-list');
  const uwList = document.getElementById('uw-list');
  const billingSection = document.getElementById('billing-section');
  const billingSummary = document.getElementById('billing-summary');
  const billingList = document.getElementById('billing-list');

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
        const statusBadge = p.status === 'active' ? '✅ Active' : p.status;
        li.innerHTML = `<strong>${p.id}</strong> – ${p.type} – <span style="color: ${p.status === 'active' ? 'green' : 'inherit'}">${statusBadge}</span>`;
        policyList.appendChild(li);
      });

      // Underwriting apps
      uwList.innerHTML = '';
      (data.underwriting_applications || []).forEach(u => {
        const li = document.createElement('li');
        const statusEmoji = u.status === 'approved' ? '✅' : u.status === 'rejected' ? '❌' : '⏳';
        li.innerHTML = `<strong>${u.id}</strong> – ${statusEmoji} ${u.status} – risk: ${u.risk_assessment}`;
        uwList.appendChild(li);
      });

      // Billing section (only show if there are active policies or bills)
      const bills = data.billing || [];
      const summary = data.billing_summary || {};
      const hasActivePolicies = (data.policies || []).some(p => p.status === 'active');
      
      if (bills.length > 0 || hasActivePolicies) {
        billingSection.style.display = 'block';
        
        // Summary
        billingSummary.innerHTML = `
          <div style="background: #f8f9fa; padding: 1rem; border-radius: 8px; margin-bottom: 0.5rem;">
            <div style="font-size: 0.9rem; color: #666;">Total Outstanding</div>
            <div style="font-size: 1.5rem; font-weight: bold; color: ${summary.total_outstanding > 0 ? '#dc3545' : '#28a745'}">
              $${(summary.total_outstanding || 0).toFixed(2)}
            </div>
          </div>
          <div style="background: #f8f9fa; padding: 1rem; border-radius: 8px; margin-bottom: 0.5rem;">
            <div style="font-size: 0.9rem; color: #666;">Outstanding Bills</div>
            <div style="font-size: 1.5rem; font-weight: bold;">${summary.outstanding_count || 0}</div>
          </div>
          ${summary.next_due ? `
          <div style="background: #f8f9fa; padding: 1rem; border-radius: 8px; margin-bottom: 0.5rem;">
            <div style="font-size: 0.9rem; color: #666;">Next Due Date</div>
            <div style="font-size: 1rem; font-weight: bold;">${new Date(summary.next_due).toLocaleDateString()}</div>
          </div>
          ` : ''}
        `;
        
        // Bill list
        billingList.innerHTML = '';
        const outstandingBills = bills.filter(b => b.status === 'outstanding' || b.status === 'partial');
        if (outstandingBills.length === 0) {
          const li = document.createElement('li');
          li.textContent = '✅ No outstanding bills';
          li.style.color = '#28a745';
          billingList.appendChild(li);
        } else {
          outstandingBills.forEach(b => {
            const li = document.createElement('li');
            const amount = b.amount || b.amount_due || 0;
            const dueDate = b.due_date ? new Date(b.due_date).toLocaleDateString() : 'N/A';
            li.innerHTML = `
              <strong>${b.id || b.bill_id}</strong> – 
              Policy: ${b.policy_id} – 
              Amount: <strong>$${amount.toFixed(2)}</strong> – 
              Due: ${dueDate} – 
              <span style="color: ${b.status === 'outstanding' ? '#dc3545' : '#ffc107'}">${b.status}</span>
            `;
            billingList.appendChild(li);
          });
        }
      }
    })
    .catch(err => {
      statusSummary.textContent = 'Failed to load status.';
      statusSummary.className = 'error';
      console.error('Error loading status:', err);
    });
});
