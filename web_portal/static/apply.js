// Customer Application JavaScript - PHINS Unified Contract
let currentStep = 1;
const totalSteps = 5;
let formData = {};

// PHINS Unified Contract allocation state
let allocationState = {
    savings: 25,
    investment: 35,
    healthWallet: 15,
    disability: 25,
    strategy: 'balanced',
    term: 15
};

// AI Bot configuration state
let aiBotConfig = {
    riskProfile: 'moderate',
    assets: ['stocks', 'bonds'],
    strategy: 'balanced',
    stopLoss: true,
    diversification: true,
    rebalancing: true
};

// Card type patterns for validation
const CARD_PATTERNS = {
    visa: { regex: /^4/, icon: '💳', name: 'Visa', lengths: [13, 16, 19], cvv: 3 },
    mastercard: { regex: /^(5[1-5]|2[2-7])/, icon: '🔵', name: 'Mastercard', lengths: [16], cvv: 3 },
    amex: { regex: /^3[47]/, icon: '💠', name: 'American Express', lengths: [15], cvv: 4 },
    discover: { regex: /^(6011|65|644|645|646|647|648|649)/, icon: '🟠', name: 'Discover', lengths: [16, 19], cvv: 3 }
};

// Strategy presets for allocation
const STRATEGY_PRESETS = {
    conservative: { savings: 40, investment: 25, healthWallet: 15, disability: 20 },
    balanced: { savings: 25, investment: 35, healthWallet: 15, disability: 25 },
    growth: { savings: 15, investment: 45, healthWallet: 10, disability: 30 },
    custom: null // User-defined
};

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    setupAllocationListeners();
    setupAIBotListeners();
    setupTermListeners();
    updateStepDisplay();
    populateExpiryYears();
    
    // Initialize coverage slider display
    const coverageSlider = document.getElementById('coverage-slider');
    if (coverageSlider) {
        coverageSlider.addEventListener('input', updateCoverageDisplay);
        // Set initial display
        updateCoverageDisplay();
    }
    
    // Initialize allocation displays
    updateAllocationDisplay();
    updateAIBotPreview();
    
    // Initial premium calculations (will update again when DOB is entered)
    setTimeout(() => {
        updatePremiumCalculations();
    }, 100);
});

function setupEventListeners() {
    // Navigation buttons
    document.getElementById('next-btn').addEventListener('click', nextStep);
    document.getElementById('prev-btn').addEventListener('click', prevStep);
    document.getElementById('customer-application-form').addEventListener('submit', handleSubmit);
    
    // Policy selection
    document.querySelectorAll('.select-policy').forEach(btn => {
        btn.addEventListener('click', selectPolicy);
    });
    
    // Coverage slider
    const slider = document.getElementById('coverage-slider');
    if (slider) {
        slider.addEventListener('input', updateCoverageDisplay);
    }
    
    // Quick amount buttons for coverage
    document.querySelectorAll('.quick-amount').forEach(btn => {
        btn.addEventListener('click', function() {
            const amount = parseInt(this.dataset.amount);
            const slider = document.getElementById('coverage-slider');
            if (slider) {
                slider.value = amount;
                updateCoverageDisplay();
            }
            
            document.querySelectorAll('.quick-amount').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
        });
    });
    
    // BMI calculation
    document.getElementById('height').addEventListener('input', calculateBMI);
    document.getElementById('weight').addEventListener('input', calculateBMI);
    
    // Card number validation (Step 4)
    const cardInput = document.getElementById('card-number');
    if (cardInput) {
        cardInput.addEventListener('input', handleCardInput);
        cardInput.addEventListener('blur', validateCardNumber);
    }
    
    // Health wallet toggle
    const healthWalletCheckbox = document.getElementById('enable-health-wallet');
    if (healthWalletCheckbox) {
        healthWalletCheckbox.addEventListener('change', function() {
            document.getElementById('health-wallet-options').style.display = this.checked ? 'block' : 'none';
        });
    }
    
    // Custom deposit amount
    const depositSelect = document.getElementById('monthly-deposit');
    if (depositSelect) {
        depositSelect.addEventListener('change', function() {
            document.getElementById('custom-deposit-group').style.display = 
                this.value === 'custom' ? 'block' : 'none';
        });
    }
    
    // Real-time validation for Step 1 fields
    const step1Fields = ['first-name', 'last-name', 'email', 'phone', 'dob'];
    step1Fields.forEach(fieldId => {
        const field = document.getElementById(fieldId);
        if (field) {
            field.addEventListener('blur', function() {
                validateField(this);
            });
            field.addEventListener('input', function() {
                // Clear error styling on input
                this.style.borderColor = '';
            });
        }
    });
    
    // Conditional fields
    document.querySelectorAll('input[name="medical-conditions"]').forEach(radio => {
        radio.addEventListener('change', function() {
            document.getElementById('medical-details').style.display = 
                this.value === 'yes' ? 'block' : 'none';
        });
    });
    
    document.querySelectorAll('input[name="surgery"]').forEach(radio => {
        radio.addEventListener('change', function() {
            document.getElementById('surgery-details').style.display = 
                this.value === 'yes' ? 'block' : 'none';
        });
    });
    
    // Family history "none" checkbox exclusive behavior
    document.querySelectorAll('input[name="family-history"]').forEach(checkbox => {
        checkbox.addEventListener('change', function() {
            if (this.value === 'none' && this.checked) {
                document.querySelectorAll('input[name="family-history"]').forEach(cb => {
                    if (cb.value !== 'none') cb.checked = false;
                });
            } else if (this.value !== 'none' && this.checked) {
                document.querySelector('input[name="family-history"][value="none"]').checked = false;
            }
        });
    });
}

// ============================================
// PHINS UNIFIED CONTRACT - ALLOCATION SYSTEM
// ============================================

function setupAllocationListeners() {
    // Strategy toggle listeners
    document.querySelectorAll('.strategy-option').forEach(option => {
        option.addEventListener('click', function() {
            selectStrategy(this.dataset.strategy);
        });
    });
    
    // Allocation slider listeners
    const sliderIds = ['savings-allocation', 'investment-allocation', 'health-wallet-allocation', 'disability-allocation'];
    sliderIds.forEach(id => {
        const slider = document.getElementById(id);
        if (slider) {
            slider.addEventListener('input', function() {
                handleAllocationChange(id, parseInt(this.value));
            });
        }
    });
}

