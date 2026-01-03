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
    usdc: '💵'
  };
  
  container.innerHTML = methods.map(method => `
    <div class="payment-method-card ${method.id === selectedPaymentMethod ? 'selected' : ''}" 
         onclick="selectPaymentMethod('${method.id}')" 
         data-method="${method.id}">
      <div class="icon">${icons[method.id] || '💰'}</div>
      <div class="name">${method.name}</div>
      <div class="badge test">TEST</div>
    </div>
  `).join('');
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
    
    const list = document.getElementById('transaction-list');
    
    if (transactions.length === 0) {
      list.innerHTML = '<p class="muted">No recent transactions</p>';
      return;
    }
    
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
      const csvData = lastTransactions.map(t => ({
        Transaction_ID: t.id || t.transaction_id,
        Customer_ID: t.customer_id,
        Customer_Name: t.customer_name || 'N/A',
        Type: t.type,
        Amount: t.amount,
        Status: t.status,
        Date: t.date,
        Payment_Method: t.payment_method || 'N/A'
      }));
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

// Export Marketplace Transactions
async function exportMarketplace(format) {
  try {
    const response = await fetch('/api/marketplace/transactions', {
      headers: { 'Authorization': `Bearer ${localStorage.getItem('phins_token')}` }
    });
    const data = await response.json();
    lastMarketplaceData = data.transactions || data || [];
    
    if (lastMarketplaceData.length === 0) {
      alert('No marketplace transactions to export');
      return;
    }
    
    if (format === 'csv') {
      const csvData = lastMarketplaceData.map(t => ({
        Transaction_ID: t.transaction_id || t.id,
        Type: t.type,
        Description: t.description || t.item_name || 'N/A',
        Amount: t.amount,
        Insurance_Covered: t.insurance_covered || 0,
        Customer_Paid: t.customer_paid || t.amount,
        Status: t.status,
        Date: t.date || t.created_at,
        NFT_ID: t.nft_token_id || 'N/A'
      }));
      downloadCSV(csvData, 'PHINS_Marketplace_Transactions');
    } else if (format === 'pdf') {
      const content = `
        <p><strong>Total Marketplace Transactions:</strong> ${lastMarketplaceData.length}</p>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Type</th>
              <th>Description</th>
              <th>Amount</th>
              <th>Status</th>
              <th>Date</th>
            </tr>
          </thead>
          <tbody>
            ${lastMarketplaceData.slice(0, 50).map(t => `
              <tr>
                <td>${t.transaction_id || t.id}</td>
                <td>${t.type}</td>
                <td>${t.description || t.item_name || 'N/A'}</td>
                <td>${formatCurrencyExport(t.amount)}</td>
                <td>${t.status}</td>
                <td>${new Date(t.date || t.created_at).toLocaleDateString()}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
      exportPDF('Marketplace Transaction Report', content);
    }
  } catch (err) {
    alert('Error exporting marketplace data: ' + err.message);
  }
}

// ========== TRANSACTION LEDGER FUNCTIONS ==========
let lastLedgerData = [];
let currentLedgerFilter = 'all';

async function loadLedger(filter = 'all') {
  currentLedgerFilter = filter;
  const token = localStorage.getItem('phins_token');
  
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
    document.getElementById('ledger-total').textContent = data.total_entries || lastLedgerData.length;
    document.getElementById('ledger-nft').textContent = data.nft_ledger_count || lastLedgerData.filter(e => e.metadata?.nft_token_id).length;
    
    displayLedger(lastLedgerData);
    
    // Update tab active state
    document.querySelectorAll('#ledger-list').forEach(tab => {
      tab.classList.remove('active');
    });
    
  } catch (err) {
    console.error('Failed to load ledger:', err);
    document.getElementById('ledger-list').innerHTML = '<p class="muted">Unable to load ledger entries.</p>';
  }
}

function displayLedger(entries) {
  const container = document.getElementById('ledger-list');
  
  if (!entries || entries.length === 0) {
    container.innerHTML = '<p class="muted">No ledger entries found.</p>';
    return;
  }
  
  const typeIcons = {
    'policy_approved': '✅',
    'billing_created': '📄',
    'claim_payment_received': '💰',
    'claim_payout': '💸',
    'health_wallet_activated': '💳',
    'pipeline_initialized': '🔄',
    'payment_received': '💵',
    'premium_payment': '💳',
    'default': '📒'
  };
  
  const typeColors = {
    'policy_approved': '#28a745',
    'billing_created': '#007bff',
    'claim_payment_received': '#ffc107',
    'claim_payout': '#dc3545',
    'health_wallet_activated': '#17a2b8',
    'pipeline_initialized': '#6f42c1',
    'payment_received': '#28a745',
    'premium_payment': '#28a745',
    'default': '#6c757d'
  };
  
  container.innerHTML = entries.map(entry => {
    const icon = typeIcons[entry.type] || typeIcons.default;
    const color = typeColors[entry.type] || typeColors.default;
    const nftId = entry.metadata?.nft_token_id;
    
    return `
      <div class="transaction-item" style="border-left: 4px solid ${color};">
        <div class="tx-details">
          <strong>${icon} ${entry.id}</strong>
          <span class="tx-type" style="background: ${color}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; margin-left: 8px;">
            ${(entry.type || 'unknown').replace(/_/g, ' ')}
          </span>
          ${nftId ? `<span style="background: #9c27b0; color: white; padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; margin-left: 4px;">🔗 NFT</span>` : ''}
        </div>
        <div style="margin-top: 5px; color: #555;">${entry.description || 'No description'}</div>
        <div class="tx-meta" style="margin-top: 8px; font-size: 0.85rem; color: #888;">
          <span>Customer: ${entry.customer_id || 'N/A'}</span>
          <span>Amount: ${formatCurrencyExport(entry.amount || 0)}</span>
          <span>${new Date(entry.timestamp).toLocaleString()}</span>
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
