// PHINS Admin Portal JavaScript
let currentUser = null;
let authToken = null;

// API Base URL
const API_BASE = '';

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    checkAuth();
    setupEventListeners();
});

async function checkAuth() {
    // Check admin-portal specific token
    let token = localStorage.getItem('phins_admin_token');
    let userData = localStorage.getItem('phins_admin_user');
    
    // If not found, check for main system token
    if (!token) {
        token = localStorage.getItem('phins_token');
        const username = sessionStorage.getItem('username');

        if (token) {
            // User is authenticated in main system, auto-login to admin portal.
            // Prefer username from sessionStorage, but fall back to API profile if absent.
            authToken = token;

            let name = username;
            let role = 'admin';
            if (!name) {
                try {
                    const prof = await fetch(`${API_BASE}/api/profile`, {headers: {'Authorization': `Bearer ${token}`} }).then(r => r.json());
                    name = prof?.name || prof?.username || prof?.email || 'Admin';
                    role = String(prof?.role || 'admin').toLowerCase();
                } catch {
                    name = 'Admin';
                }
            }

            currentUser = {name, role};
            localStorage.setItem('phins_admin_token', authToken);
            localStorage.setItem('phins_admin_user', JSON.stringify(currentUser));
            showDashboard();
            return;
        }
    }
    
    if (token) {
        authToken = token;
        if (userData) {
            currentUser = JSON.parse(userData);
            showDashboard();
            return;
        }

        // Token exists but user data missing: attempt to hydrate from profile.
        try {
            const prof = await fetch(`${API_BASE}/api/profile`, {headers: getAuthHeaders()}).then(r => r.json());
            currentUser = {name: prof?.name || prof?.username || prof?.email || 'Admin', role: String(prof?.role || 'admin').toLowerCase()};
            localStorage.setItem('phins_admin_user', JSON.stringify(currentUser));
            showDashboard();
            return;
        } catch {
            // Fall through to login screen if we can't hydrate identity.
        }
    }

    showLogin();
}

function showLogin() {
    document.getElementById('login-screen').classList.add('active');
    document.getElementById('dashboard-screen').classList.remove('active');
}

function showDashboard() {
    document.getElementById('login-screen').classList.remove('active');
    document.getElementById('dashboard-screen').classList.add('active');
    document.getElementById('user-name').textContent = currentUser?.name || 'User';
    
    // Check if redirected from main admin dashboard for new policy
    const redirectSource = localStorage.getItem('phins_redirect_source');
    if (redirectSource === 'admin-dashboard') {
        localStorage.removeItem('phins_redirect_source');
        // Auto-navigate to create policy view
        setTimeout(() => {
            const createPolicyLink = document.querySelector('[data-screen="create-policy"]');
            if (createPolicyLink) {
                createPolicyLink.click();
            }
        }, 100);
    } else {
        loadDashboardData();
    }
}

function setupEventListeners() {
    // Login form
    document.getElementById('login-form').addEventListener('submit', handleLogin);
    
    // Logout
    document.getElementById('logout-btn').addEventListener('click', handleLogout);
    
    // Navigation
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', handleNavigation);
    });
    
    // Policy form
    document.getElementById('create-policy-form').addEventListener('submit', handleCreatePolicy);
    
    // Claims
    document.getElementById('create-claim-btn').addEventListener('click', openClaimModal);
    document.getElementById('create-claim-form').addEventListener('submit', handleCreateClaim);
    document.querySelector('.close').addEventListener('click', closeClaimModal);
    
    // Filters
    document.getElementById('uw-filter').addEventListener('change', loadUnderwritingData);
    document.getElementById('claims-filter').addEventListener('change', loadClaimsData);
}

async function handleLogin(e) {
    e.preventDefault();
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    
    try {
        const response = await fetch(`${API_BASE}/api/login`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username, password})
        });
        
        const data = await response.json();
        
        if (response.ok) {
            authToken = data.token;
            currentUser = {name: data.name, role: data.role};
            localStorage.setItem('phins_admin_token', authToken);
            localStorage.setItem('phins_admin_user', JSON.stringify(currentUser));
            showDashboard();
        } else {
            document.getElementById('login-error').textContent = data.error || 'Login failed';
        }
    } catch (error) {
        document.getElementById('login-error').textContent = 'Network error: ' + error.message;
    }
}

function handleLogout() {
    authToken = null;
    currentUser = null;
    localStorage.removeItem('phins_admin_token');
    localStorage.removeItem('phins_admin_user');
    showLogin();
}

