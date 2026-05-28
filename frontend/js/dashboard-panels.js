import {
  getDashboard,
  getCatalog,
  getPolicies,
  getBrands,
  getEscalations,
  onboardBrand,
  activateBrand,
  deactivateBrand,
  resolveEscalation,
  runSimulation,
} from './api.js';

let state = {
  brands: [],
  activeBrandId: null,
  dashboard: null,
  policies: null,
  lastPreview: null,
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

export async function refreshDashboard() {
  try {
    const [dashboard, catalog, policies, brandsData, escalations] = await Promise.all([
      getDashboard(),
      getCatalog(),
      getPolicies(),
      getBrands(),
      getEscalations(),
    ]);

    state.dashboard = dashboard;
    state.policies = policies;
    state.brands = brandsData.brands || [];
    state.activeBrandId = brandsData.active_brand_id;

    renderPerformance(dashboard);
    renderCatalog(catalog.products || []);
    renderPolicies(policies);
    renderEscalations(escalations.items || []);
    renderBrandSwitcher(brandsData);
    updateHeaderChips(dashboard, policies);
  } catch (e) {
    showToast('Failed to load dashboard: ' + e.message, true);
  }
}

function updateHeaderChips(dashboard, policies) {
  const spendEl = document.getElementById('headerSpend');
  const cvrEl = document.getElementById('headerCvr');
  if (spendEl) {
    spendEl.innerHTML = `Spend <strong>$${dashboard.spend.toFixed(2)}</strong> / $${policies.daily_budget}`;
  }
  if (cvrEl) {
    cvrEl.innerHTML = `CVR <strong>${(dashboard.cvr * 100).toFixed(2)}%</strong>`;
  }
}

function renderPerformance(d) {
  const el = document.getElementById('performancePanel');
  if (!el) return;

  const bandit = (d.top_bandit_weights || []).slice(0, 5)
    .map(b => `<li>${b.creative_id}: ${b.weight.toFixed(3)}</li>`)
    .join('') || '<li class="empty-state">No bandit data yet</li>';

  el.innerHTML = `
    <div class="stat-row">
      <div class="stat-box"><div class="stat-val">${d.impressions}</div><div class="stat-lbl">Impressions</div></div>
      <div class="stat-box"><div class="stat-val">${d.clicks}</div><div class="stat-lbl">Clicks</div></div>
      <div class="stat-box"><div class="stat-val">${d.conversions}</div><div class="stat-lbl">Conversions</div></div>
    </div>
    <div style="margin-top:8px;font-size:10px;color:var(--text2)">
      Paused creatives: ${(d.paused_placements || []).length}
    </div>
    <div class="card-title" style="margin-top:10px">Top bandit weights</div>
    <ul style="font-size:10px;color:var(--text2);padding-left:14px">${bandit}</ul>
  `;
}

function renderCatalog(products) {
  const el = document.getElementById('catalogPanel');
  if (!el) return;
  if (!products.length) {
    el.innerHTML = '<div class="empty-state">No products — onboard a brand or use default catalog</div>';
    return;
  }
  el.innerHTML = `
    <table class="catalog-table">
      <thead><tr><th>Product</th><th>Category</th><th>Creatives</th></tr></thead>
      <tbody>
        ${products.map(p => `
          <tr>
            <td>${p.name}</td>
            <td>${p.category || '—'}</td>
            <td>${(p.creatives || []).length}</td>
          </tr>`).join('')}
      </tbody>
    </table>`;
}

function renderPolicies(p) {
  const el = document.getElementById('policiesPanel');
  if (!el || !p) return;
  el.innerHTML = `
    <div class="policy-list">
      <div>Daily budget: <strong>$${p.daily_budget}</strong></div>
      <div>CVR floor: <strong>${(p.cvr_floor * 100).toFixed(1)}%</strong></div>
      <div>Finalists scored: <strong>${p.top_k_finalists}</strong></div>
      <div>Creative approval: <strong>${p.require_creative_approval ? 'required' : 'off'}</strong></div>
    </div>`;
}

function renderEscalations(items) {
  const el = document.getElementById('escalationsPanel');
  if (!el) return;
  if (!items.length) {
    el.innerHTML = '<div class="empty-state">No pending escalations</div>';
    return;
  }
  el.innerHTML = items.map(item => `
    <div class="escalation-item" data-id="${item.id}">
      <p><strong>${item.gate}</strong>: ${item.message}</p>
      <div class="escalation-actions">
        <button class="btn btn-sm btn-primary" data-approve="${item.id}">Approve</button>
        <button class="btn btn-sm" data-reject="${item.id}">Reject</button>
      </div>
    </div>`).join('');

  el.querySelectorAll('[data-approve]').forEach(btn => {
    btn.addEventListener('click', async () => {
      await resolveEscalation(btn.dataset.approve, true);
      showToast('Escalation approved');
      refreshDashboard();
    });
  });
  el.querySelectorAll('[data-reject]').forEach(btn => {
    btn.addEventListener('click', async () => {
      await resolveEscalation(btn.dataset.reject, false);
      showToast('Escalation rejected');
      refreshDashboard();
    });
  });
}

function renderBrandSwitcher(brandsData) {
  const sel = document.getElementById('brandSelect');
  if (!sel) return;
  const brands = brandsData.brands || [];
  sel.innerHTML = `
    <option value="">Default catalog</option>
    ${brands.map(b => {
      const name = b.ad_plan?.brand_profile?.name || b.name || b.id;
      return `<option value="${b.id}" ${b.id === brandsData.active_brand_id ? 'selected' : ''}>${name}</option>`;
    }).join('')}`;
}

export function initDashboardPanels() {
  document.getElementById('brandSelect')?.addEventListener('change', async e => {
    const id = e.target.value;
    try {
      if (id) await activateBrand(id);
      else await deactivateBrand();
      showToast(id ? 'Brand activated' : 'Using default catalog');
      refreshDashboard();
    } catch (err) {
      showToast(err.message, true);
    }
  });

  document.getElementById('onboardBtn')?.addEventListener('click', async () => {
    const url = document.getElementById('onboardUrl')?.value?.trim();
    const notes = document.getElementById('onboardNotes')?.value?.trim() || '';
    const budget = parseFloat(document.getElementById('onboardBudget')?.value);
    if (!url) {
      showToast('Enter a website URL', true);
      return;
    }
    const btn = document.getElementById('onboardBtn');
    btn.disabled = true;
    btn.textContent = 'Building plan…';
    try {
      const result = await onboardBrand({
        website_url: url,
        advertiser_notes: notes,
        daily_budget: Number.isFinite(budget) ? budget : undefined,
        activate: true,
      });
      document.getElementById('onboardResult').textContent =
        `Brand ${result.brand_id} ready — ${result.ad_plan?.suggested_catalog?.products?.length || 0} products`;
      showToast('Ad plan created and activated');
      refreshDashboard();
    } catch (err) {
      showToast('Onboard failed: ' + err.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Build ad plan';
    }
  });

  document.getElementById('simBtn')?.addEventListener('click', async () => {
    const btn = document.getElementById('simBtn');
    const out = document.getElementById('simResults');
    btn.disabled = true;
    btn.textContent = 'Running…';
    out.innerHTML = '<div class="loading-block"><span class="spinner"></span>Simulating 50 sessions…</div>';
    try {
      const r = await runSimulation(50);
      const opt = r.optimized || {};
      const base = r.baseline || {};
      out.innerHTML = `
        <div class="sim-results">
          <div class="sim-box"><div class="label">Optimized CVR</div><div class="val" style="color:var(--green)">${((opt.cvr ?? 0) * 100).toFixed(2)}%</div></div>
          <div class="sim-box"><div class="label">Baseline CVR</div><div class="val">${((base.cvr ?? 0) * 100).toFixed(2)}%</div></div>
          <div class="sim-box"><div class="label">CVR lift</div><div class="val" style="color:var(--amber)">${r.cvr_lift_pct != null ? r.cvr_lift_pct.toFixed(1) + '%' : '—'}</div></div>
          <div class="sim-box"><div class="label">Spend saved</div><div class="val">${r.spend_savings_pct != null ? r.spend_savings_pct.toFixed(1) + '%' : '—'}</div></div>
        </div>`;
      showToast('Simulation complete');
    } catch (err) {
      out.innerHTML = `<div class="empty-state">${err.message}</div>`;
      showToast(err.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Run 50-session simulation';
    }
  });

  refreshDashboard();
}
