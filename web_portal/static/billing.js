// PHINS Billing Dashboard JavaScript
// PCI DSS Compliant Payment Processing with Multi-Gateway Support

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
  loadPaymentMethods(); // Load available payment gateways
  loadLedger(); // Load transaction ledger
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

// Current selected payment method
let selectedPaymentMethod = 'credit_card';
let availablePaymentMethods = [];

// Billing customer/policy data
let billingCustomers = [];
let billingPolicies = [];
let selectedBillingCustomer = null;
let selectedBillingPolicy = null;
let selectedBillingApplication = null;

// Load available payment methods from gateway
async function loadPaymentMethods() {
  try {
    const response = await fetch('/api/payment/methods', {
      headers: { 'Authorization': `Bearer ${localStorage.getItem('phins_token')}` }
    });
    
    if (response.ok) {
      const data = await response.json();
      availablePaymentMethods = data.methods || [];
      displayPaymentMethods(availablePaymentMethods);
    }
  } catch (err) {
    console.error('Failed to load payment methods:', err);
    // Display default methods on error
    displayPaymentMethods(getDefaultPaymentMethods());
  }
}

function getDefaultPaymentMethods() {
  return [
    { id: 'credit_card', name: 'Credit Card', gateway: 'stripe', enabled: true },
    { id: 'paypal', name: 'PayPal', gateway: 'paypal', enabled: true },
    { id: 'apple_pay', name: 'Apple Pay', gateway: 'stripe', enabled: true },
    { id: 'google_pay', name: 'Google Pay', gateway: 'stripe', enabled: true },
    { id: 'bitcoin', name: 'Bitcoin', gateway: 'crypto', enabled: true },
    { id: 'ethereum', name: 'Ethereum', gateway: 'crypto', enabled: true }
  ];
}

function displayPaymentMethods(methods) {
  const container = document.getElementById('payment-methods-grid');
  if (!container) return;
  
  const icons = {
    credit_card: '💳',
    paypal: '🅿️',
    apple_pay: '🍎',
    google_pay: '🔵',
    bitcoin: '₿',
    ethereum: '⟠',
    usdc: '💵',
    bank_transfer: '🏦',
    debit_card: '💳'
  };
  
  // Compact card design for payment methods
  container.innerHTML = methods.map(method => `
    <div class="payment-method-card ${method.id === selectedPaymentMethod ? 'selected' : ''}" 
         onclick="selectPaymentMethod('${method.id}')" 
         data-method="${method.id}"
         style="padding: 8px; min-height: auto;">
      <div class="icon" style="font-size: 1.5rem; margin-bottom: 4px;">${icons[method.id] || '💰'}</div>
      <div class="name" style="font-size: 0.8rem;">${method.name}</div>
      <div class="badge test" style="font-size: 0.6rem; padding: 1px 4px; margin-top: 2px;">${method.gateway === 'crypto' ? 'CRYPTO' : 'TEST'}</div>
    </div>
  `).join('');
  
  // Update connection status
  const statusEl = document.getElementById('payment-methods-status');
  if (statusEl && methods.length > 0) {
    statusEl.textContent = `✓ ${methods.length} Methods`;
    statusEl.style.background = '#d1fae5';
    statusEl.style.color = '#065f46';
  }
}

function selectPaymentMethod(methodId) {
  selectedPaymentMethod = methodId;
  
  // Update UI
  document.querySelectorAll('.payment-method-card').forEach(card => {
    card.classList.toggle('selected', card.dataset.method === methodId);
  });
  
  // Show test credentials for selected method
  showTestCredentials(methodId);
  
  // Update payment form visibility
  updatePaymentFormForMethod(methodId);
}

function showTestCredentials(methodId) {
  const container = document.getElementById('test-credentials');
  const content = document.getElementById('test-credentials-content');
  
  const credentials = {
    credit_card: `
      <table style="width: 100%; border-collapse: collapse; margin-top: 0.5rem;">
        <thead>
          <tr style="background: #f5f5f5;">
            <th style="padding: 0.5rem; text-align: left;">Card Number</th>
            <th style="padding: 0.5rem; text-align: left;">Brand</th>
            <th style="padding: 0.5rem; text-align: left;">Result</th>
          </tr>
        </thead>
        <tbody>
          <tr><td style="padding: 0.5rem; font-family: monospace;">4242 4242 4242 4242</td><td>Visa</td><td style="color: green;">✅ Success</td></tr>
          <tr><td style="padding: 0.5rem; font-family: monospace;">5555 5555 5555 4444</td><td>Mastercard</td><td style="color: green;">✅ Success</td></tr>
          <tr><td style="padding: 0.5rem; font-family: monospace;">3782 8224 6310 005</td><td>Amex</td><td style="color: green;">✅ Success</td></tr>
          <tr><td style="padding: 0.5rem; font-family: monospace;">4000 0000 0000 0002</td><td>Visa</td><td style="color: red;">❌ Declined</td></tr>
          <tr><td style="padding: 0.5rem; font-family: monospace;">4000 0000 0000 9995</td><td>Visa</td><td style="color: red;">❌ Insufficient Funds</td></tr>
        </tbody>
      </table>
      <p style="margin-top: 0.5rem; color: #666;"><strong>Expiry:</strong> Any future date (e.g., 12/34) | <strong>CVC:</strong> Any 3 digits (4 for Amex)</p>
    `,
    paypal: `
      <div style="background: #f5f5f5; padding: 1rem; border-radius: 4px;">
        <p><strong>🅿️ PayPal Sandbox Mode</strong></p>
        <p>1. Click "Pay with PayPal" button</p>
        <p>2. You'll be redirected to PayPal Sandbox</p>
        <p>3. Create/use a sandbox buyer account at <a href="https://developer.paypal.com/tools/sandbox/" target="_blank">developer.paypal.com</a></p>
        <p>4. Complete the payment and return to PHINS</p>
        <p style="margin-top: 0.5rem; color: #666;"><em>No real money is transferred in sandbox mode.</em></p>
      </div>
    `,
    apple_pay: `
      <div style="background: #f5f5f5; padding: 1rem; border-radius: 4px;">
        <p><strong>🍎 Apple Pay Test Mode</strong></p>
        <p>Requirements:</p>
        <ul style="margin: 0.5rem 0; padding-left: 1.5rem;">
          <li>Safari browser on macOS or iOS</li>
          <li>Apple Pay configured on device</li>
          <li>Test cards added to Apple Wallet</li>
        </ul>
        <p style="color: #666;"><em>In test mode, simulated transactions are processed.</em></p>
      </div>
    `,
    google_pay: `
      <div style="background: #f5f5f5; padding: 1rem; border-radius: 4px;">
        <p><strong>🔵 Google Pay Test Mode</strong></p>
        <p>Requirements:</p>
        <ul style="margin: 0.5rem 0; padding-left: 1.5rem;">
          <li>Chrome browser</li>
          <li>Google Pay configured</li>
          <li>Google account signed in</li>
        </ul>
        <p style="color: #666;"><em>In test mode, simulated transactions are processed.</em></p>
      </div>
    `,
    bitcoin: `
      <div style="background: #f5f5f5; padding: 1rem; border-radius: 4px;">
        <p><strong>₿ Bitcoin Testnet Mode</strong></p>
        <p>1. Get testnet BTC from a faucet: <a href="https://coinfaucet.eu/en/btc-testnet/" target="_blank">Bitcoin Testnet Faucet</a></p>
        <p>2. Send to the provided testnet address</p>
        <p>3. Wait for confirmation (simulated in ~30 seconds in test mode)</p>
        <p style="margin-top: 0.5rem; color: #666;"><strong>Network:</strong> Bitcoin Testnet | <strong>No real BTC required</strong></p>
      </div>
    `,
    ethereum: `
      <div style="background: #f5f5f5; padding: 1rem; border-radius: 4px;">
        <p><strong>⟠ Ethereum Testnet Mode</strong></p>
        <p>1. Get testnet ETH from a faucet: <a href="https://goerlifaucet.com/" target="_blank">Goerli Faucet</a></p>
        <p>2. Send to the provided testnet address</p>
        <p>3. Wait for confirmation</p>
        <p style="margin-top: 0.5rem; color: #666;"><strong>Network:</strong> Goerli Testnet | <strong>No real ETH required</strong></p>
      </div>
    `,
    usdc: `
      <div style="background: #f5f5f5; padding: 1rem; border-radius: 4px;">
        <p><strong>💵 USDC Testnet Mode</strong></p>
        <p>1. Use Goerli testnet USDC</p>
        <p>2. Send to the provided testnet address</p>
        <p>3. 1 USDC = 1 USD (stablecoin)</p>
        <p style="margin-top: 0.5rem; color: #666;"><strong>Network:</strong> Goerli Testnet | <strong>No real USDC required</strong></p>
      </div>
    `
  };
  
  if (credentials[methodId]) {
    content.innerHTML = credentials[methodId];
    container.style.display = 'block';
  } else {
    container.style.display = 'none';
  }
}

function updatePaymentFormForMethod(methodId) {
  // Show/hide card fields based on payment method
  const cardFieldset = document.querySelector('fieldset:has(#card_number)');
  if (cardFieldset) {
    cardFieldset.style.display = ['credit_card', 'debit_card'].includes(methodId) ? 'block' : 'none';
  }
  
  // Update submit button text
  const submitBtn = document.getElementById('submit-payment');
  if (submitBtn) {
    const buttonTexts = {
      credit_card: '🔐 Process Secure Payment',
      paypal: '🅿️ Pay with PayPal',
      apple_pay: '🍎 Pay with Apple Pay',
      google_pay: '🔵 Pay with Google Pay',
      bitcoin: '₿ Generate Bitcoin Invoice',
      ethereum: '⟠ Generate Ethereum Invoice',
      usdc: '💵 Generate USDC Invoice'
    };
    submitBtn.textContent = buttonTexts[methodId] || '💰 Process Payment';
  }
}

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
    // Fetch billing stats from pipeline
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
      pending_alerts: 0,
      collection_rate: 0,
      avg_payment_time: 0
    };
    
    if (response.ok) {
      const data = await response.json();
      stats = { ...stats, ...data };
    }
    
    // Try to get additional stats from financial service
    try {
      const finResponse = await fetch('/api/financial/dashboard-summary?type=billing', {
        headers: { 'Authorization': `Bearer ${localStorage.getItem('phins_token')}` }
      });
      if (finResponse.ok) {
        const finData = await finResponse.json();
        stats.total_revenue = finData.total_revenue || stats.total_revenue;
        stats.collection_rate = finData.collection_rate || stats.collection_rate || 
          (stats.total_revenue > 0 ? Math.round((stats.successful_payments / Math.max(stats.total_transactions, 1)) * 100) : 0);
      }
    } catch (e) {
      // Calculate collection rate from available data
      stats.collection_rate = stats.total_transactions > 0 
        ? Math.round((stats.successful_payments / stats.total_transactions) * 100) 
        : 0;
    }
    
    const grid = document.getElementById('stats-grid');
    if (!grid) return;
    
    // Compact stat card design with gradients
    grid.innerHTML = `
      <div class="stat-card compact" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
        <div class="stat-value">${stats.total_transactions}</div>
        <div class="stat-label">Transactions</div>
      </div>
      <div class="stat-card compact" style="background: linear-gradient(135deg, #28a745 0%, #20c997 100%);">
        <div class="stat-value">${stats.successful_payments}</div>
        <div class="stat-label">Successful</div>
      </div>
      <div class="stat-card compact" style="background: linear-gradient(135deg, #dc3545 0%, #c82333 100%);">
        <div class="stat-value">${stats.failed_payments}</div>
        <div class="stat-label">Failed</div>
      </div>
      <div class="stat-card compact" style="background: linear-gradient(135deg, #17a2b8 0%, #138496 100%);">
        <div class="stat-value">$${Number(stats.total_revenue).toLocaleString()}</div>
        <div class="stat-label">Revenue</div>
      </div>
      <div class="stat-card compact" style="background: linear-gradient(135deg, ${stats.collection_rate >= 90 ? '#28a745' : stats.collection_rate >= 70 ? '#ffc107' : '#dc3545'} 0%, ${stats.collection_rate >= 90 ? '#20c997' : stats.collection_rate >= 70 ? '#e0a800' : '#c82333'} 100%);">
        <div class="stat-value">${stats.collection_rate}%</div>
        <div class="stat-label">Collection Rate</div>
      </div>
      <div class="stat-card compact" style="background: linear-gradient(135deg, ${stats.pending_alerts > 0 ? '#dc3545' : '#6c757d'} 0%, ${stats.pending_alerts > 0 ? '#c82333' : '#5a6268'} 100%);">
        <div class="stat-value">${stats.pending_alerts}</div>
        <div class="stat-label">Alerts</div>
      </div>
    `;
    
    // Show pipeline validation status
    const pipelineStatus = document.getElementById('pipeline-validation-status');
    if (pipelineStatus) {
      pipelineStatus.style.display = 'block';
    }
  } catch (err) {
    console.error('Failed to load stats:', err);
    const grid = document.getElementById('stats-grid');
    if (grid) {
      grid.innerHTML = `<p class="muted" style="grid-column: 1/-1; text-align: center; color: #dc3545;">⚠️ Failed to load stats from pipeline</p>`;
    }
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
    
    const list = document.getElementById('transaction-list');
    
    if (transactions.length === 0) {
      list.innerHTML = '<p class="muted">No recent transactions</p>';
      return;
    }
    
    // Store for export functionality
    window.lastTransactions = transactions;
    
    list.innerHTML = transactions.map(txn => {
      // Format payment method with icon and masking
      const pmDisplay = formatPaymentMethodDisplay(txn);
      
      // Format timestamp
      const timestamp = txn.timestamp || txn.date;
      const formattedDate = timestamp ? new Date(timestamp).toLocaleString() : 'N/A';
      
      // Determine status class and display
      const statusClass = getStatusClass(txn.status);
      const statusDisplay = (txn.status || 'pending').toUpperCase();
      
      // Format amount with color based on transaction type
      const amount = Number(txn.amount || 0);
      const amountClass = amount < 0 ? 'color: #dc3545;' : 'color: #28a745;';
      const amountDisplay = amount < 0 ? `-$${Math.abs(amount).toFixed(2)}` : `$${amount.toFixed(2)}`;
      
      // Auto-pay badge (if applicable)
      const autoPayBadge = txn.auto_pay ? 
        `<span style="display: inline-flex; align-items: center; gap: 4px; background: linear-gradient(135deg, #8b5cf6 0%, #6366f1 100%); color: white; padding: 2px 8px; border-radius: 12px; font-size: 0.7rem; margin-left: 6px;">
          🤖 Auto
        </span>` : '';
      
      // Billing schedule info
      const billingSchedule = txn.billing_schedule ? 
        `<div style="font-size: 0.75rem; color: #8b5cf6; margin-top: 2px;">
          📅 ${txn.billing_schedule}
        </div>` : '';
      
      // Next billing info (for auto-pay transactions)
      const nextBillingInfo = txn.auto_pay && txn.next_billing_date ?
        `<div style="font-size: 0.7rem; color: #6b7280; margin-top: 2px;">
          Next: ${new Date(txn.next_billing_date).toLocaleDateString()}
        </div>` : '';
      
      return `
        <div class="transaction-item">
          <div style="flex: 1;">
            <div style="display: flex; align-items: center;">
              <strong>${txn.transaction_id || txn.id}</strong>
              ${autoPayBadge}
            </div>
            <div style="margin-top: 4px;">
              <span style="display: inline-flex; align-items: center; gap: 6px; font-size: 0.9rem;">
                ${pmDisplay.icon}
                <span style="font-weight: 500; color: #333;">${pmDisplay.display}</span>
              </span>
            </div>
            ${billingSchedule}
            <div style="font-size: 0.8rem; color: #666; margin-top: 2px;">
              ${txn.customer_name || txn.customer_id} • ${formattedDate}
            </div>
            ${nextBillingInfo}
          </div>
          <div style="text-align: right; min-width: 120px;">
            <strong style="${amountClass}">${amountDisplay}</strong><br>
            <span class="transaction-status ${statusClass}">${statusDisplay}</span>
            ${(txn.status === 'success' || txn.status === 'paid') && amount > 0 ? 
              `<div style="margin-top: 6px;">
                <button class="btn-small btn-refund" onclick="refundTransaction('${txn.transaction_id || txn.id}')" title="Process Refund">
                  ↩️ Refund
                </button>
              </div>` : 
              ''}
          </div>
        </div>
      `;
    }).join('');
  } catch (err) {
    console.error('Failed to load transactions:', err);
    const list = document.getElementById('transaction-list');
    list.innerHTML = '<p class="error">Failed to load transactions</p>';
  }
}

/**
 * Format payment method for display with icon and masked card number
 * DEFAULT: Use "4444" if card payment but no last 4 digits available
 * 
 * @param {Object} txn - Transaction object
 * @returns {Object} - {display, icon, tooltip, autoPay, billingSchedule}
 */