function handleNavigation(e) {
    e.preventDefault();
    const screen = e.target.dataset.screen;
    
    // Update nav active state
    document.querySelectorAll('.nav-link').forEach(link => link.classList.remove('active'));
    e.target.classList.add('active');
    
    // Show appropriate view
    document.querySelectorAll('.view').forEach(view => view.classList.remove('active'));
    document.getElementById(`${screen}-view`).classList.add('active');
    
    // Load data for specific views
    switch(screen) {
        case 'dashboard':
            loadDashboardData();
            break;
        case 'policies':
            loadPoliciesData();
            break;
        case 'underwriting':
            loadUnderwritingData();
            break;
        case 'claims':
            loadClaimsData();
            break;
        case 'bi-actuary':
            loadBIActuary();
            break;
        case 'bi-underwriting':
            loadBIUnderwriting();
            break;
        case 'bi-accounting':
            loadBIAccounting();
            break;
    }
}

async function loadDashboardData() {
    try {
        const [policies, underwriting, claims, biAccounting] = await Promise.all([
            fetch(`${API_BASE}/api/policies`, {headers: getAuthHeaders()}).then(r => r.json()),
            fetch(`${API_BASE}/api/underwriting`, {headers: getAuthHeaders()}).then(r => r.json()),
            fetch(`${API_BASE}/api/claims`, {headers: getAuthHeaders()}).then(r => r.json()),
            fetch(`${API_BASE}/api/bi/accounting`, {headers: getAuthHeaders()}).then(r => r.json())
        ]);
        const policyItems = Array.isArray(policies.items) ? policies.items : (Array.isArray(policies) ? policies : []);
        const uwItems = Array.isArray(underwriting.items) ? underwriting.items : (Array.isArray(underwriting) ? underwriting : []);
        const claimItems = Array.isArray(claims.items) ? claims.items : (Array.isArray(claims) ? claims : []);
        
        document.getElementById('stat-policies').textContent = policyItems.length;
        document.getElementById('stat-pending').textContent = uwItems.filter(u => u.status === 'pending').length;
        document.getElementById('stat-claims').textContent = claimItems.filter(c => c.status !== 'paid' && c.status !== 'rejected').length;
        document.getElementById('stat-revenue').textContent = `$${formatNumber(biAccounting.total_revenue)}`;
    } catch (error) {
        console.error('Error loading dashboard data:', error);
    }
}

async function loadPoliciesData() {
    try {
        const payload = await fetch(`${API_BASE}/api/policies`, {headers: getAuthHeaders()}).then(r => r.json());
        const policies = Array.isArray(payload.items) ? payload.items : (Array.isArray(payload) ? payload : []);
        
        const html = `
            <table>
                <thead>
                    <tr>
                        <th>Policy ID</th>
                        <th>Customer ID</th>
                        <th>Type</th>
                        <th>Coverage</th>
                        <th>Premium (Annual)</th>
                        <th>Status</th>
                        <th>Created</th>
                    </tr>
                </thead>
                <tbody>
                    ${policies.map(p => `
                        <tr>
                            <td>${p.id}</td>
                            <td>${p.customer_id}</td>
                            <td>${capitalize(p.type)}</td>
                            <td>$${formatNumber(p.coverage_amount)}</td>
                            <td>$${formatNumber(p.annual_premium)}</td>
                            <td><span class="status-badge status-${p.status.replace('_', '-')}">${capitalize(p.status)}</span></td>
                            <td>${formatDate(p.created_date)}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
        
        document.getElementById('policies-list').innerHTML = html;
    } catch (error) {
        document.getElementById('policies-list').innerHTML = '<p>Error loading policies</p>';
    }
}

