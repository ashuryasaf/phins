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

  function inDrawer(wrap) {
    // Only #mobile-nav forces the menu in-flow; a horizontal .phins-nav bar
    // keeps an absolute panel that still has to flip to stay on screen.
    var nav = wrap && wrap.closest ? wrap.closest('#mobile-nav') : null;
    if (!nav) return false;
    try {
      if (window.matchMedia && window.matchMedia('(max-width: 1024px)').matches) return true;
    } catch (e) { /* matchMedia is best-effort */ }
    return !!(nav.classList && nav.classList.contains('open'));
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

  function placeMenu(wrap, btn, menu) {
    wrap.classList.remove('assessments-nav--drop-up');
    wrap.classList.remove('assessments-nav--align-end');
    if (inDrawer(wrap) || menu.hidden) return;
    var btnRect = btn.getBoundingClientRect();
    var menuH = menu.offsetHeight || 280;
    var menuW = menu.offsetWidth || 280;
    var spaceBelow = (window.innerHeight || 0) - btnRect.bottom;
    var spaceAbove = btnRect.top;
    if (spaceBelow < menuH + 12 && spaceAbove > spaceBelow) {
      wrap.classList.add('assessments-nav--drop-up');
    }
    if (btnRect.left + menuW > (window.innerWidth || 0) - 8) {
      wrap.classList.add('assessments-nav--align-end');
    }
  }

  function revealChooser(wrap, menu) {
    try {
      if (menu && typeof menu.scrollIntoView === 'function') {
        menu.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      } else if (wrap && typeof wrap.scrollIntoView === 'function') {
        wrap.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      }
    } catch (e) { /* scrollIntoView is best-effort chrome */ }
  }

  function wire(wrap) {
    var btn = wrap.querySelector('.assessments-nav-toggle');
    var menu = wrap.querySelector('.assessments-nav-menu');
    var ignoreDocClickUntil = 0;
    function close() {
      menu.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
      wrap.classList.remove('open');
      wrap.classList.remove('assessments-nav--drop-up');
      wrap.classList.remove('assessments-nav--align-end');
    }
    function open() {
      menu.hidden = false;
      btn.setAttribute('aria-expanded', 'true');
      wrap.classList.add('open');
      placeMenu(wrap, btn, menu);
      // iOS/Android: wait a frame so the in-flow submenu has height, then
      // scroll it into the drawer (portrait and landscape).
      if (typeof requestAnimationFrame === 'function') {
        requestAnimationFrame(function () {
          placeMenu(wrap, btn, menu);
          revealChooser(wrap, menu);
        });
      } else {
        revealChooser(wrap, menu);
      }
    }
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      // Same-tap document click on iOS/WebKit would immediately re-close.
      ignoreDocClickUntil = Date.now() + 400;
      if (menu.hidden) open(); else close();
    });
    document.addEventListener('click', function (e) {
      if (Date.now() < ignoreDocClickUntil) return;
      if (!wrap.contains(e.target)) close();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') close();
    });
    window.addEventListener('orientationchange', function () {
      if (menu.hidden) return;
      placeMenu(wrap, btn, menu);
      revealChooser(wrap, menu);
    });
    window.addEventListener('resize', function () {
      if (menu.hidden) return;
      placeMenu(wrap, btn, menu);
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