function formatPaymentMethodDisplay(txn) {
  // Default card last 4 digits when not available
  const DEFAULT_CARD_LAST4 = '4444';
  
  // Use enhanced data if available
  if (txn.payment_method_icon && txn.payment_method !== 'N/A') {
    return {
      display: txn.payment_method,
      icon: txn.payment_method_icon,
      tooltip: txn.payment_method_raw || txn.payment_method,
      autoPay: txn.auto_pay || false,
      billingSchedule: txn.billing_schedule || null
    };
  }
  
  // Fallback formatting for legacy data
  const pm = txn.payment_method || '';
  const cardLast4 = txn.card_last4;
  const cardType = txn.card_type;
  
  // Icon mappings
  const icons = {
    'credit_card': '💳',
    'debit_card': '💳',
    'paypal': '🅿️',
    'apple_pay': '🍎',
    'google_pay': '📱',
    'bank_transfer': '🏦',
    'Bank Transfer': '🏦',
    'wire': '🏦',
    'crypto': '₿',
    'crypto_btc': '₿',
    'crypto_eth': 'Ξ',
    'health_wallet': '💊',
    'internal': '🔄',
    'N/A': '❓'
  };
  
  // Card type display names
  const cardNames = {
    'visa': 'Visa',
    'mastercard': 'Mastercard',
    'amex': 'Amex',
    'american_express': 'Amex',
    'discover': 'Discover',
    'jcb': 'JCB',
    'card': 'Card'
  };
  
  let display = pm || 'N/A';
  let icon = icons[pm] || '💰';
  
  // Format credit/debit card with last 4 digits (DEFAULT: 4444)
  if (pm === 'credit_card' || pm === 'debit_card' || cardLast4 || cardType) {
    const typeName = cardType ? (cardNames[cardType.toLowerCase()] || 'Card') : 'Visa';
    // Use actual last 4 or default "4444"
    const displayLast4 = cardLast4 || DEFAULT_CARD_LAST4;
    display = `${typeName} •••• ${displayLast4}`;
    icon = '💳';
  }
  // Format PayPal
  else if (pm === 'paypal' || pm.toLowerCase().includes('paypal')) {
    display = 'PayPal';
    icon = '🅿️';
  }
  // Format Apple Pay
  else if (pm === 'apple_pay') {
    display = 'Apple Pay';
    icon = '🍎';
  }
  // Format Google Pay
  else if (pm === 'google_pay') {
    display = 'Google Pay';
    icon = '📱';
  }
  // Format Bank Transfer
  else if (pm === 'bank_transfer' || pm === 'Bank Transfer' || pm === 'wire') {
    display = 'Bank Transfer';
    icon = '🏦';
  }
  // Format Crypto
  else if (pm.startsWith('crypto') || ['btc', 'eth', 'usdc'].includes(pm.toLowerCase())) {
    const crypto = pm.replace('crypto_', '').toUpperCase() || 'Crypto';
    display = `Crypto (${crypto})`;
    icon = pm.includes('eth') ? 'Ξ' : '₿';
  }
  // Format Health Wallet
  else if (pm === 'health_wallet') {
    display = 'Health Wallet';
    icon = '💊';
  }
  // Format N/A or empty - default to Card with "4444"
  else if (!pm || pm === 'N/A' || pm === '****-****-****-****') {
    // Default to showing as card with default last 4
    display = `Card •••• ${DEFAULT_CARD_LAST4}`;
    icon = '💳';
  }
  // Format other methods
  else {
    display = pm.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    icon = icons[pm] || '💰';
  }
  
  return { 
    display, 
    icon, 
    tooltip: pm || 'credit_card',
    autoPay: txn.auto_pay || false,
    billingSchedule: txn.billing_schedule || null
  };
}

/**
 * Get CSS class for transaction status
 */
function getStatusClass(status) {
  const statusLower = (status || '').toLowerCase();
  if (['success', 'paid', 'completed', 'approved'].includes(statusLower)) {
    return 'status-success';
  } else if (['failed', 'rejected', 'declined'].includes(statusLower)) {
    return 'status-failed';
  } else if (['pending', 'processing', 'outstanding'].includes(statusLower)) {
    return 'status-pending';
  } else if (statusLower === 'refunded') {
    return 'status-refunded';
  }
  return 'status-pending';
}

async function handlePayment(e) {
  e.preventDefault();
  
  const resultDiv = document.getElementById('payment-result');
  const submitBtn = document.getElementById('submit-payment');
  const form = e.target;
  const formData = new FormData(form);
  
  // Get payment details
  const customerId = formData.get('customer_id');
  const policyId = formData.get('policy_id');
  const amount = parseFloat(formData.get('amount'));
  
  if (!customerId || !policyId || !amount || amount <= 0) {
    showResult(resultDiv, 'error', '❌ Please fill in all required fields');
    return;
  }
  
  // Route to appropriate payment handler based on selected method
  switch (selectedPaymentMethod) {
    case 'credit_card':
    case 'debit_card':
      await handleCardPayment(formData, resultDiv, submitBtn);
      break;
    case 'paypal':
      await handlePayPalPayment(formData, resultDiv, submitBtn);
      break;
    case 'apple_pay':
      await handleApplePayPayment(formData, resultDiv, submitBtn);
      break;
    case 'google_pay':
      await handleGooglePayPayment(formData, resultDiv, submitBtn);
      break;
    case 'bitcoin':
    case 'ethereum':
    case 'usdc':
      await handleCryptoPayment(selectedPaymentMethod, formData, resultDiv, submitBtn);
      break;
    default:
      showResult(resultDiv, 'error', '❌ Please select a payment method');
  }
}

// Handle Credit/Debit Card Payment
async function handleCardPayment(formData, resultDiv, submitBtn) {
  // Validate card fields
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
  showResult(resultDiv, 'info', '🔄 Processing card payment...');
  
  try {
    const cardNumber = formData.get('card_number').replace(/\D/g, '');
    const cardType = detectCardType(cardNumber);
    
    // Process through unified payment gateway
    const response = await fetch('/api/payment/process', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        method: 'credit_card',
        amount: parseFloat(formData.get('amount')),
        currency: 'USD',
        customer_id: formData.get('customer_id'),
        policy_id: formData.get('policy_id'),
        card_number: cardNumber,
        expiry_month: formData.get('expiry_month'),
        expiry_year: formData.get('expiry_year'),
        cvv: formData.get('cvv'),
        email: formData.get('email')
      })
    });
    
    const result = await response.json();
    handlePaymentResult(result, resultDiv, submitBtn, 'credit_card');
    
  } catch (err) {
    showResult(resultDiv, 'error', `❌ Error: ${err.message}`);
    submitBtn.disabled = false;
    submitBtn.textContent = '🔐 Process Secure Payment';
  }
}

// Handle PayPal Payment
async function handlePayPalPayment(formData, resultDiv, submitBtn) {
  submitBtn.disabled = true;
  submitBtn.textContent = '⏳ Creating PayPal order...';
  showResult(resultDiv, 'info', '🔄 Redirecting to PayPal...');
  
  try {
    const response = await fetch('/api/payment/process', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        method: 'paypal',
        amount: parseFloat(formData.get('amount')),
        currency: 'USD',
        customer_id: formData.get('customer_id'),
        policy_id: formData.get('policy_id'),
        description: `Premium payment for policy ${formData.get('policy_id')}`
      })
    });
    
    const result = await response.json();
    
    if (result.success && result.details?.approval_url) {
      showResult(resultDiv, 'success', `
        <strong>✅ PayPal Order Created!</strong><br><br>
        <p>Order ID: ${result.transaction_id}</p>
        <p>Amount: $${result.amount.toFixed(2)}</p>
        <br>
        <a href="${result.details.approval_url}" target="_blank" class="btn btn-primary" style="display: inline-block; padding: 0.75rem 1.5rem; text-decoration: none;">
          🅿️ Complete Payment on PayPal
        </a>
        <br><br>
        <p style="color: #666; font-size: 0.9rem;">
          <em>Sandbox Mode: Use a PayPal sandbox test account to complete the payment.</em>
        </p>
      `);
    } else {
      handlePaymentResult(result, resultDiv, submitBtn, 'paypal');
    }
    
    submitBtn.disabled = false;
    submitBtn.textContent = '🅿️ Pay with PayPal';
    
  } catch (err) {
    showResult(resultDiv, 'error', `❌ Error: ${err.message}`);
    submitBtn.disabled = false;
    submitBtn.textContent = '🅿️ Pay with PayPal';
  }
}

// Handle Apple Pay Payment
async function handleApplePayPayment(formData, resultDiv, submitBtn) {
  submitBtn.disabled = true;
  submitBtn.textContent = '⏳ Initializing Apple Pay...';
  showResult(resultDiv, 'info', '🔄 Setting up Apple Pay session...');
  
  try {
    const response = await fetch('/api/payment/process', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        method: 'apple_pay',
        amount: parseFloat(formData.get('amount')),
        currency: 'USD',
        customer_id: formData.get('customer_id'),
        policy_id: formData.get('policy_id')
      })
    });
    
    const result = await response.json();
    
    showResult(resultDiv, 'success', `
      <strong>🍎 Apple Pay Session Ready!</strong><br><br>
      <p>Session ID: ${result.details?.session_id || result.transaction_id}</p>
      <p>Amount: $${result.amount.toFixed(2)}</p>
      <br>
      <div style="background: #f5f5f5; padding: 1rem; border-radius: 8px;">
        <p><strong>Test Mode Instructions:</strong></p>
        <p>In a production environment, the Apple Pay sheet would appear here.</p>
        <p>For testing, this simulates a successful Apple Pay transaction.</p>
        <br>
        <button onclick="simulateApplePaySuccess('${result.transaction_id}')" class="btn btn-primary">
          ✅ Simulate Successful Payment
        </button>
      </div>
    `);
    
    submitBtn.disabled = false;
    submitBtn.textContent = '🍎 Pay with Apple Pay';
    
  } catch (err) {
    showResult(resultDiv, 'error', `❌ Error: ${err.message}`);
    submitBtn.disabled = false;
    submitBtn.textContent = '🍎 Pay with Apple Pay';
  }
}

// Handle Google Pay Payment
async function handleGooglePayPayment(formData, resultDiv, submitBtn) {
  submitBtn.disabled = true;
  submitBtn.textContent = '⏳ Initializing Google Pay...';
  showResult(resultDiv, 'info', '🔄 Setting up Google Pay session...');
  
  try {
    const response = await fetch('/api/payment/process', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        method: 'google_pay',
        amount: parseFloat(formData.get('amount')),
        currency: 'USD',
        customer_id: formData.get('customer_id'),
        policy_id: formData.get('policy_id')
      })
    });
    
    const result = await response.json();
    
    showResult(resultDiv, 'success', `
      <strong>🔵 Google Pay Session Ready!</strong><br><br>
      <p>Session ID: ${result.details?.session_id || result.transaction_id}</p>
      <p>Amount: $${result.amount.toFixed(2)}</p>
      <br>
      <div style="background: #f5f5f5; padding: 1rem; border-radius: 8px;">
        <p><strong>Test Mode Instructions:</strong></p>
        <p>In a production environment, the Google Pay sheet would appear here.</p>
        <p>For testing, this simulates a successful Google Pay transaction.</p>
        <br>
        <button onclick="simulateGooglePaySuccess('${result.transaction_id}')" class="btn btn-primary">
          ✅ Simulate Successful Payment
        </button>
      </div>
    `);
    
    submitBtn.disabled = false;
    submitBtn.textContent = '🔵 Pay with Google Pay';
    
  } catch (err) {
    showResult(resultDiv, 'error', `❌ Error: ${err.message}`);
    submitBtn.disabled = false;
    submitBtn.textContent = '🔵 Pay with Google Pay';
  }
}

// Handle Cryptocurrency Payment
async function handleCryptoPayment(crypto, formData, resultDiv, submitBtn) {
  const cryptoNames = { bitcoin: 'Bitcoin', ethereum: 'Ethereum', usdc: 'USDC' };
  const cryptoIcons = { bitcoin: '₿', ethereum: '⟠', usdc: '💵' };
  
  submitBtn.disabled = true;
  submitBtn.textContent = `⏳ Generating ${cryptoNames[crypto]} invoice...`;
  showResult(resultDiv, 'info', `🔄 Creating ${cryptoNames[crypto]} payment request...`);
  
  try {
    const response = await fetch('/api/payment/process', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        method: crypto,
        amount: parseFloat(formData.get('amount')),
        currency: 'USD',
        customer_id: formData.get('customer_id'),
        policy_id: formData.get('policy_id')
      })
    });
    
    const result = await response.json();
    
    if (result.success) {
      const details = result.details || {};
      showResult(resultDiv, 'success', `
        <strong>${cryptoIcons[crypto]} ${cryptoNames[crypto]} Payment Request Created!</strong><br><br>
        <p><strong>Amount (USD):</strong> $${result.amount.toFixed(2)}</p>
        <p><strong>Amount (${details.crypto_symbol || crypto.toUpperCase()}):</strong> ${details.crypto_amount || 'Calculating...'}</p>
        <p><strong>Exchange Rate:</strong> 1 ${details.crypto_symbol || crypto.toUpperCase()} = $${details.exchange_rate?.toLocaleString() || 'N/A'}</p>
        <br>
        <p><strong>Send to this address:</strong></p>
        <div class="crypto-address">${details.receiving_address || 'Address pending...'}</div>
        <div class="qr-placeholder">📱 QR Code<br>(Scan to pay)</div>
        <br>
        <p><strong>Payment ID:</strong> ${result.transaction_id}</p>
        <p><strong>Expires:</strong> ${details.expires_at ? new Date(details.expires_at).toLocaleString() : '30 minutes'}</p>
        <p><strong>Network:</strong> ${details.network || (details.testnet ? 'Testnet' : 'Mainnet')}</p>
        <br>
        <div style="background: #fff3cd; padding: 1rem; border-radius: 8px; margin-top: 1rem;">
          <p><strong>⚠️ Test Mode:</strong> This is using ${details.testnet ? 'testnet' : 'mainnet'}.</p>
          <p>Get testnet coins from a faucet to test this payment.</p>
          <br>
          <button onclick="simulateCryptoPayment('${result.transaction_id}')" class="btn btn-primary">
            ✅ Simulate Payment Received
          </button>
          <button onclick="checkCryptoStatus('${result.transaction_id}')" class="btn" style="margin-left: 0.5rem;">
            🔄 Check Status
          </button>
        </div>
      `);
    } else {
      handlePaymentResult(result, resultDiv, submitBtn, crypto);
    }
    
    submitBtn.disabled = false;
    submitBtn.textContent = `${cryptoIcons[crypto]} Generate ${cryptoNames[crypto]} Invoice`;
    
  } catch (err) {
    showResult(resultDiv, 'error', `❌ Error: ${err.message}`);
    submitBtn.disabled = false;
    submitBtn.textContent = `${cryptoIcons[crypto]} Generate ${cryptoNames[crypto]} Invoice`;
  }
}

// Simulate crypto payment received (for testing)
async function simulateCryptoPayment(paymentId) {
  try {
    const response = await fetch(`/api/payment/crypto/simulate/${paymentId}`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      }
    });
    
    const result = await response.json();
    
    if (result.success && result.status === 'completed') {
      alert(`✅ Payment Confirmed!\n\nTransaction ID: ${paymentId}\nTx Hash: ${result.details?.tx_hash || 'N/A'}`);
      loadRecentTransactions();
      loadStats();
    } else {
      alert(`Payment Status: ${result.status}\n\n${result.error || ''}`);
    }
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
}

