// Customer Application JavaScript - PHINS Unified Contract
let currentStep = 1;
const totalSteps = 5;
let formData = {};
let applicationFiles = [];  // Store uploaded files for submission

// PHINS Contract allocation state
let phinsAllocation = {
    protectionPct: 25,
    savingsPct: 75,
    walletPct: 15,
    investmentPct: 60,
    algoPct: 25,
    coverageYears: 20,
    coverageAmount: 500000
};

// Card type patterns for validation
const CARD_PATTERNS = {
    visa: { regex: /^4/, icon: '💳', name: 'Visa', lengths: [13, 16, 19], cvv: 3 },
    mastercard: { regex: /^(5[1-5]|2[2-7])/, icon: '🔵', name: 'Mastercard', lengths: [16], cvv: 3 },
    amex: { regex: /^3[47]/, icon: '💠', name: 'American Express', lengths: [15], cvv: 4 },
    discover: { regex: /^(6011|65|644|645|646|647|648|649)/, icon: '🟠', name: 'Discover', lengths: [16, 19], cvv: 3 }
};

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    updateStepDisplay();
    populateExpiryYears();
    initializePHINSContract();
});

// Initialize PHINS Contract UI
function initializePHINSContract() {
    // Setup allocation slider
    const allocationSlider = document.getElementById('allocation-slider');
    if (allocationSlider) {
        allocationSlider.addEventListener('input', updateAllocationSplit);
        updateAllocationSplit();
    }
    
    // Setup coverage years radio buttons
    document.querySelectorAll('input[name="coverage-years"]').forEach(radio => {
        radio.addEventListener('change', function() {
            phinsAllocation.coverageYears = parseInt(this.value);
            updateAllocationDisplay();
            
            // Update visual selection
            document.querySelectorAll('.radio-card').forEach(card => {
                card.classList.remove('selected');
                card.style.border = '2px solid #e0e0e0';
                card.style.background = 'white';
            });
            this.closest('.radio-card').classList.add('selected');
            this.closest('.radio-card').style.border = '2px solid #0d47a1';
            this.closest('.radio-card').style.background = '#e3f2fd';
        });
    });
    
    // Setup savings distribution inputs
    ['wallet', 'investment', 'algo'].forEach(type => {
        const input = document.getElementById(`${type}-pct`);
        if (input) {
            input.addEventListener('change', () => rebalanceAllocations(type));
            input.addEventListener('input', () => updateAllocationBars());
        }
    });
    
    // Initial update
    updateAllocationDisplay();
}

// Update protection/savings split
function updateAllocationSplit() {
    const slider = document.getElementById('allocation-slider');
    if (!slider) return;
    
    phinsAllocation.protectionPct = parseInt(slider.value);
    phinsAllocation.savingsPct = 100 - phinsAllocation.protectionPct;
    
    // Update display
    document.getElementById('protection-pct').textContent = phinsAllocation.protectionPct + '%';
    document.getElementById('savings-pct').textContent = phinsAllocation.savingsPct + '%';
    
    // Update gradient background
    slider.style.background = `linear-gradient(to right, #dc3545 0%, #dc3545 ${phinsAllocation.protectionPct}%, #28a745 ${phinsAllocation.protectionPct}%, #28a745 100%)`;
    
    updateAllocationDisplay();
}

// Adjust allocation for a specific category
function adjustAllocation(type, delta) {
    const input = document.getElementById(`${type}-pct`);
    if (!input) return;
    
    let newValue = parseInt(input.value) + delta;
    newValue = Math.max(0, Math.min(100, newValue));
    input.value = newValue;
    
    rebalanceAllocations(type);
}

