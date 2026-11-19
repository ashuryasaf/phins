/* Unified cash flow statement on /cashflow-integrity.html.
 * Reads GET /api/admin/cashflow/unified-report. The page writes nothing. */
(function () {
    'use strict';

    var root = document.getElementById('unified-report');
    if (!root) return;

    var token = localStorage.getItem('phins_token') || '';
    var headers = token ? { 'Authorization': 'Bearer ' + token } : {};
    var lastReport = null;

    function money(value) {
        var number = Number(value || 0);
        var text = '$' + Math.abs(number).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        return number < 0 ? '−' + text : text;
    }

    function esc(value) {
        return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
        });
    }

    function el(id) { return document.getElementById(id); }

    function card(label, value, note) {
        return '<div class="card"><span>' + esc(label) + '</span><strong>' + money(value) + '</strong>'
            + (note ? '<em class="note">' + esc(note) + '</em>' : '') + '</div>';
    }

    function table(head, rows) {
        if (!rows.length) return '<p class="note">Nothing on this book yet.</p>';
        return '<div class="roster-wrap"><table><thead><tr>'
            + head.map(function (h) { return '<th>' + esc(h) + '</th>'; }).join('')
            + '</tr></thead><tbody>'
            + rows.map(function (cells) {
                return '<tr>' + cells.map(function (cell) { return '<td>' + cell + '</td>'; }).join('') + '</tr>';
            }).join('')
            + '</tbody></table></div>';
    }

    function renderStatement(sections) {
        return sections.map(function (section) {
            var lines = (section.lines || []).map(function (line) {
                return '<tr><td>' + esc(line.label) + '</td><td class="book">' + esc(line.book || '') + '</td><td class="amt">' + money(line.amount) + '</td></tr>';
            }).join('');
            var accruals = (section.accruals || []).map(function (line) {
                return '<tr class="accrual"><td>' + esc(line.label) + '</td><td class="book">accrual</td><td class="amt">' + money(line.amount) + '</td></tr>';
            }).join('');
            return '<section class="stmt"><h3>' + esc(section.section) + '<b>' + money(section.total) + '</b></h3>'
                + '<table><tbody>' + lines + accruals + '</tbody></table></section>';
        }).join('');
    }

    function renderChecks(integrity) {
        var checks = (integrity && integrity.checks) || [];
        return checks.map(function (check) {
            var amount = (!check.ok && check.amount != null) ? ' <b>' + esc(check.amount) + '</b>' : '';
            return '<li class="' + (check.ok ? 'ok' : 'bad') + '"><span class="tag ' + (check.ok ? 'clear' : 'attention') + '">'
                + (check.ok ? 'ties' : 'look') + '</span> ' + esc(check.detail) + amount + '</li>';
        }).join('');
    }

    function render(report) {
        lastReport = report;
        var premiums = report.premiums || {};
        var landed = premiums.landed || {};
        var claims = report.claims || {};
        var funds = report.customer_funds || {};
        var fee = funds.management_fee || {};
        var market = report.marketplace || {};
        var suppliers = market.suppliers || {};
        var agents = report.agents || {};
        var acquisition = report.acquisition || {};
        var underwriting = report.underwriting || {};
        var withdrawals = report.withdrawals || {};
        var kernel = report.kernel || {};
        var annual = kernel.annual || {};

        el('unified-basis').textContent = (report.basis || []).join(' ');
        el('unified-cards').innerHTML = [
            card('Premiums collected', premiums.collected, (premiums.months || 0) + ' paid or billed months'),
            card('Kernel risk premium', landed.risk),
            card('Claims paid, counted once', claims.paid_once, (claims.paid_claims || 0) + ' claims'),
            card('Underwriting surplus', underwriting.surplus, underwriting.loss_ratio_pct == null ? '' : 'loss ratio ' + underwriting.loss_ratio_pct + '%'),
            card('Operational cost loading', landed.expense_loading),
            card('Savings add-on', landed.savings, '30 / 65 / 5'),
            card('Assets under management', funds.assets_under_management, 'investments and algo'),
            card('Management fee, per year', fee.annual_at_current_aum, (fee.annual_rate_pct || 0) + '% · accrual only'),
            card('Marketplace commission', market.commission, (market.orders || 0) + ' orders'),
            card('Supplier payouts pending', suppliers.pending),
            card('Agent commission owed', agents.commission_owed),
            card('Withdrawals held', withdrawals.held, (withdrawals.flagged_for_retention || 0) + ' flagged')
        ].join('');

        var integrity = report.integrity || {};
        el('unified-verdict').innerHTML = integrity.ok
            ? '<span class="tag clear">all books tie</span>'
            : '<span class="tag attention">' + (integrity.failed || []).length + ' to look at</span>';
        el('unified-checks').innerHTML = renderChecks(integrity);
        el('unified-statement').innerHTML = renderStatement(report.statement || []);

        el('unified-kernel').innerHTML = table(
            ['In force', 'Kernel pinned', 'Without pin', 'Annual premium', 'Risk', 'Underwriting fee', 'Expense loading', 'Profit', 'Savings add-on'],
            kernel.policies_in_force ? [[
                esc(kernel.policies_in_force), esc(kernel.kernel_pinned), esc(kernel.without_kernel_pin),
                money(kernel.annual_premium), money(annual.risk), money(annual.underwriting_fee),
                money(annual.expense_loading), money(annual.profit), money(annual.savings_addon)
            ]] : []
        );

        var byBook = claims.by_book || {};
        el('unified-claims-note').textContent = 'Counted once: ' + money(claims.paid_once)
            + '. The customer ledger shows ' + money(byBook.ledger) + ', the health wallets ' + money(byBook.wallet)
            + ', and the balance sheet ' + money(byBook.balance_sheet) + '. Added together those three would read '
            + money(claims.if_books_were_added) + '. Repeated above a paid amount: ' + money(claims.repeated_total)
            + '. Not yet in a wallet: ' + money(claims.unposted) + '.';
        el('unified-claims').innerHTML = table(
            ['Claim', 'Customer', 'Paid', 'Customer ledger', 'Health wallet', 'Balance sheet', 'NFT seal', 'Counted', 'Repeated', 'Unposted'],
            (claims.rows || []).map(function (row) {
                return [
                    esc(row.claim_id), esc(row.customer_id), money(row.paid_amount), money(row.ledger),
                    money(row.health_wallet), money(row.balance_sheet), money(row.sealed),
                    '<strong>' + money(row.counted) + '</strong>',
                    row.repeated > 0 ? '<span class="tag attention">' + money(row.repeated) + '</span>' : money(0),
                    row.unposted > 0 ? '<span class="tag watch">' + money(row.unposted) + '</span>' : money(0)
                ];
            })
        );

        el('unified-market-note').textContent = 'Customer price ' + money(market.customer_price)
            + ' = commission ' + money(market.commission) + ' + supplier payout ' + money(market.supplier_payout)
            + '. Paid from health wallets ' + money(market.paid_from_health_wallet) + ', paid externally '
            + money(market.paid_externally) + '. Supplier payouts settled ' + money(suppliers.settled)
            + ', pending ' + money(suppliers.pending) + ', disputed ' + money(suppliers.disputed) + '.';
        el('unified-suppliers').innerHTML = table(
            ['Supplier', 'Customer price', 'Commission', 'Settled', 'Pending', 'Disputed'],
            (suppliers.rows || []).map(function (row) {
                return [
                    esc(row.name || row.supplier_id), money(row.gross), money(row.commission),
                    money(row.settled), money(row.pending), money(row.disputed)
                ];
            })
        );

        el('unified-agents').innerHTML = table(
            ['Book', 'Accrued', 'Payable', 'Paid', 'Owed'],
            [
                ['Agent commission', money(agents.commission_accrued), money(agents.commission_payable), money(agents.commission_paid), money(agents.commission_owed)],
                ['Acquisition rewards (CACSET)', money(acquisition.blocked), money(acquisition.releasable), money(acquisition.settled), money((acquisition.blocked || 0) + (acquisition.releasable || 0))]
            ]
        ) + '<p class="note">Acquisition allocated ' + money(acquisition.allocated) + ', reversed ' + money(acquisition.reversed)
            + ', on the balance sheet ' + money(acquisition.expense_on_balance_sheet)
            + '. Commission rows on a REF- code (' + money(agents.referral_rows_left_to_referral_book)
            + ') belong to the referral book and are not added to agent commission.</p>';

        el('unified-customers').innerHTML = table(
            ['Customer', 'Premiums', 'Risk', 'Fee', 'Expense', 'Profit', 'Savings', 'Wallet', 'Investments', 'Algo'],
            (report.customers || []).slice(0, 100).map(function (row) {
                return [
                    '<strong>' + esc(row.name || row.customer_id) + '</strong> <span class="note">' + esc(row.customer_id) + '</span>',
                    money(row.premiums_collected), money(row.risk), money(row.underwriting_fee), money(row.expense_loading),
                    money(row.profit), money(row.savings), money(row.health_wallet), money(row.investments), money(row.algo)
                ];
            })
        );
        el('unified-stamp').textContent = 'Read ' + new Date(report.generated_at).toLocaleString() + '. This statement writes nothing.';
    }

    function load() {
        var input = el('unified-fee');
        var url = '/api/admin/cashflow/unified-report';
        var value = input && input.value !== '' ? Number(input.value) : null;
        if (value != null && isFinite(value)) url += '?management_fee_pct=' + encodeURIComponent(value);
        el('unified-stamp').textContent = 'Reading the books…';
        return fetch(url, { headers: headers })
            .then(function (response) { return response.json().then(function (body) { return { ok: response.ok, body: body }; }); })
            .then(function (result) {
                if (!result.ok) {
                    el('unified-stamp').textContent = result.body.error || 'Sign in as admin, accountant, actuary, or claims to read this statement.';
                    return;
                }
                render(result.body.report);
            })
            .catch(function () {
                el('unified-stamp').textContent = 'The statement could not be read.';
            });
    }

    el('unified-refresh').addEventListener('click', load);
    el('unified-download').addEventListener('click', function () {
        if (!lastReport) return;
        var blob = new Blob([JSON.stringify(lastReport, null, 2)], { type: 'application/json' });
        var link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = 'phins-unified-cash-flow-' + (lastReport.as_of || 'statement') + '.json';
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
    });

    window.PhinsUnifiedCashflow = { reload: load };
    load();
})();
