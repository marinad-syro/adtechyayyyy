import {
  getDashboard,
  getCatalog,
  getPolicies,
  getBrands,
  onboardBrand,
  activateBrand,
  deactivateBrand,
  resetDashboard,
  resolveEscalation,
} from './api.js';

const ACTIVE_BRAND_KEY = 'contextbid-active-brand';

const EMPTY_STATS = { impressions: 0, clicks: 0, conversions: 0, cvr: 0 };

let state = {
  brands: [],
  activeBrandId: null,
  dashboard: null,
  policies: null,
  lastPreview: null,
  activeWebsite: null,
};

let refreshSeq = 0;

export function getAppState() {
  return state;
}

/** Active brand for chat — survives stale dashboard refreshes. */
export function getActiveBrandId() {
  return state.activeBrandId || sessionStorage.getItem(ACTIVE_BRAND_KEY) || null;
}

function rememberActiveBrand(brandId) {
  if (!brandId) return;
  state.activeBrandId = brandId;
  sessionStorage.setItem(ACTIVE_BRAND_KEY, brandId);
}

async function ensureServerActiveBrand(brandId) {
  if (!brandId) return;
  const brandsData = await getBrands();
  if (brandsData.active_brand_id === brandId) return;
  await activateBrand(brandId);
}

export function setLastPreview(preview) {
  state.lastPreview = preview;
}