async function handleCreatePolicy(e) {
    e.preventDefault();
    
    const formData = {
        customer_name: document.getElementById('customer-name').value,
        customer_email: document.getElementById('customer-email').value,
        customer_phone: document.getElementById('customer-phone').value,
        customer_dob: document.getElementById('customer-dob').value,
        type: document.getElementById('policy-type').value,
        coverage_amount: parseFloat(document.getElementById('coverage-amount').value),
        risk_score: document.getElementById('risk-score').value,
        jurisdiction: document.getElementById('jurisdiction')?.value || 'US',
        savings_percentage: parseFloat(document.getElementById('savings-percentage')?.value || '25'),
        operational_reinsurance_load: parseFloat(document.getElementById('operational-load')?.value || '50'),
        medical_exam_required: document.getElementById('medical-exam-required').checked,
        age: calculateAge(document.getElementById('customer-dob').value),
        questionnaire: {
            smoke: document.querySelector('input[name="q-smoke"]:checked')?.value,
            medical_conditions: document.querySelector('input[name="q-medical"]:checked')?.value,
            surgery: document.querySelector('input[name="q-surgery"]:checked')?.value,
            hazardous_activities: document.querySelector('input[name="q-hazard"]:checked')?.value,
            family_history: document.querySelector('input[name="q-family"]:checked')?.value,
            medications: document.getElementById('q-medications').value,
            height: document.getElementById('q-height').value,
            weight: document.getElementById('q-weight').value
        }
    };
    
    try {
        const response = await fetch(`${API_BASE}/api/policies/create`, {
            method: 'POST',
            headers: {...getAuthHeaders(), 'Content-Type': 'application/json'},
            body: JSON.stringify(formData)
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showResult('policy-result', 'success', 
                `Policy created successfully! Policy ID: ${data.policy.id}<br>` +
                `Underwriting Application ID: ${data.underwriting.id}<br>` +
                `Annual Premium: $${data.policy.annual_premium}<br>` +
                `Status: Pending Underwriting`
            );
            document.getElementById('create-policy-form').reset();
        } else {
            showResult('policy-result', 'error', data.error || 'Failed to create policy');
        }
    } catch (error) {
        showResult('policy-result', 'error', 'Network error: ' + error.message);
    }
}

async function loadUnderwritingData() {
    try {
        const filter = document.getElementById('uw-filter').value;
        const payload = await fetch(`${API_BASE}/api/underwriting`, {headers: getAuthHeaders()}).then(r => r.json());
        const applications = Array.isArray(payload.items) ? payload.items : (Array.isArray(payload) ? payload : []);
        
        const filtered = filter === 'all' ? applications : applications.filter(a => a.status === filter);
        
        const html = `
            <table>
                <thead>
                    <tr>
                        <th>Application ID</th>
                        <th>Policy ID</th>
                        <th>Customer ID</th>
                        <th>Risk Assessment</th>
                        <th>Medical Exam</th>
                        <th>Status</th>
                        <th>Submitted</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${filtered.map(a => `
                        <tr>
                            <td>${a.id}</td>
                            <td>${a.policy_id}</td>
                            <td>${a.customer_id}</td>
                            <td><span class="status-badge status-${a.risk_assessment}">${capitalize(a.risk_assessment)}</span></td>
                            <td>${a.medical_exam_required ? 'Yes' : 'No'}</td>
                            <td><span class="status-badge status-${a.status}">${capitalize(a.status)}</span></td>
                            <td>${formatDate(a.submitted_date)}</td>
                            <td>
                                ${a.status === 'pending' ? `
                                    <button class="action-btn btn-success" onclick="approveUnderwriting('${a.id}')">Approve</button>
                                    <button class="action-btn btn-danger" onclick="rejectUnderwriting('${a.id}')">Reject</button>
                                ` : '-'}
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
        
        document.getElementById('underwriting-list').innerHTML = html;
    } catch (error) {
        document.getElementById('underwriting-list').innerHTML = '<p>Error loading applications</p>';
    }
}

async function approveUnderwriting(id) {
    try {
        const response = await fetch(`${API_BASE}/api/underwriting/approve`, {
            method: 'POST',
            headers: {...getAuthHeaders(), 'Content-Type': 'application/json'},
            body: JSON.stringify({id, approved_by: currentUser.name})
        });
        
        if (response.ok) {
            alert('Application approved successfully!');
            loadUnderwritingData();
        }
    } catch (error) {
        alert('Error approving application');
    }
}

async function rejectUnderwriting(id) {
    const reason = prompt('Enter rejection reason:');
    if (!reason) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/underwriting/reject`, {
            method: 'POST',
            headers: {...getAuthHeaders(), 'Content-Type': 'application/json'},
            body: JSON.stringify({id, reason})
        });
        
        if (response.ok) {
            alert('Application rejected');
            loadUnderwritingData();
        }
    } catch (error) {
        alert('Error rejecting application');
    }
}

async function loadClaimsData() {
    try {
        const filter = document.getElementById('claims-filter').value;
        const payload = await fetch(`${API_BASE}/api/claims`, {headers: getAuthHeaders()}).then(r => r.json());
        const claims = Array.isArray(payload.items) ? payload.items : (Array.isArray(payload) ? payload : []);
        
        const filtered = filter === 'all' ? claims : claims.filter(c => c.status === filter);
        
        const html = `
            <table>
                <thead>
                    <tr>
                        <th>Claim ID</th>
                        <th>Policy ID</th>
                        <th>Type</th>
                        <th>Claimed Amount</th>
                        <th>Approved Amount</th>
                        <th>Status</th>
                        <th>Filed Date</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${filtered.map(c => `
                        <tr>
                            <td>${c.id}</td>
                            <td>${c.policy_id}</td>
                            <td>${capitalize(c.type)}</td>
                            <td>$${formatNumber(c.claimed_amount)}</td>
                            <td>${c.approved_amount ? '$' + formatNumber(c.approved_amount) : '-'}</td>
                            <td><span class="status-badge status-${c.status}">${capitalize(c.status)}</span></td>
                            <td>${formatDate(c.filed_date)}</td>
                            <td>
                                ${c.status === 'pending' ? `
                                    <button class="action-btn btn-success" onclick="approveClaim('${c.id}', ${c.claimed_amount})">Approve</button>
                                    <button class="action-btn btn-danger" onclick="rejectClaim('${c.id}')">Reject</button>
                                ` : c.status === 'approved' ? `
                                    <button class="action-btn btn-primary" onclick="payClaim('${c.id}')">Pay</button>
                                ` : '-'}
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
        
        document.getElementById('claims-list').innerHTML = html;
    } catch (error) {
        document.getElementById('claims-list').innerHTML = '<p>Error loading claims</p>';
    }
}

function openClaimModal() {
    document.getElementById('claim-modal').classList.add('active');
}

function closeClaimModal() {
    document.getElementById('claim-modal').classList.remove('active');
}

async function handleCreateClaim(e) {
    e.preventDefault();
    
    const formData = {
        policy_id: document.getElementById('claim-policy').value,
        type: document.getElementById('claim-type').value,
        claimed_amount: parseFloat(document.getElementById('claim-amount').value),
        description: document.getElementById('claim-description').value
    };
    
    try {
        const response = await fetch(`${API_BASE}/api/claims/create`, {
            method: 'POST',
            headers: {...getAuthHeaders(), 'Content-Type': 'application/json'},
            body: JSON.stringify(formData)
        });
        
        if (response.ok) {
            alert('Claim created successfully!');
            closeClaimModal();
            document.getElementById('create-claim-form').reset();
            loadClaimsData();
        }
    } catch (error) {
        alert('Error creating claim');
    }
}

async function approveClaim(id, amount) {
    const approvedAmount = prompt(`Enter approved amount (claimed: $${amount}):`, amount);
    if (!approvedAmount) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/claims/approve`, {
            method: 'POST',
            headers: {...getAuthHeaders(), 'Content-Type': 'application/json'},
            body: JSON.stringify({id, approved_amount: parseFloat(approvedAmount), approved_by: currentUser.name})
        });
        
        if (response.ok) {
            alert('Claim approved!');
            loadClaimsData();
        }
    } catch (error) {
        alert('Error approving claim');
    }
}

async function rejectClaim(id) {
    const reason = prompt('Enter rejection reason:');
    if (!reason) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/claims/reject`, {
            method: 'POST',
            headers: {...getAuthHeaders(), 'Content-Type': 'application/json'},
            body: JSON.stringify({id, reason})
        });
        
        if (response.ok) {
            alert('Claim rejected');
            loadClaimsData();
        }
    } catch (error) {
        alert('Error rejecting claim');
    }
}

async function payClaim(id) {
    const method = prompt('Enter payment method (bank_transfer, check, direct_deposit):', 'bank_transfer');
    if (!method) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/claims/pay`, {
            method: 'POST',
            headers: {...getAuthHeaders(), 'Content-Type': 'application/json'},
            body: JSON.stringify({id, payment_method: method})
        });
        
        if (response.ok) {
            const data = await response.json();
            alert(`Claim paid!\nPayment Reference: ${data.claim.payment_reference}`);
            loadClaimsData();
        }
    } catch (error) {
        alert('Error processing payment');
    }
}

