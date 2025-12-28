// PHINS Billing Dashboard JavaScript
// PCI DSS Compliant Payment Processing

document.addEventListener('DOMContentLoaded', () => {
  const token = localStorage.getItem('phins_token');
  
  if (!token) {
    window.location.href = '/login.html';
    return;
  }

  // Initialize
  loadStats();
  loadFraudAlerts();
  loadRecentTransactions();
  initializePaymentForm();
  populateExpiryYears();

  // Set up form handlers
  document.getElementById('payment-form').addEventListener('submit', handlePayment);
  document.getElementById('lookup-form').addEventListener('submit', handleLookup);
  
  // Set up real-time card validation
  document.getElementById('card_number').addEventListener('input', handleCardInput);
  document.getElementById('card_number').addEventListener('blur', validateCardNumber);
  document.getElementById('expiry_month').addEventListener('change', validateExpiry);
  document.getElementById('expiry_year').addEventListener('change', validateExpiry);
  document.getElementById('cvv').addEventListener('blur', validateCVV);
  document.getElementById('policy_id').addEventListener('blur', lookupPolicyPremium);
});

// Card type patterns for real-time detection
const CARD_PATTERNS = {
  visa: { regex: /^4/, icon: '💳', name: 'Visa', lengths: [13, 16, 19], cvv: 3 },
  mastercard: { regex: /^(5[1-5]|2[2-7])/, icon: '🔵', name: 'Mastercard', lengths: [16], cvv: 3 },
  amex: { regex: /^3[47]/, icon: '💠', name: 'American Express', lengths: [15], cvv: 4 },
  discover: { regex: /^(6011|65|644|645|646|647|648|649)/, icon: '🟠', name: 'Discover', lengths: [16, 19], cvv: 3 },
  diners: { regex: /^3(0[0-5]|6|8)/, icon: '🔷', name: 'Diners Club', lengths: [14, 16], cvv: 3 },
  jcb: { regex: /^35(2[89]|[3-8])/, icon: '🟣', name: 'JCB', lengths: [16, 19], cvv: 3 }
};

function populateExpiryYears() {
  const yearSelect = document.getElementById('expiry_year');
  const currentYear = new Date().getFullYear();
  
  for (let year = currentYear; year <= currentYear + 15; year++) {
    const option = document.createElement('option');
    option.value = year;
    option.textContent = year;
    yearSelect.appendChild(option);
  }
}

function initializePaymentForm() {
  // Clear any cached card data for security
  document.getElementById('card_number').value = '';
  document.getElementById('cvv').value = '';
}

function detectCardType(cardNumber) {
  const cleaned = cardNumber.replace(/\D/g, '');
  
  for (const [type, pattern] of Object.entries(CARD_PATTERNS)) {
    if (pattern.regex.test(cleaned)) {
      return { type, ...pattern };
    }
  }
  return null;
}

function formatCardNumber(value) {
  const cleaned = value.replace(/\D/g, '');
  const groups = cleaned.match(/.{1,4}/g) || [];
  return groups.join(' ').substr(0, 23); // Max 19 digits + 4 spaces
}

function handleCardInput(e) {
  const input = e.target;
  const formatted = formatCardNumber(input.value);
  input.value = formatted;
  
  // Detect card type in real-time
  const cardType = detectCardType(formatted);
  const iconSpan = document.getElementById('card-type-icon');
  const validationDiv = document.getElementById('card-validation');
  
  if (cardType) {
    iconSpan.textContent = cardType.icon;
    iconSpan.title = cardType.name;
    
    const digits = formatted.replace(/\D/g, '').length;
    const expectedLength = cardType.type === 'mastercard' ? 16 : cardType.lengths[cardType.lengths.length - 1];
    
    if (digits < expectedLength) {
      validationDiv.innerHTML = `<span style="color: #666;">${cardType.name} - ${digits}/${expectedLength} digits</span>`;
    } else {
      // Validate when we have enough digits
      validateCardNumber();
    }
    
    // Update CVV max length
    const cvvInput = document.getElementById('cvv');
    cvvInput.maxLength = cardType.cvv;
    cvvInput.placeholder = cardType.cvv === 4 ? '****' : '***';
  } else {
    iconSpan.textContent = '';
    if (formatted.length > 0) {
      validationDiv.innerHTML = '<span style="color: #666;">Enter card number...</span>';
    } else {
      validationDiv.innerHTML = '';
    }
  }
}

