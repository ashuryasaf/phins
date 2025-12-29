// Customer Application JavaScript
let currentStep = 1;
const totalSteps = 5;
let formData = {};

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
    document.getElementById('coverage-amount-display').textContent = 
        new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 }).format(amount);
    
    // Calculate premium based on coverage
    calculatePremium(amount);
}

function calculatePremium(coverageAmount) {
    const policyType = document.getElementById('policy-type').value;
    const dob = document.getElementById('dob').value;
    
    if (!policyType || !dob) {
        return;
    }
    
    const age = calculateAge(dob);
    
    // Base premium by type
    const basePremiums = {
        'life': 1200,
        'health': 800,
        'auto': 600,
        'property': 1500,
        'disability': 1500
    };
    
    const basePremium = basePremiums[policyType] || 1000;
    
    // Age factor
    const ageFactor = 1.0 + (Math.max(0, age - 25) * 0.02);
    
    // Coverage factor
    const coverageFactor = coverageAmount / 100000;
    
    // Risk factor (will be determined after health assessment, using medium for now)
    const riskFactor = 1.0;
    
    const annualPremium = Math.round(basePremium * ageFactor * coverageFactor * riskFactor);
    const monthlyPremium = Math.round(annualPremium / 12);
    const quarterlyPremium = Math.round(annualPremium / 4);
    
    // Update display
    document.getElementById('monthly-premium').textContent = 
        new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(monthlyPremium);
    document.getElementById('quarterly-premium').textContent = 
        new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(quarterlyPremium);
    document.getElementById('annual-premium').textContent = 
        new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(annualPremium);
    
    // Store for later
    formData.premiums = { monthly: monthlyPremium, quarterly: quarterlyPremium, annual: annualPremium };
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
        const policyType = document.getElementById('policy-type').value;
        if (!policyType) {
            alert('Please select a policy type');
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
                policyType: document.getElementById('policy-type').value,
                coverageAmount: parseInt(document.getElementById('coverage-slider').value)
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
    
    // Coverage Details
    const policyTypes = {
        'life': 'Life Insurance',
        'health': 'Health Insurance',
        'disability': 'PHINS Disability + Investment',
        'auto': 'Auto Insurance',
        'property': 'Property Insurance'
    };
    
    const coverageHtml = `
        <div class="review-item">
            <strong>Policy Type</strong>
            <span>${policyTypes[formData.coverage.policyType]}</span>
        </div>
        <div class="review-item">
            <strong>Coverage Amount</strong>
            <span>${new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 }).format(formData.coverage.coverageAmount)}</span>
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
    
    // Prepare submission data with null safety
    let submissionData;
    try {
        submissionData = {
            customer_name: `${formData.personal.firstName || ''} ${formData.personal.lastName || ''}`.trim(),
            customer_email: formData.personal.email || '',
            customer_phone: formData.personal.phone || '',
            customer_dob: formData.personal.dob || '',
            type: formData.coverage.policyType || 'life',
            coverage_amount: formData.coverage.coverageAmount || 100000,
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
                enabled: formData.payment.healthWalletEnabled || false,
                monthly_deposit: formData.payment.monthlyDeposit || 0
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
