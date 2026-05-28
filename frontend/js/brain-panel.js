const EMOTION_REGIONS = [
  { id: 'acc', name: 'ACC', full: 'Anterior Cingulate' },
  { id: 'insula', name: 'Insula', full: 'Insula' },
  { id: 'ofc', name: 'OFC', full: 'Orbitofrontal Cortex' },
  { id: 'pcc', name: 'PCC', full: 'Posterior Cingulate' },
];

function activationColor(t) {
  const stops = [
    [0, [14, 14, 40]],
    [0.25, [30, 20, 90]],
    [0.5, [110, 40, 200]],
    [0.75, [210, 90, 20]],
    [1, [255, 208, 0]],
  ];
  for (let i = 0; i < stops.length - 1; i++) {
    const [t0, c0] = stops[i];
    const [t1, c1] = stops[i + 1];
    if (t >= t0 && t <= t1) {
      const s = (t - t0) / (t1 - t0);
      return `rgb(${lerp(c0, c1, s, 0)},${lerp(c0, c1, s, 1)},${lerp(c0, c1, s, 2)})`;
    }
  }
  return 'rgb(255,208,0)';
}

function lerp(c0, c1, s, i) {
  return Math.round(c0[i] + s * (c1[i] - c0[i]));
}

function renderBars(parent, activations, prefix) {
  if (!activations) {
    parent.innerHTML = '<div class="empty-state">No activation data</div>';
    return;
  }
  parent.innerHTML = EMOTION_REGIONS.map(r => {
    const t = activations[r.id] ?? activations[r.full?.toLowerCase()] ?? 0;
    const pct = (t * 100).toFixed(1);
    const color = activationColor(t);
    return `
      <div class="ebar-row">
        <div><div class="ebar-name">${r.name}</div></div>
        <div class="ebar-track"><div class="ebar-fill" id="${prefix}-${r.id}" style="background:${color};width:0%"></div></div>
        <div class="ebar-pct" id="${prefix}-pct-${r.id}">0%</div>
      </div>`;
  }).join('');

  requestAnimationFrame(() => {
    EMOTION_REGIONS.forEach(r => {
      const t = activations[r.id] ?? 0;
      const pct = (t * 100).toFixed(1);
      const fill = document.getElementById(`${prefix}-${r.id}`);
      const label = document.getElementById(`${prefix}-pct-${r.id}`);
      if (fill) fill.style.width = pct + '%';
      if (label) label.textContent = pct + '%';
    });
  });
}

export function renderBrainPanel(container, { winner, userText, scoreFitResult }) {
  if (!container) return;

  const fit = winner?.tribe_detail?.conversion_fit ?? scoreFitResult?.conversion_fit;
  const fitPct = fit != null ? (fit * 100).toFixed(1) : '—';

  container.innerHTML = `
    <div class="fit-score">
      <div class="card-title">Conversion fit score</div>
      <div class="fit-score-val">${fitPct}${fitPct !== '—' ? '%' : ''}</div>
    </div>
    <div class="brain-dual">
      <div>
        <div class="brain-col-title">User context</div>
        <div id="brain-user-bars"></div>
      </div>
      <div>
        <div class="brain-col-title">Winning ad</div>
        <div id="brain-ad-bars"></div>
      </div>
    </div>
    ${winner?.copy ? `<p style="font-size:10px;color:var(--text2);margin-top:10px;font-family:var(--mono)">"${winner.copy.slice(0, 120)}${winner.copy.length > 120 ? '…' : ''}"</p>` : ''}
  `;

  const userActs = winner?.user_activations || scoreFitResult?.user_activations;
  const adActs = winner?.ad_activations || scoreFitResult?.ad_activations;

  renderBars(document.getElementById('brain-user-bars'), userActs, 'bu');
  renderBars(document.getElementById('brain-ad-bars'), adActs, 'ba');
}

export function showBrainLoading(container, message = 'Scoring emotional fit…') {
  if (container) {
    container.innerHTML = `<div class="loading-block"><span class="spinner"></span>${message}</div>`;
  }
}