// Check crypto payment status
async function checkCryptoStatus(paymentId) {
  try {
    const response = await fetch(`/api/payment/crypto/status/${paymentId}`, {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`
      }
    });
    
    const result = await response.json();
    
    alert(`Payment Status: ${result.status}\nConfirmations: ${result.details?.confirmations || 0}/${result.details?.required_confirmations || 6}`);
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
}

// Simulate Apple Pay success
function simulateApplePaySuccess(transactionId) {
  alert(`✅ Apple Pay Payment Simulated!\n\nTransaction ID: ${transactionId}\nStatus: Completed`);
  loadRecentTransactions();
  loadStats();
}

// Simulate Google Pay success
function simulateGooglePaySuccess(transactionId) {
  alert(`✅ Google Pay Payment Simulated!\n\nTransaction ID: ${transactionId}\nStatus: Completed`);
  loadRecentTransactions();
  loadStats();
}

// Handle payment result display
function handlePaymentResult(result, resultDiv, submitBtn, method) {
  if (result.success && result.status === 'completed') {
    showResult(resultDiv, 'success', `
      ✅ <strong>Payment Successful!</strong><br>
      Transaction ID: ${result.transaction_id}<br>
      Amount: $${Number(result.amount).toFixed(2)}<br>
      Method: ${method}<br>
      Gateway: ${result.gateway}
    `);
    
    // Clear sensitive fields
    if (document.getElementById('card_number')) {
      document.getElementById('card_number').value = '';
    }
    if (document.getElementById('cvv')) {
      document.getElementById('cvv').value = '';
    }
    
    // Refresh data
    setTimeout(() => {
      loadRecentTransactions();
      loadStats();
    }, 1000);
  } else {
    showResult(resultDiv, 'error', `❌ Payment failed: ${result.error || 'Transaction declined'}`);
  }
  
  submitBtn.disabled = false;
}

// Legacy card payment handler (kept for backward compatibility)
async function handleLegacyCardPayment(formData, resultDiv, submitBtn) {
  try {
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
  // Sanitize and validate the transaction ID before sending
  const sanitizedId = String(transactionId || '').trim().replace(/[^\w\-]/g, '');
  if (!sanitizedId) {
    alert('❌ Refund failed: Transaction ID is missing or invalid. Please select a valid transaction.');
    return;
  }

  if (!confirm(`Refund transaction ${sanitizedId}?\n\nThis action cannot be undone.`)) {
    return;
  }

  // Helper: perform the refund request with one retry on network/sync errors
  async function attemptRefund(attempt) {
    const response = await fetch('/api/billing/refund', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        transaction_id: sanitizedId,
        reason: 'Admin requested refund'
      })
    });
    return response;
  }

  try {
    let response;
    try {
      response = await attemptRefund(1);
    } catch (networkErr) {
      // Retry once after a short delay to handle transient connectivity/sync issues
      await new Promise(resolve => setTimeout(resolve, REFUND_RETRY_DELAY_MS));
      response = await attemptRefund(2);
    }

    const result = await response.json();

    if (result.success) {
      alert(`✅ Refund successful!\n\nRefund ID: ${result.refund_id}`);
      loadRecentTransactions();
      loadStats();
    } else {
      const errMsg = result.error || 'Unknown error';
      // Provide a user-friendly message when the transaction is not found (possible sync issue)
      if (errMsg.toLowerCase().includes('not found') || errMsg.toLowerCase().includes('sync')) {
        alert(`❌ Refund failed: ${refundSyncErrorMessage(errMsg)}`);
      } else {
        alert(`❌ Refund failed: ${errMsg}`);
      }
    }
  } catch (err) {
    alert(`❌ Error processing refund. Please try again or contact support if the issue persists.\n\nDetails: ${err.message}`);
  }
}

// ========== MARKETPLACE INTEGRATION ==========

// Current marketplace filter
let currentMarketplaceFilter = 'all';

// Load marketplace statistics and transactions
async function loadMarketplaceData() {
  await loadMarketplaceStats();
  await loadMarketplaceTransactions('all');
}

// Load marketplace/service statistics from unified service-transactions API
async function loadMarketplaceStats() {
  try {
    const response = await fetch('/api/service-transactions', {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`
      }
    });
    
    if (response.ok) {
      const data = await response.json();
      const stats = data.stats || {};
      
      // Update stats display
      const volumeEl = document.getElementById('marketplace-volume');
      const insuranceEl = document.getElementById('marketplace-insurance');
      const pendingEl = document.getElementById('marketplace-pending');
      const nftsEl = document.getElementById('marketplace-nfts');
      
      if (volumeEl) volumeEl.textContent = `$${(stats.total_volume || 0).toLocaleString(undefined, {minimumFractionDigits: 2})}`;
      if (insuranceEl) insuranceEl.textContent = `$${(stats.insurance_covered_total || 0).toLocaleString(undefined, {minimumFractionDigits: 2})}`;
      if (pendingEl) pendingEl.textContent = stats.pending_approvals || 0;
      if (nftsEl) nftsEl.textContent = stats.total_nfts_issued || 0;
      
      console.log('Service stats loaded:', stats);
    }
  } catch (err) {
    console.error('Failed to load service stats:', err);
  }
}

// Load marketplace/service transactions from unified API
async function loadMarketplaceTransactions(filter = 'all') {
  currentMarketplaceFilter = filter;
  const container = document.getElementById('marketplace-transactions');
  if (!container) return;
  
  container.innerHTML = '<p class="muted">Loading transactions...</p>';
  
  try {
    // Use unified service-transactions API with filter
    const endpoint = `/api/service-transactions?filter=${filter}`;
    
    const response = await fetch(endpoint, {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`
      }
    });
    
    if (response.ok) {
      const data = await response.json();
      const transactions = data.transactions || [];
      
      console.log(`Loaded ${transactions.length} service transactions (filter: ${filter})`);
      
      if (filter === 'pending') {
        displayPendingApprovals(transactions);
      } else {
        displayServiceTransactions(transactions);
      }
      
      // Update stats if available
      if (data.stats) {
        const volumeEl = document.getElementById('marketplace-volume');
        const insuranceEl = document.getElementById('marketplace-insurance');
        const pendingEl = document.getElementById('marketplace-pending');
        const nftsEl = document.getElementById('marketplace-nfts');
        
        if (volumeEl) volumeEl.textContent = `$${(data.stats.total_volume || 0).toLocaleString(undefined, {minimumFractionDigits: 2})}`;
        if (insuranceEl) insuranceEl.textContent = `$${(data.stats.insurance_covered_total || 0).toLocaleString(undefined, {minimumFractionDigits: 2})}`;
        if (pendingEl) pendingEl.textContent = data.stats.pending_approvals || 0;
        if (nftsEl) nftsEl.textContent = data.stats.total_nfts_issued || 0;
      }
    } else {
      container.innerHTML = '<p class="muted">No service transaction data available</p>';
    }
  } catch (err) {
    console.error('Failed to load service transactions:', err);
    container.innerHTML = '<p class="error">Failed to load transactions</p>';
  }
}

// Display service transactions (unified format)
function displayServiceTransactions(transactions) {
  const container = document.getElementById('marketplace-transactions');
  if (!container) return;
  
  if (!transactions || transactions.length === 0) {
    container.innerHTML = `
      <div style="text-align: center; padding: 40px; color: #666;">
        <div style="font-size: 3rem; margin-bottom: 12px;">📋</div>
        <div style="font-size: 1.1rem; font-weight: 600;">No transactions found</div>
        <div style="font-size: 0.9rem; margin-top: 8px;">Service transactions will appear here when created</div>
      </div>
    `;
    return;
  }
  
  const typeIcons = {
    'service': '🏥',
    'claim': '📋',
    'payment': '💳',
    'ledger': '📒',
    'medical_purchase': '💊',
    'insurance_claim': '🛡️',
    'premium_payment': '💰'
  };
  
  const statusColors = {
    'completed': '#28a745',
    'verified': '#28a745',
    'paid': '#28a745',
    'approved': '#28a745',
    'pending': '#ffc107',
    'submitted': '#ffc107',
    'under_review': '#17a2b8',
    'rejected': '#dc3545',
    'failed': '#dc3545'
  };
  
  container.innerHTML = transactions.map(txn => {
    const icon = typeIcons[txn.category] || typeIcons[txn.type] || '📄';
    const statusColor = statusColors[(txn.status || '').toLowerCase()] || '#6c757d';
    const date = txn.timestamp ? new Date(txn.timestamp).toLocaleDateString() : 'N/A';
    const time = txn.timestamp ? new Date(txn.timestamp).toLocaleTimeString() : '';
    
    return `
      <div class="transaction-item" style="border-left: 4px solid ${statusColor};">
        <div style="display: flex; align-items: center; gap: 12px; flex: 1;">
          <div style="font-size: 1.8rem;">${icon}</div>
          <div style="flex: 1;">
            <div style="font-weight: 600; color: #333;">${txn.description || txn.category || 'Transaction'}</div>
            <div style="font-size: 0.85rem; color: #666;">
              ${txn.customer_id || 'N/A'} • ${date} ${time}
              ${txn.nft_token_id ? `<span style="color: #6f42c1; margin-left: 8px;">🔗 ${txn.nft_token_id.substring(0, 12)}...</span>` : ''}
            </div>
            ${txn.provider ? `<div style="font-size: 0.8rem; color: #888;">Provider: ${txn.provider}</div>` : ''}
          </div>
        </div>
        <div style="text-align: right;">
          <div style="font-size: 1.2rem; font-weight: 700; color: #333;">$${Number(txn.amount || 0).toLocaleString(undefined, {minimumFractionDigits: 2})}</div>
          ${txn.insurance_covered > 0 ? `<div style="font-size: 0.8rem; color: #28a745;">Insurance: $${Number(txn.insurance_covered).toLocaleString(undefined, {minimumFractionDigits: 2})}</div>` : ''}
          <span class="transaction-status" style="background-color: ${statusColor}20; color: ${statusColor}; margin-top: 4px; display: inline-block;">
            ${(txn.status || 'Unknown').toUpperCase()}
          </span>
        </div>
      </div>
    `;
  }).join('');
}

// Display marketplace transactions
function displayMarketplaceTransactions(transactions) {
  const container = document.getElementById('marketplace-transactions');
  if (!container) return;
  
  if (transactions.length === 0) {
    container.innerHTML = '<p class="muted">No transactions found</p>';
    return;
  }
  
  container.innerHTML = transactions.map(txn => {
    const statusClass = txn.status === 'completed' ? 'status-completed' :
                       txn.status === 'approved' ? 'status-success' :
                       txn.status === 'pending' ? 'status-pending' : 'status-failed';
    const typeIcon = txn.item_type === 'service' ? '🩺' : '📦';
    
    return `
      <div class="transaction-item">
        <div>
          <strong>${typeIcon} ${txn.item_name || txn.transaction_id}</strong><br>
          <small>Customer: ${txn.customer_id}</small><br>
          <small>Category: ${txn.category} | NFT: ${txn.nft_token_id || 'N/A'}</small><br>
          <small>${new Date(txn.created_at).toLocaleString()}</small>
        </div>
        <div style="text-align: right;">
          <strong>$${Number(txn.total_amount).toFixed(2)}</strong><br>
          ${txn.insurance_covered > 0 ? `<small style="color: #28a745;">Insurance: $${txn.insurance_covered.toFixed(2)}</small><br>` : ''}
          <span class="transaction-status ${statusClass}">${txn.status.toUpperCase()}</span><br>
          ${txn.status === 'pending' || txn.status === 'pending_approval' ? `
            <div class="action-buttons" style="margin-top: 0.5rem;">
              <button class="btn-small" style="background:#28a745;color:#fff;" onclick="approveMarketplaceTransaction('${txn.transaction_id}')">Approve</button>
              <button class="btn-small" style="background:#dc3545;color:#fff;" onclick="rejectMarketplaceTransaction('${txn.transaction_id}')">Reject</button>
            </div>
          ` : ''}
        </div>
      </div>
    `;
  }).join('');
}

// Display pending approvals (works with unified transaction format)
function displayPendingApprovals(approvals) {
  const container = document.getElementById('marketplace-transactions');
  if (!container) return;
  
  if (!approvals || approvals.length === 0) {
    container.innerHTML = `
      <div style="text-align: center; padding: 40px; color: #28a745;">
        <div style="font-size: 3rem; margin-bottom: 12px;">✅</div>
        <div style="font-size: 1.1rem; font-weight: 600;">No pending approvals</div>
        <div style="font-size: 0.9rem; margin-top: 8px; color: #666;">All items have been processed</div>
      </div>
    `;
    return;
  }
  
  const typeIcons = {
    'claim': '📋',
    'service': '🏥',
    'medical_purchase': '💊',
    'insurance_claim': '🛡️'
  };
  
  container.innerHTML = approvals.map(item => {
    // Handle both old format (item.transaction) and new unified format
    const txn = item.transaction || item;
    const nft = item.nft || {};
    const typeIcon = typeIcons[txn.category] || typeIcons[txn.type] || '📄';
    const timestamp = txn.timestamp || txn.created_at || txn.filed_date;
    
    return `
      <div class="transaction-item" style="background: linear-gradient(135deg, #fff3cd 0%, #ffe8a1 100%); border-left: 4px solid #ffc107;">
        <div style="display: flex; align-items: center; gap: 12px; flex: 1;">
          <div style="font-size: 2rem;">${typeIcon}</div>
          <div>
            <div style="font-weight: 600; color: #333;">${txn.description || txn.item_name || txn.id}</div>
            <div style="font-size: 0.85rem; color: #666;">
              Customer: ${txn.customer_id || 'N/A'}
              ${txn.policy_id ? ` • Policy: ${txn.policy_id}` : ''}
            </div>
            <div style="font-size: 0.8rem; color: #888;">
              ${timestamp ? new Date(timestamp).toLocaleString() : 'N/A'}
              ${txn.nft_token_id || nft.token_id ? ` • NFT: ${(txn.nft_token_id || nft.token_id).substring(0, 12)}...` : ''}
            </div>
            ${txn.provider ? `<div style="font-size: 0.8rem; color: #666;">Provider: ${txn.provider}</div>` : ''}
          </div>
        </div>
        <div style="text-align: right;">
          <div style="font-size: 1.3rem; font-weight: 700; color: #856404;">$${Number(txn.amount || txn.total_amount || txn.claimed_amount || 0).toLocaleString(undefined, {minimumFractionDigits: 2})}</div>
          <span class="transaction-status status-pending" style="margin: 8px 0; display: inline-block;">⏳ PENDING</span>
          <div class="action-buttons" style="margin-top: 8px; display: flex; gap: 8px; justify-content: flex-end;">
            <button class="btn-small" style="background: linear-gradient(135deg, #28a745 0%, #20c997 100%); color:#fff; padding: 8px 16px; border-radius: 6px;" onclick="approvePendingItem('${txn.id}', '${txn.type || txn.category}')">✅ Approve</button>
            <button class="btn-small" style="background: linear-gradient(135deg, #dc3545 0%, #c82333 100%); color:#fff; padding: 8px 16px; border-radius: 6px;" onclick="rejectPendingItem('${txn.id}', '${txn.type || txn.category}')">❌ Reject</button>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

// Approve pending item (claims, transactions, etc.)
async function approvePendingItem(itemId, itemType) {
  if (!confirm(`Approve ${itemType} ${itemId}?`)) return;
  
  try {
    let endpoint = '/api/claims/approve';
    let body = { id: itemId, approved_by: 'admin' };
    
    if (itemType === 'service' || itemType === 'medical_purchase') {
      endpoint = '/api/marketplace/admin/approve';
      body = { transaction_id: itemId };
    }
    
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(body)
    });
    
    if (response.ok) {
      alert('✅ Item approved successfully!');
      loadMarketplaceData();
    } else {
      const data = await response.json();
      alert('❌ Failed to approve: ' + (data.error || 'Unknown error'));
    }
  } catch (err) {
    alert('❌ Error: ' + err.message);
  }
}

// Reject pending item
async function rejectPendingItem(itemId, itemType) {
  const reason = prompt('Enter rejection reason:');
  if (!reason) return;
  
  try {
    let endpoint = '/api/claims/reject';
    let body = { id: itemId, reason: reason };
    
    if (itemType === 'service' || itemType === 'medical_purchase') {
      endpoint = '/api/marketplace/admin/reject';
      body = { transaction_id: itemId, reason: reason };
    }
    
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(body)
    });
    
    if (response.ok) {
      alert('Item rejected');
      loadMarketplaceData();
    } else {
      const data = await response.json();
      alert('❌ Failed to reject: ' + (data.error || 'Unknown error'));
    }
  } catch (err) {
    alert('❌ Error: ' + err.message);
  }
}

// Approve marketplace transaction
async function approveMarketplaceTransaction(transactionId) {
  const notes = prompt('Enter approval notes (optional):');
  
  try {
    const response = await fetch('/api/marketplace/admin/approve', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        transaction_id: transactionId,
        notes: notes || ''
      })
    });
    
    const result = await response.json();
    
    if (result.success) {
      alert(`✅ Transaction approved!\n\nTransaction ID: ${transactionId}`);
      loadMarketplaceData();
    } else {
      alert(`❌ Approval failed: ${result.error}`);
    }
  } catch (err) {
    alert(`❌ Error: ${err.message}`);
  }
}

// Reject marketplace transaction
async function rejectMarketplaceTransaction(transactionId) {
  const reason = prompt('Enter rejection reason:');
  if (!reason) {
    alert('Rejection reason is required');
    return;
  }
  
  try {
    const response = await fetch('/api/marketplace/admin/reject', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        transaction_id: transactionId,
        reason: reason
      })
    });
    
    const result = await response.json();
    
    if (result.success) {
      alert(`Transaction rejected.\n\nTransaction ID: ${transactionId}`);
      loadMarketplaceData();
    } else {
      alert(`❌ Rejection failed: ${result.error}`);
    }
  } catch (err) {
    alert(`❌ Error: ${err.message}`);
  }
}

// Switch marketplace tabs
function showMarketplaceTab(filter) {
  currentMarketplaceFilter = filter;
  
  // Update tab styles
  document.querySelectorAll('.tabs .tab').forEach(tab => {
    tab.classList.remove('active');
  });
  event.target.classList.add('active');
  
  // Load data for selected filter
  loadMarketplaceTransactions(filter);
}

// Initialize marketplace on page load
document.addEventListener('DOMContentLoaded', () => {
  // Load marketplace data after other initialization
  setTimeout(loadMarketplaceData, 500);
});

// ========== EXPORT FUNCTIONS ==========

// Store loaded data for exports
let lastBillingStats = null;
let lastTransactions = [];
let lastMarketplaceData = [];