function luhnCheck(cardNumber) {
  const digits = cardNumber.replace(/\D/g, '');
  let sum = 0;
  let isEven = false;
  
  for (let i = digits.length - 1; i >= 0; i--) {
    let digit = parseInt(digits[i], 10);
    
    if (isEven) {
      digit *= 2;
      if (digit > 9) digit -= 9;
    }
    
    sum += digit;
    isEven = !isEven;
  }
  
  return sum % 10 === 0;
}

function validateCardNumber() {
  const input = document.getElementById('card_number');
  const validationDiv = document.getElementById('card-validation');
  const cardNumber = input.value.replace(/\D/g, '');
  
  if (cardNumber.length === 0) {
    validationDiv.innerHTML = '';
    input.style.borderColor = '';
    return false;
  }
  
  const cardType = detectCardType(cardNumber);
  
  // Check card type-specific length
  if (!cardType) {
    validationDiv.innerHTML = '<span style="color: #dc3545;">❌ Unknown card type</span>';
    input.style.borderColor = '#dc3545';
    return false;
  }
  
  // Mastercard MUST be exactly 16 digits
  if (cardType.type === 'mastercard' && cardNumber.length !== 16) {
    validationDiv.innerHTML = `<span style="color: #dc3545;">❌ Mastercard must be exactly 16 digits (currently ${cardNumber.length})</span>`;
    input.style.borderColor = '#dc3545';
    return false;
  }
  
  // Other cards - check valid lengths
  if (!cardType.lengths.includes(cardNumber.length)) {
    validationDiv.innerHTML = `<span style="color: #dc3545;">❌ ${cardType.name} must be ${cardType.lengths.join(' or ')} digits</span>`;
    input.style.borderColor = '#dc3545';
    return false;
  }
  
  // Luhn algorithm check
  if (!luhnCheck(cardNumber)) {
    validationDiv.innerHTML = '<span style="color: #dc3545;">❌ Invalid card number (checksum failed)</span>';
    input.style.borderColor = '#dc3545';
    return false;
  }
  
  // All validations passed
  validationDiv.innerHTML = `<span style="color: #28a745;">✅ Valid ${cardType.name} card</span>`;
  input.style.borderColor = '#28a745';
  return true;
}

function validateExpiry() {
  const month = document.getElementById('expiry_month').value;
  const year = document.getElementById('expiry_year').value;
  const validationDiv = document.getElementById('expiry-validation');
  
  if (!month || !year) {
    validationDiv.innerHTML = '';
    return false;
  }
  
  const now = new Date();
  const currentYear = now.getFullYear();
  const currentMonth = now.getMonth() + 1;
  
  const expYear = parseInt(year, 10);
  const expMonth = parseInt(month, 10);
  
  if (expYear < currentYear || (expYear === currentYear && expMonth < currentMonth)) {
    validationDiv.innerHTML = '<span style="color: #dc3545;">❌ Card has expired</span>';
    return false;
  }
  
  // Warning for cards expiring soon
  const monthsUntilExpiry = (expYear - currentYear) * 12 + (expMonth - currentMonth);
  if (monthsUntilExpiry <= 2) {
    validationDiv.innerHTML = `<span style="color: #ffc107;">⚠️ Card expires in ${monthsUntilExpiry} month(s)</span>`;
  } else {
    validationDiv.innerHTML = '<span style="color: #28a745;">✅ Valid expiry date</span>';
  }
  
  return true;
}

function validateCVV() {
  const cvvInput = document.getElementById('cvv');
  const cardNumber = document.getElementById('card_number').value;
  const cardType = detectCardType(cardNumber);
  const cvv = cvvInput.value;
  
  if (!cvv) return false;
  
  const expectedLength = cardType?.cvv || 3;
  
  if (!/^\d+$/.test(cvv)) {
    cvvInput.style.borderColor = '#dc3545';
    return false;
  }
  
  if (cvv.length !== expectedLength) {
    cvvInput.style.borderColor = '#dc3545';
    return false;
  }
  
  cvvInput.style.borderColor = '#28a745';
  return true;
}