function selectStrategy(strategy) {
    // Update UI
    document.querySelectorAll('.strategy-option').forEach(opt => {
        opt.classList.remove('active');
    });
    document.querySelector(`.strategy-option[data-strategy="${strategy}"]`)?.classList.add('active');
    
    allocationState.strategy = strategy;
    
    // Apply preset if not custom
    if (strategy !== 'custom' && STRATEGY_PRESETS[strategy]) {
        const preset = STRATEGY_PRESETS[strategy];
        allocationState.savings = preset.savings;
        allocationState.investment = preset.investment;
        allocationState.healthWallet = preset.healthWallet;
        allocationState.disability = preset.disability;
        
        // Update sliders
        document.getElementById('savings-allocation').value = preset.savings;
        document.getElementById('investment-allocation').value = preset.investment;
        document.getElementById('health-wallet-allocation').value = preset.healthWallet;
        document.getElementById('disability-allocation').value = preset.disability;
    }
    
    updateAllocationDisplay();
    updatePremiumCalculations();
}

function handleAllocationChange(sliderId, value) {
    // Switch to custom strategy when user adjusts sliders
    if (allocationState.strategy !== 'custom') {
        selectStrategy('custom');
    }
    
    // Map slider IDs to state properties
    const mapping = {
        'savings-allocation': 'savings',
        'investment-allocation': 'investment',
        'health-wallet-allocation': 'healthWallet',
        'disability-allocation': 'disability'
    };
    
    const prop = mapping[sliderId];
    if (!prop) return;
    
    // Calculate how much room we have
    const otherAllocations = Object.entries(allocationState)
        .filter(([key]) => key !== prop && key !== 'strategy' && key !== 'term')
        .reduce((sum, [, val]) => sum + val, 0);
    
    // Ensure total doesn't exceed 100%
    const maxValue = 100 - otherAllocations;
    const adjustedValue = Math.min(value, maxValue);
    
    allocationState[prop] = adjustedValue;
    document.getElementById(sliderId).value = adjustedValue;
    
    // Auto-balance if total < 100%
    const total = allocationState.savings + allocationState.investment + 
                  allocationState.healthWallet + allocationState.disability;
    
    if (total < 100) {
        // Add remainder to disability (or next available)
        const remainder = 100 - total;
        if (prop !== 'disability') {
            allocationState.disability = Math.min(50, allocationState.disability + remainder);
            document.getElementById('disability-allocation').value = allocationState.disability;
        }
    }
    
    updateAllocationDisplay();
    updatePremiumCalculations();
}

function updateAllocationDisplay() {
    // Update percentage displays
    document.getElementById('savings-pct-display').textContent = `${allocationState.savings}%`;
    document.getElementById('investment-pct-display').textContent = `${allocationState.investment}%`;
    document.getElementById('health-wallet-pct-display').textContent = `${allocationState.healthWallet}%`;
    document.getElementById('disability-pct-display').textContent = `${allocationState.disability}%`;
    
    // Update allocation bar
    document.getElementById('total-savings-bar').style.width = `${allocationState.savings}%`;
    document.getElementById('total-investment-bar').style.width = `${allocationState.investment}%`;
    document.getElementById('total-health-bar').style.width = `${allocationState.healthWallet}%`;
    document.getElementById('total-disability-bar').style.width = `${allocationState.disability}%`;
    
    // Update total status
    const total = allocationState.savings + allocationState.investment + 
                  allocationState.healthWallet + allocationState.disability;
    const statusEl = document.getElementById('allocation-status');
    
    if (total === 100) {
        statusEl.innerHTML = '<span class="status-icon">✅</span><span class="status-text">Allocation Complete: 100%</span>';
        statusEl.classList.remove('error');
    } else {
        statusEl.innerHTML = `<span class="status-icon">⚠️</span><span class="status-text">Allocation: ${total}% (must equal 100%)</span>`;
        statusEl.classList.add('error');
    }
}

// ============================================
// AI BOT CONFIGURATION
// ============================================

function setupAIBotListeners() {
    // Risk profile
    const riskSelect = document.getElementById('ai-risk-profile');
    if (riskSelect) {
        riskSelect.addEventListener('change', function() {
            aiBotConfig.riskProfile = this.value;
            updateAIBotPreview();
        });
    }
    
    // Strategy
    const strategySelect = document.getElementById('ai-strategy');
    if (strategySelect) {
        strategySelect.addEventListener('change', function() {
            aiBotConfig.strategy = this.value;
            updateAIBotPreview();
        });
    }
    
    // Asset checkboxes
    document.querySelectorAll('input[name="ai-assets"]').forEach(checkbox => {
        checkbox.addEventListener('change', function() {
            const selectedAssets = Array.from(document.querySelectorAll('input[name="ai-assets"]:checked'))
                .map(cb => cb.value);
            aiBotConfig.assets = selectedAssets;
            updateAIBotPreview();
        });
    });
    
    // Safety settings
    const safetyIds = ['stop-loss', 'diversification', 'rebalancing'];
    safetyIds.forEach(id => {
        const checkbox = document.getElementById(id);
        if (checkbox) {
            checkbox.addEventListener('change', function() {
                aiBotConfig[id.replace('-', '')] = this.checked;
                updateAIBotPreview();
            });
        }
    });
}

function updateAIBotPreview() {
    // Expected return based on risk profile and assets
    const returnRanges = {
        conservative: '4-7%',
        moderate: '8-12%',
        aggressive: '12-18%',
        ai_optimized: '10-15%'
    };
    
    const riskLabels = {
        conservative: 'Low',
        moderate: 'Moderate',
        aggressive: 'High',
        ai_optimized: 'AI-Adjusted'
    };
    
    const freqLabels = {
        dca: 'Daily DCA',
        momentum: 'Real-Time',
        value: 'Monthly',
        balanced: 'Weekly Rebalance',
        custom: 'AI-Determined'
    };
    
    // Adjust return based on assets
    let baseReturn = returnRanges[aiBotConfig.riskProfile] || '8-12%';
    if (aiBotConfig.assets.includes('crypto')) {
        baseReturn = baseReturn.replace(/(\d+)-(\d+)/, (m, low, high) => 
            `${parseInt(low) + 2}-${parseInt(high) + 5}%`);
    }
    
    document.getElementById('expected-return').textContent = baseReturn + ' annually';
    document.getElementById('risk-level').textContent = riskLabels[aiBotConfig.riskProfile] || 'Moderate';
    document.getElementById('trading-freq').textContent = freqLabels[aiBotConfig.strategy] || 'Weekly Rebalance';
}

