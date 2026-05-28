import {
  getDashboard,
  getCatalog,
  getPolicies,
  getBrands,
  onboardBrand,
  deactivateBrand,
  resetDashboard,
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

export function getAppState() {
  return state;
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
  try {
    if (resetStats) {
      try {
        await resetDashboard();
      } catch {
        /* ignore */
      }
      showEmptyPerformance();
    }
    const [dashboard, catalog, policies, brandsData] = await Promise.all([
      getDashboard(),
      getCatalog(),
      getPolicies(),
      getBrands(),
    ]);

    state.dashboard = dashboard;
    state.policies = policies;
    state.brands = brandsData.brands || [];
    state.activeBrandId = brandsData.active_brand_id;

    renderPerformance(dashboard);
    const products = state.activeBrandId ? (catalog.products || []) : [];
    renderCatalog(products);
    state.activeWebsite = state.activeBrandId
      ? (brandsData.brands || []).find(b => b.id === state.activeBrandId)?.website_url
      : null;
  } catch (e) {
    showToast('Failed to load dashboard: ' + e.message, true);
  }
}

function renderPerformance(d) {
  const el = document.getElementById('performancePanel');
  if (!el) return;

  const hasActivity = (d.impressions || 0) + (d.clicks || 0) + (d.conversions || 0) > 0;

  if (!hasActivity) {
    el.innerHTML = `
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

function renderCatalog(products) {
  const el = document.getElementById('catalogPanel');
  if (!el) return;
  if (!products.length) {
    el.innerHTML = '';
    return;
  }
  el.innerHTML = `
    <p class="catalog-count">${products.length} product${products.length === 1 ? '' : 's'} ready to bid on</p>
    <ul class="catalog-list">
      ${products.map(p => `
        <li class="catalog-item">
          <span class="catalog-name">${p.name}</span>
          <span class="catalog-meta">${(p.creatives || []).length} ad variant${(p.creatives || []).length === 1 ? '' : 's'}</span>
        </li>`).join('')}
    </ul>`;
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
  await clearActiveBrand();
  const catalogEl = document.getElementById('catalogPanel');
  if (catalogEl) catalogEl.innerHTML = '';
  const resultEl = document.getElementById('onboardResult');
  if (resultEl) {
    resultEl.className = 'onboard-result';
    resultEl.textContent = '';
  }
  const urlInput = document.getElementById('onboardUrl');
  if (urlInput) urlInput.value = '';

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
      showToast('Catalog ready — try chat preview');
      refreshDashboard();
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

  await refreshDashboard({ resetStats: true });
}