async function loadBIActuary() {
    try {
        const data = await fetch(`${API_BASE}/api/bi/actuary`, {headers: getAuthHeaders()}).then(r => r.json());
        
        document.getElementById('bi-actuary-exposure').textContent = `$${formatNumber(data.total_exposure)}`;
        document.getElementById('bi-actuary-avg-premium').textContent = `$${formatNumber(data.average_premium)}`;
        document.getElementById('bi-actuary-claims-ratio').textContent = `${(data.claims_ratio * 100).toFixed(2)}%`;
        document.getElementById('bi-actuary-loss-ratio').textContent = `${(data.loss_ratio * 100).toFixed(2)}%`;
        
        renderBarChart('risk-distribution-chart', data.risk_distribution);
        renderBarChart('policy-types-chart', data.policy_by_type);
    } catch (error) {
        console.error('Error loading actuary BI:', error);
    }
}

async function loadBIUnderwriting() {
    try {
        const data = await fetch(`${API_BASE}/api/bi/underwriting`, {headers: getAuthHeaders()}).then(r => r.json());
        
        document.getElementById('bi-uw-pending').textContent = data.pending_applications;
        document.getElementById('bi-uw-approved').textContent = data.approved_this_month;
        document.getElementById('bi-uw-rejection').textContent = `${(data.rejection_rate * 100).toFixed(2)}%`;
        document.getElementById('bi-uw-processing').textContent = `${data.average_processing_time} days`;
        document.getElementById('bi-uw-medical').textContent = data.medical_exams_required;
        
        renderBarChart('risk-assessment-chart', data.risk_assessment_distribution);
    } catch (error) {
        console.error('Error loading underwriting BI:', error);
    }
}