// ============================================
// TERM SELECTION
// ============================================

function setupTermListeners() {
    document.querySelectorAll('.term-option').forEach(option => {
        option.addEventListener('click', function() {
            // Update UI
            document.querySelectorAll('.term-option').forEach(opt => opt.classList.remove('active'));
            this.classList.add('active');
            
            // Update state
            allocationState.term = parseInt(this.dataset.years);
            document.getElementById('savings-term').value = allocationState.term;
            
            // Recalculate projections
            updatePremiumCalculations();
        });
    });
}

// ============================================
// PREMIUM CALCULATIONS WITH PROJECTIONS
// ============================================

function updatePremiumCalculations() {
    const coverageAmount = parseInt(document.getElementById('coverage-slider')?.value || 500000);
    const dob = document.getElementById('dob')?.value;
    const age = dob ? calculateAge(dob) : 35;
    
    // Base premium calculation
    const basePremiumPerThousand = 0.35; // $0.35 per $1000 coverage
    const ageFactor = 1.0 + (Math.max(0, age - 25) * 0.025);
    
    // Calculate annual premium based on coverage
    let annualPremium = (coverageAmount / 1000) * basePremiumPerThousand * ageFactor * 12;
    
    // Minimum premium of $1200/year
    annualPremium = Math.max(1200, annualPremium);
    
    const monthlyPremium = annualPremium / 12;
    const quarterlyPremium = annualPremium / 4;
    const annualWithDiscount = annualPremium * 0.90; // 10% annual discount
    
    // Update premium displays
    document.getElementById('monthly-premium').textContent = formatCurrency(monthlyPremium);
    document.getElementById('quarterly-premium').textContent = formatCurrency(quarterlyPremium);
    document.getElementById('annual-premium').textContent = formatCurrency(annualWithDiscount);
    
    // Update allocation amount displays
    const savingsAmount = monthlyPremium * (allocationState.savings / 100);
    const investmentAmount = monthlyPremium * (allocationState.investment / 100);
    const healthWalletAmount = monthlyPremium * (allocationState.healthWallet / 100);
    const disabilityAmount = monthlyPremium * (allocationState.disability / 100);
    
    document.getElementById('savings-amount-display').textContent = `${formatCurrency(savingsAmount)}/mo`;
    document.getElementById('investment-amount-display').textContent = `${formatCurrency(investmentAmount)}/mo`;
    document.getElementById('health-wallet-amount-display').textContent = `${formatCurrency(healthWalletAmount)}/mo`;
    document.getElementById('disability-amount-display').textContent = `${formatCurrency(disabilityAmount)}/mo`;
    
    // Update breakdown
    document.getElementById('breakdown-savings').textContent = formatCurrency(savingsAmount);
    document.getElementById('breakdown-investment').textContent = formatCurrency(investmentAmount);
    document.getElementById('breakdown-health').textContent = formatCurrency(healthWalletAmount);
    document.getElementById('breakdown-disability').textContent = formatCurrency(disabilityAmount);
    
    // Calculate projections
    calculateProjections(savingsAmount, investmentAmount, coverageAmount);
    
    // Store for later
    formData.premiums = {
        monthly: monthlyPremium,
        quarterly: quarterlyPremium,
        annual: annualWithDiscount,
        fullAnnual: annualPremium
    };
    
    formData.allocation = {
        savings: { pct: allocationState.savings, amount: savingsAmount },
        investment: { pct: allocationState.investment, amount: investmentAmount },
        healthWallet: { pct: allocationState.healthWallet, amount: healthWalletAmount },
        disability: { pct: allocationState.disability, amount: disabilityAmount }
    };
}

function calculateProjections(monthlySavings, monthlyInvestment, coverageAmount) {
    const years = allocationState.term;
    
    // Savings projection (4% annual return, compounded)
    const savingsRate = 0.04;
    const totalSavingsMonths = years * 12;
    const savingsProjection = monthlySavings * 
        ((Math.pow(1 + savingsRate/12, totalSavingsMonths) - 1) / (savingsRate/12));
    
    // Investment projection (based on risk profile)
    const investmentRates = {
        conservative: 0.06,
        moderate: 0.10,
        aggressive: 0.14,
        ai_optimized: 0.12
    };
    const investmentRate = investmentRates[aiBotConfig.riskProfile] || 0.10;
    const investmentProjection = monthlyInvestment * 
        ((Math.pow(1 + investmentRate/12, totalSavingsMonths) - 1) / (investmentRate/12));
    
    // Total contract value
    const totalProjection = savingsProjection + investmentProjection + coverageAmount;
    
    // Update displays
    document.getElementById('proj-savings').textContent = formatCurrency(savingsProjection);
    document.getElementById('proj-investment').textContent = formatCurrency(investmentProjection);
    document.getElementById('proj-coverage').textContent = formatCurrency(coverageAmount);
    document.getElementById('proj-total').textContent = formatCurrency(totalProjection);
    
    // Update projection preview title with term
    const projTitle = document.querySelector('.projection-preview h4');
    if (projTitle) {
        projTitle.textContent = `📊 Projected Growth (${years} Years)`;
    }
    
    formData.projections = {
        savings: savingsProjection,
        investment: investmentProjection,
        coverage: coverageAmount,
        total: totalProjection,
        term: years
    };
}

function formatCurrency(amount) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
    }).format(amount);
}

// ============================================
// POLICY SELECTION (Legacy support)
// ============================================