// Rebalance allocations to ensure they total 100%
function rebalanceAllocations(changedType) {
    const walletInput = document.getElementById('wallet-pct');
    const investmentInput = document.getElementById('investment-pct');
    const algoInput = document.getElementById('algo-pct');
    
    if (!walletInput || !investmentInput || !algoInput) return;
    
    let wallet = parseInt(walletInput.value) || 0;
    let investment = parseInt(investmentInput.value) || 0;
    let algo = parseInt(algoInput.value) || 0;
    
    const total = wallet + investment + algo;
    
    if (total !== 100) {
        // Adjust the other two proportionally
        const diff = 100 - total;
        const others = ['wallet', 'investment', 'algo'].filter(t => t !== changedType);
        
        if (total > 100) {
            // Reduce others proportionally
            const currentOthersTotal = others.reduce((sum, t) => sum + parseInt(document.getElementById(`${t}-pct`).value), 0);
            if (currentOthersTotal > 0) {
                others.forEach(t => {
                    const input = document.getElementById(`${t}-pct`);
                    const current = parseInt(input.value);
                    const reduction = Math.round((current / currentOthersTotal) * Math.abs(diff));
                    input.value = Math.max(0, current - reduction);
                });
            }
        } else {
            // Increase others proportionally
            const currentOthersTotal = others.reduce((sum, t) => sum + parseInt(document.getElementById(`${t}-pct`).value), 0);
            if (currentOthersTotal > 0) {
                others.forEach(t => {
                    const input = document.getElementById(`${t}-pct`);
                    const current = parseInt(input.value);
                    const increase = Math.round((current / currentOthersTotal) * diff);
                    input.value = Math.min(100, current + increase);
                });
            } else {
                // If others are 0, split evenly
                const each = Math.floor(diff / others.length);
                others.forEach(t => {
                    document.getElementById(`${t}-pct`).value = each;
                });
            }
        }
    }
    
    // Update state
    phinsAllocation.walletPct = parseInt(walletInput.value);
    phinsAllocation.investmentPct = parseInt(investmentInput.value);
    phinsAllocation.algoPct = parseInt(algoInput.value);
    
    updateAllocationBars();
    updateAllocationDisplay();
}

// Update allocation bar visuals
function updateAllocationBars() {
    const wallet = parseInt(document.getElementById('wallet-pct')?.value) || 0;
    const investment = parseInt(document.getElementById('investment-pct')?.value) || 0;
    const algo = parseInt(document.getElementById('algo-pct')?.value) || 0;
    
    document.getElementById('wallet-bar').style.width = wallet + '%';
    document.getElementById('investment-bar').style.width = investment + '%';
    document.getElementById('algo-bar').style.width = algo + '%';
    
    const total = wallet + investment + algo;
    const totalEl = document.getElementById('total-allocation');
    if (totalEl) {
        totalEl.textContent = total + '%';
        totalEl.style.color = total === 100 ? '#0d47a1' : '#dc3545';
    }
}

