import { initDashboardPanels, refreshDashboard } from './dashboard-panels.js';
import { initConsumerChat } from './consumer-chat.js';
import { initAgentDrawer } from './agent-drawer.js';
import { getHealth } from './api.js';

function initTabs() {
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const name = tab.dataset.tab;
      document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
      document.querySelectorAll('.tab-panel').forEach(p => {
        p.classList.toggle('active', p.id === `tab-${name}`);
      });
    });
  });
}

async function checkHealth() {
  try {
    const h = await getHealth();
    const status = document.getElementById('tribeStatus');
    if (!status) return;
    if (h.error) status.textContent = 'Tribe: error';
    else if (h.loading) {
      status.textContent = 'Tribe: loading…';
      setTimeout(checkHealth, 4000);
    } else if (h.ready) status.textContent = 'Tribe: ready';
    else status.textContent = 'Tribe: offline';

    const emb = h.embeddings;
    const embEl = document.getElementById('embedStatus');
    if (embEl && emb) {
      embEl.textContent = emb.ready ? 'Embeddings: ready' : emb.loading ? 'Embeddings: loading…' : 'Embeddings: keyword fallback';
    }
  } catch {
    setTimeout(checkHealth, 5000);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initDashboardPanels();
  initConsumerChat();
  initAgentDrawer();
  checkHealth();

  document.getElementById('refreshBtn')?.addEventListener('click', refreshDashboard);

  document.getElementById('tourBtn')?.addEventListener('click', () => {
    alert(
      '60-second demo:\n\n' +
      '1. Onboard a brand (left) or use default catalog\n' +
      '2. Type a user prompt in the center chat (e.g. back pain after desk work)\n' +
      '3. Check Conversion tab — p(CVR), EV, serve/no_bid\n' +
      '4. Auction tab — semantic bid mechanics\n' +
      '5. Brain tab — Tribe emotional fit\n' +
      '6. Simulate conversion → watch CVR update\n' +
      '7. Run 50-session simulation to prove lift'
    );
  });
});