function selectPolicy(e) {
    const type = e.target.dataset.type || 'phins_unified';
    
    // Update UI
    document.querySelectorAll('.policy-option').forEach(option => {
        option.classList.remove('selected');
    });
    if (e.target.closest('.policy-option')) {
        e.target.closest('.policy-option').classList.add('selected');
    }
    
    // Set hidden input - PHINS unified is the default
    document.getElementById('policy-type').value = 'phins_unified';
    
    // Update premium estimate
    updatePremiumCalculations();
}

function updateCoverageDisplay() {
    const amount = parseInt(document.getElementById('coverage-slider').value);
    document.getElementById('coverage-amount-display').textContent = 
        new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 }).format(amount);
    
    // Update projections and premium calculations
    updatePremiumCalculations();
}

function calculatePremium(coverageAmount) {
    // Deprecated - use updatePremiumCalculations() instead
    updatePremiumCalculations();
}

function calculateAge(dobString) {
    const dob = new Date(dobString);
    const today = new Date();
    let age = today.getFullYear() - dob.getFullYear();
    const monthDiff = today.getMonth() - dob.getMonth();
    if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < dob.getDate())) {
        age--;
    }
    return age;
}

function calculateBMI() {
    const height = parseFloat(document.getElementById('height').value);
    const weight = parseFloat(document.getElementById('weight').value);
    
    if (height && weight && height > 0) {
        const bmi = (weight / ((height / 100) ** 2)).toFixed(1);
        document.getElementById('bmi-value').textContent = bmi;
        
        let category = '';
        let color = '';
        
        if (bmi < 18.5) {
            category = 'Underweight';
            color = '#ffc107';
        } else if (bmi < 25) {
            category = 'Normal';
            color = '#28a745';
        } else if (bmi < 30) {
            category = 'Overweight';
            color = '#ff9800';
        } else {
            category = 'Obese';
            color = '#dc3545';
        }
        
        const categoryEl = document.getElementById('bmi-category');
        categoryEl.textContent = category;
        categoryEl.style.color = color;
    }
}

// Populate expiry years dropdown
function populateExpiryYears() {
    const yearSelect = document.getElementById('expiry-year');
    if (!yearSelect) return;
    
    const currentYear = new Date().getFullYear();
    for (let year = currentYear; year <= currentYear + 15; year++) {
        const option = document.createElement('option');
        option.value = year;
        option.textContent = year;
        yearSelect.appendChild(option);
    }
}