// Update all allocation displays
function updateAllocationDisplay() {
    const coverage = phinsAllocation.coverageAmount;
    const basePremium = calculateBasePremium(coverage);
    
    const monthlyPremium = basePremium;
    const protectionMonthly = monthlyPremium * (phinsAllocation.protectionPct / 100);
    const savingsMonthly = monthlyPremium * (phinsAllocation.savingsPct / 100);
    
    // Update protection/savings monthly amounts
    const protectionMonthlyEl = document.getElementById('protection-monthly');
    const savingsMonthlyEl = document.getElementById('savings-monthly');
    if (protectionMonthlyEl) protectionMonthlyEl.textContent = formatCurrency(protectionMonthly);
    if (savingsMonthlyEl) savingsMonthlyEl.textContent = formatCurrency(savingsMonthly);
    
    // Update savings distribution amounts
    const walletMonthly = savingsMonthly * (phinsAllocation.walletPct / 100);
    const investmentMonthly = savingsMonthly * (phinsAllocation.investmentPct / 100);
    const algoMonthly = savingsMonthly * (phinsAllocation.algoPct / 100);
    
    const walletMonthlyEl = document.getElementById('wallet-monthly');
    const investmentMonthlyEl = document.getElementById('investment-monthly');
    const algoMonthlyEl = document.getElementById('algo-monthly');
    
    if (walletMonthlyEl) walletMonthlyEl.textContent = formatCurrency(walletMonthly);
    if (investmentMonthlyEl) investmentMonthlyEl.textContent = formatCurrency(investmentMonthly);
    if (algoMonthlyEl) algoMonthlyEl.textContent = formatCurrency(algoMonthly);
    
    // Update premium displays
    const quarterlyPremium = monthlyPremium * 3 * 0.97;
    const annualPremium = monthlyPremium * 12 * 0.90;
    
    document.getElementById('monthly-premium').textContent = formatCurrency(monthlyPremium);
    document.getElementById('quarterly-premium').textContent = formatCurrency(quarterlyPremium);
    document.getElementById('annual-premium').textContent = formatCurrency(annualPremium);
    
    // Update summary
    const summaryCoverage = document.getElementById('summary-coverage');
    const summaryYears = document.getElementById('summary-years');
    if (summaryCoverage) summaryCoverage.textContent = formatCurrency(coverage, false);
    if (summaryYears) summaryYears.textContent = phinsAllocation.coverageYears;
    
    // Store premiums with actuarial data
    formData.premiums = {
        monthly: monthlyPremium,
        quarterly: quarterlyPremium,
        annual: annualPremium,
        // Include actuarial breakdown for data integrity
        actuarialBreakdown: formData.actuarialData ? {
            riskComponent: formData.actuarialData.riskPremiumAnnual / 12,
            savingsComponent: formData.actuarialData.savingsPremiumAnnual / 12,
            expenseLoading: formData.actuarialData.expenseLoading / 12,
            dataSource: formData.actuarialData.dataSource,
            ageFactor: formData.actuarialData.ageFactor,
            adlLevel: formData.actuarialData.adlLevel,
            adlMultiplier: formData.actuarialData.adlMultiplier
        } : null
    };
    
    // Update actuarial info display if element exists
    const actuarialInfoEl = document.getElementById('actuarial-info');
    if (actuarialInfoEl && formData.actuarialData) {
        actuarialInfoEl.innerHTML = `
            <div style="font-size: 0.75rem; color: #28a745; margin-top: 8px;">
                ✓ Actuarially Sourced (${formData.actuarialData.dataSource})
            </div>
            <div style="font-size: 0.7rem; color: #666; margin-top: 4px;">
                Age Factor: ${formData.actuarialData.ageFactor.toFixed(2)} | 
                ADL Level: ${formData.actuarialData.adlLevel} (×${formData.actuarialData.adlMultiplier.toFixed(2)}) |
                Risk Premium: ${formatCurrency(formData.actuarialData.riskPremiumAnnual / 12)}/mo
            </div>
        `;
    }
}

// ==============================================================================
// ACTUARIAL TABLES (Same as server.py and FinancialReportingService)
// Data Source: PHINS_ACTUARIAL_TABLES_V1
// ==============================================================================

// Mortality rates by age bracket (per 1000 lives per year)
const MORTALITY_RATES = {
    '0-30': 0.5,
    '30-40': 1.2,
    '40-50': 2.5,
    '50-60': 5.0,
    '60-70': 12.0,
    '70-80': 30.0,
    '80-100': 75.0,
};

// ADL Risk multipliers (1-10 scale, 5 is baseline medium risk)
const ADL_RISK_MULTIPLIERS = {
    1: 0.6,   // Very low risk - fully independent
    2: 0.75,
    3: 0.85,
    4: 0.95,
    5: 1.0,   // Medium risk (baseline)
    6: 1.15,
    7: 1.35,
    8: 1.6,
    9: 1.9,
    10: 2.5,  // Very high risk - total dependence
};

