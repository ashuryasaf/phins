/**
 * PHINS Insurance Quote Form - Interactive JavaScript
 * Handles validation, multimedia capture, and form submission
 */

// Global state
let photoBlob = null;
let videoBlob = null;
let audioBlob = null;
let mediaRecorder = null;
let recordingTimer = null;
let recordingSeconds = 0;
let cameraStream = null;

// Form validation state
const formData = {};
const requiredFields = [
  'firstName', 'lastName', 'dob', 'gender', 'email', 'phone',
  'address', 'city', 'postalCode', 'nationalId', 'healthCondition',
  'height', 'weight', 'smoking', 'preExisting', 'maritalStatus',
  'occupation', 'incomeRange', 'exercise', 'coverageAmount',
  'policyTerm', 'truthDeclaration', 'privacyConsent', 'termsAccept', 'signature'
];

function getToken() {
  return localStorage.getItem('phins_token') || localStorage.getItem('phins_admin_token');
}

function setToken(token) {
  if (token) localStorage.setItem('phins_token', token);
}

function setQuoteLocked(locked) {
  const rest = document.getElementById('quote-rest');
  const nextBlock = document.getElementById('account-next-block');
  const pwRow = document.getElementById('account-password-row');
  const pw = document.getElementById('accountPassword');
  const pw2 = document.getElementById('accountPasswordConfirm');
  if (rest) rest.style.display = locked ? 'none' : 'block';
  if (nextBlock) nextBlock.style.display = locked ? 'flex' : 'none';
  if (pwRow) pwRow.style.display = locked ? 'grid' : 'none';
  if (pw) pw.required = !!locked;
  if (pw2) pw2.required = !!locked;
}

// Initialize form
document.addEventListener('DOMContentLoaded', function() {
  setupFormValidation();
  setupConditionalFields();
  setupHealthSlider();
  loadDraft();
  updateProgress();

  // Gate the rest of the application behind account creation/login,
  // so we can send underwriting/billing/claims notifications and keep the pipeline linked.
  const hasToken = !!getToken();
  setQuoteLocked(!hasToken);

  const nextBtn = document.getElementById('accountNextBtn');
  if (nextBtn) {
    nextBtn.addEventListener('click', async () => {
      const msg = document.getElementById('accountNextMsg');
      if (msg) msg.textContent = '';

      // Validate key identity fields
      const first = document.getElementById('firstName');
      const last = document.getElementById('lastName');
      const dob = document.getElementById('dob');
      const email = document.getElementById('email');
      const phone = document.getElementById('phone');
      const pw = document.getElementById('accountPassword');
      const pw2 = document.getElementById('accountPasswordConfirm');

      const must = [first, last, dob, email, phone, pw, pw2].filter(Boolean);
      let ok = true;
      must.forEach((el) => { if (el && !validateField(el)) ok = false; });
      if (!ok) {
        if (msg) msg.textContent = 'Please complete the required fields above.';
        return;
      }

      if (String(pw.value || '').length < 8) {
        const e = document.getElementById('accountPassword-error');
        if (e) { e.textContent = 'Password must be at least 8 characters'; e.style.display = 'block'; }
        return;
      }
      if (String(pw.value || '') !== String(pw2.value || '')) {
        const e = document.getElementById('accountPasswordConfirm-error');
        if (e) { e.textContent = 'Passwords do not match'; e.style.display = 'block'; }
        return;
      }

      nextBtn.disabled = true;
      nextBtn.textContent = 'Saving…';
      try {
        const fullName = `${String(first.value || '').trim()} ${String(last.value || '').trim()}`.trim();

        // Register (best-effort; if already registered, proceed to login)
        const regResp = await fetch('/api/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: fullName || String(email.value || '').trim(),
            email: String(email.value || '').trim(),
            phone: String(phone.value || '').trim(),
            dob: String(dob.value || '').trim(),
            password: String(pw.value || ''),
          }),
        });
        if (!regResp.ok && regResp.status !== 409) {
          const reg = await regResp.json().catch(() => ({}));
          throw new Error(reg.error || 'Registration failed');
        }

        // Login to create an authenticated session for notifications/pipeline
        const loginResp = await fetch('/api/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: String(email.value || '').trim().toLowerCase(), password: String(pw.value || '') }),
        });
        const login = await loginResp.json().catch(() => ({}));
        if (!loginResp.ok || !login.token) throw new Error(login.error || 'Login failed');

        setToken(login.token);
        saveDraft(); // save on "Next"
        setQuoteLocked(false);
        if (msg) msg.textContent = 'Account saved. Continue your application below.';
      } catch (e) {
        if (msg) msg.textContent = String(e && e.message ? e.message : 'Account setup failed');
      } finally {
        nextBtn.disabled = false;
        nextBtn.textContent = 'Next: Save Account & Continue';
      }
    });
  }
});