async function loadBIAccounting() {
    try {
        const data = await fetch(`${API_BASE}/api/bi/accounting`, {headers: getAuthHeaders()}).then(r => r.json());
        
        document.getElementById('bi-acct-revenue').textContent = `$${formatNumber(data.total_revenue)}`;
        document.getElementById('bi-acct-claims').textContent = `$${formatNumber(data.total_claims_paid)}`;
        document.getElementById('bi-acct-net').textContent = `$${formatNumber(data.net_income)}`;
        document.getElementById('bi-acct-margin').textContent = `${data.profit_margin.toFixed(2)}%`;
        document.getElementById('bi-acct-outstanding').textContent = `$${formatNumber(data.outstanding_premiums)}`;
        document.getElementById('bi-acct-liability').textContent = `$${formatNumber(data.pending_claims_liability)}`;
        
        renderMonthlyChart('monthly-breakdown-chart', data.monthly_breakdown);
    } catch (error) {
        console.error('Error loading accounting BI:', error);
    }
}

// Utility Functions
function getAuthHeaders() {
    return authToken ? {'Authorization': `Bearer ${authToken}`} : {};
}

function formatNumber(num) {
    return new Intl.NumberFormat('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}).format(num);
}

function formatDate(dateString) {
    if (!dateString) return '-';
    return new Date(dateString).toLocaleDateString('en-US', {year: 'numeric', month: 'short', day: 'numeric'});
}

function capitalize(str) {
    return str.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

function calculateAge(dob) {
    const diff = Date.now() - new Date(dob).getTime();
    return Math.floor(diff / (365.25 * 24 * 60 * 60 * 1000));
}

function showResult(elementId, type, message) {
    const el = document.getElementById(elementId);
    el.className = `result-message ${type}`;
    el.innerHTML = message;
}

function renderBarChart(elementId, data) {
    const total = Object.values(data).reduce((a, b) => a + b, 0);
    const html = Object.entries(data).map(([key, value]) => {
        const percent = total > 0 ? (value / total * 100) : 0;
        return `
            <div style="margin: 10px 0;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                    <span>${capitalize(key)}</span>
                    <span>${value} (${percent.toFixed(1)}%)</span>
                </div>
                <div style="background: #e1e8ed; height: 24px; border-radius: 4px; overflow: hidden;">
                    <div style="background: #667eea; height: 100%; width: ${percent}%; transition: width 0.3s;"></div>
                </div>
            </div>
        `;
    }).join('');
    
    document.getElementById(elementId).innerHTML = html;
}

function renderMonthlyChart(elementId, data) {
    const maxValue = Math.max(...data.flatMap(d => [d.revenue, d.claims]));
    const html = data.map(d => `
        <div style="display: inline-block; width: ${100 / data.length}%; text-align: center; vertical-align: bottom;">
            <div style="display: flex; flex-direction: column; align-items: center; height: 200px; justify-content: flex-end;">
                <div style="width: 30%; background: #667eea; height: ${(d.revenue / maxValue * 180)}px; margin: 2px;" title="Revenue: $${formatNumber(d.revenue)}"></div>
                <div style="width: 30%; background: #dc3545; height: ${(d.claims / maxValue * 180)}px; margin: 2px;" title="Claims: $${formatNumber(d.claims)}"></div>
            </div>
            <div style="font-size: 0.7rem; margin-top: 5px;">${d.month}</div>
        </div>
    `).join('');
    
    document.getElementById(elementId).innerHTML = `
        <div style="display: flex; justify-content: center; margin-bottom: 10px;">
            <span style="margin: 0 10px;"><span style="display: inline-block; width: 12px; height: 12px; background: #667eea; margin-right: 5px;"></span>Revenue</span>
            <span style="margin: 0 10px;"><span style="display: inline-block; width: 12px; height: 12px; background: #dc3545; margin-right: 5px;"></span>Claims</span>
        </div>
        ${html}
    `;
}
