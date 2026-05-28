const API = '';

async function request(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

export const getHealth = () => request('/api/health');
export const getDashboard = () => request('/api/dashboard');
export const resetDashboard = () =>
  request('/api/dashboard/reset', { method: 'POST' });
export const getCatalog = () => request('/api/catalog');
export const getPolicies = () => request('/api/policies');
export const getBrands = () => request('/api/brand');
export const getEscalations = () => request('/api/escalations');

export const onboardBrand = (body) =>
  request('/api/brand/onboard', { method: 'POST', body: JSON.stringify(body) });

export const activateBrand = (brandId) =>
  request(`/api/brand/${brandId}/activate`, { method: 'POST' });

export const deactivateBrand = () =>
  request('/api/brand/deactivate', { method: 'POST' });

export const resolveEscalation = (escalation_id, approved) =>
  request('/api/escalations/resolve', {
    method: 'POST',
    body: JSON.stringify({ escalation_id, approved }),
  });

export const recordOutcome = (placement_id, event) =>
  request('/api/outcome', {
    method: 'POST',
    body: JSON.stringify({ placement_id, event }),
  });

export const placementPreview = (body) =>
  request('/api/placement/preview', {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const advertiserAgent = (message, context) =>
  request('/api/agent/advertiser', {
    method: 'POST',
    body: JSON.stringify({ message, context }),
  });

export const runSimulation = (n_sessions = 50) =>
  request('/api/simulate/batch', {
    method: 'POST',
    body: JSON.stringify({ n_sessions, seed: 42 }),
  });

export const runLiveAuction = (user_text) =>
  request('/api/auction/live', {
    method: 'POST',
    body: JSON.stringify({ user_text }),
  });

export const scoreFit = (user_text, ad_copy) =>
  request('/api/score-fit', {
    method: 'POST',
    body: JSON.stringify({ user_text, ad_copy }),
  });