// Setup real-time validation for all inputs
function setupFormValidation() {
  const form = document.getElementById('quoteForm');
  
  // Add event listeners to all inputs
  const inputs = form.querySelectorAll('input, select, textarea');
  inputs.forEach(input => {
    input.addEventListener('blur', function() {
      validateField(this);
      updateProgress();
    });
    
    input.addEventListener('input', function() {
      if (this.classList.contains('invalid')) {
        validateField(this);
      }
      updateProgress();
    });
  });
  
  // Form submission
  form.addEventListener('submit', function(e) {
    e.preventDefault();
    handleSubmit();
  });
}

// Setup conditional field visibility
function setupConditionalFields() {
  // Pre-existing conditions
  document.querySelectorAll('input[name="preExisting"]').forEach(radio => {
    radio.addEventListener('change', function() {
      const detailsGroup = document.getElementById('conditionsDetailsGroup');
      const detailsField = document.getElementById('conditionsDetails');
      if (this.value === 'yes') {
        detailsGroup.style.display = 'block';
        detailsField.required = true;
      } else {
        detailsGroup.style.display = 'none';
        detailsField.required = false;
      }
    });
  });
  
  // Medications
  document.querySelectorAll('input[name="medications"]').forEach(radio => {
    radio.addEventListener('change', function() {
      const detailsGroup = document.getElementById('medicationsDetailsGroup');
      if (this.value === 'yes') {
        detailsGroup.style.display = 'block';
      } else {
        detailsGroup.style.display = 'none';
      }
    });
  });
  
  // Surgeries
  document.querySelectorAll('input[name="surgeries"]').forEach(radio => {
    radio.addEventListener('change', function() {
      const detailsGroup = document.getElementById('surgeriesDetailsGroup');
      if (this.value === 'yes') {
        detailsGroup.style.display = 'block';
      } else {
        detailsGroup.style.display = 'none';
      }
    });
  });
  
  // Custom coverage amount
  document.getElementById('coverageAmount').addEventListener('change', function() {
    const customGroup = document.getElementById('customCoverageGroup');
    const customField = document.getElementById('customCoverage');
    if (this.value === 'custom') {
      customGroup.style.display = 'block';
      customField.required = true;
    } else {
      customGroup.style.display = 'none';
      customField.required = false;
    }
  });
}

// Setup health condition slider
function setupHealthSlider() {
  const slider = document.getElementById('healthCondition');
  const valueDisplay = document.getElementById('healthConditionValue');
  
  slider.addEventListener('input', function() {
    valueDisplay.textContent = this.value;
    updateSliderColor(this);
  });
  
  updateSliderColor(slider);
}

function updateSliderColor(slider) {
  const value = slider.value;
  const percentage = ((value - 1) / 9) * 100;
  
  // Color gradient from green (healthy) to red (critical)
  let color;
  if (value <= 3) color = '#4CAF50';
  else if (value <= 5) color = '#8BC34A';
  else if (value <= 7) color = '#FF9800';
  else color = '#f44336';
  
  slider.style.background = `linear-gradient(90deg, ${color} ${percentage}%, #ddd ${percentage}%)`;
}

