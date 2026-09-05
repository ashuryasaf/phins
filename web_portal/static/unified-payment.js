/**
 * PHINS Unified Payment System
 * ============================
 * Versatile payment modal supporting all deposit destinations and payment methods
 * 
 * Payment Methods:
 * - Credit/Debit Card (via Stripe)
 * - Apple Pay / Google Pay
 * - PayPal
 * - Cryptocurrency (BTC, ETH, USDC)
 * - Bank Transfer
 * - Internal Transfer (between PHINS accounts)
 * 
 * Destinations:
 * - Health Wallet
 * - Investment Account
 * - Algo Trading Account
 */

class UnifiedPaymentModal {
  constructor(options = {}) {
    // Get customer ID from multiple sources - NO HARDCODED FALLBACK
    this.customerId = options.customerId 
                   || sessionStorage.getItem('customer_id') 
                   || localStorage.getItem('customer_id')
                   || '';
    
    if (!this.customerId) {
      console.error('UnifiedPaymentModal: No customer ID provided');
      throw new Error('Customer ID is required for payment operations');
    }
    
    this.authToken = options.authToken || localStorage.getItem('phins_token');
    this.onSuccess = options.onSuccess || (() => {});
    this.onError = options.onError || (() => {});
    this.defaultDestination = options.defaultDestination || 'health_wallet';
    
    this.balances = {};
    this.paymentMethods = [];
    this.destinations = [];
    
    this.init();
  }
  
  async init() {
    await this.loadBalances();
    this.createModal();
    this.attachEventListeners();
  }
  