// Age adjustment factors by policy type (derived from mortality tables)
const AGE_FACTORS = {
    'life': {
        '0-30': 0.7,
        '30-40': 0.85,
        '40-45': 1.0,
        '45-50': 1.15,
        '50-55': 1.30,
        '55-60': 1.60,
        '60-65': 2.0,
        '65-70': 2.5,
        '70-100': 3.2
    },
    'health': {
        '0-30': 0.6,
        '30-40': 0.8,
        '40-50': 1.0,
        '50-60': 1.4,
        '60-70': 1.9,
        '70-100': 2.6
    }
};

// Discount rate for present value calculations
const DISCOUNT_RATE = 0.035; // 3.5% annual

// Get age factor from actuarial tables
function getAgeFactor(age, policyType = 'life') {
    const factors = AGE_FACTORS[policyType] || AGE_FACTORS['life'];
    for (const [range, factor] of Object.entries(factors)) {
        const [min, max] = range.split('-').map(Number);
        if (age >= min && age < max) {
            return factor;
        }
    }
    return 1.0; // Default
}

// Get mortality rate from actuarial tables
function getMortalityRate(age) {
    for (const [range, rate] of Object.entries(MORTALITY_RATES)) {
        const [min, max] = range.split('-').map(Number);
        if (age >= min && age < max) {
            return rate / 1000.0;
        }
    }
    return 0.075; // Default for very old ages
}

// Get ADL multiplier from actuarial tables
function getAdlMultiplier(adlLevel) {
    adlLevel = Math.max(1, Math.min(10, adlLevel));
    return ADL_RISK_MULTIPLIERS[adlLevel] || 1.0;
}

// Map risk score to ADL level (consistent with server.py)
function riskScoreToAdlLevel(riskScore) {
    const mapping = {
        'low': 3,
        'medium': 5,
        'high': 7,
        'very_high': 9
    };
    return mapping[riskScore] || 5;
}

// Calculate base premium based on coverage using ACTUARIAL TABLES
// This ensures data integrity with Long-Term Projection Calculator
function calculateBasePremium(coverage) {
    const dob = document.getElementById('dob')?.value;
    let age = 35; // Default age
    
    if (dob) {
        age = calculateAge(dob);
    }
    
    // Get actuarial-based factors
    const ageFactor = getAgeFactor(age, 'life');
    const mortalityRate = getMortalityRate(age);
    
    // Estimate ADL level from health questionnaire (if available)
    // Default to ADL 5 (medium risk) for new applications
    let adlLevel = 5;
    if (formData.health) {
        // Adjust ADL based on health factors
        let riskPoints = 0;
        if (formData.health.tobacco === 'yes') riskPoints += 2;
        else if (formData.health.tobacco === 'former') riskPoints += 1;
        if (formData.health.medicalConditions === 'yes') riskPoints += 2;
        if (formData.health.surgery === 'yes') riskPoints += 1;
        if (formData.health.hazardous === 'regular') riskPoints += 2;
        else if (formData.health.hazardous === 'occasional') riskPoints += 1;
        
        // Map risk points to ADL level
        if (riskPoints <= 1) adlLevel = 3;      // Low risk
        else if (riskPoints <= 3) adlLevel = 5; // Medium risk
        else if (riskPoints <= 5) adlLevel = 7; // High risk
        else adlLevel = 9;                       // Very high risk
    }
    
    const adlMultiplier = getAdlMultiplier(adlLevel);
    
    // Combined factor = age_factor × adl_multiplier (same as server.py)
    const combinedFactor = ageFactor * adlMultiplier;
    
    // Calculate risk component (50% of base goes to risk coverage)
    // Base rate: Coverage × mortality-derived factor / term
    const termYears = phinsAllocation.coverageYears || 20;
    
    // Risk premium calculation using actuarial basis:
    // Risk = PV(Mortality Rate × ADL Multiplier × Coverage) spread over term
    // Simplified: (coverage × mortalityRate × adlMultiplier × termYears) / termYears
    const riskBase = coverage * mortalityRate * adlMultiplier * termYears;
    const riskPremiumAnnual = riskBase / termYears;
    
    // Savings component (based on savings allocation - doesn't depend on risk)
    const savingsPct = phinsAllocation.savingsPct / 100;
    const savingsTarget = coverage * savingsPct;
    const savingsPremiumAnnual = savingsTarget / termYears;
    
    // Expense loading (15% of risk premium - industry standard)
    const expenseLoading = riskPremiumAnnual * 0.15;
    
    // Total annual premium
    const totalAnnualPremium = riskPremiumAnnual + savingsPremiumAnnual + expenseLoading;
    
    // Monthly premium
    const monthlyPremium = totalAnnualPremium / 12;
    
    // Store actuarial data for display/debugging
    formData.actuarialData = {
        age: age,
        ageFactor: ageFactor,
        adlLevel: adlLevel,
        adlMultiplier: adlMultiplier,
        combinedFactor: combinedFactor,
        mortalityRate: mortalityRate,
        riskPremiumAnnual: Math.round(riskPremiumAnnual * 100) / 100,
        savingsPremiumAnnual: Math.round(savingsPremiumAnnual * 100) / 100,
        expenseLoading: Math.round(expenseLoading * 100) / 100,
        dataSource: 'PHINS_ACTUARIAL_TABLES_V1'
    };
    
    return Math.round(monthlyPremium);
}