// Field validation
function validateField(field) {
  const fieldId = field.id || field.name;
  const errorDiv = document.getElementById(`${fieldId}-error`);
  const successDiv = document.getElementById(`${fieldId}-success`);
  
  let isValid = true;
  let errorMessage = '';
  
  // Check if field is required and empty
  if (field.required && !field.value.trim()) {
    isValid = false;
    errorMessage = 'This field is required';
  }
  
  // Specific validations
  if (isValid && field.value) {
    switch(field.id) {
      case 'firstName':
      case 'lastName':
        if (!/^[a-zA-Z\s\-']{2,100}$/.test(field.value)) {
          isValid = false;
          errorMessage = 'Only letters, spaces, hyphens, and apostrophes allowed (2-100 characters)';
        }
        break;
        
      case 'email':
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(field.value)) {
          isValid = false;
          errorMessage = 'Please enter a valid email address';
        } else {
          // Real-time email validation via API
          validateEmailAsync(field.value);
        }
        break;
        
      case 'phone':
        if (!/^\+?[\d\s\-\(\)\.]{7,30}$/.test(field.value)) {
          isValid = false;
          errorMessage = 'Please enter a valid phone number (e.g., +1 555-123-4567)';
        }
        break;
        
      case 'dob':
        const age = calculateAge(new Date(field.value));
        if (age < 18) {
          isValid = false;
          errorMessage = 'Applicant must be at least 18 years old';
        } else if (age > 100) {
          isValid = false;
          errorMessage = 'Please enter a valid date of birth';
        }
        break;
        
      case 'nationalId':
        if (field.value.length < 5) {
          isValid = false;
          errorMessage = 'National ID must be at least 5 characters';
        } else {
          // Real-time ID validation via API
          validateNationalIdAsync(field.value);
        }
        break;
        
      case 'height':
        if (field.value < 50 || field.value > 250) {
          isValid = false;
          errorMessage = 'Height must be between 50 and 250 cm';
        }
        break;
        
      case 'weight':
        if (field.value < 20 || field.value > 300) {
          isValid = false;
          errorMessage = 'Weight must be between 20 and 300 kg';
        }
        break;
        
      case 'bloodPressure':
        if (field.value && !/^\d{2,3}\/\d{2,3}$/.test(field.value)) {
          isValid = false;
          errorMessage = 'Format should be: 120/80';
        }
        break;
        
      case 'postalCode':
        if (!/^[A-Za-z0-9\s\-]{3,10}$/.test(field.value)) {
          isValid = false;
          errorMessage = 'Please enter a valid postal code';
        }
        break;
    }
  }
  
  // Update UI
  if (errorDiv) {
    if (isValid) {
      field.classList.remove('invalid');
      errorDiv.style.display = 'none';
      if (successDiv && field.value) {
        successDiv.textContent = '✓ Valid';
        successDiv.style.display = 'block';
      }
    } else {
      field.classList.add('invalid');
      errorDiv.textContent = errorMessage;
      errorDiv.style.display = 'block';
      if (successDiv) {
        successDiv.style.display = 'none';
      }
    }
  }
  
  return isValid;
}

// Async validation for email
async function validateEmailAsync(email) {
  try {
    // Simulate API call (replace with actual validation endpoint)
    const response = await fetch(`/api/validate-email?email=${encodeURIComponent(email)}`);
    const result = await response.json();
    
    const successDiv = document.getElementById('email-success');
    const errorDiv = document.getElementById('email-error');
    
    if (result.valid) {
      successDiv.textContent = '✓ Email verified';
      successDiv.style.display = 'block';
      errorDiv.style.display = 'none';
    }
  } catch (error) {
    console.log('Email validation service unavailable');
  }
}

// Async validation for National ID
async function validateNationalIdAsync(nationalId) {
  try {
    const dob = document.getElementById('dob').value;
    const response = await fetch(`/api/validate?type=ni&value=${encodeURIComponent(nationalId)}&extra=${encodeURIComponent(dob)}`);
    const result = await response.json();
    
    const successDiv = document.getElementById('nationalId-success');
    const errorDiv = document.getElementById('nationalId-error');
    
    if (result.status === 'valid') {
      successDiv.textContent = '✓ ID verified';
      successDiv.style.display = 'block';
      errorDiv.style.display = 'none';
    } else if (result.status === 'invalid') {
      errorDiv.textContent = 'ID verification failed';
      errorDiv.style.display = 'block';
      successDiv.style.display = 'none';
    }
  } catch (error) {
    console.log('ID validation service unavailable');
  }
}

