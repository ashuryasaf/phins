document.addEventListener('DOMContentLoaded', function () {
  const summaryEl = document.getElementById('summary');
  const allocList = document.getElementById('alloc-list');

  function renderSummary(data) {
    summaryEl.innerHTML = `
      <p><strong>Customer:</strong> ${data.customer_id}</p>
      <p><strong>Total Premium Paid:</strong> $${data.total_premium.toFixed(2)}</p>
      <p><strong>Risk Coverage:</strong> $${data.risk_total.toFixed(2)}</p>
      <p><strong>Your Savings:</strong> $${data.savings_total.toFixed(2)}</p>
    `;
  }

  function renderAllocations(data) {
    allocList.innerHTML = '';
    data.forEach(function (a) {
      const li = document.createElement('li');
      li.innerHTML = `<div>${a.allocation_id} — $${a.amount.toFixed(2)}</div><div>$${a.risk_amount.toFixed(2)} | $${a.savings_amount.toFixed(2)}</div>`;
      allocList.appendChild(li);
    });
  }

  // Fetch statement
  fetch('/api/statement?customer_id=CUST001')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      renderSummary(data);
      renderAllocations(data.allocations || []);
    })
    .catch(function (err) {
      summaryEl.innerHTML = '<p class="muted">Unable to load statement.</p>';
      console.error(err);
    });
});
