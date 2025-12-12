// PHINS Billing Dashboard JavaScript
document.addEventListener('DOMContentLoaded', () => {
  const token = localStorage.getItem('phins_token');
  
  if (!token) {
    window.location.href = '/login.html';
    return;
  }

  // Load initial data
  loadStats();
  loadFraudAlerts();
  loadRecentTransactions();

  // Set up form handlers
  document.getElementById('payment-form').addEventListener('submit', handlePayment);
  document.getElementById('lookup-form').addEventListener('submit', handleLookup);
});

async function loadStats() {
  try {
    const response = await fetch('/api/billing/fraud-alerts', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({})
    });
    
    // Mock stats for demo
    const stats = {
      total_transactions: 156,
      successful_payments: 142,
      failed_payments: 14,
      total_revenue: 45780.50,
      pending_alerts: 3
    };
    
    const grid = document.getElementById('stats-grid');
    grid.innerHTML = `
      <div class="stat-card">
        <div class="stat-value">${stats.total_transactions}</div>
        <div class="stat-label">Total Transactions</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${stats.successful_payments}</div>
        <div class="stat-label">Successful</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${stats.failed_payments}</div>
        <div class="stat-label">Failed</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">$${stats.total_revenue.toLocaleString()}</div>
        <div class="stat-label">Total Revenue</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${stats.pending_alerts}</div>
        <div class="stat-label">Fraud Alerts</div>
      </div>
    `;
  } catch (err) {
    console.error('Failed to load stats:', err);
  }
}

async function loadFraudAlerts() {
  try {
    const response = await fetch('/api/billing/fraud-alerts', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({})
    });
    
    const data = await response.json();
    const alerts = data.alerts || [];
    
    const container = document.getElementById('fraud-alerts-container');
    
    if (alerts.length === 0) {
      container.innerHTML = '<p class="muted">✅ No active fraud alerts</p>';
      return;
    }
    
    container.innerHTML = alerts.map(alert => `
      <div class="fraud-alert-item alert-${alert.severity || 'medium'}">
        <strong>🚨 ${alert.reason}</strong>
        <p>Customer: ${alert.customer_id}</p>
        <p>Transaction: ${alert.transaction_id}</p>
        <p>Time: ${new Date(alert.timestamp).toLocaleString()}</p>
        <p>Severity: <span style="text-transform: uppercase;">${alert.severity}</span></p>
        <p>Status: ${alert.status}</p>
      </div>
    `).join('');
  } catch (err) {
    console.error('Failed to load fraud alerts:', err);
    document.getElementById('fraud-alerts-container').innerHTML = 
      '<p class="error">Failed to load alerts</p>';
  }
}

async function loadRecentTransactions() {
  // For demo, show mock transactions
  const mockTransactions = [
    {
      transaction_id: 'TXN-20251212-a1b2c3d4',
      customer_id: 'CUST-12345',
      amount: 250.00,
      status: 'success',
      timestamp: new Date().toISOString(),
      payment_method: '****-****-****-4242'
    },
    {
      transaction_id: 'TXN-20251212-e5f6g7h8',
      customer_id: 'CUST-67890',
      amount: 180.00,
      status: 'success',
      timestamp: new Date(Date.now() - 3600000).toISOString(),
      payment_method: '****-****-****-1234'
    },
    {
      transaction_id: 'TXN-20251212-i9j0k1l2',
      customer_id: 'CUST-11111',
      amount: 420.00,
      status: 'failed',
      timestamp: new Date(Date.now() - 7200000).toISOString(),
      payment_method: '****-****-****-5678'
    }
  ];
  
  const list = document.getElementById('transaction-list');
  list.innerHTML = mockTransactions.map(txn => `
    <div class="transaction-item">
      <div>
        <strong>${txn.transaction_id}</strong><br>
        <small>${txn.customer_id} • ${txn.payment_method}</small><br>
        <small>${new Date(txn.timestamp).toLocaleString()}</small>
      </div>
      <div style="text-align: right;">
        <strong>$${txn.amount.toFixed(2)}</strong><br>
        <span class="transaction-status status-${txn.status}">${txn.status.toUpperCase()}</span><br>
        <div class="action-buttons" style="margin-top: 0.5rem;">
          ${txn.status === 'success' ? 
            `<button class="btn-small btn-refund" onclick="refundTransaction('${txn.transaction_id}')">Refund</button>` : 
            ''}
        </div>
      </div>
    </div>
  `).join('');
}