// Card number formatting and detection
function formatCardNumber(value) {
    const cleaned = value.replace(/\D/g, '');
    const groups = cleaned.match(/.{1,4}/g) || [];
    return groups.join(' ').substr(0, 23);
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

function handleCardInput(e) {
    const input = e.target;
    const formatted = formatCardNumber(input.value);
    input.value = formatted;
    
    const cardType = detectCardType(formatted);
    const iconSpan = document.getElementById('card-type-icon');
    const validationDiv = document.getElementById('card-validation-msg');
    
    if (cardType) {
        iconSpan.textContent = cardType.icon;
        iconSpan.title = cardType.name;
        
        const digits = formatted.replace(/\D/g, '').length;
        const expectedLength = cardType.type === 'mastercard' ? 16 : cardType.lengths[cardType.lengths.length - 1];
        
        if (digits < expectedLength) {
            validationDiv.innerHTML = `<span style="color: #666;">${cardType.name} - ${digits}/${expectedLength} digits</span>`;
        } else {
            validateCardNumber();
        }
        
        // Update CVV max length
        const cvvInput = document.getElementById('cvv');
        if (cvvInput) {
            cvvInput.maxLength = cardType.cvv;
            cvvInput.placeholder = cardType.cvv === 4 ? '****' : '***';
        }
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
    const input = document.getElementById('card-number');
    const validationDiv = document.getElementById('card-validation-msg');
    if (!input || !validationDiv) return false;
    
    const cardNumber = input.value.replace(/\D/g, '');
    
    if (cardNumber.length === 0) {
        validationDiv.innerHTML = '';
        input.style.borderColor = '';
        return false;
    }
    
    const cardType = detectCardType(cardNumber);
    
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
    
    // Luhn check
    if (!luhnCheck(cardNumber)) {
        validationDiv.innerHTML = '<span style="color: #dc3545;">❌ Invalid card number</span>';
        input.style.borderColor = '#dc3545';
        return false;
    }
    
    validationDiv.innerHTML = `<span style="color: #28a745;">✅ Valid ${cardType.name} card</span>`;
    input.style.borderColor = '#28a745';
    return true;
}

function nextStep() {
    if (!validateStep(currentStep)) {
        return;
    }
    
    saveStepData(currentStep);
    
    if (currentStep < totalSteps) {
        currentStep++;
        updateStepDisplay();
        
        if (currentStep === 5) {
            populateReview();
        }
        
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
}

function prevStep() {
    if (currentStep > 1) {
        currentStep--;
        updateStepDisplay();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
}

function goToStep(step) {
    currentStep = step;
    updateStepDisplay();
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function updateStepDisplay() {
    // Update progress bar
    document.querySelectorAll('.progress-step').forEach((step, index) => {
        if (index + 1 < currentStep) {
            step.classList.add('completed');
            step.classList.remove('active');
        } else if (index + 1 === currentStep) {
            step.classList.add('active');
            step.classList.remove('completed');
        } else {
            step.classList.remove('active', 'completed');
        }
    });
    
    // Update form steps
    document.querySelectorAll('.form-step').forEach(step => {
        step.classList.remove('active');
    });
    document.querySelector(`.form-step[data-step="${currentStep}"]`).classList.add('active');
    
    // Update navigation buttons
    document.getElementById('prev-btn').style.display = currentStep === 1 ? 'none' : 'block';
    document.getElementById('next-btn').style.display = currentStep === totalSteps ? 'none' : 'block';
    document.getElementById('submit-btn').style.display = currentStep === totalSteps ? 'block' : 'none';
}

// Field validation function
function validateField(field) {
    let isValid = true;
    let errorMessage = '';
    
    // Check if field is required and empty
    if (field.required && !field.value.trim()) {
        isValid = false;
        errorMessage = 'This field is required';
    }
    
    // Specific format validations
    if (isValid && field.value.trim()) {
        switch(field.id) {
            case 'first-name':
            case 'last-name':
                // Name validation: letters, spaces, hyphens, apostrophes only (2-100 chars)
                if (!/^[a-zA-Z\s\-']{2,100}$/.test(field.value)) {
                    isValid = false;
                    errorMessage = 'Only letters, spaces, hyphens, and apostrophes allowed (2-100 characters)';
                }
                break;
                
            case 'email':
                // Email format validation
                if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(field.value)) {
                    isValid = false;
                    errorMessage = 'Please enter a valid email address (e.g., name@example.com)';
                }
                break;
                
            case 'phone':
                // Phone format validation (7-30 chars, allows international format)
                const phoneRegex = /^\+?[\d\s\-\(\)\.]{7,30}$/;
                const digitCount = field.value.replace(/\D/g, '').length;
                if (!phoneRegex.test(field.value) || digitCount < 7) {
                    isValid = false;
                    errorMessage = 'Please enter a valid phone number (e.g., +1-555-0123 or 555-0123)';
                }
                break;
                
            case 'dob':
                // Age validation: must be 18-100 years old
                const birthDate = new Date(field.value);
                const today = new Date();
                let age = today.getFullYear() - birthDate.getFullYear();
                const monthDiff = today.getMonth() - birthDate.getMonth();
                if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birthDate.getDate())) {
                    age--;
                }
                
                if (age < 18) {
                    isValid = false;
                    errorMessage = 'Applicant must be at least 18 years old';
                } else if (age > 100) {
                    isValid = false;
                    errorMessage = 'Please enter a valid date of birth';
                }
                break;
                
            case 'zip':
                // ZIP code validation: 5 digits or 5+4 format
                if (!/^\d{5}(-\d{4})?$/.test(field.value)) {
                    isValid = false;
                    errorMessage = 'Please enter a valid ZIP code (e.g., 12345 or 12345-6789)';
                }
                break;
        }
    }
    
    // Visual feedback
    if (!isValid) {
        field.style.borderColor = '#dc3545';
        field.style.backgroundColor = '#fff5f5';
        // Show error message if available
        if (errorMessage) {
            field.title = errorMessage;
        }
    } else {
        field.style.borderColor = '#28a745';
        field.style.backgroundColor = '';
        field.title = '';
    }
    
    return isValid;
}

function validateStep(step) {
    const currentStepEl = document.querySelector(`.form-step[data-step="${step}"]`);
    const inputs = currentStepEl.querySelectorAll('input[required], select[required], textarea[required]');
    
    let isValid = true;
    let firstInvalidField = null;
    let errorMessages = [];
    
    inputs.forEach(input => {
        const fieldValid = validateField(input);
        if (!fieldValid) {
            isValid = false;
            if (!firstInvalidField) {
                firstInvalidField = input;
            }
            // Collect error message
            if (input.title) {
                errorMessages.push(`${input.previousElementSibling?.textContent || input.placeholder || 'Field'}: ${input.title}`);
            }
        }
    });
    
    // Additional validations
    if (step === 2) {
        // Validate allocation equals 100%
        const total = allocationState.savings + allocationState.investment + 
                      allocationState.healthWallet + allocationState.disability;
        
        if (total !== 100) {
            alert(`Premium allocation must equal 100%. Current: ${total}%`);
            isValid = false;
        }
        
        // Ensure coverage amount is selected
        const coverageAmount = parseInt(document.getElementById('coverage-slider')?.value || 0);
        if (coverageAmount < 100000) {
            alert('Please select a coverage amount of at least $100,000');
            isValid = false;
        }
    }
    
    // Step 4: Payment validation
    if (step === 4) {
        // Validate card number with Mastercard 16-digit check
        if (!validateCardNumber()) {
            errorMessages.push('Please enter a valid card number (Mastercard must be 16 digits)');
            isValid = false;
        }
        
        // Validate expiry
        const month = document.getElementById('expiry-month').value;
        const year = document.getElementById('expiry-year').value;
        if (month && year) {
            const now = new Date();
            const expiry = new Date(parseInt(year), parseInt(month) - 1);
            if (expiry < now) {
                errorMessages.push('Card has expired');
                isValid = false;
            }
        }
        
        // Validate CVV
        const cvv = document.getElementById('cvv').value;
        const cardNumber = document.getElementById('card-number').value.replace(/\D/g, '');
        const cardType = detectCardType(cardNumber);
        const expectedCvvLength = cardType?.cvv || 3;
        if (cvv.length !== expectedCvvLength) {
            errorMessages.push(`CVV must be ${expectedCvvLength} digits`);
            isValid = false;
        }
    }
    
    if (!isValid) {
        // Show detailed error messages
        if (errorMessages.length > 0) {
            alert('Please correct the following errors:\n\n' + errorMessages.join('\n'));
        } else {
            alert('Please fill in all required fields correctly');
        }
        
        // Focus on first invalid field
        if (firstInvalidField) {
            firstInvalidField.focus();
        }
    }
    
    return isValid;
}

function saveStepData(step) {
    switch(step) {
        case 1:
            formData.personal = {
                firstName: document.getElementById('first-name').value,
                lastName: document.getElementById('last-name').value,
                email: document.getElementById('email').value,
                phone: document.getElementById('phone').value,
                dob: document.getElementById('dob').value,
                gender: document.getElementById('gender').value,
                address: document.getElementById('address').value,
                city: document.getElementById('city').value,
                state: document.getElementById('state').value,
                zip: document.getElementById('zip').value,
                occupation: document.getElementById('occupation').value
            };
            break;
            
        case 2:
            // PHINS Unified Contract data
            const coverageAmount = parseInt(document.getElementById('coverage-slider').value);
            const monthlyPremium = formData.premiums?.monthly || 250;
            
            formData.coverage = {
                policyType: 'phins_unified',
                coverageAmount: coverageAmount,
                term: allocationState.term,
                
                // Allocation breakdown
                allocation: {
                    strategy: allocationState.strategy,
                    savings: {
                        percentage: allocationState.savings,
                        monthlyAmount: monthlyPremium * (allocationState.savings / 100)
                    },
                    investment: {
                        percentage: allocationState.investment,
                        monthlyAmount: monthlyPremium * (allocationState.investment / 100)
                    },
                    healthWallet: {
                        percentage: allocationState.healthWallet,
                        monthlyAmount: monthlyPremium * (allocationState.healthWallet / 100)
                    },
                    disability: {
                        percentage: allocationState.disability,
                        monthlyAmount: monthlyPremium * (allocationState.disability / 100)
                    }
                },
                
                // AI Bot configuration
                aiBot: {
                    riskProfile: aiBotConfig.riskProfile,
                    assets: aiBotConfig.assets,
                    strategy: aiBotConfig.strategy,
                    safetySettings: {
                        stopLoss: aiBotConfig.stopLoss,
                        diversification: aiBotConfig.diversification,
                        rebalancing: aiBotConfig.rebalancing
                    }
                },
                
                // Projections
                projections: formData.projections || {}
            };
            break;
            
        case 3:
            const familyHistory = [];
            document.querySelectorAll('input[name="family-history"]:checked').forEach(cb => {
                familyHistory.push(cb.value);
            });
            
            formData.health = {
                tobacco: document.querySelector('input[name="tobacco"]:checked').value,
                medicalConditions: document.querySelector('input[name="medical-conditions"]:checked').value,
                conditionsList: document.getElementById('conditions-list')?.value || '',
                surgery: document.querySelector('input[name="surgery"]:checked').value,
                surgeryList: document.getElementById('surgery-list')?.value || '',
                hazardous: document.querySelector('input[name="hazardous"]:checked').value,
                familyHistory: familyHistory,
                height: document.getElementById('height').value,
                weight: document.getElementById('weight').value,
                medications: document.getElementById('medications').value
            };
            break;
            
        case 4:
            // Payment info - store masked card only (never store full card number in form data)
            const cardNumber = document.getElementById('card-number').value.replace(/\D/g, '');
            const cardType = detectCardType(cardNumber);
            const monthlyDeposit = document.getElementById('monthly-deposit').value;
            
            formData.payment = {
                cardLast4: cardNumber.slice(-4),
                cardType: cardType?.type || 'unknown',
                cardholderName: document.getElementById('cardholder-name').value,
                expiryMonth: document.getElementById('expiry-month').value,
                expiryYear: document.getElementById('expiry-year').value,
                billingFrequency: document.querySelector('input[name="billing-frequency"]:checked')?.value || 'monthly',
                autoPay: document.querySelector('input[name="auto-pay"]:checked')?.value === 'yes',
                healthWalletEnabled: document.getElementById('enable-health-wallet')?.checked || false,
                monthlyDeposit: monthlyDeposit === 'custom' 
                    ? parseFloat(document.getElementById('custom-deposit')?.value || 0) 
                    : parseFloat(monthlyDeposit || 0),
                // Store full card for submission (will be tokenized server-side)
                _cardNumber: cardNumber,
                _cvv: document.getElementById('cvv').value
            };
            break;
    }
}

function populateReview() {
    // Personal Information
    const personalHtml = `
        <div class="review-item">
            <strong>Name</strong>
            <span>${formData.personal.firstName} ${formData.personal.lastName}</span>
        </div>
        <div class="review-item">
            <strong>Email</strong>
            <span>${formData.personal.email}</span>
        </div>
        <div class="review-item">
            <strong>Phone</strong>
            <span>${formData.personal.phone}</span>
        </div>
        <div class="review-item">
            <strong>Date of Birth</strong>
            <span>${new Date(formData.personal.dob).toLocaleDateString()}</span>
        </div>
        <div class="review-item">
            <strong>Address</strong>
            <span>${formData.personal.address}, ${formData.personal.city}, ${formData.personal.state} ${formData.personal.zip}</span>
        </div>
        <div class="review-item">
            <strong>Occupation</strong>
            <span>${formData.personal.occupation}</span>
        </div>
    `;
    document.getElementById('review-personal').innerHTML = personalHtml;
    
    // Coverage Details - PHINS Unified Contract
    const coverageHtml = `
        <div class="review-item" style="grid-column: 1 / -1;">
            <strong>Contract Type</strong>
            <span style="font-size: 1.1rem; color: #1565c0;">🛡️ PHINS Unified Contract (Save • Pay • Invest • Consume • Hedge)</span>
        </div>
        <div class="review-item">
            <strong>Disability Coverage</strong>
            <span>${new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 }).format(formData.coverage.coverageAmount)}</span>
        </div>
        <div class="review-item">
            <strong>Contract Term</strong>
            <span>${formData.coverage.term || 15} Years</span>
        </div>
        <div class="review-item" style="grid-column: 1 / -1;">
            <strong>Premium Allocation Strategy</strong>
            <span style="text-transform: capitalize;">${formData.coverage.allocation?.strategy || 'Balanced'}</span>
        </div>
        <div class="review-item">
            <strong>💰 Savings</strong>
            <span>${formData.coverage.allocation?.savings?.percentage || 25}% (${formatCurrency(formData.coverage.allocation?.savings?.monthlyAmount || 0)}/mo)</span>
        </div>
        <div class="review-item">
            <strong>📈 Investment</strong>
            <span>${formData.coverage.allocation?.investment?.percentage || 35}% (${formatCurrency(formData.coverage.allocation?.investment?.monthlyAmount || 0)}/mo)</span>
        </div>
        <div class="review-item">
            <strong>🏥 Health Wallet</strong>
            <span>${formData.coverage.allocation?.healthWallet?.percentage || 15}% (${formatCurrency(formData.coverage.allocation?.healthWallet?.monthlyAmount || 0)}/mo)</span>
        </div>
        <div class="review-item">
            <strong>🛡️ Disability</strong>
            <span>${formData.coverage.allocation?.disability?.percentage || 25}% (${formatCurrency(formData.coverage.allocation?.disability?.monthlyAmount || 0)}/mo)</span>
        </div>
        <div class="review-item" style="grid-column: 1 / -1; margin-top: 1rem; padding-top: 1rem; border-top: 1px dashed #e1e8ed;">
            <strong>🤖 AI Investment Bot</strong>
            <span>Risk: ${(formData.coverage.aiBot?.riskProfile || 'moderate').replace('_', '-')} | Strategy: ${formData.coverage.aiBot?.strategy || 'balanced'} | Assets: ${(formData.coverage.aiBot?.assets || ['stocks', 'bonds']).join(', ')}</span>
        </div>
        <div class="review-item" style="grid-column: 1 / -1; background: linear-gradient(135deg, #e8f5e9, #f1f8e9); padding: 12px; border-radius: 8px;">
            <strong>📊 Projected Value (${formData.coverage.term || 15} Years)</strong>
            <span style="font-size: 1.2rem; color: #2E7D32; font-weight: 700;">${formatCurrency(formData.coverage.projections?.total || 0)}</span>
        </div>
    `;
    document.getElementById('review-coverage').innerHTML = coverageHtml;
    
    // Health Assessment
    const healthHtml = `
        <div class="review-item">
            <strong>Tobacco Use</strong>
            <span>${formData.health.tobacco === 'no' ? 'No' : formData.health.tobacco === 'yes' ? 'Yes' : 'Former User'}</span>
        </div>
        <div class="review-item">
            <strong>Medical Conditions</strong>
            <span>${formData.health.medicalConditions === 'no' ? 'None' : 'Yes - ' + formData.health.conditionsList}</span>
        </div>
        <div class="review-item">
            <strong>Height</strong>
            <span>${formData.health.height} cm</span>
        </div>
        <div class="review-item">
            <strong>Weight</strong>
            <span>${formData.health.weight} kg</span>
        </div>
        <div class="review-item">
            <strong>Hazardous Activities</strong>
            <span>${formData.health.hazardous === 'no' ? 'None' : formData.health.hazardous}</span>
        </div>
        <div class="review-item">
            <strong>Family History</strong>
            <span>${formData.health.familyHistory.includes('none') ? 'None' : formData.health.familyHistory.join(', ')}</span>
        </div>
    `;
    document.getElementById('review-health').innerHTML = healthHtml;
    
    // Payment Information
    const cardIcons = { visa: '💳', mastercard: '🔵', amex: '💠', discover: '🟠' };
    const billingFreqLabels = { monthly: 'Monthly', quarterly: 'Quarterly (Save 3%)', annual: 'Annual (Save 10%)' };
    
    const paymentHtml = `
        <div class="review-item">
            <strong>Payment Method</strong>
            <span>${cardIcons[formData.payment?.cardType] || '💳'} ****-****-****-${formData.payment?.cardLast4 || '****'}</span>
        </div>
        <div class="review-item">
            <strong>Cardholder</strong>
            <span>${formData.payment?.cardholderName || 'N/A'}</span>
        </div>
        <div class="review-item">
            <strong>Expiry</strong>
            <span>${formData.payment?.expiryMonth || '--'}/${formData.payment?.expiryYear || '----'}</span>
        </div>
        <div class="review-item">
            <strong>Billing Frequency</strong>
            <span>${billingFreqLabels[formData.payment?.billingFrequency] || 'Monthly'}</span>
        </div>
        <div class="review-item">
            <strong>Auto-Pay</strong>
            <span>${formData.payment?.autoPay ? '✅ Enabled' : '❌ Disabled'}</span>
        </div>
        <div class="review-item">
            <strong>Health Wallet</strong>
            <span>${formData.payment?.healthWalletEnabled ? '✅ Enabled' : '❌ Disabled'}</span>
        </div>
        ${formData.payment?.healthWalletEnabled && formData.payment?.monthlyDeposit > 0 ? `
        <div class="review-item">
            <strong>Wallet Deposit</strong>
            <span>$${formData.payment.monthlyDeposit}/month</span>
        </div>
        ` : ''}
    `;
    document.getElementById('review-payment').innerHTML = paymentHtml;
    
    // Update final premium display based on billing frequency
    if (formData.premiums) {
        let displayAmount = formData.premiums.annual;
        let periodText = 'per year';
        
        if (formData.payment?.billingFrequency === 'monthly') {
            displayAmount = formData.premiums.monthly;
            periodText = 'per month';
        } else if (formData.payment?.billingFrequency === 'quarterly') {
            displayAmount = formData.premiums.quarterly * 0.97; // 3% discount
            periodText = 'per quarter';
        } else {
            displayAmount = formData.premiums.annual * 0.90; // 10% discount
        }
        
        document.getElementById('final-premium-amount').textContent = 
            new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 }).format(displayAmount);
        document.getElementById('final-period').textContent = periodText;
        document.getElementById('final-monthly').textContent = 
            new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(formData.premiums.monthly);
        document.getElementById('final-quarterly').textContent = 
            new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(formData.premiums.quarterly * 0.97);
        
        // Health wallet summary
        const walletSummary = document.getElementById('health-wallet-summary');
        if (walletSummary) {
            if (formData.payment?.healthWalletEnabled && formData.payment?.monthlyDeposit > 0) {
                walletSummary.style.display = 'block';
                document.getElementById('final-wallet-deposit').textContent = `$${formData.payment.monthlyDeposit}/month`;
            } else {
                walletSummary.style.display = 'none';
            }
        }
    }
}

async function handleSubmit(e) {
    e.preventDefault();
    
    if (!document.getElementById('terms-agree').checked || 
        !document.getElementById('accuracy-agree').checked ||
        !document.getElementById('billing-agree').checked) {
        alert('Please agree to all terms and conditions');
        return;
    }
    
    // Validate that all form data is present
    if (!formData.personal || !formData.coverage || !formData.health || !formData.payment) {
        alert('Some application data is missing. Please go back and complete all steps.');
        console.error('Missing formData:', { 
            personal: !!formData.personal, 
            coverage: !!formData.coverage, 
            health: !!formData.health, 
            payment: !!formData.payment 
        });
        return;
    }
    
    // Prepare submission data with null safety - PHINS Unified Contract
    let submissionData;
    try {
        const allocation = formData.coverage?.allocation || {};
        const aiBot = formData.coverage?.aiBot || {};
        const projections = formData.coverage?.projections || {};
        
        submissionData = {
            customer_name: `${formData.personal.firstName || ''} ${formData.personal.lastName || ''}`.trim(),
            customer_email: formData.personal.email || '',
            customer_phone: formData.personal.phone || '',
            customer_dob: formData.personal.dob || '',
            
            // PHINS Unified Contract type
            type: 'phins_unified',
            coverage_amount: formData.coverage?.coverageAmount || 500000,
            contract_term: formData.coverage?.term || 15,
            
            age: formData.personal.dob ? calculateAge(formData.personal.dob) : 30,
            risk_score: calculateRiskScore(),
            medical_exam_required: formData.health?.medicalConditions === 'yes' || formData.health?.surgery === 'yes',
            
            // PHINS Premium Allocation
            premium_allocation: {
                strategy: allocation.strategy || 'balanced',
                savings_pct: allocation.savings?.percentage || 25,
                investment_pct: allocation.investment?.percentage || 35,
                health_wallet_pct: allocation.healthWallet?.percentage || 15,
                disability_pct: allocation.disability?.percentage || 25,
                
                // Monthly amounts
                savings_amount: allocation.savings?.monthlyAmount || 0,
                investment_amount: allocation.investment?.monthlyAmount || 0,
                health_wallet_amount: allocation.healthWallet?.monthlyAmount || 0,
                disability_amount: allocation.disability?.monthlyAmount || 0
            },
            
            // AI Investment Bot Configuration
            ai_bot_config: {
                enabled: true,
                risk_profile: aiBot.riskProfile || 'moderate',
                assets: aiBot.assets || ['stocks', 'bonds'],
                strategy: aiBot.strategy || 'balanced',
                stop_loss_enabled: aiBot.safetySettings?.stopLoss ?? true,
                diversification_enabled: aiBot.safetySettings?.diversification ?? true,
                auto_rebalancing: aiBot.safetySettings?.rebalancing ?? true
            },
            
            // Projections (for underwriting reference)
            projections: {
                term_years: projections.term || 15,
                projected_savings: projections.savings || 0,
                projected_investment: projections.investment || 0,
                projected_total_value: projections.total || 0
            },
            
            questionnaire: {
                smoke: formData.health?.tobacco || 'no',
                medical_conditions: formData.health?.medicalConditions || 'no',
                conditions_list: formData.health?.conditionsList || '',
                surgery: formData.health?.surgery || 'no',
                surgery_list: formData.health?.surgeryList || '',
                hazardous_activities: formData.health?.hazardous || 'no',
                family_history: (formData.health?.familyHistory || []).join(','),
                medications: formData.health?.medications || '',
                height: formData.health?.height || '',
                weight: formData.health?.weight || ''
            },
            
            // Payment and billing information
            payment: {
                card_number: formData.payment?._cardNumber || '',
                cvv: formData.payment?._cvv || '',
                expiry_month: formData.payment?.expiryMonth || '',
                expiry_year: formData.payment?.expiryYear || '',
                cardholder_name: formData.payment?.cardholderName || '',
                card_type: formData.payment?.cardType || 'unknown',
                billing_frequency: formData.payment?.billingFrequency || 'monthly',
                auto_pay: formData.payment?.autoPay || false
            },
            
            // Health Wallet (now integrated into allocation)
            health_wallet: {
                enabled: true, // Always enabled in PHINS unified
                monthly_deposit: allocation.healthWallet?.monthlyAmount || 0,
                allocation_pct: allocation.healthWallet?.percentage || 15
            }
        };
    } catch (dataError) {
        alert('Error preparing application data. Please review your information and try again.');
        console.error('Data preparation error:', dataError);
        return;
    }
    
    // Validate required fields
    if (!submissionData.customer_name.trim()) {
        alert('Customer name is required');
        return;
    }
    if (!submissionData.customer_email.trim()) {
        alert('Email address is required');
        return;
    }
    
    // Show loading state
    const submitBtn = document.getElementById('submit-btn');
    const originalText = submitBtn.textContent;
    submitBtn.textContent = 'Submitting...';
    submitBtn.disabled = true;
    
    try {
        const response = await fetch('/api/policies/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(submissionData)
        });
        
        let data;
        try {
            data = await response.json();
        } catch (parseError) {
            console.error('Response parse error:', parseError);
            alert('Server returned an invalid response. Please try again.');
            return;
        }
        
        if (response.ok) {
            // Show success message
            document.getElementById('app-id').textContent = data.underwriting?.id || 'N/A';
            document.getElementById('policy-id').textContent = data.policy?.id || 'N/A';
            document.getElementById('success-premium').textContent = 
                new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(data.policy?.annual_premium || 0) + ' per year';
            
            document.getElementById('success-message').style.display = 'flex';
            
            // Hide form
            document.getElementById('customer-application-form').style.display = 'none';
        } else {
            alert('Error submitting application: ' + (data.error || 'Please try again'));
        }
    } catch (error) {
        console.error('Submission error:', error);
        alert('Error submitting application: ' + (error.message || 'Please check your connection and try again.'));
    } finally {
        // Reset button state
        submitBtn.textContent = originalText;
        submitBtn.disabled = false;
    }
}

