// Customer Application JavaScript
let currentStep = 1;
const totalSteps = 4;
let formData = {};

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    updateStepDisplay();
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

    // PHI investment settings trigger re-price
    ['phi-jurisdiction', 'phi-savings-percentage', 'phi-operational-load'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', () => updateCoverageDisplay());
            el.addEventListener('change', () => updateCoverageDisplay());
        }
    });
    
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

    // Show PHI investment settings only for disability/PHI product
    const phiSettings = document.getElementById('phi-investment-settings');
    if (phiSettings) {
        phiSettings.style.display = type === 'disability' ? 'block' : 'none';
    }
    
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

let _pricingEstimateTimer = null;

function calculatePremium(coverageAmount) {
    const policyType = document.getElementById('policy-type').value;
    const dob = document.getElementById('dob').value;
    
    if (!policyType || !dob) {
        return;
    }
    
    const age = calculateAge(dob);

    // For PHI disability, get a live estimate from the server pricing engine (actuarial table + adjustable split).
    if (policyType === 'disability') {
        const jurisdiction = document.getElementById('phi-jurisdiction')?.value || 'US';
        const savingsPercentage = document.getElementById('phi-savings-percentage')?.value || '25';
        const operationalLoad = document.getElementById('phi-operational-load')?.value || '50';

        // Debounce to avoid spamming API while typing
        if (_pricingEstimateTimer) clearTimeout(_pricingEstimateTimer);
        _pricingEstimateTimer = setTimeout(async () => {
            try {
                const url = `/api/pricing/estimate?type=disability&coverage_amount=${encodeURIComponent(coverageAmount)}&age=${encodeURIComponent(age)}&jurisdiction=${encodeURIComponent(jurisdiction)}&savings_percentage=${encodeURIComponent(savingsPercentage)}&operational_reinsurance_load=${encodeURIComponent(operationalLoad)}`;
                const priced = await fetch(url).then(r => r.json());
                const annualPremium = Number(priced.annual || 0);
                const monthlyPremium = Number(priced.monthly || 0);
                const quarterlyPremium = Number(priced.quarterly || 0);

                document.getElementById('monthly-premium').textContent =
                    new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(monthlyPremium);
                document.getElementById('quarterly-premium').textContent =
                    new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(quarterlyPremium);
                document.getElementById('annual-premium').textContent =
                    new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(annualPremium);

                formData.premiums = { monthly: monthlyPremium, quarterly: quarterlyPremium, annual: annualPremium, breakdown: priced.breakdown };
            } catch (e) {
                console.error('Pricing estimate failed:', e);
            }
        }, 250);
        return;
    }

    // Fallback estimate for other products (simple)
    const basePremiums = { life: 1200, health: 800, auto: 600, property: 1500, business: 3000 };
    const basePremium = basePremiums[policyType] || 1000;
    const ageFactor = 1.0 + (Math.max(0, age - 25) * 0.02);
    const coverageFactor = coverageAmount / 100000;
    const annualPremium = Math.round(basePremium * ageFactor * coverageFactor);
    const monthlyPremium = Math.round(annualPremium / 12);
    const quarterlyPremium = Math.round(annualPremium / 4);

    document.getElementById('monthly-premium').textContent =
        new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(monthlyPremium);
    document.getElementById('quarterly-premium').textContent =
        new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(quarterlyPremium);
    document.getElementById('annual-premium').textContent =
        new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(annualPremium);

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

function nextStep() {
    if (!validateStep(currentStep)) {
        return;
    }
    
    saveStepData(currentStep);
    
    if (currentStep < totalSteps) {
        currentStep++;
        updateStepDisplay();
        
        if (currentStep === 4) {
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
    
    // Update final premium display
    if (formData.premiums) {
        document.getElementById('final-premium-amount').textContent = 
            new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 }).format(formData.premiums.annual);
        document.getElementById('final-monthly').textContent = 
            new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(formData.premiums.monthly);
        document.getElementById('final-quarterly').textContent = 
            new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(formData.premiums.quarterly);
    }
}

async function handleSubmit(e) {
    e.preventDefault();
    
    if (!document.getElementById('terms-agree').checked || !document.getElementById('accuracy-agree').checked) {
        alert('Please agree to the terms and conditions');
        return;
    }
    
    // Prepare submission data
    const submissionData = {
        customer_name: `${formData.personal.firstName} ${formData.personal.lastName}`,
        customer_email: formData.personal.email,
        customer_phone: formData.personal.phone,
        customer_dob: formData.personal.dob,
        type: formData.coverage.policyType,
        coverage_amount: formData.coverage.coverageAmount,
        age: calculateAge(formData.personal.dob),
        risk_score: calculateRiskScore(),
        medical_exam_required: formData.health.medicalConditions === 'yes' || formData.health.surgery === 'yes',
        // PHI configuration fields (only used for disability/PHI product)
        jurisdiction: document.getElementById('phi-jurisdiction')?.value || 'US',
        savings_percentage: parseFloat(document.getElementById('phi-savings-percentage')?.value || '25'),
        operational_reinsurance_load: parseFloat(document.getElementById('phi-operational-load')?.value || '50'),
        questionnaire: {
            smoke: formData.health.tobacco,
            medical_conditions: formData.health.medicalConditions,
            conditions_list: formData.health.conditionsList,
            surgery: formData.health.surgery,
            surgery_list: formData.health.surgeryList,
            hazardous_activities: formData.health.hazardous,
            family_history: formData.health.familyHistory.join(','),
            medications: formData.health.medications,
            height: formData.health.height,
            weight: formData.health.weight
        }
    };
    
    try {
        const response = await fetch('/api/policies/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(submissionData)
        });
        
        const data = await response.json();
        
        if (response.ok) {
            // Show success message
            document.getElementById('app-id').textContent = data.underwriting.id;
            document.getElementById('policy-id').textContent = data.policy.id;
            document.getElementById('success-premium').textContent = 
                new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(data.policy.annual_premium) + ' per year';
            
            document.getElementById('success-message').style.display = 'flex';
        } else {
            alert('Error submitting application: ' + (data.error || 'Please try again'));
        }
    } catch (error) {
        alert('Network error. Please check your connection and try again.');
        console.error('Submission error:', error);
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