// Calculate age from date of birth
function calculateAge(birthDate) {
  const today = new Date();
  let age = today.getFullYear() - birthDate.getFullYear();
  const monthDiff = today.getMonth() - birthDate.getMonth();
  
  if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birthDate.getDate())) {
    age--;
  }
  
  return age;
}

// Update progress bar
function updateProgress() {
  const form = document.getElementById('quoteForm');
  const totalFields = requiredFields.length;
  let completedFields = 0;
  
  requiredFields.forEach(fieldId => {
    const field = form.querySelector(`[id="${fieldId}"], [name="${fieldId}"]`);
    if (field) {
      if (field.type === 'checkbox' || field.type === 'radio') {
        const checked = form.querySelector(`[name="${fieldId}"]:checked`);
        if (checked) completedFields++;
      } else if (field.value && field.value.trim()) {
        completedFields++;
      }
    }
  });
  
  const percentage = Math.round((completedFields / totalFields) * 100);
  document.getElementById('progressFill').style.width = percentage + '%';
}

// Add beneficiary
function addBeneficiary() {
  const container = document.getElementById('beneficiariesContainer');
  const newEntry = document.createElement('div');
  newEntry.className = 'beneficiary-entry';
  newEntry.style.marginTop = '10px';
  newEntry.innerHTML = `
    <input type="text" name="beneficiary[]" placeholder="Full Name">
    <input type="text" name="beneficiaryRelation[]" placeholder="Relationship">
    <input type="number" name="beneficiaryPercentage[]" placeholder="Percentage %" min="0" max="100">
    <button type="button" class="file-list .remove-btn" onclick="this.parentElement.remove()">Remove</button>
  `;
  container.appendChild(newEntry);
}

// ============================================================================
// MULTIMEDIA CAPTURE FUNCTIONS
// ============================================================================

// Photo capture
async function capturePhoto() {
  try {
    const modal = document.getElementById('cameraModal');
    const video = document.getElementById('cameraStream');
    
    cameraStream = await navigator.mediaDevices.getUserMedia({ 
      video: { facingMode: 'user', width: 1280, height: 720 } 
    });
    
    video.srcObject = cameraStream;
    modal.classList.add('active');
  } catch (error) {
    alert('Camera access denied or not available: ' + error.message);
  }
}

function takeSnapshot() {
  const video = document.getElementById('cameraStream');
  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  
  const ctx = canvas.getContext('2d');
  ctx.drawImage(video, 0, 0);
  
  canvas.toBlob(blob => {
    photoBlob = blob;
    
    const preview = document.getElementById('photoPreview');
    const img = document.getElementById('photoImage');
    img.src = URL.createObjectURL(blob);
    preview.classList.add('active');
    
    closeCamera();
    showSuccess('Photo captured successfully!');
  }, 'image/jpeg', 0.95);
}

function closeCamera() {
  if (cameraStream) {
    cameraStream.getTracks().forEach(track => track.stop());
    cameraStream = null;
  }
  document.getElementById('cameraModal').classList.remove('active');
}

// Video capture
async function captureVideo() {
  try {
    const modal = document.getElementById('videoModal');
    const video = document.getElementById('videoStream');
    
    cameraStream = await navigator.mediaDevices.getUserMedia({ 
      video: { facingMode: 'user', width: 1280, height: 720 },
      audio: true
    });
    
    video.srcObject = cameraStream;
    modal.classList.add('active');
    
    document.getElementById('startVideoBtn').style.display = 'inline-block';
    document.getElementById('stopVideoBtn').style.display = 'none';
  } catch (error) {
    alert('Camera/microphone access denied or not available: ' + error.message);
  }
}