function calculateRiskScore() {
    let riskPoints = 0;
    
    // Tobacco use
    if (formData.health.tobacco === 'yes') riskPoints += 2;
    else if (formData.health.tobacco === 'former') riskPoints += 1;
    
    // Medical conditions
    if (formData.health.medicalConditions === 'yes') riskPoints += 2;
    
    // Surgery
    if (formData.health.surgery === 'yes') riskPoints += 1;
    
    // Hazardous activities
    if (formData.health.hazardous === 'regular') riskPoints += 2;
    else if (formData.health.hazardous === 'occasional') riskPoints += 1;
    
    // Family history
    if (formData.health.familyHistory.length > 0 && !formData.health.familyHistory.includes('none')) {
        riskPoints += formData.health.familyHistory.length;
    }
    
    // BMI
    const height = parseFloat(formData.health.height);
    const weight = parseFloat(formData.health.weight);
    if (height && weight) {
        const bmi = weight / ((height / 100) ** 2);
        if (bmi < 18.5 || bmi > 30) riskPoints += 1;
        if (bmi > 35) riskPoints += 2;
    }
    
    // Convert points to risk level
    if (riskPoints <= 2) return 'low';
    if (riskPoints <= 5) return 'medium';
    if (riskPoints <= 8) return 'high';
    return 'very_high';
}
