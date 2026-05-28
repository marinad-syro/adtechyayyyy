import { advertiserAgent } from './api.js';
import { showToast } from './dashboard-panels.js';
import { getAgentContext } from './consumer-chat.js';

const QUICK_PROMPTS = [
  'Why did we no-bid on the last message?',
  'Explain the Tribe fit on the winning creative.',
  'Which finalist had the best expected value?',
  'What prompts should we target for this brand?',
];

export function initAgentDrawer() {
  const drawer = document.getElementById('agentDrawer');
  const header = document.getElementById('drawerToggle');
  header?.addEventListener('click', () => drawer.classList.toggle('collapsed'));

  document.getElementById('agentSend')?.addEventListener('click', sendAgentMessage);
  document.getElementById('agentInput')?.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendAgentMessage();
    }
  });

  const chips = document.getElementById('agentChips');
  QUICK_PROMPTS.forEach(text => {
    const chip = document.createElement('button');
    chip.className = 'quick-chip';
    chip.textContent = text;
    chip.addEventListener('click', () => {
      document.getElementById('agentInput').value = text;
      sendAgentMessage();
    });
    chips?.appendChild(chip);
  });
}

function appendAgentMsg(role, text) {
  const c = document.getElementById('agentMessages');
  const div = document.createElement('div');
  div.className = `agent-msg agent-msg-${role}`;
  div.textContent = text;
  c.appendChild(div);
  c.scrollTop = c.scrollHeight;
}

async function sendAgentMessage() {
  const input = document.getElementById('agentInput');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';
  appendAgentMsg('user', msg);

  const btn = document.getElementById('agentSend');
  btn.disabled = true;

  try {
    const data = await advertiserAgent(msg, getAgentContext());
    appendAgentMsg('bot', data.response);
  } catch (e) {
    appendAgentMsg('bot', 'Could not reach advisor: ' + e.message);
    showToast(e.message, true);
  } finally {
    btn.disabled = false;
  }
}
