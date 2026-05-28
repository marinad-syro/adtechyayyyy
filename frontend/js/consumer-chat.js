import { placementPreview, recordOutcome } from './api.js';
import { renderAuction } from './auction-panel.js';
import { refreshDashboard, setLastPreview, showToast, getAppState } from './dashboard-panels.js';

let conversationHistory = [];
let currentPlacementId = null;
let lastUserText = '';

export function initConsumerChat() {
  document.getElementById('consumerSend')?.addEventListener('click', sendConsumerMessage);
  document.getElementById('consumerInput')?.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendConsumerMessage();
    }
  });
}

function appendMessage(role, text) {
  const c = document.getElementById('consumerMessages');
  const div = document.createElement('div');
  div.className = `msg msg-${role}`;
  div.textContent = text;
  c.appendChild(div);
  c.scrollTop = c.scrollHeight;
}

async function appendInlineAd(winner, source = 'decision') {
  const c = document.getElementById('consumerMessages');
  const div = document.createElement('div');
  div.className = 'inline-ad';
  const name = winner.product_name || winner.advertiser_name || 'Sponsored';
  const copy = winner.copy || winner.ad_copy || '';

  const label = document.createElement('div');
  label.className = 'inline-ad-label';
  label.textContent = `Sponsored · ${name} · ${source === 'decision' ? 'conversion-optimized' : 'auction'}`;

  const copyEl = document.createElement('div');
  copyEl.className = 'inline-ad-copy';
  copyEl.textContent = copy;

  const cta = document.createElement('button');
  cta.type = 'button';
  cta.className = 'inline-ad-cta';
  cta.textContent = 'Learn more →';

  if (currentPlacementId) {
    cta.addEventListener('click', async () => {
      if (cta.disabled) return;
      const ok = await logOutcome('click', { silent: false, successLabel: 'Click recorded' });
      if (ok) {
        cta.disabled = true;
        cta.textContent = 'Clicked ✓';
        div.classList.add('inline-ad-clicked');
      }
    });
    await logOutcome('impression', { silent: true });
  } else {
    cta.disabled = true;
    cta.title = 'No tracked placement for this ad';
  }

  div.append(label, copyEl, cta);
  c.appendChild(div);
  c.scrollTop = c.scrollHeight;
}

function setTyping(on) {
  const c = document.getElementById('consumerMessages');
  let el = document.getElementById('consumerTyping');
  if (on && !el) {
    el = document.createElement('div');
    el.id = 'consumerTyping';
    el.className = 'typing-indicator msg-system';
    el.innerHTML = '<span></span><span></span><span></span> Scoring placement…';
    c.appendChild(el);
    c.scrollTop = c.scrollHeight;
  } else if (!on && el) {
    el.remove();
  }
}

function renderDecidePanel(decision) {
  const el = document.getElementById('decidePanel');
  if (!el || !decision) return;

  const action = decision.action || 'no_bid';
  const winner = decision.winner;
  const candidates = decision.candidates || [];

  el.innerHTML = `
    <div style="margin-bottom:10px">
      <span class="action-badge action-${action}">${action.replace('_', ' ')}</span>
      ${decision.no_recommend_reason ? `<span style="font-size:10px;color:var(--text2);margin-left:8px">${decision.no_recommend_reason}</span>` : ''}
      ${decision.escalate_reasons?.length ? `<span style="font-size:10px;color:var(--amber);margin-left:8px">${decision.escalate_reasons.join('; ')}</span>` : ''}
    </div>
    ${winner ? `
      <div class="winner-card">
        <strong>${winner.product_name}</strong>
        <p style="font-size:11px;margin:6px 0">${winner.copy}</p>
        <div style="font-family:var(--mono);font-size:10px;color:var(--text2)">
          p(CVR) ${(winner.p_cvr * 100).toFixed(2)}% · bid $${(winner.bid || 0).toFixed(3)} · EV $${(winner.ev || 0).toFixed(3)}
        </div>
      </div>` : '<div class="empty-state">No winning placement</div>'}
    <div class="card-title" style="margin-top:12px">Finalists</div>
    <table class="candidates-table">
      <thead><tr><th>Creative</th><th>Intent</th><th>Fit</th><th>pCVR</th><th>EV</th></tr></thead>
      <tbody>
        ${candidates.slice(0, 5).map(c => `
          <tr>
            <td>${c.product_name}<br><span style="color:var(--text2)">${c.tone || ''}</span></td>
            <td>${(c.intent_score * 100).toFixed(1)}%</td>
            <td>${c.tribe_fit != null ? (c.tribe_fit * 100).toFixed(1) + '%' : '—'}</td>
            <td>${(c.p_cvr * 100).toFixed(2)}%</td>
            <td>${(c.ev || 0).toFixed(3)}</td>
          </tr>`).join('')}
      </tbody>
    </table>`;
}