function startVideoRecording() {
  const video = document.getElementById('videoStream');
  const chunks = [];
  
  mediaRecorder = new MediaRecorder(cameraStream, {
    mimeType: 'video/webm;codecs=vp8,opus'
  });
  
  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) {
      chunks.push(e.data);
    }
  };
  
  mediaRecorder.onstop = () => {
    videoBlob = new Blob(chunks, { type: 'video/webm' });
    
    const preview = document.getElementById('videoPreview');
    const videoEl = document.getElementById('videoElement');
    videoEl.src = URL.createObjectURL(videoBlob);
    preview.classList.add('active');
    
    closeVideoRecorder();
    showSuccess('Video recorded successfully!');
  };
  
  mediaRecorder.start();
  recordingSeconds = 0;
  
  document.getElementById('startVideoBtn').style.display = 'none';
  document.getElementById('stopVideoBtn').style.display = 'inline-block';
  document.getElementById('videoTimer').style.display = 'block';
  
  recordingTimer = setInterval(() => {
    recordingSeconds++;
    document.getElementById('videoTimerValue').textContent = recordingSeconds;
    
    if (recordingSeconds >= 30) {
      stopVideoRecording();
    }
  }, 1000);
}

function stopVideoRecording() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  }
  if (recordingTimer) {
    clearInterval(recordingTimer);
    recordingTimer = null;
  }
  document.getElementById('videoTimer').style.display = 'none';
}

function closeVideoRecorder() {
  stopVideoRecording();
  if (cameraStream) {
    cameraStream.getTracks().forEach(track => track.stop());
    cameraStream = null;
  }
  document.getElementById('videoModal').classList.remove('active');
}

// Audio capture
async function captureAudio() {
  try {
    const modal = document.getElementById('audioModal');
    
    cameraStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    
    modal.classList.add('active');
    
    document.getElementById('startAudioBtn').style.display = 'inline-block';
    document.getElementById('stopAudioBtn').style.display = 'none';
  } catch (error) {
    alert('Microphone access denied or not available: ' + error.message);
  }
}

function startAudioRecording() {
  const chunks = [];
  
  mediaRecorder = new MediaRecorder(cameraStream);
  
  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) {
      chunks.push(e.data);
    }
  };
  
  mediaRecorder.onstop = () => {
    audioBlob = new Blob(chunks, { type: 'audio/webm' });
    
    const preview = document.getElementById('audioPreview');
    const audioEl = document.getElementById('audioElement');
    audioEl.src = URL.createObjectURL(audioBlob);
    preview.classList.add('active');
    
    closeAudioRecorder();
    showSuccess('Audio recorded successfully!');
  };
  
  mediaRecorder.start();
  recordingSeconds = 0;
  
  document.getElementById('startAudioBtn').style.display = 'none';
  document.getElementById('stopAudioBtn').style.display = 'inline-block';
  document.getElementById('audioTimer').style.display = 'block';
  
  recordingTimer = setInterval(() => {
    recordingSeconds++;
    document.getElementById('audioTimerValue').textContent = recordingSeconds;
    
    if (recordingSeconds >= 60) {
      stopAudioRecording();
    }
  }, 1000);
}

function stopAudioRecording() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  }
  if (recordingTimer) {
    clearInterval(recordingTimer);
    recordingTimer = null;
  }
  document.getElementById('audioTimer').style.display = 'none';
}

function closeAudioRecorder() {
  stopAudioRecording();
  if (cameraStream) {
    cameraStream.getTracks().forEach(track => track.stop());
    cameraStream = null;
  }
  document.getElementById('audioModal').classList.remove('active');
}

// Handle media file upload
function handleMediaUpload(input) {
  const file = input.files[0];
  if (!file) return;
  
  const fileList = document.getElementById('mediaFileList');
  const li = document.createElement('li');
  li.innerHTML = `
    <span>📎 ${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB)</span>
    <button class="remove-btn" onclick="this.parentElement.remove()">Remove</button>
  `;
  fileList.appendChild(li);
  
  showSuccess(`${file.name} uploaded successfully!`);
}

// Clear captured media
function clearCapture(type) {
  if (type === 'photo') {
    photoBlob = null;
    document.getElementById('photoPreview').classList.remove('active');
  } else if (type === 'video') {
    videoBlob = null;
    document.getElementById('videoPreview').classList.remove('active');
  } else if (type === 'audio') {
    audioBlob = null;
    document.getElementById('audioPreview').classList.remove('active');
  }
}