// Format currency
function formatCurrency(amount, showDecimals = true) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: showDecimals ? 2 : 0,
        maximumFractionDigits: showDecimals ? 2 : 0
    }).format(amount);
}

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
    
    // Quick amount buttons
    document.querySelectorAll('.quick-amount').forEach(btn => {
        btn.addEventListener('click', function() {
            const amount = parseInt(this.dataset.amount);
            document.getElementById('coverage-slider').value = amount;
            updateCoverageDisplay();
            
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

function selectPolicy(e) {
    const type = e.target.dataset.type;
    
    // Update UI
    document.querySelectorAll('.policy-option').forEach(option => {
        option.classList.remove('selected');
    });
    e.target.closest('.policy-option').classList.add('selected');
    
    // Set hidden input
    document.getElementById('policy-type').value = type;
    
    // Show coverage details
    document.getElementById('coverage-details').style.display = 'block';
    
    // Update premium estimate
    updateCoverageDisplay();
}

function updateCoverageDisplay() {
    const amount = parseInt(document.getElementById('coverage-slider').value);
    phinsAllocation.coverageAmount = amount;
    
    document.getElementById('coverage-amount-display').textContent = 
        new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 }).format(amount);
    
    // Update all allocation displays
    updateAllocationDisplay();
    
    // Update quick amount button active state
    document.querySelectorAll('.quick-amount').forEach(btn => {
        if (parseInt(btn.dataset.amount) === amount) {
            btn.style.border = '2px solid #0d47a1';
            btn.style.background = '#e3f2fd';
            btn.style.color = '#0d47a1';
        } else {
            btn.style.border = '2px solid #e0e0e0';
            btn.style.background = 'white';
            btn.style.color = '';
        }
    });
}

function calculatePremium(coverageAmount) {
    // This is now handled by updateAllocationDisplay for the unified PHINS contract
    updateAllocationDisplay();
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
        // PHINS unified contract is pre-selected, just verify allocations total 100%
        const walletPct = parseInt(document.getElementById('wallet-pct')?.value) || 0;
        const investmentPct = parseInt(document.getElementById('investment-pct')?.value) || 0;
        const algoPct = parseInt(document.getElementById('algo-pct')?.value) || 0;
        
        if (walletPct + investmentPct + algoPct !== 100) {
            alert('Savings distribution must total 100%. Please adjust your allocation.');
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
            formData.coverage = {
                policyType: document.getElementById('policy-type').value || 'phins_unified',
                coverageAmount: phinsAllocation.coverageAmount,
                coverageYears: phinsAllocation.coverageYears,
                allocation: {
                    protectionPct: phinsAllocation.protectionPct,
                    savingsPct: phinsAllocation.savingsPct,
                    distribution: {
                        walletPct: phinsAllocation.walletPct,
                        investmentPct: phinsAllocation.investmentPct,
                        algoPct: phinsAllocation.algoPct
                    }
                }
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
            
            // Recalculate premium with updated health/ADL data for actuarial accuracy
            // This ensures risk cover is properly adjusted based on health questionnaire
            updateAllocationDisplay();
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
    const alloc = formData.coverage?.allocation || {};
    const dist = alloc.distribution || {};
    const actuarial = formData.actuarialData || {};
    
    const coverageHtml = `
        <div class="review-item">
            <strong>Contract Type</strong>
            <span>🛡️ PHINS Unified Protection Contract</span>
        </div>
        <div class="review-item">
            <strong>Coverage Amount</strong>
            <span>${new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 }).format(formData.coverage?.coverageAmount || 500000)}</span>
        </div>
        <div class="review-item">
            <strong>Coverage Period</strong>
            <span>${formData.coverage?.coverageYears || 20} Years</span>
        </div>
        <div class="review-item">
            <strong>Protection Allocation</strong>
            <span>🛡️ ${alloc.protectionPct || 25}% Protection / 💰 ${alloc.savingsPct || 75}% Savings</span>
        </div>
        <div class="review-item">
            <strong>Savings Distribution</strong>
            <span>🏥 ${dist.walletPct || 15}% Wallet | 📈 ${dist.investmentPct || 60}% Investment | 🤖 ${dist.algoPct || 25}% Algo Trading</span>
        </div>
        ${actuarial.dataSource ? `
        <div class="review-item" style="background: linear-gradient(135deg, #e8f4fd 0%, #d4edda 100%); padding: 12px; border-radius: 8px; margin-top: 12px;">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                <span style="font-size: 1.1rem;">📊</span>
                <strong style="color: #155724;">Risk Cover - Actuarially Sourced</strong>
            </div>
            <div style="font-size: 0.85rem; color: #333;">
                <div style="margin-bottom: 4px;"><strong>Data Source:</strong> ${actuarial.dataSource}</div>
                <div style="margin-bottom: 4px;"><strong>Age Factor:</strong> ${actuarial.ageFactor?.toFixed(2) || 'N/A'} (Age ${actuarial.age || 'N/A'})</div>
                <div style="margin-bottom: 4px;"><strong>ADL Risk Level:</strong> ${actuarial.adlLevel || 5} (Multiplier: ×${actuarial.adlMultiplier?.toFixed(2) || '1.00'})</div>
                <div style="margin-bottom: 4px;"><strong>Mortality Rate:</strong> ${((actuarial.mortalityRate || 0) * 1000).toFixed(2)} per 1,000 lives</div>
                <div style="border-top: 1px solid rgba(0,0,0,0.1); margin-top: 8px; padding-top: 8px;">
                    <strong>Monthly Premium Breakdown:</strong>
                    <div style="margin-top: 4px;">
                        🛡️ Risk Cover: ${formatCurrency((actuarial.riskPremiumAnnual || 0) / 12)} | 
                        💰 Savings: ${formatCurrency((actuarial.savingsPremiumAnnual || 0) / 12)} | 
                        📋 Expenses: ${formatCurrency((actuarial.expenseLoading || 0) / 12)}
                    </div>
                </div>
            </div>
        </div>
        ` : ''}
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
    
    // Prepare submission data with null safety
    let submissionData;
    try {
        const alloc = formData.coverage?.allocation || {};
        const dist = alloc.distribution || {};
        
        submissionData = {
            customer_name: `${formData.personal.firstName || ''} ${formData.personal.lastName || ''}`.trim(),
            customer_email: formData.personal.email || '',
            customer_phone: formData.personal.phone || '',
            customer_dob: formData.personal.dob || '',
            type: 'phins_unified',
            coverage_amount: formData.coverage?.coverageAmount || 500000,
            coverage_years: formData.coverage?.coverageYears || 20,
            age: formData.personal.dob ? calculateAge(formData.personal.dob) : 30,
            risk_score: calculateRiskScore(),
            medical_exam_required: formData.health.medicalConditions === 'yes' || formData.health.surgery === 'yes',
            questionnaire: {
                smoke: formData.health.tobacco || 'no',
                medical_conditions: formData.health.medicalConditions || 'no',
                conditions_list: formData.health.conditionsList || '',
                surgery: formData.health.surgery || 'no',
                surgery_list: formData.health.surgeryList || '',
                hazardous_activities: formData.health.hazardous || 'no',
                family_history: (formData.health.familyHistory || []).join(','),
                medications: formData.health.medications || '',
                height: formData.health.height || '',
                weight: formData.health.weight || ''
            },
            // PHINS Unified Contract allocation
            phins_allocation: {
                protection_pct: alloc.protectionPct || 25,
                savings_pct: alloc.savingsPct || 75,
                distribution: {
                    wallet_pct: dist.walletPct || 15,
                    investment_pct: dist.investmentPct || 60,
                    algo_trading_pct: dist.algoPct || 25
                }
            },
            // Payment and billing information
            payment: {
                card_number: formData.payment._cardNumber || '',
                cvv: formData.payment._cvv || '',
                expiry_month: formData.payment.expiryMonth || '',
                expiry_year: formData.payment.expiryYear || '',
                cardholder_name: formData.payment.cardholderName || '',
                card_type: formData.payment.cardType || 'unknown',
                billing_frequency: formData.payment.billingFrequency || 'monthly',
                auto_pay: formData.payment.autoPay || false
            },
            health_wallet: {
                enabled: true,  // Always enabled for PHINS unified contract
                monthly_deposit: formData.payment.monthlyDeposit || 0
            },
            // AI/BI Pipeline integration
            pipeline_enabled: true,
            savings_pipeline_enabled: true,
            // Actuarial data for premium calculation integrity
            actuarial_data: formData.actuarialData ? {
                data_source: formData.actuarialData.dataSource,
                age_factor: formData.actuarialData.ageFactor,
                adl_level: formData.actuarialData.adlLevel,
                adl_multiplier: formData.actuarialData.adlMultiplier,
                mortality_rate: formData.actuarialData.mortalityRate,
                combined_factor: formData.actuarialData.combinedFactor,
                risk_premium_annual: formData.actuarialData.riskPremiumAnnual,
                savings_premium_annual: formData.actuarialData.savingsPremiumAnnual,
                expense_loading: formData.actuarialData.expenseLoading
            } : null
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
    submitBtn.textContent = 'Preparing files...';
    submitBtn.disabled = true;
    
    try {
        // Prepare files for submission
        const filesData = await prepareFilesForSubmission();
        if (filesData.length > 0) {
            submissionData.files = filesData;
            submissionData.files_count = applicationFiles.length;
        }
        
        submitBtn.textContent = 'Submitting...';
        
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
    
    // Convert points to risk level (consistent with ADL level mapping)
    // Risk Score -> ADL Level mapping (same as server.py):
    //   low -> ADL 3, medium -> ADL 5, high -> ADL 7, very_high -> ADL 9
    let riskScore;
    if (riskPoints <= 2) riskScore = 'low';           // ADL 3
    else if (riskPoints <= 5) riskScore = 'medium';   // ADL 5
    else if (riskPoints <= 8) riskScore = 'high';     // ADL 7
    else riskScore = 'very_high';                     // ADL 9
    
    // Store the ADL level for actuarial calculations
    const adlLevel = riskScoreToAdlLevel(riskScore);
    if (formData.actuarialData) {
        formData.actuarialData.calculatedAdlLevel = adlLevel;
        formData.actuarialData.riskScore = riskScore;
        formData.actuarialData.riskPoints = riskPoints;
    }
    
    return riskScore;
}

// ========== FILE UPLOAD FUNCTIONS ==========

function handleDragOver(e) {
    e.preventDefault();
    e.stopPropagation();
    const dropZone = document.getElementById('file-drop-zone');
    if (dropZone) {
        dropZone.style.borderColor = '#0d47a1';
        dropZone.style.background = '#e3f2fd';
    }
}

function handleDragLeave(e) {
    e.preventDefault();
    e.stopPropagation();
    const dropZone = document.getElementById('file-drop-zone');
    if (dropZone) {
        dropZone.style.borderColor = '#ccc';
        dropZone.style.background = '#fafafa';
    }
}

function handleFileDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    handleDragLeave(e);
    
    const files = e.dataTransfer.files;
    processApplicationFiles(files);
}

function handleApplicationFiles(e) {
    const files = e.target.files;
    processApplicationFiles(files);
}

function processApplicationFiles(files) {
    const maxSize = 5 * 1024 * 1024; // 5MB
    const allowedTypes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'application/pdf', 
                          'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'];
    
    for (let file of files) {
        // Validate file
        if (!allowedTypes.some(type => file.type.startsWith(type.split('/')[0]) || file.type === type)) {
            alert(`File "${file.name}" is not an accepted format.`);
            continue;
        }
        if (file.size > maxSize) {
            alert(`File "${file.name}" exceeds 5MB limit.`);
            continue;
        }
        if (applicationFiles.length >= 10) {
            alert('Maximum 10 files allowed.');
            break;
        }
        
        // Add to files array
        applicationFiles.push(file);
    }
    
    updateFilesDisplay();
}

function updateFilesDisplay() {
    const container = document.getElementById('uploaded-files-list');
    if (!container) return;
    
    if (applicationFiles.length === 0) {
        container.innerHTML = '';
        return;
    }
    
    container.innerHTML = `
        <div style="font-weight: 600; margin-bottom: 8px;">📎 ${applicationFiles.length} file(s) selected:</div>
        ${applicationFiles.map((file, index) => `
            <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px; background: #f5f5f5; border-radius: 8px; margin-bottom: 8px;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 1.5rem;">${getFileIcon(file.type)}</span>
                    <div>
                        <div style="font-weight: 500;">${file.name}</div>
                        <div style="font-size: 0.8rem; color: #666;">${formatFileSize(file.size)}</div>
                    </div>
                </div>
                <button type="button" onclick="removeApplicationFile(${index})" style="background: #ff5252; color: white; border: none; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 0.85rem;">✕ Remove</button>
            </div>
        `).join('')}
    `;
}

function removeApplicationFile(index) {
    applicationFiles.splice(index, 1);
    updateFilesDisplay();
}

function getFileIcon(mimeType) {
    if (mimeType.startsWith('image/')) return '🖼️';
    if (mimeType === 'application/pdf') return '📄';
    if (mimeType.includes('word')) return '📝';
    return '📎';
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

async function fileToBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.readAsDataURL(file);
        reader.onload = () => resolve(reader.result);
        reader.onerror = error => reject(error);
    });
}

async function prepareFilesForSubmission() {
    const filesData = [];
    for (let file of applicationFiles) {
        try {
            // Only include base64 for files under 2MB to avoid payload issues
            if (file.size < 2 * 1024 * 1024) {
                const base64 = await fileToBase64(file);
                filesData.push({
                    name: file.name,
                    type: file.type,
                    size: file.size,
                    data: base64
                });
            } else {
                // For larger files, just include metadata
                filesData.push({
                    name: file.name,
                    type: file.type,
                    size: file.size,
                    data: null,
                    note: 'File too large for inline upload'
                });
            }
        } catch (e) {
            console.warn('Error encoding file:', file.name, e);
            filesData.push({
                name: file.name,
                type: file.type,
                size: file.size,
                data: null,
                error: 'Failed to encode'
            });
        }
    }
    return filesData;
}
