/**
 * PHINS Assessments route chooser
 * --------------------------------------------------------------------------
 * Turns any element with [data-assessments-nav] into a themed dropdown so
 * staff/customers can pick an assessment surface without losing the unified
 * entry point. Data integrity is unchanged — this is chrome/navigation only.
 */
(function () {
  'use strict';

  var ADMIN_ROUTES = [
    { href: '/unified-workbench.html', label: 'Unified Workbench', hint: 'One-pass 360 · risk · BI · report' },
    { href: '/assessment-center.html', label: 'Assessment Center', hint: 'Customer 360 facts + Mislaka link' },
    { href: '/risk-dashboard.html', label: 'Risk Assessment', hint: 'Upload · analyze · generate' },
    { href: '/risk-reports-dashboard.html', label: 'Mislaka & AI Reports', hint: 'Swiftness / clearinghouse library' },
    { href: '/risk-assessment-viewer.html', label: 'Application Risk Viewer', hint: 'Underwriting application reports' },
  ];

  var CUSTOMER_ROUTES = [
    { href: '/unified-workbench.html', label: 'Unified Workbench', hint: 'Documents · assessment · risk · reports' },
    { href: '/assessment-center.html', label: 'Assessment Center', hint: 'Your Customer 360 facts' },
    { href: '/customer-ai-report.html', label: 'AI Report', hint: 'Period report with assessment join' },
    { href: '/risk-reports-dashboard.html', label: 'Reports Library', hint: 'Uploaded report archive' },
  ];

  function currentPath() {
    try { return (location.pathname || '').split('?')[0]; } catch (e) { return ''; }
  }

  function isActive(href) {
    var path = currentPath();
    try {
      var u = new URL(href, location.origin);
      return path === u.pathname;
    } catch (e) {
      return path === href;
    }
  }

  function roleFromSession() {
    try {
      var raw = sessionStorage.getItem('phins_session') || localStorage.getItem('phins_session');
      if (!raw) return null;
      var s = JSON.parse(raw);
      return (s && (s.role || s.user_role || s.userRole)) || null;
    } catch (e) {
      return null;
    }
  }

  function pickRoutes() {
    var role = (roleFromSession() || '').toLowerCase();
    var host = document.querySelector('[data-assessments-nav]');
    var mode = (host && host.getAttribute('data-assessments-role')) || '';
    if (mode === 'admin' || mode === 'staff') return ADMIN_ROUTES;
    if (mode === 'customer') return CUSTOMER_ROUTES;
    if (role === 'customer' || role === 'insured' || role === 'member') return CUSTOMER_ROUTES;
    if (role) return ADMIN_ROUTES;
    // Default: if we're on admin.html, staff routes; else customer-leaning.
    if (currentPath().indexOf('admin') !== -1 || currentPath().indexOf('underwriter') !== -1 ||
        currentPath().indexOf('claims') !== -1 || currentPath().indexOf('actuary') !== -1) {
      return ADMIN_ROUTES;
    }
    return CUSTOMER_ROUTES;
  }

  function buildMenu(routes) {
    var wrap = document.createElement('div');
    wrap.className = 'assessments-nav';
    var anyActive = routes.some(function (r) { return isActive(r.href); });
    wrap.innerHTML =
      '<button type="button" class="assessments-nav-toggle' + (anyActive ? ' active' : '') + '" aria-haspopup="true" aria-expanded="false">' +
      'Assessments <span class="assessments-nav-caret" aria-hidden="true">▾</span>' +
      '</button>' +
      '<div class="assessments-nav-menu" role="menu" hidden></div>';
    var menu = wrap.querySelector('.assessments-nav-menu');
    routes.forEach(function (r) {
      var a = document.createElement('a');
      a.href = r.href;
      a.setAttribute('role', 'menuitem');
      a.className = 'assessments-nav-item' + (isActive(r.href) ? ' is-active' : '');
      a.innerHTML =
        '<span class="assessments-nav-item-label">' + r.label + '</span>' +
        '<span class="assessments-nav-item-hint">' + r.hint + '</span>';
      menu.appendChild(a);
    });
    return wrap;
  }

  function wire(wrap) {
    var btn = wrap.querySelector('.assessments-nav-toggle');
    var menu = wrap.querySelector('.assessments-nav-menu');
    function close() {
      menu.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
      wrap.classList.remove('open');
    }
    function open() {
      menu.hidden = false;
      btn.setAttribute('aria-expanded', 'true');
      wrap.classList.add('open');
    }
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (menu.hidden) open(); else close();
    });
    document.addEventListener('click', function (e) {
      if (!wrap.contains(e.target)) close();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') close();
    });
  }

  function mount() {
    var hosts = document.querySelectorAll('[data-assessments-nav]');
    if (!hosts.length) return;
    var routes = pickRoutes();
    hosts.forEach(function (host) {
      if (host.getAttribute('data-assessments-ready') === '1') return;
      var menu = buildMenu(routes);
      host.innerHTML = '';
      host.appendChild(menu);
      wire(menu);
      host.setAttribute('data-assessments-ready', '1');
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();