export function showToast(message, isError = false) {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();
  const el = document.createElement('div');
  el.className = 'toast' + (isError ? ' error' : '');
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

export async function refreshDashboard({ resetStats = false } = {}) {
  const seq = ++refreshSeq;
  try {
    if (resetStats) {
      try {
        await resetDashboard();
      } catch {
        /* ignore */
      }
      if (seq !== refreshSeq) return;
      showEmptyPerformance();
    }

    const storedBrand = getActiveBrandId();
    if (storedBrand) {
      try {
        await ensureServerActiveBrand(storedBrand);
      } catch {
        /* brand may have been removed */
      }
    }
    if (seq !== refreshSeq) return;

    const [dashboard, catalog, policies, brandsData] = await Promise.all([
      getDashboard(),
      getCatalog(),
      getPolicies(),
      getBrands(),
    ]);
    if (seq !== refreshSeq) return;

    state.dashboard = dashboard;
    state.policies = policies;
    state.brands = brandsData.brands || [];

    const serverActive = brandsData.active_brand_id;
    const resolvedActive = serverActive || storedBrand || null;
    if (resolvedActive) {
      rememberActiveBrand(resolvedActive);
    } else if (!storedBrand) {
      state.activeBrandId = null;
    }

    renderPerformance(dashboard);
    renderEscalations(dashboard);
    const products = getActiveBrandId() ? (catalog.products || []) : [];
    renderCatalog(products);
    state.activeWebsite = getActiveBrandId()
      ? (brandsData.brands || []).find(b => b.id === getActiveBrandId())?.website_url
      : null;
  } catch (e) {
    if (seq !== refreshSeq) return;
    showToast('Failed to load dashboard: ' + e.message, true);
  }
}

function renderPerformance(d) {
  const el = document.getElementById('performancePanel');
  if (!el) return;

  const budget = d.daily_budget || state.policies?.daily_budget || 500;
  const spend = d.spend ?? 0;
  const pct = budget ? Math.min(100, (spend / budget) * 100) : 0;
  const budgetBar = budget ? `
    <div class="budget-row">
      <div class="budget-labels">
        <span>Spend $${spend.toFixed(2)}</span>
        <span>${pct.toFixed(0)}% of $${budget} daily</span>
      </div>
      <div class="budget-track"><div class="budget-fill ${pct >= 80 ? 'warn' : ''}" style="width:${pct}%"></div></div>
    </div>` : '';

  const hasActivity = (d.impressions || 0) + (d.clicks || 0) + (d.conversions || 0) > 0;

  if (!hasActivity) {
    el.innerHTML = `
      ${budgetBar}
      <div class="stat-row">
        <div class="stat-box"><div class="stat-val">0</div><div class="stat-lbl">Impressions</div></div>
        <div class="stat-box"><div class="stat-val">0</div><div class="stat-lbl">Clicks</div></div>
        <div class="stat-box"><div class="stat-val">0</div><div class="stat-lbl">Conversions</div></div>
      </div>
      <p class="perf-note">Counts ads shown in chat and clicks on <strong>Learn more →</strong>. Load a URL in step ①, send a chat message, then click the sponsored ad.</p>`;
    return;
  }

  const ctr = d.impressions ? ((d.clicks / d.impressions) * 100).toFixed(1) : '0.0';
  const cvr = d.clicks ? ((d.conversions / d.clicks) * 100).toFixed(1) : '0.0';

  el.innerHTML = `
    ${budgetBar}
    <div class="stat-row">
      <div class="stat-box">
        <div class="stat-val">${d.impressions}</div>
        <div class="stat-lbl">Impressions</div>
        <div class="stat-desc">Ads shown in chat</div>
      </div>
      <div class="stat-box">
        <div class="stat-val">${d.clicks}</div>
        <div class="stat-lbl">Clicks</div>
        <div class="stat-desc">${ctr}% CTR</div>
      </div>
      <div class="stat-box">
        <div class="stat-val">${d.conversions}</div>
        <div class="stat-lbl">Conversions</div>
        <div class="stat-desc">${cvr}% post-click</div>
      </div>
    </div>
    <p class="perf-note">This session: impressions when an ad appears, clicks when you press <strong>Learn more →</strong>.</p>
  `;
}

function formatDepartment(dept) {
  if (!dept || dept === 'general' || dept === 'products') return '';
  const labels = { men: "Men's", women: "Women's", kids: 'Kids', baby: 'Baby', home: 'Home', accessories: 'Accessories' };
  return labels[dept] || dept.charAt(0).toUpperCase() + dept.slice(1);
}

function renderCatalog(products) {
  const el = document.getElementById('catalogPanel');
  if (!el) return;
  if (!products.length) {
    el.innerHTML = '';
    return;
  }
  const depts = [...new Set(products.map(p => p.department).filter(d => d && d !== 'general' && d !== 'products'))];
  const diversityNote = depts.length > 1
    ? ` across ${depts.map(formatDepartment).join(', ')}`
    : depts.length === 1
      ? ` · ${formatDepartment(depts[0])}`
      : '';
  el.innerHTML = `
    <p class="catalog-count">${products.length} product${products.length === 1 ? '' : 's'} ready to bid on${diversityNote}</p>
    <ul class="catalog-list">
      ${products.map(p => {
        const deptLabel = formatDepartment(p.department);
        return `
        <li class="catalog-item">
          <span class="catalog-name">${p.name}${deptLabel ? `<span class="catalog-dept">${deptLabel}</span>` : ''}</span>
          <span class="catalog-meta">${(p.creatives || []).length} ad variant${(p.creatives || []).length === 1 ? '' : 's'}</span>
        </li>`;
      }).join('')}
    </ul>`;
}

const GATE_LABELS = {
  budget_exceeded: 'Budget cap',
  spend_high: 'High spend',
  spend_spike: 'Spend spike',
  no_conversions: 'No conversions',
  new_creative: 'New creative',
  pause_unprofitable: 'Paused creative',
  insula_spike: 'Gut check',
};

function renderEscalations(dashboard) {
  const el = document.getElementById('hitlPanel');
  if (!el) return;

  const items = (dashboard?.escalation_queue || []).filter(i => i.status === 'pending');
  const alert = dashboard?.hitl?.spend_alert;

  if (!items.length && !alert) {
    el.innerHTML = '<p class="section-hint">No pending reviews. The agent will queue items here when spend or performance limits are hit.</p>';
    return;
  }

  let html = '';
  if (alert) {
    html += `<div class="hitl-alert"><strong>Intervention needed:</strong> ${alert.message}</div>`;
  }
  if (items.length) {
    html += items.map(item => `
      <div class="escalation-item" data-id="${item.id}">
        <span class="escalation-tag">${GATE_LABELS[item.gate] || item.gate}</span>
        <p class="escalation-msg">${item.message}</p>
        <div class="escalation-actions">
          <button type="button" class="btn btn-sm btn-primary hitl-approve" data-id="${item.id}">Approve</button>
          <button type="button" class="btn btn-sm hitl-reject" data-id="${item.id}">Reject</button>
        </div>
      </div>`).join('');
  }
  el.innerHTML = html;

  el.querySelectorAll('.hitl-approve').forEach(btn => {
    btn.addEventListener('click', () => handleEscalationResolve(btn.dataset.id, true));
  });
  el.querySelectorAll('.hitl-reject').forEach(btn => {
    btn.addEventListener('click', () => handleEscalationResolve(btn.dataset.id, false));
  });
}

async function handleEscalationResolve(id, approved) {
  try {
    await resolveEscalation(id, approved);
    showToast(approved ? 'Approved — you can retry the chat message' : 'Rejected');
    await refreshDashboard();
  } catch (e) {
    showToast(e.message, true);
  }
}

async function clearActiveBrand() {
  sessionStorage.removeItem(ACTIVE_BRAND_KEY);
  try {
    await deactivateBrand();
  } catch {
    /* server may not be up yet */
  }
}

function showEmptyPerformance() {
  renderPerformance(EMPTY_STATS);
}

export async function initDashboardPanels() {
  showEmptyPerformance();

  const storedBrand = sessionStorage.getItem(ACTIVE_BRAND_KEY);
  if (storedBrand) {
    rememberActiveBrand(storedBrand);
  }

  const catalogEl = document.getElementById('catalogPanel');
  if (catalogEl) catalogEl.innerHTML = '';
  const resultEl = document.getElementById('onboardResult');
  if (resultEl) {
    resultEl.className = 'onboard-result';
    resultEl.textContent = '';
  }
  const urlInput = document.getElementById('onboardUrl');
  if (urlInput && !storedBrand) urlInput.value = '';

  document.getElementById('onboardBtn')?.addEventListener('click', async () => {
    const url = document.getElementById('onboardUrl')?.value?.trim();
    if (!url) {
      showToast('Enter a website URL', true);
      return;
    }
    const btn = document.getElementById('onboardBtn');
    const resultEl = document.getElementById('onboardResult');
    btn.disabled = true;
    btn.textContent = 'Scraping…';
    if (resultEl) {
      resultEl.className = 'onboard-result';
      resultEl.textContent = 'Tavily is reading the site…';
    }
    try {
      const result = await onboardBrand({
        website_url: url,
        activate: true,
      });
      const n = result.ad_plan?.suggested_catalog?.products?.length || 0;
      const meta = result.ad_plan?.source?.tavily_extract || {};
      const pages = meta.pages_crawled ?? meta.crawl_pages ?? meta.urls_scraped?.length;
      const method = meta.method;
      const crawlNote =
        pages != null && method
          ? ` (${pages} pages via ${method})`
          : pages != null
            ? ` (${pages} pages scraped)`
            : '';
      if (resultEl) {
        resultEl.className = 'onboard-result success';
        resultEl.textContent = `✓ ${n} product${n === 1 ? '' : 's'} loaded${crawlNote}. Try a prompt in chat preview →`;
      }
      sessionStorage.setItem(ACTIVE_BRAND_KEY, result.brand_id);
      rememberActiveBrand(result.brand_id);
      showToast('Catalog ready — try chat preview');
      await refreshDashboard();
    } catch (err) {
      if (resultEl) {
        resultEl.className = 'onboard-result error';
        resultEl.textContent = err.message;
      }
      showToast('Scrape failed: ' + err.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Scrape site & load catalog';
    }
  });

  await refreshDashboard({ resetStats: !storedBrand });
}