async function sendConsumerMessage() {
  const input = document.getElementById('consumerInput');
  const msg = input.value.trim();
  if (!msg) return;

  if (!getAppState().activeBrandId) {
    showToast('Load a website URL in the dashboard first', true);
    return;
  }

  input.value = '';
  lastUserText = msg;
  appendMessage('user', msg);
  setTyping(true);

  const sendBtn = document.getElementById('consumerSend');
  sendBtn.disabled = true;

  document.getElementById('decidePanel').innerHTML =
    '<div class="loading-block"><span class="spinner"></span>Running conversion model…</div>';

  try {
    const brandId = getAppState().activeBrandId;
    const data = await placementPreview({
      user_text: msg,
      brand_id: brandId || undefined,
      skip_hitl: true,
      include_llm: true,
      conversation_history: conversationHistory,
    });

    setLastPreview(data);
    setTyping(false);
    appendMessage('assistant', data.llm?.response || 'No response');

    conversationHistory.push(
      { role: 'user', content: msg },
      { role: 'assistant', content: data.llm?.response || '' },
    );

    const decision = data.decision;
    currentPlacementId = decision?.placement_id || null;

    document.getElementById('placementMeta').textContent = currentPlacementId
      ? `Placement ${currentPlacementId.slice(0, 8)}… · Click “Learn more” on the ad to count a click`
      : decision?.no_recommend_reason
        ? `No recommendation — ${decision.no_recommend_reason}`
        : data.auction?.no_recommend_reason
          ? `No recommendation — ${data.auction.no_recommend_reason}`
          : decision?.action === 'no_bid'
            ? 'No bid — below score floor, CVR floor, or safety gate'
            : decision?.action === 'escalate'
              ? `Escalated: ${(decision.escalate_reasons || []).join(', ')}`
              : '';

    if (decision?.action === 'serve' && decision.winner) {
      await appendInlineAd(decision.winner, 'decision');
    }

    renderDecidePanel(decision);
    renderAuction(document.getElementById('auctionPanel'), data.auction);
    refreshDashboard();
  } catch (e) {
    setTyping(false);
    appendMessage('system', 'Error: ' + e.message);
    showToast(e.message, true);
  } finally {
    sendBtn.disabled = false;
  }
}

async function logOutcome(event, { silent = false, successLabel = null } = {}) {
  if (!currentPlacementId) {
    if (!silent) showToast('No active placement — send a message first', true);
    return false;
  }
  try {
    await recordOutcome(currentPlacementId, event);
    if (!silent) {
      showToast(successLabel || `Recorded: ${event}`);
    }
    await refreshDashboard();
    return true;
  } catch (e) {
    if (!silent) showToast(e.message, true);
    return false;
  }
}

export function getAgentContext() {
  const preview = getAppState().lastPreview;
  return {
    active_brand_id: getAppState().activeBrandId,
    last_decision: preview?.decision || null,
    last_auction: preview?.auction || null,
    dashboard_stats: getAppState().dashboard,
    last_user_text: lastUserText,
  };
}