async function handlePayment(e) {
  e.preventDefault();
  const form = e.target;
  const formData = new FormData(form);
  const result = document.getElementById('payment-result');
  
  result.textContent = 'Processing payment...';
  result.className = 'muted';
  
  try {
    // Parse expiry
    const expiry = formData.get('expiry').split('/');
    const expiry_month = expiry[0];
    const expiry_year = expiry[1];
    
    // First, add payment method
    const paymentMethodResponse = await fetch('/api/billing/payment-method', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        customer_id: formData.get('customer_id'),
        card_number: formData.get('card_number'),
        cvv: formData.get('cvv'),
        expiry_month: expiry_month,
        expiry_year: expiry_year,
        card_type: 'visa'
      })
    });
    
    const paymentMethod = await paymentMethodResponse.json();
    
    if (!paymentMethod.success) {
      result.textContent = `❌ Payment method error: ${paymentMethod.error}`;
      result.style.color = '#dc3545';
      return;
    }
    
    // Now process payment
    const chargeResponse = await fetch('/api/billing/charge', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        customer_id: formData.get('customer_id'),
        policy_id: formData.get('policy_id'),
        amount: parseFloat(formData.get('amount')),
        payment_token: paymentMethod.token,
        metadata: {
          type: formData.get('payment_type')
        }
      })
    });
    
    const chargeResult = await chargeResponse.json();
    
    if (chargeResult.success) {
      result.textContent = `✅ Payment successful! Transaction ID: ${chargeResult.transaction_id}`;
      result.style.color = '#28a745';
      form.reset();
      
      // Reload transactions
      setTimeout(() => {
        loadRecentTransactions();
        loadStats();
      }, 1000);
    } else {
      result.textContent = `❌ Payment failed: ${chargeResult.error}`;
      result.style.color = '#dc3545';
    }
  } catch (err) {
    result.textContent = `❌ Error: ${err.message}`;
    result.style.color = '#dc3545';
  }
}

async function handleLookup(e) {
  e.preventDefault();
  const form = e.target;
  const formData = new FormData(form);
  const customerId = formData.get('lookup_customer_id');
  const resultDiv = document.getElementById('statement-result');
  
  resultDiv.innerHTML = '<p class="muted">Loading statement...</p>';
  
  try {
    const response = await fetch('/api/billing/statement', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ customer_id: customerId })
    });
    
    const statement = await response.json();
    
    if (statement.error) {
      resultDiv.innerHTML = `<p class="error">${statement.error}</p>`;
      return;
    }
    
    const summary = statement.summary || {};
    const transactions = statement.transactions || [];
    
    resultDiv.innerHTML = `
      <div style="margin-top: 1rem;">
        <h3>Billing Statement: ${customerId}</h3>
        <div class="stats-grid">
          <div class="stat-card">
            <div class="stat-value">${summary.total_transactions || 0}</div>
            <div class="stat-label">Total Transactions</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">${summary.successful_payments || 0}</div>
            <div class="stat-label">Successful</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">$${(summary.total_amount_paid || 0).toFixed(2)}</div>
            <div class="stat-label">Total Paid</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">${summary.failed_payments || 0}</div>
            <div class="stat-label">Failed</div>
          </div>
        </div>
        
        <h4>Transaction History</h4>
        <div class="transaction-list">
          ${transactions.length > 0 ? 
            transactions.map(txn => `
              <div class="transaction-item">
                <div>
                  <strong>${txn.transaction_id}</strong><br>
                  <small>${new Date(txn.timestamp).toLocaleString()}</small>
                </div>
                <div style="text-align: right;">
                  <strong>$${txn.amount.toFixed(2)}</strong><br>
                  <span class="transaction-status status-${txn.status}">${txn.status}</span>
                </div>
              </div>
            `).join('') :
            '<p class="muted">No transactions found</p>'
          }
        </div>
      </div>
    `;
  } catch (err) {
    resultDiv.innerHTML = `<p class="error">Failed to load statement: ${err.message}</p>`;
  }
}

async function refundTransaction(transactionId) {
  if (!confirm(`Refund transaction ${transactionId}?`)) {
    return;
  }
  
  try {
    const response = await fetch('/api/billing/refund', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        transaction_id: transactionId,
        reason: 'Admin requested refund'
      })
    });
    
    const result = await response.json();
    
    if (result.success) {
      alert(`✅ Refund successful! Refund ID: ${result.refund_id}`);
      loadRecentTransactions();
      loadStats();
    } else {
      alert(`❌ Refund failed: ${result.error}`);
    }
  } catch (err) {
    alert(`❌ Error: ${err.message}`);
  }
}