// ============================================================================
// FORM SUBMISSION
// ============================================================================

async function handleSubmit() {
  const form = document.getElementById('quoteForm');
  const submitBtn = document.getElementById('submitBtn');

  if (!getToken()) {
    showError('Please save your account (Next) before submitting.');
    return;
  }
  
  // Validate all required fields
  let isValid = true;
  const inputs = form.querySelectorAll('input, select, textarea');
  inputs.forEach(input => {
    if (input.required && !validateField(input)) {
      isValid = false;
    }
  });
  
  if (!isValid) {
    showError('Please fill in all required fields correctly.');
    // Scroll to first error
    const firstError = form.querySelector('.invalid');
    if (firstError) {
      firstError.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    return;
  }
  
  // Prepare form data
  const formData = new FormData(form);
  // Never submit passwords as part of the quote payload (registration/login is handled separately)
  formData.delete('accountPassword');
  formData.delete('accountPasswordConfirm');
  
  // Add multimedia files
  if (photoBlob) {
    formData.append('photo', photoBlob, 'verification-photo.jpg');
  }
  if (videoBlob) {
    formData.append('video', videoBlob, 'verification-video.webm');
  }
  if (audioBlob) {
    formData.append('audio', audioBlob, 'verification-audio.webm');
  }
  
  // Disable submit button
  submitBtn.disabled = true;
  submitBtn.textContent = 'Submitting...';
  
  try {
    // Submit to server
    const response = await fetch('/api/submit-quote', {
      method: 'POST',
      headers: (function() {
        const t = getToken();
        return t ? { Authorization: `Bearer ${t}` } : {};
      })(),
      body: formData,
    });
    
    const result = await response.json();
    
    if (response.ok) {
      showSuccess('Quote submitted successfully! You will receive a confirmation email shortly.');
      
      // Clear form and storage
      form.reset();
      localStorage.removeItem('quoteDraft');
      
      // Redirect after 3 seconds
      setTimeout(() => {
        window.location.href = '/dashboard.html';
      }, 3000);
    } else {
      showError(result.message || 'Submission failed. Please try again.');
      submitBtn.disabled = false;
      submitBtn.textContent = 'Submit Quote Request';
    }
  } catch (error) {
    showError('Network error. Please check your connection and try again.');
    submitBtn.disabled = false;
    submitBtn.textContent = 'Submit Quote Request';
  }
}

// Save draft to localStorage
function saveDraft() {
  const form = document.getElementById('quoteForm');
  const formData = new FormData(form);
  const data = {};
  
  for (let [key, value] of formData.entries()) {
    // Never store passwords in drafts/localStorage
    if (key === 'accountPassword' || key === 'accountPasswordConfirm') continue;
    data[key] = value;
  }
  
  localStorage.setItem('quoteDraft', JSON.stringify(data));
  showSuccess('Draft saved successfully!');
}

// Load draft from localStorage
function loadDraft() {
  const draft = localStorage.getItem('quoteDraft');
  if (!draft) return;
  
  const data = JSON.parse(draft);
  const form = document.getElementById('quoteForm');
  
  Object.keys(data).forEach(key => {
    if (key === 'accountPassword' || key === 'accountPasswordConfirm') return;
    const field = form.querySelector(`[name="${key}"]`);
    if (field) {
      field.value = data[key];
    }
  });
  
  updateProgress();
  showSuccess('Draft loaded!');
}

// Show/hide modals
function showTerms() {
  document.getElementById('termsModal').classList.add('active');
}

function closeModal(modalId) {
  document.getElementById(modalId).classList.remove('active');
}

// Status messages
function showError(message) {
  const status = document.getElementById('validationStatus');
  status.className = 'validation-status error';
  status.textContent = '❌ ' + message;
  status.scrollIntoView({ behavior: 'smooth', block: 'start' });
  
  setTimeout(() => {
    status.style.display = 'none';
  }, 5000);
}

function showSuccess(message) {
  const status = document.getElementById('validationStatus');
  status.className = 'validation-status success';
  status.textContent = '✓ ' + message;
  
  setTimeout(() => {
    status.style.display = 'none';
  }, 3000);
}
