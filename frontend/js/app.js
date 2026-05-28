import { initDashboardPanels, refreshDashboard, showToast } from './dashboard-panels.js';
import { initConsumerChat, getLastUserText } from './consumer-chat.js';
import { initAgentDrawer } from './agent-drawer.js';
import { runLiveAuction } from './api.js';
import { renderAuction } from './auction-panel.js';

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

const RIGHT_PANEL_KEY = 'contextbid-right-panel-open';

function initRightPanel() {
  const panel = document.getElementById('rightPanel');
  const grid = document.getElementById('mainGrid');
  const toggle = document.getElementById('rightPanelToggle');
  if (!panel || !grid || !toggle) return;

  const setOpen = (open) => {
    panel.classList.toggle('collapsed', !open);
    grid.classList.toggle('right-collapsed', !open);
    toggle.classList.toggle('is-collapsed', !open);
    toggle.setAttribute('aria-expanded', String(open));
    toggle.title = open ? 'Hide decision panel' : 'Show decision panel';
    const icon = toggle.querySelector('.toggle-icon');
    if (icon) icon.textContent = open ? '›' : '‹';
    try {
      localStorage.setItem(RIGHT_PANEL_KEY, String(open));
    } catch {
      /* ignore */
    }
  };

  const stored = localStorage.getItem(RIGHT_PANEL_KEY);
  setOpen(stored !== 'false');

  toggle.addEventListener('click', () => setOpen(panel.classList.contains('collapsed')));
}

document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initRightPanel();
  initDashboardPanels();
  initConsumerChat();
  initAgentDrawer();

  document.getElementById('refreshBtn')?.addEventListener('click', () => refreshDashboard({ resetStats: true }));

  document.getElementById('runLiveAuctionBtn')?.addEventListener('click', async () => {
    const text = document.getElementById('consumerInput')?.value?.trim() || getLastUserText();
    if (!text || text.length < 3) {
      showToast('Send a chat message first (or type one in the input)', true);
      return;
    }
    const btn = document.getElementById('runLiveAuctionBtn');
    const panel = document.getElementById('auctionPanel');
    btn.disabled = true;
    panel.innerHTML = '<div class="loading-block"><span class="spinner"></span>Running live auction…</div>';
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === 'auction'));
    document.querySelectorAll('.tab-panel').forEach(p => {
      p.classList.toggle('active', p.id === 'tab-auction');
    });
    try {
      const auction = await runLiveAuction(text);
      renderAuction(panel, auction);
      showToast(`Auction #${auction.auction_id} — ${auction.total_bidders} bidders`);
    } catch (e) {
      panel.innerHTML = `<div class="empty-state">${e.message}</div>`;
      showToast(e.message, true);
    } finally {
      btn.disabled = false;
    }
  });
});