  async loadBalances() {
    try {
      const response = await fetch('/api/unified-payment/balances', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.authToken}`
        },
        body: JSON.stringify({ customer_id: this.customerId })
      });
      
      const data = await response.json();
      if (data.success) {
        this.balances = data.balances;
        this.paymentMethods = data.payment_methods;
        this.destinations = data.destinations;
        this.totalAssets = data.total_assets;
      }
    } catch (err) {
      console.error('Failed to load balances:', err);
    }
  }
  
  createModal() {
    // Remove existing modal if any
    const existing = document.getElementById('unified-payment-modal');
    if (existing) existing.remove();
    
    const modal = document.createElement('div');
    modal.id = 'unified-payment-modal';
    modal.innerHTML = `
      <div class="upm-overlay" onclick="unifiedPayment.close()"></div>
      <div class="upm-container">
        <div class="upm-header">
          <h2>Add Funds</h2>
          <button class="upm-close" onclick="unifiedPayment.close()">Close</button>
        </div>
        
        <div class="upm-content">
          <!-- Step 1: Select Destination -->
          <div class="upm-step" id="upm-step-destination">
            <h3>Select Destination</h3>
            <div class="upm-destinations" id="upm-destinations">
              ${this.destinations.map(d => `
                <div class="upm-dest-card ${d.id === this.defaultDestination ? 'selected' : ''}" data-dest="${d.id}" onclick="unifiedPayment.selectDestination('${d.id}')">
                  <span class="upm-dest-icon">${d.icon}</span>
                  <div class="upm-dest-info">
                    <div class="upm-dest-name">${d.name}</div>
                    <div class="upm-dest-balance">Balance: $${(this.balances[d.id]?.balance || 0).toLocaleString(undefined, {minimumFractionDigits: 2})}</div>
                  </div>
                  <div class="upm-dest-check"></div>
                </div>
              `).join('')}
            </div>
          </div>
          
          <!-- Step 2: Enter Amount -->
          <div class="upm-step">
            <h3>Enter Amount</h3>
            <div class="upm-amount-container">
              <span class="upm-currency">$</span>
              <input type="number" id="upm-amount" class="upm-amount-input" placeholder="0.00" min="1" max="1000000" step="0.01" oninput="unifiedPayment.updateAmount()">
            </div>
            <div class="upm-quick-amounts">
              <button onclick="unifiedPayment.setAmount(50)">$50</button>
              <button onclick="unifiedPayment.setAmount(100)">$100</button>
              <button onclick="unifiedPayment.setAmount(250)">$250</button>
              <button onclick="unifiedPayment.setAmount(500)">$500</button>
              <button onclick="unifiedPayment.setAmount(1000)">$1,000</button>
            </div>
          </div>
          
          <!-- Step 3: Select Payment Method -->
          <div class="upm-step">
            <h3>Payment Method</h3>
            <div class="upm-methods" id="upm-methods">
              <div class="upm-method-group">
                <div class="upm-method-group-title">Cards & Wallets</div>
                <div class="upm-method-options">
                  <div class="upm-method selected" data-method="credit_card" onclick="unifiedPayment.selectMethod('credit_card')">
                    <span class="upm-method-icon">CARD</span>
                    <span class="upm-method-name">Credit Card</span>
                  </div>
                  <div class="upm-method" data-method="debit_card" onclick="unifiedPayment.selectMethod('debit_card')">
                    <span class="upm-method-icon">DEBIT</span>
                    <span class="upm-method-name">Debit Card</span>
                  </div>
                  <div class="upm-method" data-method="apple_pay" onclick="unifiedPayment.selectMethod('apple_pay')">
                    <span class="upm-method-icon">APPLE</span>
                    <span class="upm-method-name">Apple Pay</span>
                  </div>
                  <div class="upm-method" data-method="google_pay" onclick="unifiedPayment.selectMethod('google_pay')">
                    <span class="upm-method-icon">GPay</span>
                    <span class="upm-method-name">Google Pay</span>
                  </div>
                  <div class="upm-method" data-method="paypal" onclick="unifiedPayment.selectMethod('paypal')">
                    <span class="upm-method-icon">PAYPAL</span>
                    <span class="upm-method-name">PayPal</span>
                  </div>
                </div>
              </div>
              
              <div class="upm-method-group">
                <div class="upm-method-group-title">Cryptocurrency</div>
                <div class="upm-method-options">
                  <div class="upm-method" data-method="crypto_btc" onclick="unifiedPayment.selectMethod('crypto_btc')">
                    <span class="upm-method-icon">BTC</span>
                    <span class="upm-method-name">Bitcoin</span>
                  </div>
                  <div class="upm-method" data-method="crypto_eth" onclick="unifiedPayment.selectMethod('crypto_eth')">
                    <span class="upm-method-icon">ETH</span>
                    <span class="upm-method-name">Ethereum</span>
                  </div>
                  <div class="upm-method" data-method="crypto_usdc" onclick="unifiedPayment.selectMethod('crypto_usdc')">
                    <span class="upm-method-icon">USDC</span>
                    <span class="upm-method-name">USDC</span>
                  </div>
                </div>
              </div>
              
              <div class="upm-method-group">
                <div class="upm-method-group-title">Transfer</div>
                <div class="upm-method-options">
                  <div class="upm-method" data-method="bank_transfer" onclick="unifiedPayment.selectMethod('bank_transfer')">
                    <span class="upm-method-icon">BANK</span>
                    <span class="upm-method-name">Bank Transfer</span>
                  </div>
                  <div class="upm-method" data-method="internal_transfer" onclick="unifiedPayment.selectMethod('internal_transfer')">
                    <span class="upm-method-icon">INTERNAL</span>
                    <span class="upm-method-name">Internal Transfer</span>
                  </div>
                </div>
              </div>
            </div>
            
            <!-- Internal Transfer Source Selection -->
            <div class="upm-internal-source" id="upm-internal-source" style="display: none;">
              <h4>Transfer From:</h4>
              <div class="upm-source-options" id="upm-source-options"></div>
            </div>
            
            <!-- Card Input (for credit/debit card) -->
            <div class="upm-card-input" id="upm-card-input" style="display: none;">
              <input type="text" id="upm-card-number" placeholder="Card Number" maxlength="19" oninput="unifiedPayment.formatCardNumber(this)">
              <div class="upm-card-row">
                <input type="text" id="upm-card-expiry" placeholder="MM/YY" maxlength="5" oninput="unifiedPayment.formatExpiry(this)">
                <input type="text" id="upm-card-cvv" placeholder="CVV" maxlength="4">
              </div>
            </div>
          </div>
          
          <!-- Summary -->
          <div class="upm-summary" id="upm-summary">
            <div class="upm-summary-row">
              <span>Amount</span>
              <span id="upm-summary-amount">$0.00</span>
            </div>
            <div class="upm-summary-row">
              <span>Destination</span>
              <span id="upm-summary-dest">Health Wallet</span>
            </div>
            <div class="upm-summary-row">
              <span>Method</span>
              <span id="upm-summary-method">Credit Card</span>
            </div>
            <div class="upm-summary-row upm-summary-total">
              <span>Total</span>
              <span id="upm-summary-total">$0.00</span>
            </div>
          </div>
          
          <!-- Validation Messages -->
          <div class="upm-validation" id="upm-validation"></div>
        </div>
        
        <div class="upm-footer">
          <button class="upm-btn upm-btn-secondary" onclick="unifiedPayment.close()">Cancel</button>
          <button class="upm-btn upm-btn-primary" id="upm-submit-btn" onclick="unifiedPayment.submit()">
            <span id="upm-submit-text">Add Funds</span>
            <span id="upm-submit-loading" style="display: none;">Processing...</span>
          </button>
        </div>
      </div>
    `;
    
    // Add styles
    const styles = document.createElement('style');
    styles.id = 'unified-payment-styles';
    styles.textContent = `
      #unified-payment-modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 10000; }
      #unified-payment-modal.open { display: block; }
      .upm-overlay { position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); backdrop-filter: blur(4px); }
      .upm-container { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); background: white; border-radius: 20px; width: 90%; max-width: 520px; max-height: 90vh; overflow-y: auto; box-shadow: 0 20px 60px rgba(0,0,0,0.3); }
      .upm-header { display: flex; justify-content: space-between; align-items: center; padding: 20px 24px; border-bottom: 1px solid #eee; background: linear-gradient(135deg, #1565c0 0%, #1976d2 100%); color: white; border-radius: 20px 20px 0 0; }
      .upm-header h2 { margin: 0; font-size: 1.3rem; }
      .upm-close { background: rgba(255,255,255,0.2); border: none; color: white; width: 32px; height: 32px; border-radius: 50%; cursor: pointer; font-size: 1.2rem; }
      .upm-content { padding: 24px; }
      .upm-step { margin-bottom: 24px; }
      .upm-step h3 { margin: 0 0 12px 0; font-size: 1rem; color: #333; }
      
      .upm-destinations { display: flex; flex-direction: column; gap: 10px; }
      .upm-dest-card { display: flex; align-items: center; gap: 12px; padding: 14px 16px; border: 2px solid #e0e0e0; border-radius: 12px; cursor: pointer; transition: all 0.2s; }
      .upm-dest-card:hover { border-color: #1565c0; background: #f5f9fc; }
      .upm-dest-card.selected { border-color: #1565c0; background: #e3f2fd; }
      .upm-dest-icon { font-size: 1.5rem; }
      .upm-dest-info { flex: 1; }
      .upm-dest-name { font-weight: 600; color: #333; }
      .upm-dest-balance { font-size: 0.85rem; color: #666; }
      .upm-dest-check { width: 24px; height: 24px; border-radius: 50%; background: #1565c0; color: white; display: none; align-items: center; justify-content: center; font-size: 0.9rem; }
      .upm-dest-card.selected .upm-dest-check { display: flex; }
      
      .upm-amount-container { display: flex; align-items: center; border: 2px solid #e0e0e0; border-radius: 12px; padding: 4px 16px; background: #fafafa; }
      .upm-currency { font-size: 1.5rem; color: #666; margin-right: 8px; }
      .upm-amount-input { flex: 1; border: none; background: none; font-size: 2rem; font-weight: 700; color: #1565c0; outline: none; }
      .upm-quick-amounts { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
      .upm-quick-amounts button { padding: 8px 16px; border: 1px solid #ddd; border-radius: 8px; background: white; cursor: pointer; font-weight: 500; transition: all 0.2s; }
      .upm-quick-amounts button:hover { background: #1565c0; color: white; border-color: #1565c0; }
      
      .upm-method-group { margin-bottom: 16px; }
      .upm-method-group-title { font-size: 0.85rem; color: #666; margin-bottom: 8px; font-weight: 600; }
      .upm-method-options { display: flex; flex-wrap: wrap; gap: 8px; }
      .upm-method { display: flex; align-items: center; gap: 8px; padding: 10px 14px; border: 2px solid #e0e0e0; border-radius: 10px; cursor: pointer; transition: all 0.2s; background: white; }
      .upm-method:hover { border-color: #1565c0; }
      .upm-method.selected { border-color: #1565c0; background: #e3f2fd; }
      .upm-method-icon { font-size: 1.2rem; }
      .upm-method-name { font-size: 0.9rem; font-weight: 500; }
      
      .upm-internal-source { margin-top: 16px; padding: 16px; background: #f5f5f5; border-radius: 12px; }
      .upm-internal-source h4 { margin: 0 0 12px 0; font-size: 0.95rem; }
      .upm-source-options { display: flex; flex-direction: column; gap: 8px; }
      .upm-source-option { display: flex; align-items: center; gap: 12px; padding: 12px; border: 2px solid #e0e0e0; border-radius: 10px; cursor: pointer; background: white; }
      .upm-source-option:hover { border-color: #1565c0; }
      .upm-source-option.selected { border-color: #1565c0; background: #e3f2fd; }
      .upm-source-option.disabled { opacity: 0.5; cursor: not-allowed; }
      
      .upm-card-input { margin-top: 16px; display: flex; flex-direction: column; gap: 12px; }
      .upm-card-input input { padding: 14px 16px; border: 2px solid #e0e0e0; border-radius: 10px; font-size: 1rem; }
      .upm-card-input input:focus { border-color: #1565c0; outline: none; }
      .upm-card-row { display: flex; gap: 12px; }
      .upm-card-row input { flex: 1; }
      
      .upm-summary { background: #f8f9fa; border-radius: 12px; padding: 16px; margin-top: 8px; }
      .upm-summary-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #e0e0e0; }
      .upm-summary-row:last-child { border-bottom: none; }
      .upm-summary-total { font-weight: 700; font-size: 1.1rem; color: #1565c0; border-top: 2px solid #1565c0; margin-top: 8px; padding-top: 12px; }
      
      .upm-validation { margin-top: 12px; }
      .upm-validation .error { color: #c62828; font-size: 0.9rem; padding: 8px 12px; background: #ffebee; border-radius: 8px; margin-bottom: 8px; }
      .upm-validation .warning { color: #f57c00; font-size: 0.9rem; padding: 8px 12px; background: #fff3e0; border-radius: 8px; margin-bottom: 8px; }
      
      .upm-footer { display: flex; justify-content: flex-end; gap: 12px; padding: 16px 24px; border-top: 1px solid #eee; }
      .upm-btn { padding: 12px 24px; border-radius: 10px; font-size: 1rem; font-weight: 600; cursor: pointer; transition: all 0.2s; border: none; }
      .upm-btn-secondary { background: #f5f5f5; color: #666; }
      .upm-btn-secondary:hover { background: #e0e0e0; }
      .upm-btn-primary { background: linear-gradient(135deg, #1565c0 0%, #1976d2 100%); color: white; }
      .upm-btn-primary:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(21,101,192,0.3); }
      .upm-btn-primary:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
      
      @media (max-width: 600px) {
        .upm-container { width: 95%; max-height: 85vh; border-radius: 16px 16px 0 0; top: auto; bottom: 0; transform: translate(-50%, 0); }
        .upm-method-options { flex-direction: column; }
        .upm-quick-amounts button { flex: 1; min-width: calc(33% - 8px); }
      }
    `;
    
    // Check if styles already exist
    if (!document.getElementById('unified-payment-styles')) {
      document.head.appendChild(styles);
    }
    
    document.body.appendChild(modal);
    this.modal = modal;
    this.selectedDestination = this.defaultDestination;
    this.selectedMethod = 'credit_card';
    this.selectedSource = null;
  }
  
  attachEventListeners() {
    // Amount input
    const amountInput = document.getElementById('upm-amount');
    if (amountInput) {
      amountInput.addEventListener('input', () => this.updateSummary());
    }
  }
  
  open(options = {}) {
    if (options.destination) {
      this.selectDestination(options.destination);
    }
    if (options.amount) {
      this.setAmount(options.amount);
    }
    
    this.loadBalances().then(() => {
      this.updateSourceOptions();
      this.modal.classList.add('open');
    });
  }
  
  close() {
    this.modal.classList.remove('open');
  }
  
  selectDestination(destId) {
    this.selectedDestination = destId;
    
    // Update UI
    document.querySelectorAll('.upm-dest-card').forEach(card => {
      card.classList.toggle('selected', card.dataset.dest === destId);
    });
    
    this.updateSourceOptions();
    this.updateSummary();
  }
  
  selectMethod(methodId) {
    this.selectedMethod = methodId;
    
    // Update UI
    document.querySelectorAll('.upm-method').forEach(method => {
      method.classList.toggle('selected', method.dataset.method === methodId);
    });
    
    // Show/hide card input
    const cardInput = document.getElementById('upm-card-input');
    if (cardInput) {
      cardInput.style.display = ['credit_card', 'debit_card'].includes(methodId) ? 'flex' : 'none';
    }
    
    // Show/hide internal transfer source
    const sourceSection = document.getElementById('upm-internal-source');
    if (sourceSection) {
      sourceSection.style.display = methodId === 'internal_transfer' ? 'block' : 'none';
    }
    
    this.updateSummary();
  }
  
  selectSource(sourceId) {
    this.selectedSource = sourceId;
    
    // Update UI
    document.querySelectorAll('.upm-source-option').forEach(option => {
      option.classList.toggle('selected', option.dataset.source === sourceId);
    });
    
    this.updateSummary();
  }
  
  updateSourceOptions() {
    const container = document.getElementById('upm-source-options');
    if (!container) return;
    
    const sources = Object.entries(this.balances)
      .filter(([id]) => id !== this.selectedDestination && id !== 'pipeline_cash')
      .map(([id, data]) => ({
        id,
        name: data.name,
        icon: data.icon,
        balance: data.balance,
        canWithdraw: data.can_withdraw
      }));
    
    container.innerHTML = sources.map(s => `
      <div class="upm-source-option ${s.canWithdraw ? '' : 'disabled'}" data-source="${s.id}" onclick="unifiedPayment.selectSource('${s.id}')">
        <span style="font-size: 1.3rem;">${s.icon}</span>
        <div style="flex: 1;">
          <div style="font-weight: 600;">${s.name}</div>
          <div style="font-size: 0.85rem; color: #666;">Available: $${s.balance.toLocaleString(undefined, {minimumFractionDigits: 2})}</div>
        </div>
        <div style="width: 20px; height: 20px; border-radius: 50%; border: 2px solid #1565c0; display: flex; align-items: center; justify-content: center;">
          <div style="width: 12px; height: 12px; border-radius: 50%; background: #1565c0; display: none;"></div>
        </div>
      </div>
    `).join('');
    
    // Select first available source
    if (sources.length > 0 && sources[0].canWithdraw) {
      this.selectSource(sources[0].id);
    }
  }
  
  setAmount(amount) {
    const input = document.getElementById('upm-amount');
    if (input) {
      input.value = amount;
      this.updateSummary();
    }
  }
  
  updateAmount() {
    this.updateSummary();
  }
  
  updateSummary() {
    const amount = parseFloat(document.getElementById('upm-amount')?.value) || 0;
    
    document.getElementById('upm-summary-amount').textContent = `$${amount.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
    document.getElementById('upm-summary-total').textContent = `$${amount.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
    
    const destData = this.destinations.find(d => d.id === this.selectedDestination);
    document.getElementById('upm-summary-dest').textContent = destData?.name || 'Unknown';
    
    const methodNames = {
      'credit_card': 'Credit Card',
      'debit_card': 'Debit Card',
      'apple_pay': 'Apple Pay',
      'google_pay': 'Google Pay',
      'paypal': 'PayPal',
      'crypto_btc': 'Bitcoin',
      'crypto_eth': 'Ethereum',
      'crypto_usdc': 'USDC',
      'bank_transfer': 'Bank Transfer',
      'internal_transfer': 'Internal Transfer'
    };
    document.getElementById('upm-summary-method').textContent = methodNames[this.selectedMethod] || this.selectedMethod;
  }
  
  formatCardNumber(input) {
    let value = input.value.replace(/\D/g, '');
    value = value.replace(/(.{4})/g, '$1 ').trim();
    input.value = value.substring(0, 19);
  }
  
  formatExpiry(input) {
    let value = input.value.replace(/\D/g, '');
    if (value.length >= 2) {
      value = value.substring(0, 2) + '/' + value.substring(2);
    }
    input.value = value.substring(0, 5);
  }
  
  async validate() {
    const amount = parseFloat(document.getElementById('upm-amount')?.value) || 0;
    
    try {
      const response = await fetch('/api/unified-payment/validate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.authToken}`
        },
        body: JSON.stringify({
          customer_id: this.customerId,
          amount: amount,
          destination: this.selectedDestination,
          payment_method: this.selectedMethod,
          source_account: this.selectedSource
        })
      });
      
      const data = await response.json();
      
      const validationDiv = document.getElementById('upm-validation');
      validationDiv.innerHTML = '';
      
      if (data.errors && data.errors.length > 0) {
        data.errors.forEach(err => {
          validationDiv.innerHTML += `<div class="error">${err}</div>`;
        });
      }
      
      if (data.warnings && data.warnings.length > 0) {
        data.warnings.forEach(warn => {
          validationDiv.innerHTML += `<div class="warning">${warn}</div>`;
        });
      }
      
      return data.valid;
    } catch (err) {
      console.error('Validation error:', err);
      return false;
    }
  }
  
  async submit() {
    const submitBtn = document.getElementById('upm-submit-btn');
    const submitText = document.getElementById('upm-submit-text');
    const submitLoading = document.getElementById('upm-submit-loading');
    
    // Validate first
    const isValid = await this.validate();
    if (!isValid) return;
    
    // Show loading
    submitBtn.disabled = true;
    submitText.style.display = 'none';
    submitLoading.style.display = 'inline';
    
    const amount = parseFloat(document.getElementById('upm-amount')?.value) || 0;
    
    try {
      const payload = {
        customer_id: this.customerId,
        amount: amount,
        destination: this.selectedDestination,
        payment_method: this.selectedMethod,
        description: `Add funds to ${this.selectedDestination.replace('_', ' ')}`
      };
      
      if (this.selectedMethod === 'internal_transfer') {
        payload.source_account = this.selectedSource;
      }
      
      // Add card details if card payment
      if (['credit_card', 'debit_card'].includes(this.selectedMethod)) {
        payload.card_number = document.getElementById('upm-card-number')?.value?.replace(/\s/g, '');
        payload.card_expiry = document.getElementById('upm-card-expiry')?.value;
        payload.card_cvv = document.getElementById('upm-card-cvv')?.value;
      }
      
      const response = await fetch('/api/unified-payment/deposit', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.authToken}`
        },
        body: JSON.stringify(payload)
      });
      
      const result = await response.json();
      
      if (result.success) {
        this.close();
        this.onSuccess(result);
        
        // Show success notification
        if (typeof showNotification === 'function') {
          showNotification(`Successfully added $${amount.toLocaleString(undefined, {minimumFractionDigits: 2})} to ${this.selectedDestination.replace('_', ' ')}`, 'success');
        } else {
          alert(`Successfully added $${amount.toLocaleString(undefined, {minimumFractionDigits: 2})}!\n\nTransaction ID: ${result.transaction_id}\nNew Balance: $${result.destination_new_balance?.toLocaleString(undefined, {minimumFractionDigits: 2}) || 'N/A'}`);
        }
      } else {
        throw new Error(result.error || 'Payment failed');
      }
      
    } catch (err) {
      console.error('Payment error:', err);
      this.onError(err);
      
      const validationDiv = document.getElementById('upm-validation');
      validationDiv.innerHTML = `<div class="error">${err.message}</div>`;
      
    } finally {
      submitBtn.disabled = false;
      submitText.style.display = 'inline';
      submitLoading.style.display = 'none';
    }
  }
}

// Global instance
let unifiedPayment = null;

// Initialize on DOM load
function initUnifiedPayment(options = {}) {
  unifiedPayment = new UnifiedPaymentModal(options);
  return unifiedPayment;
}

// Quick open functions for different contexts
function openAddFundsModal(destination = 'health_wallet', amount = null) {
  if (!unifiedPayment) {
    unifiedPayment = new UnifiedPaymentModal({ defaultDestination: destination });
  }
  unifiedPayment.open({ destination, amount });
}

function openHealthWalletDeposit(amount = null) {
  openAddFundsModal('health_wallet', amount);
}

function openInvestmentDeposit(amount = null) {
  openAddFundsModal('investment', amount);
}

function openAlgoTradingDeposit(amount = null) {
  openAddFundsModal('algo_trading', amount);
}
