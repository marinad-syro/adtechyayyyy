import { placementPreview, recordOutcome, scoreFit } from './api.js';
import { renderAuction } from './auction-panel.js';
import { renderBrainPanel, showBrainLoading } from './brain-panel.js';
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

  document.getElementById('outcomeClick')?.addEventListener('click', () => logOutcome('click'));
  document.getElementById('outcomeConvert')?.addEventListener('click', () => logOutcome('conversion'));
  document.getElementById('outcomeNoClick')?.addEventListener('click', () => logOutcome('no_click'));
}

function appendMessage(role, text) {
  const c = document.getElementById('consumerMessages');
  const div = document.createElement('div');
  div.className = `msg msg-${role}`;
  div.textContent = text;
  c.appendChild(div);
  c.scrollTop = c.scrollHeight;
}

function appendInlineAd(winner, source = 'decision') {
  const c = document.getElementById('consumerMessages');
  const div = document.createElement('div');
  div.className = 'inline-ad';
  const name = winner.product_name || winner.advertiser_name || 'Sponsored';
  const copy = winner.copy || winner.ad_copy || '';
  div.innerHTML = `
    <div class="inline-ad-label">Sponsored · ${name} · ${source === 'decision' ? 'conversion-optimized' : 'auction'}</div>
    <div class="inline-ad-copy">${copy}</div>
    <div class="inline-ad-cta">Learn more →</div>`;
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

  input.value = '';
  lastUserText = msg;
  appendMessage('user', msg);
  setTyping(true);

  const sendBtn = document.getElementById('consumerSend');
  sendBtn.disabled = true;

  showBrainLoading(document.getElementById('brainPanel'), 'Scoring emotional fit…');
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
      ? `Placement ${currentPlacementId} · action: ${decision?.action || '—'}`
      : decision?.action === 'no_bid'
        ? 'No bid — below CVR floor or safety gate'
        : decision?.action === 'escalate'
          ? `Escalated: ${(decision.escalate_reasons || []).join(', ')}`
          : '';

    if (decision?.action === 'serve' && decision.winner) {
      appendInlineAd(decision.winner, 'decision');
    } else if (data.auction?.winner?.relevance_score > 0.18) {
      appendInlineAd(data.auction.winner, 'auction');
    }

    renderDecidePanel(decision);
    renderAuction(document.getElementById('auctionPanel'), data.auction);

    if (decision?.winner?.user_activations) {
      renderBrainPanel(document.getElementById('brainPanel'), { winner: decision.winner, userText: msg });
    } else if (decision?.winner?.copy && msg.length >= 10) {
      try {
        const fit = await scoreFit(msg, decision.winner.copy);
        renderBrainPanel(document.getElementById('brainPanel'), {
          winner: {
            ...decision.winner,
            user_activations: fit.activations?.user,
            ad_activations: fit.activations?.ad,
            tribe_detail: { conversion_fit: fit.conversion_fit },
          },
          userText: msg,
          scoreFitResult: fit,
        });
      } catch {
        renderBrainPanel(document.getElementById('brainPanel'), { winner: decision.winner, userText: msg });
      }
    } else {
      document.getElementById('brainPanel').innerHTML =
        '<div class="empty-state">Emotional fit unavailable or text too short</div>';
    }

    if (data.dashboard_snapshot) {
      const d = data.dashboard_snapshot;
      document.getElementById('headerCvr').innerHTML =
        `CVR <strong>${(d.cvr * 100).toFixed(2)}%</strong>`;
    }
  } catch (e) {
    setTyping(false);
    appendMessage('system', 'Error: ' + e.message);
    showToast(e.message, true);
  } finally {
    sendBtn.disabled = false;
  }
}

async function logOutcome(event) {
  if (!currentPlacementId) {
    showToast('No active placement — send a message first', true);
    return;
  }
  try {
    await recordOutcome(currentPlacementId, event);
    showToast(`Recorded: ${event}`);
    refreshDashboard();
  } catch (e) {
    showToast(e.message, true);
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