// Format currency for display
function formatCurrencyExport(amount) {
  return '$' + Number(amount || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
}

// Export to CSV helper
function downloadCSV(data, filename) {
  if (!data || data.length === 0) {
    alert('No data to export');
    return;
  }
  const headers = Object.keys(data[0]);
  const csvContent = [
    headers.join(','),
    ...data.map(row => headers.map(h => {
      const val = row[h];
      if (typeof val === 'string' && (val.includes(',') || val.includes('"'))) return `"${val.replace(/"/g, '""')}"`;
      return val;
    }).join(','))
  ].join('\n');
  
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `${filename}_${new Date().toISOString().split('T')[0]}.csv`;
  link.click();
}

// Export to PDF helper (opens print dialog)
function exportPDF(title, contentHtml) {
  const printWindow = window.open('', '_blank');
  printWindow.document.write(`
    <html>
    <head>
      <title>${title}</title>
      <style>
        body { font-family: Arial, sans-serif; padding: 40px; max-width: 800px; margin: 0 auto; }
        table { width: 100%; border-collapse: collapse; margin: 15px 0; }
        th, td { border: 1px solid #333; padding: 8px; text-align: left; font-size: 11px; }
        th { background: #f0f0f0; font-weight: bold; }
        h1 { color: #1a1f36; border-bottom: 2px solid #667eea; padding-bottom: 10px; }
        .header { display: flex; justify-content: space-between; margin-bottom: 20px; }
        .logo { font-size: 24px; font-weight: bold; }
        .date { color: #666; }
        .summary-box { background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 15px 0; }
        .metric { display: inline-block; margin: 10px 20px 10px 0; text-align: center; }
        .metric-value { font-size: 18px; font-weight: bold; color: #667eea; }
        .metric-label { font-size: 10px; color: #666; }
        @page { margin: 1cm; }
      </style>
    </head>
    <body>
      <div class="header">
        <div class="logo">🛡️ PHINS Insurance</div>
        <div class="date">${new Date().toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}</div>
      </div>
      <h1>${title}</h1>
      ${contentHtml}
      <hr style="margin-top: 40px;">
      <p style="font-size: 10px; color: #666;">
        Generated by PHINS Billing Platform | Report ID: BIL-${Date.now().toString(36).toUpperCase()}
      </p>
    </body>
    </html>
  `);
  printWindow.document.close();
  setTimeout(() => printWindow.print(), 500);
}

// Export Billing Statistics
async function exportBillingStats(format) {
  // Fetch fresh data
  try {
    const response = await fetch('/api/billing/stats', {
      headers: { 'Authorization': `Bearer ${localStorage.getItem('phins_token')}` }
    });
    const stats = await response.json();
    lastBillingStats = stats;
    
    if (format === 'csv') {
      const data = [
        { Metric: 'Total Revenue', Value: stats.total_revenue || 0 },
        { Metric: 'Monthly Premium Income', Value: stats.monthly_premium_income || 0 },
        { Metric: 'Total Billed', Value: stats.total_billed || 0 },
        { Metric: 'Total Collected', Value: stats.total_collected || 0 },
        { Metric: 'Outstanding Balance', Value: stats.outstanding_balance || 0 },
        { Metric: 'Claims Paid', Value: stats.claims_paid || 0 },
        { Metric: 'Collection Rate', Value: (stats.collection_rate || 0) + '%' },
        { Metric: 'Total Transactions', Value: stats.total_transactions || 0 },
        { Metric: 'Paid Count', Value: stats.paid_count || 0 },
        { Metric: 'Pending Count', Value: stats.pending_count || 0 },
        { Metric: 'Overdue Count', Value: stats.overdue_count || 0 },
      ];
      downloadCSV(data, 'PHINS_Billing_Statistics');
    } else if (format === 'pdf') {
      const content = `
        <div class="summary-box">
          <div class="metric"><span class="metric-value">${formatCurrencyExport(stats.total_revenue)}</span><br><span class="metric-label">Total Revenue</span></div>
          <div class="metric"><span class="metric-value">${formatCurrencyExport(stats.total_collected)}</span><br><span class="metric-label">Collected</span></div>
          <div class="metric"><span class="metric-value">${formatCurrencyExport(stats.outstanding_balance)}</span><br><span class="metric-label">Outstanding</span></div>
          <div class="metric"><span class="metric-value">${(stats.collection_rate || 0).toFixed(1)}%</span><br><span class="metric-label">Collection Rate</span></div>
        </div>
        <h3>Billing Summary</h3>
        <table>
          <tr><th>Metric</th><th>Value</th></tr>
          <tr><td>Total Revenue (Annual)</td><td>${formatCurrencyExport(stats.total_revenue)}</td></tr>
          <tr><td>Monthly Premium Income</td><td>${formatCurrencyExport(stats.monthly_premium_income)}</td></tr>
          <tr><td>Total Billed</td><td>${formatCurrencyExport(stats.total_billed)}</td></tr>
          <tr><td>Total Collected</td><td>${formatCurrencyExport(stats.total_collected)}</td></tr>
          <tr><td>Outstanding Balance</td><td>${formatCurrencyExport(stats.outstanding_balance)}</td></tr>
          <tr><td>Claims Paid</td><td>${formatCurrencyExport(stats.claims_paid)}</td></tr>
          <tr><td>Collection Rate</td><td>${(stats.collection_rate || 0).toFixed(1)}%</td></tr>
        </table>
        <h3>Transaction Counts</h3>
        <table>
          <tr><th>Status</th><th>Count</th></tr>
          <tr><td>Total Transactions</td><td>${stats.total_transactions || 0}</td></tr>
          <tr><td>Paid</td><td>${stats.paid_count || 0}</td></tr>
          <tr><td>Pending</td><td>${stats.pending_count || 0}</td></tr>
          <tr><td>Overdue</td><td>${stats.overdue_count || 0}</td></tr>
        </table>
      `;
      exportPDF('Billing Statistics Report', content);
    }
  } catch (err) {
    alert('Error exporting billing stats: ' + err.message);
  }
}

// Export Transactions
async function exportTransactions(format) {
  try {
    const response = await fetch('/api/billing/transactions', {
      headers: { 'Authorization': `Bearer ${localStorage.getItem('phins_token')}` }
    });
    const data = await response.json();
    lastTransactions = data.transactions || [];
    
    if (lastTransactions.length === 0) {
      alert('No transactions to export');
      return;
    }
    
    if (format === 'csv') {
      const csvData = lastTransactions.map(t => {
        // Format payment method for export
        const pmDisplay = formatPaymentMethodDisplay(t);
        return {
          Transaction_ID: t.id || t.transaction_id,
          Customer_ID: t.customer_id,
          Customer_Name: t.customer_name || 'N/A',
          Policy_ID: t.policy_id || '',
          Type: t.type,
          Amount: t.amount,
          Status: t.status,
          Date: t.date,
          Payment_Method: pmDisplay.display,
          Card_Type: t.card_type || 'card',
          Card_Last_4: t.card_last4 || '4444',
          Auto_Pay: t.auto_pay ? 'Yes' : 'No',
          Billing_Frequency: t.billing_frequency || '',
          Billing_Schedule: t.billing_schedule || '',
          Next_Billing_Date: t.next_billing_date ? t.next_billing_date.substring(0, 10) : ''
        };
      });
      downloadCSV(csvData, 'PHINS_Transactions');
    } else if (format === 'pdf') {
      const content = `
        <p><strong>Total Transactions:</strong> ${lastTransactions.length}</p>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Customer</th>
              <th>Type</th>
              <th>Amount</th>
              <th>Status</th>
              <th>Date</th>
            </tr>
          </thead>
          <tbody>
            ${lastTransactions.slice(0, 50).map(t => `
              <tr>
                <td>${t.id || t.transaction_id}</td>
                <td>${t.customer_name || t.customer_id}</td>
                <td>${t.type}</td>
                <td>${formatCurrencyExport(t.amount)}</td>
                <td>${t.status}</td>
                <td>${new Date(t.date).toLocaleDateString()}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
        ${lastTransactions.length > 50 ? '<p><em>Showing first 50 of ' + lastTransactions.length + ' transactions</em></p>' : ''}
      `;
      exportPDF('Transaction Report', content);
    }
  } catch (err) {
    alert('Error exporting transactions: ' + err.message);
  }
}

// Print Transactions
function printTransactions() {
  const content = document.getElementById('transaction-list');
  if (!content || content.innerHTML.includes('Loading')) {
    alert('Please wait for transactions to load');
    return;
  }
  exportPDF('Transaction List', content.innerHTML);
}

// Export Marketplace/Service Transactions
async function exportMarketplace(format) {
  try {
    const response = await fetch('/api/service-transactions', {
      headers: { 'Authorization': `Bearer ${localStorage.getItem('phins_token')}` }
    });
    const data = await response.json();
    lastMarketplaceData = data.transactions || [];
    
    if (lastMarketplaceData.length === 0) {
      alert('No service transactions to export');
      return;
    }
    
    if (format === 'csv') {
      const csvData = lastMarketplaceData.map(t => ({
        Transaction_ID: t.id,
        Type: t.type,
        Category: t.category,
        Description: t.description || 'N/A',
        Amount: t.amount || 0,
        Insurance_Covered: t.insurance_covered || 0,
        Wallet_Paid: t.wallet_paid || 0,
        Customer_ID: t.customer_id || 'N/A',
        Provider: t.provider || 'N/A',
        Status: t.status,
        Date: t.timestamp ? new Date(t.timestamp).toISOString().split('T')[0] : 'N/A',
        NFT_Token_ID: t.nft_token_id || 'N/A'
      }));
      downloadCSV(csvData, 'PHINS_Service_Transactions');
    } else if (format === 'pdf') {
      const totalVolume = lastMarketplaceData.reduce((sum, t) => sum + (t.amount || 0), 0);
      const totalInsurance = lastMarketplaceData.reduce((sum, t) => sum + (t.insurance_covered || 0), 0);
      
      const content = `
        <div style="margin-bottom: 20px;">
          <p><strong>Total Service Transactions:</strong> ${lastMarketplaceData.length}</p>
          <p><strong>Total Volume:</strong> $${totalVolume.toLocaleString(undefined, {minimumFractionDigits: 2})}</p>
          <p><strong>Insurance Covered:</strong> $${totalInsurance.toLocaleString(undefined, {minimumFractionDigits: 2})}</p>
        </div>
        <table style="width: 100%; border-collapse: collapse;">
          <thead>
            <tr style="background: #f5f5f5;">
              <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">ID</th>
              <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Type</th>
              <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Description</th>
              <th style="padding: 8px; border: 1px solid #ddd; text-align: right;">Amount</th>
              <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Status</th>
              <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Date</th>
            </tr>
          </thead>
          <tbody>
            ${lastMarketplaceData.slice(0, 50).map(t => `
              <tr>
                <td style="padding: 6px; border: 1px solid #ddd;">${t.id}</td>
                <td style="padding: 6px; border: 1px solid #ddd;">${t.type} / ${t.category}</td>
                <td style="padding: 6px; border: 1px solid #ddd;">${(t.description || 'N/A').substring(0, 40)}</td>
                <td style="padding: 6px; border: 1px solid #ddd; text-align: right;">$${Number(t.amount || 0).toLocaleString(undefined, {minimumFractionDigits: 2})}</td>
                <td style="padding: 6px; border: 1px solid #ddd;">${t.status}</td>
                <td style="padding: 6px; border: 1px solid #ddd;">${t.timestamp ? new Date(t.timestamp).toLocaleDateString() : 'N/A'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
      exportPDF('Service Transaction Report', content);
    }
  } catch (err) {
    alert('Error exporting service data: ' + err.message);
  }
}

// ========== TRANSACTION LEDGER FUNCTIONS ==========
let lastLedgerData = [];
let currentLedgerFilter = 'all';

async function loadLedger(filter = 'all') {
  currentLedgerFilter = filter;
  const token = localStorage.getItem('phins_token');
  const container = document.getElementById('ledger-list');
  
  if (container) {
    container.innerHTML = '<p class="muted">Loading ledger entries...</p>';
  }
  
  try {
    let url = '/api/ledger?limit=100';
    if (filter && filter !== 'all') {
      url += `&type=${filter}`;
    }
    
    const response = await fetch(url, {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    
    if (!response.ok) throw new Error('Failed to load ledger');
    
    const data = await response.json();
    lastLedgerData = data.ledger_entries || [];
    
    // Update stats
    const totalEl = document.getElementById('ledger-total');
    const nftEl = document.getElementById('ledger-nft');
    const integrityEl = document.getElementById('ledger-integrity');
    
    if (totalEl) totalEl.textContent = data.total_entries || lastLedgerData.length;
    
    // Count NFT-verified entries
    const nftCount = lastLedgerData.filter(e => e.nft_token_id || e.metadata?.nft_token_id).length;
    if (nftEl) nftEl.textContent = nftCount;
    
    // Update integrity status based on NFT coverage
    if (integrityEl) {
      const coverage = lastLedgerData.length > 0 ? (nftCount / lastLedgerData.length * 100) : 0;
      if (coverage >= 90) {
        integrityEl.textContent = '✅ HEALTHY';
        integrityEl.style.color = '#28a745';
      } else if (coverage >= 70) {
        integrityEl.textContent = '⚠️ WARNING';
        integrityEl.style.color = '#ffc107';
      } else {
        integrityEl.textContent = '🔍 CHECKING';
        integrityEl.style.color = '#17a2b8';
      }
    }
    
    console.log(`Ledger loaded: ${lastLedgerData.length} entries (filter: ${filter})`);
    displayLedger(lastLedgerData);
    
  } catch (err) {
    console.error('Failed to load ledger:', err);
    document.getElementById('ledger-list').innerHTML = '<p class="muted">Unable to load ledger entries.</p>';
  }
}

function displayLedger(entries) {
  const container = document.getElementById('ledger-list');
  
  if (!entries || entries.length === 0) {
    container.innerHTML = `
      <div style="text-align: center; padding: 40px; color: #666;">
        <div style="font-size: 3rem; margin-bottom: 12px;">📒</div>
        <div style="font-size: 1.1rem; font-weight: 600;">No ledger entries found</div>
        <div style="font-size: 0.9rem; margin-top: 8px;">Transaction records will appear here</div>
      </div>
    `;
    return;
  }
  
  const typeIcons = {
    'policy_approved': '✅',
    'billing_created': '💳',
    'claim_submitted': '📋',
    'claim_payment': '💰',
    'claim_payment_received': '💰',
    'claim_payout': '💸',
    'health_wallet_activated': '🏥',
    'wallet_deposit': '💵',
    'investment_deposit': '📈',
    'pipeline_initialized': '🔄',
    'payment_received': '💵',
    'premium_payment': '💳',
    'premium_refund': '↩️',
    'refund_deposit': '↩️',
    'default': '📒'
  };
  
  const typeColors = {
    'policy_approved': '#28a745',
    'billing_created': '#007bff',
    'claim_submitted': '#ffc107',
    'claim_payment': '#17a2b8',
    'claim_payment_received': '#ffc107',
    'claim_payout': '#dc3545',
    'health_wallet_activated': '#17a2b8',
    'wallet_deposit': '#20c997',
    'investment_deposit': '#6f42c1',
    'pipeline_initialized': '#9c27b0',
    'payment_received': '#28a745',
    'premium_payment': '#28a745',
    'premium_refund': '#e0a800',
    'refund_deposit': '#e0a800',
    'default': '#6c757d'
  };
  
  const statusBadges = {
    'completed': { bg: '#d4edda', color: '#155724', text: 'COMPLETED' },
    'pending': { bg: '#fff3cd', color: '#856404', text: 'PENDING' },
    'failed': { bg: '#f8d7da', color: '#721c24', text: 'FAILED' }
  };
  
  container.innerHTML = entries.map(entry => {
    const icon = typeIcons[entry.type] || typeIcons.default;
    const color = typeColors[entry.type] || typeColors.default;
    const nftId = entry.nft_token_id || entry.metadata?.nft_token_id;
    const status = statusBadges[entry.status] || statusBadges.completed;
    const metadata = entry.metadata || {};
    
    // Format metadata details
    let metaDetails = [];
    if (metadata.policy_id) metaDetails.push(`Policy: ${metadata.policy_id}`);
    if (metadata.claim_id) metaDetails.push(`Claim: ${metadata.claim_id}`);
    if (metadata.bill_id) metaDetails.push(`Bill: ${metadata.bill_id}`);
    if (metadata.pipeline_name) metaDetails.push(`Pipeline: ${metadata.pipeline_name}`);
    if (metadata.payment_method) metaDetails.push(`Method: ${metadata.payment_method}`);
    
    return `
      <div class="transaction-item" style="border-left: 4px solid ${color}; padding: 12px; margin-bottom: 8px; background: #fafafa; border-radius: 0 8px 8px 0;">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 8px;">
          <div style="flex: 1;">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <span style="font-size: 1.5rem;">${icon}</span>
              <strong style="color: #333;">${entry.id}</strong>
              <span style="background: ${color}; color: white; padding: 3px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase;">
                ${(entry.type || 'unknown').replace(/_/g, ' ')}
              </span>
              ${nftId ? `<span style="background: linear-gradient(135deg, #9c27b0, #673ab7); color: white; padding: 3px 8px; border-radius: 4px; font-size: 0.7rem;">🔗 NFT Verified</span>` : ''}
            </div>
            <div style="margin-top: 8px; color: #444; font-size: 0.95rem;">${entry.description || 'No description'}</div>
            ${metaDetails.length > 0 ? `<div style="margin-top: 6px; font-size: 0.8rem; color: #666;">${metaDetails.join(' • ')}</div>` : ''}
          </div>
          <div style="text-align: right; min-width: 120px;">
            ${entry.amount > 0 ? `<div style="font-size: 1.2rem; font-weight: 700; color: ${color};">$${Number(entry.amount).toLocaleString(undefined, {minimumFractionDigits: 2})}</div>` : ''}
            <div style="background: ${status.bg}; color: ${status.color}; padding: 3px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; display: inline-block; margin-top: 4px;">
              ${status.text}
            </div>
          </div>
        </div>
        <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid #e0e0e0; font-size: 0.8rem; color: #888; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
          <span>👤 ${entry.customer_id || 'SYSTEM'}</span>
          <span>🕐 ${new Date(entry.timestamp).toLocaleString()}</span>
          ${nftId ? `<span style="color: #9c27b0;">🔗 ${nftId.substring(0, 20)}...</span>` : ''}
        </div>
      </div>
    `;
  }).join('');
}

function filterLedger(filter) {
  // Update tab active states
  document.querySelectorAll('.tabs .tab').forEach(tab => {
    if (tab.textContent.toLowerCase().includes(filter.toLowerCase().replace('_', ' ')) || 
        (filter === 'all' && tab.textContent === 'All')) {
      tab.classList.add('active');
    } else {
      tab.classList.remove('active');
    }
  });
  
  loadLedger(filter);
}

function refreshLedger() {
  loadLedger(currentLedgerFilter);
}

async function validateLedger() {
  const token = localStorage.getItem('phins_token');
  
  try {
    const response = await fetch('/api/ledger/validate', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    
    if (!response.ok) throw new Error('Validation failed');
    
    const data = await response.json();
    const statusEl = document.getElementById('ledger-integrity');
    
    const statusColors = {
      'HEALTHY': '#28a745',
      'WARNING': '#ffc107',
      'CRITICAL': '#dc3545'
    };
    
    statusEl.textContent = data.integrity_status;
    statusEl.style.color = statusColors[data.integrity_status] || '#6c757d';
    
    // Show detailed alert
    let message = `Ledger Integrity: ${data.integrity_status}\n\n`;
    message += `✓ Validated Entries: ${data.validated_entries}\n`;
    message += `✓ NFT Ledger Count: ${data.nft_ledger_count}\n`;
    message += `✓ Transaction Ledger: ${data.transaction_ledger_count}\n`;
    message += `✓ Billing Records: ${data.billing_records_count}\n`;
    
    if (data.issues_found > 0) {
      message += `\n⚠️ Issues Found: ${data.issues_found}\n`;
      data.issues.slice(0, 5).forEach(issue => {
        message += `  - ${issue.issue}\n`;
      });
    }
    
    alert(message);
    
  } catch (err) {
    console.error('Ledger validation failed:', err);
    document.getElementById('ledger-integrity').textContent = 'ERROR';
    document.getElementById('ledger-integrity').style.color = '#dc3545';
    alert('Failed to validate ledger: ' + err.message);
  }
}

function exportLedger(format) {
  if (!lastLedgerData || lastLedgerData.length === 0) {
    alert('No ledger entries to export');
    return;
  }
  
  if (format === 'csv') {
    const csvData = lastLedgerData.map(entry => ({
      Transaction_ID: entry.id,
      Customer_ID: entry.customer_id,
      Type: entry.type,
      Amount: entry.amount,
      Description: entry.description,
      Status: entry.status,
      NFT_Token: entry.metadata?.nft_token_id || 'N/A',
      Timestamp: entry.timestamp
    }));
    downloadCSV(csvData, 'PHINS_Transaction_Ledger');
  } else if (format === 'pdf') {
    const content = `
      <p><strong>Total Ledger Entries:</strong> ${lastLedgerData.length}</p>
      <p><strong>Generated:</strong> ${new Date().toLocaleString()}</p>
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Customer</th>
            <th>Type</th>
            <th>Amount</th>
            <th>Status</th>
            <th>Timestamp</th>
          </tr>
        </thead>
        <tbody>
          ${lastLedgerData.slice(0, 100).map(entry => `
            <tr>
              <td>${entry.id}</td>
              <td>${entry.customer_id || 'N/A'}</td>
              <td>${entry.type}</td>
              <td>${formatCurrencyExport(entry.amount || 0)}</td>
              <td>${entry.status}</td>
              <td>${new Date(entry.timestamp).toLocaleString()}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
    exportPDF('Transaction Ledger Report', content);
  }
}

// ========== CUSTOMER & POLICY SELECTION FOR BILLING ==========

// Load all customers for billing
async function loadAllCustomersForBilling() {
  const token = localStorage.getItem('phins_token');
  const select = document.getElementById('billing-customer-select');
  
  select.innerHTML = '<option value="">Loading customers...</option>';
  
  try {
    const response = await fetch('/api/customers', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    
    if (!response.ok) throw new Error('Failed to load customers');
    
    const data = await response.json();
    billingCustomers = data.customers || data || [];
    
    select.innerHTML = '<option value="">-- Select Customer --</option>';
    
    if (billingCustomers.length === 0) {
      select.innerHTML += '<option value="" disabled>No customers found</option>';
      return;
    }
    
    billingCustomers.forEach(c => {
      const name = c.name || c.full_name || `${c.first_name || ''} ${c.last_name || ''}`.trim() || c.email;
      select.innerHTML += `<option value="${c.id}">${name} (${c.email})</option>`;
    });
    
    console.log(`Loaded ${billingCustomers.length} customers for billing`);
    
  } catch (err) {
    console.error('Error loading customers:', err);
    select.innerHTML = '<option value="">-- Error loading customers --</option>';
  }
}

// Search customer by email
function searchCustomerForBilling() {
  const searchInput = document.getElementById('billing-customer-search').value.toLowerCase().trim();
  const select = document.getElementById('billing-customer-select');
  
  if (!searchInput) {
    loadAllCustomersForBilling();
    return;
  }
  
  // First ensure we have customers loaded
  if (billingCustomers.length === 0) {
    loadAllCustomersForBilling().then(() => {
      filterBillingCustomers(searchInput);
    });
  } else {
    filterBillingCustomers(searchInput);
  }
}

function filterBillingCustomers(searchTerm) {
  const select = document.getElementById('billing-customer-select');
  const filtered = billingCustomers.filter(c => 
    (c.email || '').toLowerCase().includes(searchTerm) ||
    (c.name || '').toLowerCase().includes(searchTerm)
  );
  
  select.innerHTML = '<option value="">-- Select Customer --</option>';
  
  if (filtered.length === 0) {
    select.innerHTML += '<option value="" disabled>No matching customers</option>';
    return;
  }
  
  filtered.forEach(c => {
    const name = c.name || c.full_name || `${c.first_name || ''} ${c.last_name || ''}`.trim() || c.email;
    select.innerHTML += `<option value="${c.id}">${name} (${c.email})</option>`;
  });
  
  // Auto-select if only one match
  if (filtered.length === 1) {
    select.value = filtered[0].id;
    loadCustomerPoliciesForBilling();
  }
}

// Load policies for selected customer
async function loadCustomerPoliciesForBilling() {
  const token = localStorage.getItem('phins_token');
  const customerId = document.getElementById('billing-customer-select').value;
  const policySelect = document.getElementById('billing-policy-select');
  
  if (!customerId) {
    policySelect.innerHTML = '<option value="">-- Select Policy --</option>';
    document.getElementById('billing-customer-info').style.display = 'none';
    clearBillingFormFields();
    return;
  }
  
  policySelect.innerHTML = '<option value="">Loading policies...</option>';
  
  // Get selected customer data
  selectedBillingCustomer = billingCustomers.find(c => c.id === customerId);
  
  try {
    const response = await fetch('/api/policies', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    
    if (!response.ok) throw new Error('Failed to load policies');
    
    const data = await response.json();
    const allPolicies = data.policies || data || [];
    
    // Filter policies for this customer
    billingPolicies = allPolicies.filter(p => 
      p.customer_id === customerId || 
      (selectedBillingCustomer && (p.customer_email || '').toLowerCase() === (selectedBillingCustomer.email || '').toLowerCase())
    );
    
    policySelect.innerHTML = '<option value="">-- Select Policy --</option>';
    
    if (billingPolicies.length === 0) {
      policySelect.innerHTML += '<option value="" disabled>No policies found for this customer</option>';
    } else {
      billingPolicies.forEach(p => {
        const status = p.status || 'active';
        const coverage = p.coverage_amount || p.coverage || 0;
        const premium = p.monthly_premium || 0;
        policySelect.innerHTML += `<option value="${p.id}">${p.id} - $${Number(coverage).toLocaleString()} coverage - $${Number(premium).toFixed(2)}/mo - ${status}</option>`;
      });
      
      // Auto-select first policy (prefer active)
      const activePolicy = billingPolicies.find(p => (p.status || '').toLowerCase() === 'active');
      const firstPolicy = activePolicy || billingPolicies[0];
      if (firstPolicy) {
        policySelect.value = firstPolicy.id;
        await loadPolicyDataForBilling();
      }
    }
    
    // Update customer info display
    updateBillingCustomerInfo();
    
  } catch (err) {
    console.error('Error loading policies:', err);
    policySelect.innerHTML = '<option value="">-- Error loading policies --</option>';
  }
}

// Load policy data and application data
async function loadPolicyDataForBilling() {
  const token = localStorage.getItem('phins_token');
  const policyId = document.getElementById('billing-policy-select').value;
  
  if (!policyId) {
    return;
  }
  
  selectedBillingPolicy = billingPolicies.find(p => p.id === policyId);
  
  // Try to load underwriting application data
  try {
    const response = await fetch('/api/underwriting/applications', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    
    if (response.ok) {
      const data = await response.json();
      const applications = data.applications || data.items || [];
      
      // Find application for this customer/policy
      selectedBillingApplication = applications.find(a => 
        a.policy_id === policyId ||
        a.customer_id === selectedBillingCustomer?.id ||
        (a.customer_email || '').toLowerCase() === (selectedBillingCustomer?.email || '').toLowerCase()
      );
    }
  } catch (err) {
    console.error('Error loading application data:', err);
  }
  
  // Update display and form fields
  updateBillingCustomerInfo();
  populateBillingFormFields();
}

// Update customer info display card
function updateBillingCustomerInfo() {
  const infoDiv = document.getElementById('billing-customer-info');
  
  if (!selectedBillingCustomer) {
    infoDiv.style.display = 'none';
    return;
  }
  
  infoDiv.style.display = 'block';
  
  // Customer details
  const name = selectedBillingCustomer.name || selectedBillingCustomer.full_name || 
               `${selectedBillingCustomer.first_name || ''} ${selectedBillingCustomer.last_name || ''}`.trim() || 'N/A';
  document.getElementById('billing-info-name').textContent = name;
  document.getElementById('billing-info-email').textContent = selectedBillingCustomer.email || 'N/A';
  document.getElementById('billing-info-phone').textContent = selectedBillingCustomer.phone || selectedBillingCustomer.mobile || 'N/A';
  
  // Age from application or customer
  const age = selectedBillingApplication?.age ?? selectedBillingCustomer?.age ?? 'N/A';
  document.getElementById('billing-info-age').textContent = age;
  
  // Policy details
  if (selectedBillingPolicy) {
    document.getElementById('billing-info-policy').textContent = selectedBillingPolicy.id;
    document.getElementById('billing-info-coverage').textContent = '$' + Number(selectedBillingPolicy.coverage_amount || 0).toLocaleString();
    document.getElementById('billing-info-status').textContent = selectedBillingPolicy.status || 'N/A';
    document.getElementById('billing-info-status').style.color = 
      (selectedBillingPolicy.status || '').toLowerCase() === 'active' ? '#28a745' : '#ffc107';
    document.getElementById('billing-info-type').textContent = selectedBillingPolicy.type || 'N/A';
    
    // Premium info
    const monthly = selectedBillingPolicy.monthly_premium || 0;
    const annual = selectedBillingPolicy.annual_premium || (monthly * 12);
    document.getElementById('billing-info-monthly').textContent = '$' + Number(monthly).toFixed(2);
    document.getElementById('billing-info-annual').textContent = '$' + Number(annual).toFixed(2);
    
    // Calculate next due date (simple: next month)
    const nextDue = new Date();
    nextDue.setMonth(nextDue.getMonth() + 1);
    nextDue.setDate(1);
    document.getElementById('billing-info-due').textContent = nextDue.toLocaleDateString('en-GB', {day: '2-digit', month: 'short', year: 'numeric'});
  } else {
    document.getElementById('billing-info-policy').textContent = '-';
    document.getElementById('billing-info-coverage').textContent = '-';
    document.getElementById('billing-info-status').textContent = '-';
    document.getElementById('billing-info-type').textContent = '-';
    document.getElementById('billing-info-monthly').textContent = '-';
    document.getElementById('billing-info-annual').textContent = '-';
    document.getElementById('billing-info-due').textContent = '-';
  }
  
  console.log('Billing info updated:', {
    customer: name,
    age: age,
    policy: selectedBillingPolicy?.id,
    monthly: selectedBillingPolicy?.monthly_premium
  });
}

// Populate billing form fields from selected data
function populateBillingFormFields() {
  if (!selectedBillingCustomer || !selectedBillingPolicy) return;
  
  // Set hidden form fields
  document.getElementById('customer_id').value = selectedBillingCustomer.id;
  document.getElementById('policy_id').value = selectedBillingPolicy.id;
  
  // Auto-fill payment amount based on payment type
  const paymentType = document.getElementById('payment_type').value;
  const amountInput = document.getElementById('payment_amount');
  
  if (selectedBillingPolicy) {
    const monthly = selectedBillingPolicy.monthly_premium || 0;
    const annual = selectedBillingPolicy.annual_premium || (monthly * 12);
    const quarterly = selectedBillingPolicy.quarterly_premium || (monthly * 3);
    
    switch (paymentType) {
      case 'premium':
        amountInput.value = monthly.toFixed(2);
        break;
      case 'quarterly_premium':
        amountInput.value = quarterly.toFixed(2);
        break;
      case 'annual_premium':
        amountInput.value = annual.toFixed(2);
        break;
      default:
        amountInput.value = monthly.toFixed(2);
    }
    
    validateAmount();
  }
}

// Clear billing form fields
function clearBillingFormFields() {
  document.getElementById('customer_id').value = '';
  document.getElementById('policy_id').value = '';
  document.getElementById('payment_amount').value = '';
}

// Clear customer selection
function clearBillingCustomerSelection() {
  document.getElementById('billing-customer-search').value = '';
  document.getElementById('billing-customer-select').value = '';
  document.getElementById('billing-policy-select').innerHTML = '<option value="">-- Select Policy --</option>';
  document.getElementById('billing-customer-info').style.display = 'none';
  document.getElementById('billing-ai-assessment').style.display = 'none';
  
  selectedBillingCustomer = null;
  selectedBillingPolicy = null;
  selectedBillingApplication = null;
  
  clearBillingFormFields();
}

// Sync manual entry to hidden fields
function syncManualToHidden() {
  const manualCustomer = document.getElementById('manual_customer_id')?.value;
  const manualPolicy = document.getElementById('manual_policy_id')?.value;
  
  if (manualCustomer) document.getElementById('customer_id').value = manualCustomer;
  if (manualPolicy) document.getElementById('policy_id').value = manualPolicy;
}

// ========== AI BILLING ASSESSMENT ==========

function runBillingAIAssessment() {
  if (!selectedBillingCustomer || !selectedBillingPolicy) {
    alert('Please select a customer and policy first');
    return;
  }
  
  const assessmentDiv = document.getElementById('billing-ai-assessment');
  assessmentDiv.style.display = 'block';
  assessmentDiv.innerHTML = '<div style="text-align: center; padding: 2rem;"><div style="font-size: 2rem;">🤖</div><p>Running AI Billing Assessment...</p></div>';
  
  // Simulate AI assessment (in production, this would call a backend service)
  setTimeout(() => {
    const assessment = generateBillingAIAssessment();
    renderBillingAIAssessment(assessment);
  }, 1000);
}

function generateBillingAIAssessment() {
  const customer = selectedBillingCustomer;
  const policy = selectedBillingPolicy;
  const app = selectedBillingApplication;
  
  // Risk factors
  let riskScore = 20; // Base score (low risk)
  let riskFactors = [];
  let recommendations = [];
  let insights = [];
  
  // Age factor
  const age = app?.age ?? customer?.age ?? 35;
  if (age > 60) {
    riskScore += 15;
    riskFactors.push(`Higher age (${age}) increases claim likelihood`);
  } else if (age < 25) {
    riskScore += 5;
    riskFactors.push(`Younger age may indicate lower payment history`);
  } else {
    insights.push(`Age ${age} is within optimal range for premium stability`);
  }
  
  // Disability factor
  const disability = app?.disability_percentage ?? 0;
  if (disability > 50) {
    riskScore += 20;
    riskFactors.push(`High disability (${disability}%) - increased ADL claim potential`);
    recommendations.push('Consider premium adjustment for disability coverage');
  } else if (disability > 0) {
    riskScore += 10;
    insights.push(`Moderate disability (${disability}%) factored into premium`);
  }
  
  // BMI factor
  const bmi = app?.bmi ?? 24;
  if (bmi >= 30) {
    riskScore += 10;
    riskFactors.push(`BMI ${bmi} (Obese) - higher health risk`);
  } else if (bmi >= 25) {
    riskScore += 5;
    insights.push(`BMI ${bmi} (Overweight) - moderate health consideration`);
  } else {
    insights.push(`BMI ${bmi} - healthy weight range`);
  }
  
  // Policy status
  const status = (policy?.status || '').toLowerCase();
  if (status === 'active') {
    insights.push('Policy is active - ready for premium collection');
    recommendations.push('Proceed with standard billing cycle');
  } else if (status === 'pending_underwriting') {
    riskScore += 5;
    riskFactors.push('Policy pending underwriting - billing may be deferred');
    recommendations.push('Complete underwriting before billing');
  } else if (status === 'lapsed') {
    riskScore += 30;
    riskFactors.push('Policy has lapsed - reinstatement required');
    recommendations.push('Apply reinstatement fee before premium collection');
  }
  
  // Coverage amount
  const coverage = policy?.coverage_amount || 0;
  if (coverage > 500000) {
    riskScore += 10;
    insights.push(`High coverage ($${coverage.toLocaleString()}) - premium reflects comprehensive protection`);
    recommendations.push('Verify identity before processing large premium');
  }
  
  // Payment prediction
  const paymentScore = Math.max(0, 100 - riskScore);
  let paymentPrediction = 'HIGH';
  let paymentColor = '#28a745';
  
  if (paymentScore < 50) {
    paymentPrediction = 'LOW';
    paymentColor = '#dc3545';
    recommendations.push('Consider payment plan options');
    recommendations.push('Send payment reminder before due date');
  } else if (paymentScore < 75) {
    paymentPrediction = 'MODERATE';
    paymentColor = '#ffc107';
    recommendations.push('Monitor payment timeline closely');
  } else {
    recommendations.push('Standard billing process recommended');
  }
  
  // Add positive insights
  if (insights.length === 0) {
    insights.push('Customer profile shows standard risk factors');
  }
  
  return {
    riskScore: Math.min(100, riskScore),
    paymentProbability: paymentScore,
    paymentPrediction,
    paymentColor,
    riskFactors,
    recommendations,
    insights,
    customerData: {
      name: customer?.name || customer?.email,
      age,
      disability,
      bmi,
      policyStatus: status,
      coverage,
      monthlyPremium: policy?.monthly_premium || 0
    }
  };
}

function renderBillingAIAssessment(assessment) {
  const assessmentDiv = document.getElementById('billing-ai-assessment');
  
  assessmentDiv.innerHTML = `
    <div style="background: linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%); border-radius: 12px; padding: 20px; color: white; margin-top: 1rem;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; flex-wrap: wrap; gap: 10px;">
        <h3 style="margin: 0; font-size: 1.2rem;">🤖 AI Billing Assessment</h3>
        <span style="background: rgba(255,255,255,0.2); padding: 4px 12px; border-radius: 20px; font-size: 0.8rem;">
          ${new Date().toLocaleString()}
        </span>
      </div>
      
      <!-- Main Scores -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 20px;">
        <div style="background: rgba(255,255,255,0.1); border-radius: 8px; padding: 15px; text-align: center;">
          <div style="font-size: 2rem; font-weight: bold; color: ${assessment.paymentColor};">${assessment.paymentProbability}%</div>
          <div style="font-size: 0.85rem; opacity: 0.8;">Payment Probability</div>
          <div style="margin-top: 5px; font-weight: bold; color: ${assessment.paymentColor};">${assessment.paymentPrediction}</div>
        </div>
        <div style="background: rgba(255,255,255,0.1); border-radius: 8px; padding: 15px; text-align: center;">
          <div style="font-size: 2rem; font-weight: bold; color: ${assessment.riskScore > 50 ? '#dc3545' : assessment.riskScore > 30 ? '#ffc107' : '#28a745'};">${assessment.riskScore}%</div>
          <div style="font-size: 0.85rem; opacity: 0.8;">Risk Score</div>
          <div style="margin-top: 5px; font-weight: bold;">${assessment.riskScore > 50 ? 'HIGH' : assessment.riskScore > 30 ? 'MODERATE' : 'LOW'}</div>
        </div>
        <div style="background: rgba(255,255,255,0.1); border-radius: 8px; padding: 15px; text-align: center;">
          <div style="font-size: 2rem; font-weight: bold; color: #4facfe;">$${assessment.customerData.monthlyPremium.toFixed(2)}</div>
          <div style="font-size: 0.85rem; opacity: 0.8;">Monthly Premium</div>
          <div style="margin-top: 5px; font-size: 0.8rem; opacity: 0.7;">Due next billing</div>
        </div>
      </div>
      
      <!-- Customer Summary -->
      <div style="background: rgba(255,255,255,0.05); border-radius: 8px; padding: 12px; margin-bottom: 15px;">
        <div style="font-weight: 600; margin-bottom: 8px;">📊 Customer Profile</div>
        <div style="display: flex; flex-wrap: wrap; gap: 15px; font-size: 0.9rem;">
          <span>👤 ${assessment.customerData.name}</span>
          <span>🎂 Age: ${assessment.customerData.age}</span>
          <span>♿ Disability: ${assessment.customerData.disability}%</span>
          <span>📏 BMI: ${assessment.customerData.bmi}</span>
          <span>📋 Status: ${assessment.customerData.policyStatus}</span>
          <span>💰 Coverage: $${assessment.customerData.coverage.toLocaleString()}</span>
        </div>
      </div>
      
      <!-- Risk Factors -->
      ${assessment.riskFactors.length > 0 ? `
        <div style="margin-bottom: 15px;">
          <div style="font-weight: 600; margin-bottom: 8px; color: #ff6b6b;">⚠️ Risk Factors</div>
          <div style="background: rgba(220,53,69,0.2); border-radius: 8px; padding: 10px;">
            ${assessment.riskFactors.map(f => `<div style="padding: 4px 0; font-size: 0.9rem;">• ${f}</div>`).join('')}
          </div>
        </div>
      ` : ''}
      
      <!-- Insights -->
      ${assessment.insights.length > 0 ? `
        <div style="margin-bottom: 15px;">
          <div style="font-weight: 600; margin-bottom: 8px; color: #4facfe;">💡 Insights</div>
          <div style="background: rgba(79,172,254,0.2); border-radius: 8px; padding: 10px;">
            ${assessment.insights.map(i => `<div style="padding: 4px 0; font-size: 0.9rem;">• ${i}</div>`).join('')}
          </div>
        </div>
      ` : ''}
      
      <!-- Recommendations -->
      <div style="margin-bottom: 10px;">
        <div style="font-weight: 600; margin-bottom: 8px; color: #28a745;">✅ Recommendations</div>
        <div style="background: rgba(40,167,69,0.2); border-radius: 8px; padding: 10px;">
          ${assessment.recommendations.map(r => `<div style="padding: 4px 0; font-size: 0.9rem;">• ${r}</div>`).join('')}
        </div>
      </div>
      
      <!-- Action Buttons -->
      <div style="display: flex; gap: 10px; margin-top: 15px; flex-wrap: wrap;">
        <button type="button" onclick="applyRecommendedPaymentType()" class="btn" style="background: #28a745; color: white;">
          ✓ Apply Recommendations
        </button>
        <button type="button" onclick="downloadBillingAssessment()" class="btn" style="background: rgba(255,255,255,0.2); color: white;">
          📄 Download Report
        </button>
      </div>
    </div>
  `;
}

// Apply recommended payment type based on assessment
function applyRecommendedPaymentType() {
  if (!selectedBillingPolicy) return;
  
  // Set payment type to monthly premium
  document.getElementById('payment_type').value = 'premium';
  document.getElementById('payment_amount').value = (selectedBillingPolicy.monthly_premium || 0).toFixed(2);
  validateAmount();
  
  alert('✅ Recommendations applied!\n\nPayment type set to Monthly Premium.\nAmount set to $' + (selectedBillingPolicy.monthly_premium || 0).toFixed(2));
}

// Download billing assessment as PDF
function downloadBillingAssessment() {
  if (!selectedBillingCustomer || !selectedBillingPolicy) {
    alert('No assessment data available');
    return;
  }
  
  const assessment = generateBillingAIAssessment();
  const content = `
    <div class="summary-box" style="background: linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%); color: white; padding: 20px; border-radius: 8px;">
      <h3 style="color: white;">Customer: ${assessment.customerData.name}</h3>
      <p>Age: ${assessment.customerData.age} | Disability: ${assessment.customerData.disability}% | BMI: ${assessment.customerData.bmi}</p>
      <p>Policy Status: ${assessment.customerData.policyStatus} | Coverage: $${assessment.customerData.coverage.toLocaleString()}</p>
    </div>
    
    <h3>AI Assessment Results</h3>
    <div class="summary-box">
      <div class="metric"><span class="metric-value" style="color: ${assessment.paymentColor};">${assessment.paymentProbability}%</span><br><span class="metric-label">Payment Probability</span></div>
      <div class="metric"><span class="metric-value">${assessment.riskScore}%</span><br><span class="metric-label">Risk Score</span></div>
      <div class="metric"><span class="metric-value">$${assessment.customerData.monthlyPremium.toFixed(2)}</span><br><span class="metric-label">Monthly Premium</span></div>
    </div>
    
    ${assessment.riskFactors.length > 0 ? `
      <h4>⚠️ Risk Factors</h4>
      <ul>${assessment.riskFactors.map(f => `<li>${f}</li>`).join('')}</ul>
    ` : ''}
    
    <h4>💡 Insights</h4>
    <ul>${assessment.insights.map(i => `<li>${i}</li>`).join('')}</ul>
    
    <h4>✅ Recommendations</h4>
    <ul>${assessment.recommendations.map(r => `<li>${r}</li>`).join('')}</ul>
  `;
  
  exportPDF('AI Billing Assessment - ' + assessment.customerData.name, content);
}

// Update payment amount when payment type changes
document.addEventListener('DOMContentLoaded', () => {
  const paymentTypeSelect = document.getElementById('payment_type');
  if (paymentTypeSelect) {
    paymentTypeSelect.addEventListener('change', () => {
      populateBillingFormFields();
    });
  }
  
  // Initialize pipeline validation
  validatePipelineConnection();
  
  // Update fraud alert count
  updateFraudAlertCount();
});

// ==================== PIPELINE VALIDATION & REFRESH FUNCTIONS ====================

// Validate connection to PHINS pipeline
async function validatePipelineConnection() {
  const statusElement = document.getElementById('pipeline-validation-status');
  const statusText = document.getElementById('pipeline-status-text');
  const lastSync = document.getElementById('pipeline-last-sync');
  
  if (!statusElement || !statusText) return;
  
  statusElement.style.display = 'block';
  statusText.textContent = 'Connecting...';
  statusText.style.color = '#ffc107';
  
  try {
    // Check multiple pipeline endpoints
    const checks = await Promise.allSettled([
      fetch('/api/billing/stats', { headers: { 'Authorization': `Bearer ${localStorage.getItem('phins_token')}` } }),
      fetch('/api/customers', { headers: { 'Authorization': `Bearer ${localStorage.getItem('phins_token')}` } }),
      fetch('/api/policies', { headers: { 'Authorization': `Bearer ${localStorage.getItem('phins_token')}` } })
    ]);
    
    const successCount = checks.filter(c => c.status === 'fulfilled' && c.value.ok).length;
    
    if (successCount === 3) {
      statusText.textContent = '✓ All Systems Connected';
      statusText.style.color = '#28a745';
      statusElement.style.background = '#d4edda';
    } else if (successCount > 0) {
      statusText.textContent = `⚠️ Partial (${successCount}/3 services)`;
      statusText.style.color = '#856404';
      statusElement.style.background = '#fff3cd';
    } else {
      statusText.textContent = '❌ Disconnected';
      statusText.style.color = '#dc3545';
      statusElement.style.background = '#f8d7da';
    }
    
    if (lastSync) {
      lastSync.textContent = 'Last sync: ' + new Date().toLocaleTimeString();
    }
  } catch (err) {
    console.error('Pipeline validation error:', err);
    statusText.textContent = '❌ Error';
    statusText.style.color = '#dc3545';
  }
}

// Refresh billing stats
async function refreshBillingStats() {
  const grid = document.getElementById('stats-grid');
  if (grid) {
    grid.innerHTML = '<p class="muted" style="grid-column: 1/-1; text-align: center;">🔄 Refreshing...</p>';
  }
  
  await loadStats();
  await validatePipelineConnection();
  
  // Show notification
  showNotification('Stats refreshed from pipeline', 'success');
}

// Refresh payment methods from pipeline
async function refreshPaymentMethods() {
  const statusEl = document.getElementById('payment-methods-status');
  if (statusEl) {
    statusEl.textContent = '🔄 Syncing...';
    statusEl.style.background = '#fff3cd';
    statusEl.style.color = '#856404';
  }
  
  await loadPaymentMethods();
  
  // Verify connection to payment gateway pipeline
  try {
    const response = await fetch('/api/payment/methods', {
      headers: { 'Authorization': `Bearer ${localStorage.getItem('phins_token')}` }
    });
    
    if (statusEl) {
      if (response.ok) {
        statusEl.textContent = '✓ Connected';
        statusEl.style.background = '#d1fae5';
        statusEl.style.color = '#065f46';
      } else {
        statusEl.textContent = '⚠️ Limited';
        statusEl.style.background = '#fff3cd';
        statusEl.style.color = '#856404';
      }
    }
  } catch (err) {
    if (statusEl) {
      statusEl.textContent = '❌ Offline';
      statusEl.style.background = '#fee2e2';
      statusEl.style.color = '#991b1b';
    }
  }
}

// Update fraud alert count badge
async function updateFraudAlertCount() {
  const countEl = document.getElementById('fraud-alert-count');
  if (!countEl) return;
  
  try {
    const response = await fetch('/api/billing/fraud-alerts', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({})
    });
    
    if (response.ok) {
      const data = await response.json();
      const alerts = data.alerts || [];
      const activeAlerts = alerts.filter(a => a.status !== 'resolved').length;
      
      countEl.textContent = `${activeAlerts} Active`;
      
      if (activeAlerts > 0) {
        countEl.style.background = '#f8d7da';
        countEl.style.color = '#721c24';
      } else {
        countEl.style.background = '#d4edda';
        countEl.style.color = '#155724';
      }
    }
  } catch (err) {
    console.error('Error updating fraud alert count:', err);
  }
}

// Show notification toast
function showNotification(message, type = 'info') {
  // Remove existing notifications
  const existing = document.querySelector('.billing-notification');
  if (existing) existing.remove();
  
  const colors = {
    success: { bg: '#d4edda', border: '#28a745', text: '#155724' },
    error: { bg: '#f8d7da', border: '#dc3545', text: '#721c24' },
    info: { bg: '#d1ecf1', border: '#17a2b8', text: '#0c5460' },
    warning: { bg: '#fff3cd', border: '#ffc107', text: '#856404' }
  };
  
  const style = colors[type] || colors.info;
  
  const notification = document.createElement('div');
  notification.className = 'billing-notification';
  notification.style.cssText = `
    position: fixed;
    top: 80px;
    right: 20px;
    padding: 12px 20px;
    background: ${style.bg};
    border-left: 4px solid ${style.border};
    color: ${style.text};
    border-radius: 4px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    z-index: 9999;
    animation: slideIn 0.3s ease;
    font-weight: 500;
  `;
  notification.innerHTML = message;
  
  document.body.appendChild(notification);
  
  // Auto remove after 3 seconds
  setTimeout(() => {
    notification.style.animation = 'slideOut 0.3s ease';
    setTimeout(() => notification.remove(), 300);
  }, 3000);
}

// Add CSS for notifications
const notificationStyles = document.createElement('style');
notificationStyles.textContent = `
  @keyframes slideIn {
    from { transform: translateX(100%); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
  }
  @keyframes slideOut {
    from { transform: translateX(0); opacity: 1; }
    to { transform: translateX(100%); opacity: 0; }
  }
`;
document.head.appendChild(notificationStyles);

// ============================================================================
// BILLING CREDITS MANAGEMENT
// ============================================================================

let currentCreditCustomerId = null;
let currentCreditsData = null;

// Initialize credit lookup form handler
document.addEventListener('DOMContentLoaded', () => {
  const creditLookupForm = document.getElementById('credit-lookup-form');
  if (creditLookupForm) {
    creditLookupForm.addEventListener('submit', handleCreditLookup);
  }
});

// Handle credit lookup form submission
async function handleCreditLookup(event) {
  event.preventDefault();
  const customerId = document.getElementById('credit-customer-id').value.trim();
  if (!customerId) {
    showNotification('Please enter a Customer ID', 'warning');
    return;
  }
  await loadCreditsForCustomer(customerId);
}

// Refresh credits for current customer
async function refreshCredits() {
  if (currentCreditCustomerId) {
    await loadCreditsForCustomer(currentCreditCustomerId);
  } else {
    showNotification('Please enter a Customer ID first', 'info');
  }
}

// Load credits for a specific customer
async function loadCreditsForCustomer(customerId) {
  const creditsList = document.getElementById('credits-list');
  const creditSummary = document.getElementById('credit-balance-summary');
  const creditActions = document.getElementById('credit-actions');
  const creditStatus = document.getElementById('credit-status');
  
  creditsList.innerHTML = '<p class="muted">Loading credits...</p>';
  
  try {
    const response = await fetch('/api/billing/credits', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ customer_id: customerId })
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'Failed to load credits');
    }
    
    const data = await response.json();
    currentCreditCustomerId = customerId;
    currentCreditsData = data;
    
    // Update summary
    const totalCredit = data.total_with_interest || 0;
    const interest = data.total_interest_accrued || 0;
    const creditCount = data.active_credits_count || 0;
    
    document.getElementById('credit-total').textContent = `$${totalCredit.toLocaleString('en-US', {minimumFractionDigits: 2})}`;
    document.getElementById('credit-interest').textContent = `$${interest.toLocaleString('en-US', {minimumFractionDigits: 2})}`;
    document.getElementById('credit-count').textContent = creditCount;
    creditStatus.textContent = `$${totalCredit.toFixed(2)}`;
    
    // Show/hide sections based on credit balance
    if (totalCredit > 0) {
      creditSummary.style.display = 'block';
      creditActions.style.display = 'block';
      creditStatus.style.background = '#d1fae5';
      creditStatus.style.color = '#065f46';
    } else {
      creditSummary.style.display = 'none';
      creditActions.style.display = 'none';
      creditStatus.style.background = '#e2e8f0';
      creditStatus.style.color = '#64748b';
    }
    
    // Display credit details
    const credits = data.credits || [];
    if (credits.length === 0) {
      creditsList.innerHTML = `
        <div style="text-align: center; padding: 20px; color: #666;">
          <p>No active credits for this customer.</p>
          <p style="font-size: 0.85rem;">Credits are created automatically when overpayments or billing errors are detected.</p>
        </div>
      `;
    } else {
      creditsList.innerHTML = `
        <table style="width: 100%; border-collapse: collapse; font-size: 0.85rem;">
          <thead style="background: #f5f5f5;">
            <tr>
              <th style="padding: 8px; text-align: left;">Credit ID</th>
              <th style="padding: 8px; text-align: left;">Type</th>
              <th style="padding: 8px; text-align: right;">Amount</th>
              <th style="padding: 8px; text-align: right;">Remaining</th>
              <th style="padding: 8px; text-align: left;">Reason</th>
              <th style="padding: 8px; text-align: left;">Created</th>
            </tr>
          </thead>
          <tbody>
            ${credits.map(c => `
              <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 8px; font-family: monospace; font-size: 0.75rem;">${c.credit_id || '-'}</td>
                <td style="padding: 8px;">
                  <span style="padding: 2px 6px; background: ${getCreditTypeBadgeColor(c.credit_type)}; border-radius: 4px; font-size: 0.75rem;">
                    ${formatCreditType(c.credit_type)}
                  </span>
                </td>
                <td style="padding: 8px; text-align: right; font-weight: bold;">$${(c.amount || 0).toFixed(2)}</td>
                <td style="padding: 8px; text-align: right; color: #2e7d32; font-weight: bold;">$${(c.remaining_amount || 0).toFixed(2)}</td>
                <td style="padding: 8px; font-size: 0.8rem; color: #666;">${c.reason || '-'}</td>
                <td style="padding: 8px; font-size: 0.8rem;">${formatDate(c.created_at)}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    }
    
    showNotification(`Credits loaded for ${customerId}`, 'success');
    
  } catch (err) {
    console.error('Error loading credits:', err);
    creditsList.innerHTML = `<p style="color: #dc3545;">Error: ${err.message}</p>`;
    showNotification(`Failed to load credits: ${err.message}`, 'error');
  }
}

// Helper functions for credit display
function getCreditTypeBadgeColor(type) {
  const colors = {
    overpayment: '#c8e6c9',
    billing_error: '#ffcdd2',
    refund: '#bbdefb',
    promotional: '#e1bee7',
    loyalty: '#fff9c4',
    interest: '#b2dfdb'
  };
  return colors[type] || '#e0e0e0';
}

function formatCreditType(type) {
  const labels = {
    overpayment: 'Overpayment',
    billing_error: 'Billing Error',
    refund: 'Refund',
    promotional: 'Promo',
    loyalty: 'Loyalty',
    interest: 'Interest'
  };
  return labels[type] || type;
}

function formatDate(dateStr) {
  if (!dateStr) return '-';
  const date = new Date(dateStr);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

// Withdraw credit to bank
async function showCreditWithdrawModal() {
  if (!currentCreditsData || currentCreditsData.total_with_interest <= 0) {
    showNotification('No credit balance available to withdraw', 'warning');
    return;
  }
  
  const amount = prompt(
    `Enter amount to withdraw (Available: $${currentCreditsData.total_with_interest.toFixed(2)})`,
    currentCreditsData.total_with_interest.toFixed(2)
  );
  
  if (!amount || isNaN(parseFloat(amount))) return;
  
  const withdrawAmount = parseFloat(amount);
  if (withdrawAmount <= 0 || withdrawAmount > currentCreditsData.total_with_interest) {
    showNotification('Invalid withdrawal amount', 'error');
    return;
  }
  
  try {
    const response = await fetch('/api/billing/credits/withdraw', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        customer_id: currentCreditCustomerId,
        amount: withdrawAmount,
        method: 'bank_transfer'
      })
    });
    
    const result = await response.json();
    
    if (result.success) {
      showNotification(`Withdrawal of $${withdrawAmount.toFixed(2)} initiated! ${result.message || ''}`, 'success');
      await loadCreditsForCustomer(currentCreditCustomerId);
    } else {
      showNotification(`Withdrawal failed: ${result.error}`, 'error');
    }
  } catch (err) {
    console.error('Withdrawal error:', err);
    showNotification(`Error: ${err.message}`, 'error');
  }
}

// Transfer credit to wallet
async function showCreditTransferModal() {
  if (!currentCreditsData || currentCreditsData.total_with_interest <= 0) {
    showNotification('No credit balance available to transfer', 'warning');
    return;
  }
  
  const amount = prompt(
    `Enter amount to transfer to Health Wallet (Available: $${currentCreditsData.total_with_interest.toFixed(2)})`,
    currentCreditsData.total_with_interest.toFixed(2)
  );
  
  if (!amount || isNaN(parseFloat(amount))) return;
  
  const transferAmount = parseFloat(amount);
  if (transferAmount <= 0 || transferAmount > currentCreditsData.total_with_interest) {
    showNotification('Invalid transfer amount', 'error');
    return;
  }
  
  try {
    const response = await fetch('/api/billing/credits/transfer-to-wallet', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        customer_id: currentCreditCustomerId,
        amount: transferAmount,
        wallet_type: 'health_wallet'
      })
    });
    
    const result = await response.json();
    
    if (result.success) {
      showNotification(`$${transferAmount.toFixed(2)} transferred to Health Wallet! New balance: $${result.new_wallet_balance?.toFixed(2) || '0.00'}`, 'success');
      await loadCreditsForCustomer(currentCreditCustomerId);
    } else {
      showNotification(`Transfer failed: ${result.error}`, 'error');
    }
  } catch (err) {
    console.error('Transfer error:', err);
    showNotification(`Error: ${err.message}`, 'error');
  }
}

// Apply credit to outstanding bill
async function showApplyToBillModal() {
  if (!currentCreditsData || currentCreditsData.total_with_interest <= 0) {
    showNotification('No credit balance available to apply', 'warning');
    return;
  }
  
  const billId = prompt('Enter Bill ID to apply credit to:');
  if (!billId || !billId.trim()) return;
  
  const amount = prompt(
    `Enter amount to apply (Available: $${currentCreditsData.total_with_interest.toFixed(2)}, or leave blank for full bill amount)`,
    ''
  );
  
  try {
    const body = {
      customer_id: currentCreditCustomerId,
      bill_id: billId.trim()
    };
    
    if (amount && !isNaN(parseFloat(amount))) {
      body.amount = parseFloat(amount);
    }
    
    const response = await fetch('/api/billing/credits/apply-to-bill', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(body)
    });
    
    const result = await response.json();
    
    if (result.success) {
      showNotification(`$${result.amount_applied?.toFixed(2) || '0.00'} applied to bill ${billId}! Bill status: ${result.bill_status}`, 'success');
      await loadCreditsForCustomer(currentCreditCustomerId);
    } else {
      showNotification(`Apply failed: ${result.error}`, 'error');
    }
  } catch (err) {
    console.error('Apply credit error:', err);
    showNotification(`Error: ${err.message}`, 'error');
  }
}

// Validate billing and detect credits
async function validateMyBilling() {
  const customerId = document.getElementById('credit-customer-id').value.trim() || currentCreditCustomerId;
  
  if (!customerId) {
    showNotification('Please enter a Customer ID first', 'warning');
    return;
  }
  
  try {
    const response = await fetch('/api/billing/validate', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        customer_id: customerId,
        auto_create_credits: true
      })
    });
    
    const result = await response.json();
    
    if (result.is_valid) {
      showNotification('Billing validation passed! No errors detected.', 'success');
    } else {
      const errors = result.errors || [];
      const credits = result.credits_detected || [];
      
      let message = `Found ${errors.length} billing issue(s)`;
      if (credits.length > 0) {
        const totalCredit = credits.reduce((sum, c) => sum + (c.amount || 0), 0);
        message += `. $${totalCredit.toFixed(2)} in credits created.`;
      }
      showNotification(message, 'warning');
      
      // Refresh credits to show new ones
      await loadCreditsForCustomer(customerId);
    }
    
    // Show detailed validation results
    const creditsList = document.getElementById('credits-list');
    if (result.errors?.length > 0 || result.warnings?.length > 0) {
      let detailsHtml = '<div style="margin-top: 16px; padding: 12px; background: #fff3e0; border-radius: 8px;">';
      detailsHtml += '<h4 style="margin: 0 0 8px 0;">⚠️ Validation Results</h4>';
      
      if (result.errors?.length > 0) {
        detailsHtml += '<div style="color: #c62828; margin-bottom: 8px;"><strong>Errors:</strong><ul style="margin: 4px 0;">';
        result.errors.forEach(e => detailsHtml += `<li>${e}</li>`);
        detailsHtml += '</ul></div>';
      }
      
      if (result.warnings?.length > 0) {
        detailsHtml += '<div style="color: #f57c00;"><strong>Warnings:</strong><ul style="margin: 4px 0;">';
        result.warnings.forEach(w => detailsHtml += `<li>${w}</li>`);
        detailsHtml += '</ul></div>';
      }
      
      detailsHtml += '</div>';
      creditsList.innerHTML += detailsHtml;
    }
    
  } catch (err) {
    console.error('Validation error:', err);
    showNotification(`Validation failed: ${err.message}`, 'error');
  }
}

// ============================================================================
// BILLING NOTIFICATIONS
// ============================================================================

// Send billing reminder for current customer
async function sendBillingReminder() {
  const customerId = document.getElementById('credit-customer-id').value.trim() || currentCreditCustomerId;
  
  if (!customerId) {
    showNotification('Please enter a Customer ID first', 'warning');
    return;
  }
  
  const notificationResults = document.getElementById('notification-results');
  notificationResults.innerHTML = '<p class="muted">Sending notifications...</p>';
  
  try {
    const response = await fetch('/api/billing/notify-outstanding', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ customer_id: customerId })
    });
    
    const result = await response.json();
    
    if (result.success) {
      if (result.notifications_sent > 0) {
        showNotification(`${result.notifications_sent} notification(s) sent!`, 'success');
        notificationResults.innerHTML = `
          <div style="padding: 12px; background: #d4edda; border-radius: 8px;">
            <strong>✅ Notifications Sent</strong>
            <p style="margin: 4px 0 0 0;">${result.notifications_sent} notification(s) sent for outstanding bills.</p>
          </div>
        `;
      } else {
        showNotification('No outstanding bills found to notify about', 'info');
        notificationResults.innerHTML = `
          <div style="padding: 12px; background: #d1ecf1; border-radius: 8px;">
            <strong>ℹ️ No Outstanding Bills</strong>
            <p style="margin: 4px 0 0 0;">No outstanding or overdue bills found for this customer.</p>
          </div>
        `;
      }
    } else {
      showNotification(`Failed: ${result.error}`, 'error');
      notificationResults.innerHTML = `<p style="color: #dc3545;">Error: ${result.error}</p>`;
    }
  } catch (err) {
    console.error('Notification error:', err);
    showNotification(`Error: ${err.message}`, 'error');
    notificationResults.innerHTML = `<p style="color: #dc3545;">Error: ${err.message}</p>`;
  }
}

// Send billing reminders to all customers (admin only)
async function sendAllBillingReminders() {
  if (!confirm('This will send notifications to ALL customers with outstanding bills. Continue?')) {
    return;
  }
  
  const notificationResults = document.getElementById('notification-results');
  notificationResults.innerHTML = '<p class="muted">Sending notifications to all customers...</p>';
  
  try {
    const response = await fetch('/api/billing/notify-outstanding', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({})  // No customer_id = all customers
    });
    
    const result = await response.json();
    
    if (result.success) {
      showNotification(`${result.notifications_sent} notification(s) sent to customers!`, 'success');
      notificationResults.innerHTML = `
        <div style="padding: 12px; background: #d4edda; border-radius: 8px;">
          <strong>✅ Bulk Notifications Sent</strong>
          <p style="margin: 4px 0 0 0;">${result.notifications_sent} notification(s) sent to customers with outstanding bills.</p>
        </div>
      `;
    } else {
      showNotification(`Failed: ${result.error}`, 'error');
      notificationResults.innerHTML = `<p style="color: #dc3545;">Error: ${result.error}</p>`;
    }
  } catch (err) {
    console.error('Bulk notification error:', err);
    showNotification(`Error: ${err.message}`, 'error');
    notificationResults.innerHTML = `<p style="color: #dc3545;">Error: ${err.message}</p>`;
  }
}

// ========== AUTO-PAY AI CONFIGURATION FUNCTIONS ==========

// Load auto-pay settings for the selected customer/policy
async function loadAutoPaySettings() {
  const statusIcon = document.getElementById('autopay-status-icon');
  const statusText = document.getElementById('autopay-status-text');
  const nextBilling = document.getElementById('autopay-next-billing');
  const policySelect = document.getElementById('autopay-policy-select');
  
  statusIcon.textContent = '⏳';
  statusText.textContent = 'Loading...';
  
  try {
    // Load customer's policies for the dropdown
    const customerId = document.getElementById('customer_id')?.value || 
                       document.getElementById('billing-customer-select')?.value ||
                       localStorage.getItem('phins_customer_id');
    
    if (!customerId) {
      statusIcon.textContent = '❓';
      statusText.textContent = 'Select a customer first';
      return;
    }
    
    // Fetch customer's policies
    const policiesResponse = await fetch(`/api/policies?customer_id=${customerId}`, {
      headers: { 'Authorization': `Bearer ${localStorage.getItem('phins_token')}` }
    });
    
    if (policiesResponse.ok) {
      const policiesData = await policiesResponse.json();
      const policies = policiesData.items || policiesData.policies || [];
      
      // Populate policy dropdown
      policySelect.innerHTML = '<option value="">-- Select Policy --</option>';
      policies.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.id || p.policy_id;
        opt.textContent = `${p.id || p.policy_id} - ${p.type || 'Insurance'} (${p.status || 'Active'})`;
        policySelect.appendChild(opt);
      });
      
      // If only one policy, select it automatically
      if (policies.length === 1) {
        policySelect.value = policies[0].id || policies[0].policy_id;
        await loadPolicyAutoPayStatus(policies[0].id || policies[0].policy_id, customerId);
      } else if (policies.length > 0) {
        statusIcon.textContent = '📋';
        statusText.textContent = `${policies.length} policies found - select one to configure`;
      } else {
        statusIcon.textContent = '❌';
        statusText.textContent = 'No policies found for this customer';
      }
    }
  } catch (err) {
    console.error('Error loading auto-pay settings:', err);
    statusIcon.textContent = '❌';
    statusText.textContent = 'Error loading settings';
  }
}

// Load auto-pay status for a specific policy
async function loadPolicyAutoPayStatus(policyId, customerId) {
  const statusIcon = document.getElementById('autopay-status-icon');
  const statusText = document.getElementById('autopay-status-text');
  const nextBilling = document.getElementById('autopay-next-billing');
  
  if (!policyId) {
    statusIcon.textContent = '❓';
    statusText.textContent = 'Select a policy';
    return;
  }
  
  try {
    const response = await fetch('/api/billing/auto-pay/settings', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ policy_id: policyId, customer_id: customerId })
    });
    
    if (response.ok) {
      const data = await response.json();
      const autoPay = data.auto_pay || {};
      
      if (autoPay.enabled) {
        statusIcon.textContent = '✅';
        statusText.innerHTML = `<span style="color: #10b981;">Active</span> - ${autoPay.payment_method} (${autoPay.schedule})`;
        
        if (autoPay.next_billing_date) {
          const nextDate = new Date(autoPay.next_billing_date);
          nextBilling.innerHTML = `📅 Next: <strong>${nextDate.toLocaleDateString()}</strong>`;
        }
        
        // Pre-fill form with current settings
        document.getElementById('autopay-enabled').value = 'true';
        document.getElementById('autopay-method').value = autoPay.payment_method_raw || 'credit_card';
        document.getElementById('autopay-card-type').value = autoPay.card_type || 'visa';
        document.getElementById('autopay-card-last4').value = autoPay.card_last4 || '4444';
        document.getElementById('autopay-frequency').value = autoPay.billing_frequency || 'monthly';
        document.getElementById('autopay-billing-day').value = autoPay.billing_day || '1';
        document.getElementById('autopay-ai-optimization').checked = autoPay.ai_optimization || false;
      } else {
        statusIcon.textContent = '⏸️';
        statusText.innerHTML = '<span style="color: #f59e0b;">Not Configured</span> - Click below to enable';
        nextBilling.textContent = '';
      }
    }
  } catch (err) {
    console.error('Error loading policy auto-pay status:', err);
    statusIcon.textContent = '⚠️';
    statusText.textContent = 'Could not load status';
  }
}

// Handle policy selection change for auto-pay
document.addEventListener('DOMContentLoaded', function() {
  const policySelect = document.getElementById('autopay-policy-select');
  if (policySelect) {
    policySelect.addEventListener('change', function() {
      const policyId = this.value;
      const customerId = document.getElementById('customer_id')?.value || 
                         document.getElementById('billing-customer-select')?.value ||
                         localStorage.getItem('phins_customer_id');
      if (policyId && customerId) {
        loadPolicyAutoPayStatus(policyId, customerId);
      }
    });
  }
  
  // Show/hide card fields based on payment method
  const methodSelect = document.getElementById('autopay-method');
  if (methodSelect) {
    methodSelect.addEventListener('change', function() {
      const cardSection = document.getElementById('autopay-card-section');
      const cardLast4Section = document.getElementById('autopay-card-last4-section');
      if (this.value === 'credit_card') {
        cardSection.style.display = 'block';
        cardLast4Section.style.display = 'block';
      } else {
        cardSection.style.display = 'none';
        cardLast4Section.style.display = 'none';
      }
    });
  }
  
  // Initial load
  setTimeout(loadAutoPaySettings, 500);
});

// Save auto-pay configuration
async function saveAutoPayConfig(event) {
  event.preventDefault();
  
  const resultDiv = document.getElementById('autopay-config-result');
  resultDiv.style.display = 'block';
  resultDiv.style.background = '#f8f9fa';
  resultDiv.innerHTML = '⏳ Saving configuration...';
  
  const policyId = document.getElementById('autopay-policy-select').value;
  const customerId = document.getElementById('customer_id')?.value || 
                     document.getElementById('billing-customer-select')?.value ||
                     localStorage.getItem('phins_customer_id');
  
  if (!policyId || !customerId) {
    resultDiv.style.background = '#f8d7da';
    resultDiv.innerHTML = '❌ Please select a customer and policy first';
    return;
  }
  
  const config = {
    customer_id: customerId,
    policy_id: policyId,
    enabled: document.getElementById('autopay-enabled').value === 'true',
    payment_method: document.getElementById('autopay-method').value,
    card_type: document.getElementById('autopay-card-type').value,
    card_last4: document.getElementById('autopay-card-last4').value || '4444',
    billing_frequency: document.getElementById('autopay-frequency').value,
    billing_day: parseInt(document.getElementById('autopay-billing-day').value),
    ai_optimization: document.getElementById('autopay-ai-optimization').checked
  };
  
  try {
    const response = await fetch('/api/billing/auto-pay/configure', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(config)
    });
    
    const result = await response.json();
    
    if (result.success) {
      resultDiv.style.background = '#d4edda';
      resultDiv.innerHTML = `
        <div style="display: flex; align-items: flex-start; gap: 12px;">
          <span style="font-size: 1.5rem;">✅</span>
          <div>
            <strong>Auto-Pay Configured Successfully!</strong>
            <div style="margin-top: 8px; font-size: 0.9rem;">
              <div>${result.auto_pay_config.payment_method_icon} ${result.auto_pay_config.payment_method}</div>
              <div>📅 ${result.auto_pay_config.schedule}</div>
              <div>📆 Next billing: ${result.auto_pay_config.next_billing_date}</div>
              ${result.ai_note ? `<div style="color: #8b5cf6; margin-top: 4px;">🤖 ${result.ai_note}</div>` : ''}
              <div style="font-size: 0.8rem; color: #666; margin-top: 4px;">
                Ledger TX: ${result.ledger_tx_id || 'N/A'} | NFT: ${result.nft_token_id || 'N/A'}
              </div>
            </div>
          </div>
        </div>
      `;
      
      // Refresh status panel
      loadPolicyAutoPayStatus(policyId, customerId);
      
      // Reload transactions to show any changes
      loadRecentTransactions();
      
      showNotification('Auto-pay configured successfully!', 'success');
    } else {
      resultDiv.style.background = '#f8d7da';
      resultDiv.innerHTML = `❌ Error: ${result.error}`;
      showNotification(`Failed: ${result.error}`, 'error');
    }
  } catch (err) {
    console.error('Error saving auto-pay config:', err);
    resultDiv.style.background = '#f8d7da';
    resultDiv.innerHTML = `❌ Error: ${err.message}`;
    showNotification(`Error: ${err.message}`, 'error');
  }
}

// Execute auto-pay manually
async function executeAutoPay() {
  const policyId = document.getElementById('autopay-policy-select').value;
  const customerId = document.getElementById('customer_id')?.value || 
                     document.getElementById('billing-customer-select')?.value ||
                     localStorage.getItem('phins_customer_id');
  
  const resultDiv = document.getElementById('autopay-config-result');
  resultDiv.style.display = 'block';
  resultDiv.style.background = '#f8f9fa';
  resultDiv.innerHTML = '⏳ Executing auto-pay...';
  
  // First do a dry run
  if (!confirm('Execute auto-pay now? This will process payment for the selected policy.')) {
    resultDiv.innerHTML = 'Cancelled';
    return;
  }
  
  try {
    const response = await fetch('/api/billing/auto-pay/execute', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        policy_id: policyId,
        customer_id: customerId,
        dry_run: false
      })
    });
    
    const result = await response.json();
    
    if (result.success) {
      if (result.processed > 0) {
        resultDiv.style.background = '#d4edda';
        resultDiv.innerHTML = `
          <div style="display: flex; align-items: flex-start; gap: 12px;">
            <span style="font-size: 1.5rem;">✅</span>
            <div>
              <strong>Auto-Pay Executed Successfully!</strong>
              <div style="margin-top: 8px; font-size: 0.9rem;">
                <div>💰 Total: <strong>$${result.total_amount.toFixed(2)}</strong></div>
                <div>📝 Payments processed: ${result.processed}</div>
                ${result.payments.map(p => `
                  <div style="margin-top: 4px; padding: 6px; background: rgba(0,0,0,0.05); border-radius: 4px;">
                    Policy: ${p.policy_id} | Amount: $${p.amount.toFixed(2)} | ${p.payment_method}
                    <br>Next billing: ${p.next_billing_date}
                  </div>
                `).join('')}
              </div>
            </div>
          </div>
        `;
        
        showNotification(`Processed ${result.processed} payment(s) totaling $${result.total_amount.toFixed(2)}`, 'success');
      } else {
        resultDiv.style.background = '#fff3cd';
        resultDiv.innerHTML = `
          <div style="display: flex; align-items: center; gap: 12px;">
            <span style="font-size: 1.5rem;">ℹ️</span>
            <div>
              <strong>No Payments Due</strong>
              <div style="font-size: 0.9rem; margin-top: 4px;">
                ${result.message}
              </div>
            </div>
          </div>
        `;
        showNotification('No auto-pay payments due', 'info');
      }
      
      // Reload transactions
      loadRecentTransactions();
      
      // Refresh status
      if (policyId && customerId) {
        loadPolicyAutoPayStatus(policyId, customerId);
      }
    } else {
      resultDiv.style.background = '#f8d7da';
      resultDiv.innerHTML = `❌ Error: ${result.error}`;
      showNotification(`Failed: ${result.error}`, 'error');
    }
  } catch (err) {
    console.error('Error executing auto-pay:', err);
    resultDiv.style.background = '#f8d7da';
    resultDiv.innerHTML = `❌ Error: ${err.message}`;
    showNotification(`Error: ${err.message}`, 'error');
  }
}

// Update auto-pay settings when customer selection changes
if (typeof loadCustomerPoliciesForBilling === 'function') {
  const originalLoadCustomerPolicies = loadCustomerPoliciesForBilling;
  loadCustomerPoliciesForBilling = async function() {
    await originalLoadCustomerPolicies.apply(this, arguments);
    // Also load auto-pay settings
    setTimeout(loadAutoPaySettings, 300);
  };
}

// Expose functions globally
window.loadAutoPaySettings = loadAutoPaySettings;
window.loadPolicyAutoPayStatus = loadPolicyAutoPayStatus;
window.saveAutoPayConfig = saveAutoPayConfig;
window.executeAutoPay = executeAutoPay;

// ==================== CUSTOMER REFUND FUNCTIONS ====================

/** Delay (ms) before retrying a failed refund API call (handles transient ledger sync issues). */
const REFUND_RETRY_DELAY_MS = 1500;

/**
 * Return a user-friendly message when a refund fails due to a "not found" / sync error.
 * @param {string} errMsg - The error string from the API or exception.
 * @returns {string}
 */
function refundSyncErrorMessage(errMsg) {
  return `${errMsg} — If this transaction was recently created, please wait a moment and try again. Ledger records may take a few seconds to sync.`;
}

/**
 * Load refundable (paid) bills for a customer and display them.
 */
async function loadRefundableBills(event) {
  if (event) event.preventDefault();
  const customerId = document.getElementById('refund-customer-id').value.trim();
  if (!customerId) return;

  const listEl = document.getElementById('refundable-bills-list');
  const resultEl = document.getElementById('refund-result');
  resultEl.style.display = 'none';
  listEl.innerHTML = '<p style="color:#666;">⏳ Loading refundable bills...</p>';

  // Helper: escape text content to prevent XSS in HTML
  function escHtml(str) {
    const d = document.createElement('div');
    d.textContent = String(str);
    return d.innerHTML;
  }

  try {
    const response = await fetch(`/api/billing/refundable?customer_id=${encodeURIComponent(customerId)}`, {
      headers: { 'Authorization': `Bearer ${localStorage.getItem('phins_token')}` }
    });
    const data = await response.json();

    if (!response.ok) {
      listEl.innerHTML = `<p style="color:#dc3545;">❌ ${escHtml(data.error || 'Failed to load bills')}</p>`;
      return;
    }

    const bills = data.refundable_bills || [];
    if (bills.length === 0) {
      listEl.innerHTML = `
        <div style="text-align:center;padding:24px;color:#666;">
          <div style="font-size:2.5rem;margin-bottom:8px;">✅</div>
          <div style="font-weight:600;">No refundable bills found</div>
          <div style="font-size:0.85rem;margin-top:4px;">All paid bills have already been refunded or no paid bills exist.</div>
        </div>`;
      return;
    }

    // Build HTML using safe escaping for all server-supplied strings
    listEl.innerHTML = bills.map((bill, idx) => {
      const paidDate = bill.paid_date ? new Date(bill.paid_date).toLocaleDateString() : 'N/A';
      const policyLabel = escHtml(
        bill.policy_id
          ? `${bill.policy_id}${bill.policy_type && bill.policy_type !== 'N/A' ? ' · ' + bill.policy_type : ''}`
          : 'N/A'
      );
      const alreadyRefundedHtml = bill.already_refunded > 0
        ? `<div style="font-size:0.8rem;color:#856404;">Already refunded: $${bill.already_refunded.toFixed(2)}</div>`
        : '';
      return `
        <div style="border:1px solid #e0e0e0;border-radius:8px;padding:14px;margin-bottom:10px;background:#fff;">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
            <div style="flex:1;min-width:180px;">
              <div style="font-weight:700;color:#333;font-size:0.95rem;">${escHtml(bill.bill_id)}</div>
              <div style="font-size:0.8rem;color:#666;margin-top:2px;">Policy: ${policyLabel}</div>
              <div style="font-size:0.8rem;color:#666;">Paid on: ${escHtml(paidDate)}</div>
              ${alreadyRefundedHtml}
            </div>
            <div style="text-align:right;min-width:140px;">
              <div style="font-size:1.1rem;font-weight:700;color:#28a745;">↩️ $${bill.refundable_amount.toFixed(2)}</div>
              <div style="font-size:0.75rem;color:#666;">refundable</div>
              <div style="margin-top:8px;">
                <button class="btn refund-bill-btn"
                  data-bill-idx="${idx}"
                  style="background:linear-gradient(135deg,#ffc107 0%,#e0a800 100%);color:#000;font-weight:600;padding:6px 14px;font-size:0.85rem;">
                  ↩️ Refund to Wallet
                </button>
              </div>
            </div>
          </div>
        </div>`;
    }).join('');

    // Attach event listeners using stored bill data (no inline script / interpolated IDs)
    listEl.querySelectorAll('.refund-bill-btn').forEach(btn => {
      const idx = parseInt(btn.getAttribute('data-bill-idx'), 10);
      const bill = bills[idx];
      btn.addEventListener('click', () => {
        confirmCustomerRefund(bill.bill_id, customerId, bill.refundable_amount);
      });
    });
  } catch (err) {
    listEl.innerHTML = `<p style="color:#dc3545;">❌ Error: ${escHtml(err.message)}</p>`;
  }
}

/**
 * Show confirmation dialog before processing refund.
 */
function confirmCustomerRefund(billId, customerId, amount) {
  // Sanitize user-visible text (confirm() renders plain text, but we guard against non-string values)
  const safeBillId = String(billId).replace(/[^\w\-]/g, '');
  const confirmed = confirm(
    `↩️ Confirm Refund\n\nBill ID: ${safeBillId}\nRefund Amount: $${Number(amount).toFixed(2)}\nDestination: 💊 Health Wallet\n\nThe refunded amount will be instantly deposited to your Health Wallet and recorded in the ledger.\n\nProceed?`
  );
  if (confirmed) {
    processCustomerRefund(billId, customerId, amount);
  }
}

/**
 * Process a customer refund via the API and show the result.
 * Includes one automatic retry for transient sync/network errors.
 */
async function processCustomerRefund(billId, customerId, amount) {
  const resultEl = document.getElementById('refund-result');
  const badgeEl = document.getElementById('refund-status-badge');
  resultEl.style.display = 'none';

  // Validate inputs before sending to the API
  const safeBillId = String(billId || '').trim();
  const safeCustomerId = String(customerId || '').trim();
  if (!safeBillId || !safeCustomerId) {
    resultEl.style.background = '#f8d7da';
    resultEl.style.border = '1px solid #dc3545';
    resultEl.style.borderRadius = '8px';
    resultEl.innerHTML = '<div style="color:#721c24;font-weight:600;">❌ Refund Failed</div><div style="margin-top:6px;font-size:0.9rem;">Bill ID and Customer ID are required to process a refund.</div>';
    resultEl.style.display = 'block';
    return;
  }

  // Helper: perform the refund API call
  async function attemptRefund() {
    return fetch('/api/billing/customer-refund', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('phins_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        bill_id: safeBillId,
        customer_id: safeCustomerId,
        amount: amount,
        reason: 'Customer refund request'
      })
    });
  }

  try {
    let response;
    try {
      response = await attemptRefund();
    } catch (networkErr) {
      // Retry once after a brief delay to handle transient ledger sync issues
      await new Promise(resolve => setTimeout(resolve, REFUND_RETRY_DELAY_MS));
      response = await attemptRefund();
    }

    const result = await response.json();

    if (result.success) {
      // Use DOM API to safely set text values from server response
      const refundId = document.createElement('code');
      refundId.style.fontSize = '0.8rem';
      refundId.textContent = result.refund_id || 'N/A';

      const ledgerTx = document.createElement('code');
      ledgerTx.textContent = result.ledger_tx_id || 'N/A';

      const nftToken = document.createElement('code');
      nftToken.textContent = result.nft_token_id || 'N/A';

      resultEl.style.background = 'linear-gradient(135deg,#e8f5e9 0%,#f1f8e9 100%)';
      resultEl.style.border = '1px solid #43a047';
      resultEl.style.borderRadius = '8px';
      resultEl.innerHTML = `
        <div style="font-size:1.1rem;font-weight:700;color:#2e7d32;margin-bottom:8px;">✅ Refund Processed!</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;font-size:0.9rem;">
          <div><strong>Refund ID:</strong><br><span id="_rfid"></span></div>
          <div><strong>Amount Refunded:</strong><br><span style="color:#28a745;font-weight:700;">$${Number(result.refund_amount).toFixed(2)}</span></div>
          <div><strong>Deposited To:</strong><br>💊 Health Wallet</div>
          <div><strong>New Wallet Balance:</strong><br><span style="color:#1565c0;font-weight:700;">$${Number(result.wallet_balance_after).toFixed(2)}</span></div>
        </div>
        <div style="margin-top:10px;padding:8px;background:#fff;border-radius:6px;font-size:0.8rem;color:#555;">
          🔗 Ledger TX: <span id="_ltx"></span> &nbsp;|&nbsp;
          🔐 NFT Token: <span id="_nft"></span>
        </div>`;
      resultEl.querySelector('#_rfid').appendChild(refundId);
      resultEl.querySelector('#_ltx').appendChild(ledgerTx);
      resultEl.querySelector('#_nft').appendChild(nftToken);
      resultEl.style.display = 'block';
      if (badgeEl) {
        badgeEl.textContent = '✅ Refunded';
        badgeEl.style.background = '#d4edda';
        badgeEl.style.color = '#155724';
      }
      // Reload the refundable bills list to reflect updated state
      loadRefundableBills(null);
      // Reload stats and transactions in the page
      if (typeof loadStats === 'function') loadStats();
      if (typeof loadRecentTransactions === 'function') loadRecentTransactions();
    } else {
      const errMsg = result.error || 'Unknown error';
      // Provide a user-friendly hint when the error suggests a sync or not-found issue
      const displayMsg = (errMsg.toLowerCase().includes('not found') || errMsg.toLowerCase().includes('sync'))
        ? refundSyncErrorMessage(errMsg)
        : errMsg;
      resultEl.style.background = '#f8d7da';
      resultEl.style.border = '1px solid #dc3545';
      resultEl.style.borderRadius = '8px';
      resultEl.innerHTML = '<div style="color:#721c24;font-weight:600;">❌ Refund Failed</div><div style="margin-top:6px;font-size:0.9rem;" id="_rferr"></div>';
      resultEl.querySelector('#_rferr').textContent = displayMsg;
      resultEl.style.display = 'block';
    }
  } catch (err) {
    resultEl.style.background = '#f8d7da';
    resultEl.style.border = '1px solid #dc3545';
    resultEl.style.borderRadius = '8px';
    resultEl.innerHTML = '<div style="color:#721c24;font-weight:600;">❌ Error</div><div style="margin-top:6px;font-size:0.9rem;" id="_rferr2"></div>';
    resultEl.querySelector('#_rferr2').textContent = `Request failed. Please check your connection and try again. (${err.message})`;
    resultEl.style.display = 'block';
  }
}

// Expose refund functions globally
window.loadRefundableBills = loadRefundableBills;
window.confirmCustomerRefund = confirmCustomerRefund;
window.processCustomerRefund = processCustomerRefund;
