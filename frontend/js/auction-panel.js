export function renderAuction(container, auction) {
  if (!auction || !container) return;

  const maxCPM = Math.max(...auction.all_bids.map(b => b.effective_cpm), 0.0001);
  const w = auction.winner;

  container.innerHTML = `
    <div class="auction-meta-row">
      <div><span class="ameta-lbl">Auction ID</span><br><span class="ameta-val">#${auction.auction_id}</span></div>
      <div><span class="ameta-lbl">Latency</span><br><span class="ameta-val green">${auction.latency_ms} ms</span></div>
      <div><span class="ameta-lbl">Bidders</span><br><span class="ameta-val">${auction.total_bidders}${auction.competitor_count != null ? ` <span class="bidder-mix">(${auction.own_brand_count || 0} yours · ${auction.competitor_count || 0} competitors)</span>` : ''}</span></div>
      <div><span class="ameta-lbl">Context</span><br><span class="ameta-val" style="font-size:9px;color:var(--text2)">"${auction.context_snippet}"</span></div>
    </div>
    <div class="card-title">Live bids — effective CPM</div>
    <div class="bid-list">
      ${auction.all_bids.map((bid, i) => {
        const pct = (bid.effective_cpm / maxCPM * 100).toFixed(1);
        const tag = bid.is_own_brand
          ? '<span class="bidder-tag own">Your brand</span>'
          : bid.bidder_type === 'legacy'
            ? '<span class="bidder-tag legacy">Demo</span>'
            : '<span class="bidder-tag competitor">Competitor</span>';
        return `
          <div class="bid-row ${i === 0 ? 'is-winner' : ''}">
            <span>${i === 0 ? '👑' : bid.logo || '📦'} ${bid.advertiser_name} ${tag}</span>
            <div class="bar-track"><div class="bar-fill" data-pct="${pct}" style="width:0%">${(bid.relevance_score * 100).toFixed(0)}%</div></div>
            <span class="ameta-val">$${bid.effective_cpm.toFixed(3)}</span>
          </div>`;
      }).join('')}
    </div>
    <div class="winner-card">
      <div class="card-title">Auction winner</div>
      <strong>${w.logo || ''} ${w.advertiser_name}</strong>
      <p style="font-size:11px;margin:6px 0">${w.ad_copy || '—'}</p>
      <span class="ameta-lbl">Clears at $${(w.clearing_price_cpm || 0).toFixed(4)} CPM</span>
    </div>
  `;

  requestAnimationFrame(() => {
    container.querySelectorAll('.bar-fill').forEach(bar => {
      bar.style.width = bar.dataset.pct + '%';
    });
  });
}