async function lookupPolicyPremium() {
  const policyId = document.getElementById('policy_id').value;
  const premiumInfo = document.getElementById('premium-info');
  const premiumDetails = document.getElementById('premium-details');
  const amountInput = document.getElementById('payment_amount');
  
  if (!policyId) {
    premiumInfo.style.display = 'none';
    return;
  }
  
  try {
    const response = await fetch(`/api/policies?id=${encodeURIComponent(policyId)}`, {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`
      }
    });
    
    if (response.ok) {
      const data = await response.json();
      const policy = data.policy || data;
      
      if (policy && policy.monthly_premium) {
        const monthlyPremium = parseFloat(policy.monthly_premium);
        const annualPremium = parseFloat(policy.annual_premium || monthlyPremium * 12);
        
        premiumDetails.innerHTML = `
          <p><strong>Policy Type:</strong> ${policy.type || 'N/A'}</p>
          <p><strong>Coverage:</strong> $${(policy.coverage_amount || 0).toLocaleString()}</p>
          <p><strong>Monthly Premium:</strong> $${monthlyPremium.toFixed(2)}</p>
          <p><strong>Annual Premium:</strong> $${annualPremium.toFixed(2)}</p>
          <p><strong>Status:</strong> ${policy.status || 'N/A'}</p>
        `;
        premiumInfo.style.display = 'block';
        
        // Auto-fill amount based on payment type
        const paymentType = document.getElementById('payment_type').value;
        if (paymentType === 'premium' || paymentType === '') {
          amountInput.value = monthlyPremium.toFixed(2);
          validateAmount();
        }
      }
    }
  } catch (err) {
    console.error('Failed to lookup policy:', err);
  }
}

function validateAmount() {
  const amountInput = document.getElementById('payment_amount');
  const validationDiv = document.getElementById('amount-validation');
  const amount = parseFloat(amountInput.value);
  
  if (isNaN(amount) || amount <= 0) {
    validationDiv.innerHTML = '<span style="color: #dc3545;">❌ Please enter a valid amount</span>';
    return false;
  }
  
  if (amount > 100000) {
    validationDiv.innerHTML = '<span style="color: #ffc107;">⚠️ Large payment - additional verification may be required</span>';
  } else {
    validationDiv.innerHTML = '<span style="color: #28a745;">✅ Amount: $' + amount.toFixed(2) + '</span>';
  }
  
  return true;
}

async function loadStats() {
  try {
    const response = await fetch('/api/billing/stats', {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`
      }
    });
    
    let stats = {
      total_transactions: 0,
      successful_payments: 0,
      failed_payments: 0,
      total_revenue: 0,
      pending_alerts: 0
    };
    
    if (response.ok) {
      const data = await response.json();
      stats = { ...stats, ...data };
    }
    
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
        <div class="stat-value">$${Number(stats.total_revenue).toLocaleString()}</div>
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
  try {
    const response = await fetch('/api/billing/transactions', {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`
      }
    });
    
    let transactions = [];
    
    if (response.ok) {
      const data = await response.json();
      transactions = data.transactions || [];
    }
    
    // Fallback mock data if no transactions
    if (transactions.length === 0) {
      transactions = [
        {
          transaction_id: 'TXN-' + Date.now(),
          customer_id: 'CUST-DEMO',
          amount: 250.00,
          status: 'success',
          timestamp: new Date().toISOString(),
          payment_method: '****-****-****-4242'
        }
      ];
    }
    
    const list = document.getElementById('transaction-list');
    list.innerHTML = transactions.map(txn => `
      <div class="transaction-item">
        <div>
          <strong>${txn.transaction_id}</strong><br>
          <small>${txn.customer_id} • ${txn.payment_method || '****'}</small><br>
          <small>${new Date(txn.timestamp).toLocaleString()}</small>
        </div>
        <div style="text-align: right;">
          <strong>$${Number(txn.amount).toFixed(2)}</strong><br>
          <span class="transaction-status status-${txn.status}">${txn.status.toUpperCase()}</span><br>
          <div class="action-buttons" style="margin-top: 0.5rem;">
            ${txn.status === 'success' ? 
              `<button class="btn-small btn-refund" onclick="refundTransaction('${txn.transaction_id}')">Refund</button>` : 
              ''}
          </div>
        </div>
      </div>
    `).join('');
  } catch (err) {
    console.error('Failed to load transactions:', err);
  }
}

async function handlePayment(e) {
  e.preventDefault();
  
  const resultDiv = document.getElementById('payment-result');
  const submitBtn = document.getElementById('submit-payment');
  
  // Validate all fields
  if (!validateCardNumber()) {
    showResult(resultDiv, 'error', '❌ Please enter a valid card number');
    return;
  }
  
  if (!validateExpiry()) {
    showResult(resultDiv, 'error', '❌ Please enter a valid expiry date');
    return;
  }
  
  if (!validateCVV()) {
    showResult(resultDiv, 'error', '❌ Please enter a valid CVV');
    return;
  }
  
  // Verify checkboxes
  if (!document.getElementById('confirm_amount').checked ||
      !document.getElementById('confirm_cardholder').checked ||
      !document.getElementById('confirm_terms').checked) {
    showResult(resultDiv, 'error', '❌ Please confirm all payment acknowledgments');
    return;
  }
  
  // Disable submit button
  submitBtn.disabled = true;
  submitBtn.textContent = '⏳ Processing...';
  showResult(resultDiv, 'info', '🔄 Validating payment information...');
  
  const form = e.target;
  const formData = new FormData(form);
  
  try {
    // Get card details
    const cardNumber = formData.get('card_number').replace(/\D/g, '');
    const cardType = detectCardType(cardNumber);
    const expiryMonth = formData.get('expiry_month');
    const expiryYear = formData.get('expiry_year');
    
    // First, validate card with server
    const validateResponse = await fetch('/api/billing/validate-card', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        card_number: cardNumber,
        card_type: cardType?.type || 'unknown'
      })
    });
    
    const validateResult = await validateResponse.json();
    
    if (validateResult.valid === false) {
      showResult(resultDiv, 'error', `❌ Card validation failed: ${validateResult.errors?.join(', ') || 'Invalid card'}`);
      submitBtn.disabled = false;
      submitBtn.textContent = '🔐 Process Secure Payment';
      return;
    }
    
    // Add payment method (tokenize card)
    const paymentMethodResponse = await fetch('/api/billing/payment-method', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        customer_id: formData.get('customer_id'),
        card_number: cardNumber,
        cardholder_name: formData.get('cardholder_name'),
        cvv: formData.get('cvv'),
        expiry_month: expiryMonth,
        expiry_year: expiryYear,
        card_type: cardType?.type || 'unknown'
      })
    });
    
    const paymentMethod = await paymentMethodResponse.json();
    
    if (!paymentMethod.success) {
      showResult(resultDiv, 'error', `❌ Payment method error: ${paymentMethod.error}`);
      submitBtn.disabled = false;
      submitBtn.textContent = '🔐 Process Secure Payment';
      return;
    }
    
    // Process payment
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
          type: formData.get('payment_type'),
          cardholder_name: formData.get('cardholder_name')
        }
      })
    });
    
    const chargeResult = await chargeResponse.json();
    
    if (chargeResult.success) {
      showResult(resultDiv, 'success', `
        ✅ <strong>Payment Successful!</strong><br>
        Transaction ID: ${chargeResult.transaction_id}<br>
        Amount: $${parseFloat(formData.get('amount')).toFixed(2)}<br>
        Card: ${paymentMethod.masked_card || '****'}
      `);
      
      // Clear sensitive fields
      document.getElementById('card_number').value = '';
      document.getElementById('cvv').value = '';
      document.getElementById('card-type-icon').textContent = '';
      document.getElementById('card-validation').innerHTML = '';
      
      // Refresh data
      setTimeout(() => {
        loadRecentTransactions();
        loadStats();
      }, 1000);
    } else {
      showResult(resultDiv, 'error', `❌ Payment failed: ${chargeResult.error || 'Transaction declined'}`);
    }
  } catch (err) {
    showResult(resultDiv, 'error', `❌ Error: ${err.message}`);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = '🔐 Process Secure Payment';
  }
}

function showResult(element, type, message) {
  element.style.display = 'block';
  element.innerHTML = message;
  
  const colors = {
    success: { bg: '#d4edda', border: '#28a745', text: '#155724' },
    error: { bg: '#f8d7da', border: '#dc3545', text: '#721c24' },
    info: { bg: '#d1ecf1', border: '#17a2b8', text: '#0c5460' }
  };
  
  const style = colors[type] || colors.info;
  element.style.backgroundColor = style.bg;
  element.style.borderColor = style.border;
  element.style.color = style.text;
  element.style.border = `1px solid ${style.border}`;
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
                  <strong>$${Number(txn.amount).toFixed(2)}</strong><br>
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
  if (!confirm(`Refund transaction ${transactionId}?\n\nThis action cannot be undone.`)) {
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
      alert(`✅ Refund successful!\n\nRefund ID: ${result.refund_id}`);
      loadRecentTransactions();
      loadStats();
    } else {
      alert(`❌ Refund failed: ${result.error}`);
    }
  } catch (err) {
    alert(`❌ Error: ${err.message}`);
  }
}
