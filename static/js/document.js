/**
 * document.js — Document analysis page logic
 * Handles: analysis loading, Q&A, search, lawyer prep, brief, TTS, voice
 */

let analysisData = null;
let isVoiceRecording = false;
let recognition = null;

// ============================================================
// ANALYSIS LOADING
// ============================================================

function loadAnalysis() {
  fetch(`/api/documents/${DOC_ID}/analysis`)
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        console.warn('No analysis found:', data.error);
        return;
      }
      analysisData = data;
      renderAnalysis(data);
    })
    .catch(err => console.error('Load analysis error:', err));
}

function renderAnalysis(data) {
  // Show stats row
  const statsRow = document.getElementById('statsRow');
  if (statsRow) statsRow.style.removeProperty('display');

  // Animate stats
  animateCounter('statClauses', (data.important_clauses || []).length);
  animateCounter('statPoints', (data.points_to_review || []).length);
  animateCounter('statDates', (data.important_dates || []).length);
  animateCounter('statFinancial', (data.financial_terms || []).length);

  // Update doc type
  if (data.document_type) {
    const el = document.getElementById('docType');
    if (el) el.textContent = data.document_type;
  }

  // Show listen button
  const listenBtn = document.getElementById('listenSummaryBtn');
  if (listenBtn) listenBtn.style.display = 'flex';

  renderSummary(data);
  renderClauses(data.important_clauses || []);
  renderReviewPoints(data.points_to_review || []);
  renderObligations(data.obligations || {});
  renderDates(data.important_dates || []);
  renderFinancial(data.financial_terms || []);
}

function animateCounter(id, target) {
  const el = document.getElementById(id);
  if (!el) return;
  let current = 0;
  const step = Math.max(1, Math.ceil(target / 20));
  const interval = setInterval(() => {
    current = Math.min(current + step, target);
    el.textContent = current;
    if (current >= target) clearInterval(interval);
  }, 40);
}

// ============================================================
// SUMMARY
// ============================================================

function renderSummary(data) {
  const summaryEl = document.getElementById('summaryText');
  if (summaryEl) {
    summaryEl.innerHTML = `<p>${escapeHtml(data.summary || 'No summary available.')}</p>`;
  }

  const takeawaysEl = document.getElementById('keyTakeaways');
  if (takeawaysEl) {
    const items = data.key_takeaways || [];
    if (items.length) {
      takeawaysEl.innerHTML = `<ul style="list-style:none; padding:0; margin:0; display:flex; flex-direction:column; gap:8px;">
        ${items.map(t => `
          <li style="display:flex; align-items:flex-start; gap:10px; font-size:14px;">
            <i class="bi bi-check-circle-fill" style="color:var(--color-success); flex-shrink:0; margin-top:2px;"></i>
            <span>${escapeHtml(t)}</span>
          </li>`).join('')}
      </ul>`;
    } else {
      takeawaysEl.innerHTML = '<p class="text-muted fs-13">No key takeaways found.</p>';
    }
  }

  const partiesEl = document.getElementById('partiesSection');
  if (partiesEl) {
    const parties = data.parties || [];
    if (parties.length) {
      partiesEl.innerHTML = parties.map(p => `
        <div class="d-flex align-items-center gap-2 p-2 rounded" style="background:var(--bg-secondary); font-size:13px;">
          <i class="bi bi-person-circle text-primary"></i>
          <span>${escapeHtml(p)}</span>
        </div>`).join('');
    } else {
      partiesEl.innerHTML = '<span class="text-muted fs-13">Parties could not be identified.</span>';
    }
  }
}

// ============================================================
// CLAUSES
// ============================================================

function renderClauses(clauses) {
  const grid = document.getElementById('clausesGrid');
  const count = document.getElementById('clauseCount');
  if (!grid) return;

  if (count) count.textContent = `${clauses.length} found`;

  if (!clauses.length) {
    grid.innerHTML = '<div class="col-12"><div class="empty-state"><div class="empty-icon"><i class="bi bi-list-check"></i></div><p>No important clauses were identified.</p></div></div>';
    return;
  }

  const categoryColors = {
    'Termination': 'var(--color-accent)',
    'Payment': 'var(--color-success)',
    'Confidentiality': 'var(--color-primary)',
    'Non-compete': 'var(--color-gold)',
    'Liability': 'var(--color-accent)',
    'Indemnity': 'var(--color-gold)',
    'Notice Period': 'var(--color-primary)',
  };

  grid.innerHTML = clauses.map((clause, i) => {
    const color = categoryColors[clause.category] || 'var(--color-primary)';
    const page = clause.page ? `Page ${clause.page}` : '';
    const section = clause.section || '';
    const ref = [section, page].filter(Boolean).join(' · ');

    return `
      <div class="col-md-6 col-lg-4">
        <div class="clause-card fade-in" style="border-left-color:${color};" onclick="showClauseDetail(${i})">
          <div class="clause-name">${escapeHtml(clause.name || 'Unnamed Clause')}</div>
          <div class="clause-meta">
            ${clause.category ? `<span class="badge badge-muted">${escapeHtml(clause.category)}</span>` : ''}
            ${ref ? `<span style="font-size:11px; color:var(--color-text-muted);">${escapeHtml(ref)}</span>` : ''}
          </div>
          <div class="clause-excerpt">${escapeHtml((clause.explanation || '').slice(0, 100))}${clause.explanation && clause.explanation.length > 100 ? '...' : ''}</div>
          <div class="mt-2">
            <span style="font-size:11px; color:var(--color-primary); font-weight:500;">Click to expand <i class="bi bi-arrow-right"></i></span>
          </div>
        </div>
      </div>`;
  }).join('');
}

function showClauseDetail(index) {
  if (!analysisData) return;
  const clause = analysisData.important_clauses[index];
  if (!clause) return;

  const page = clause.page ? `<span class="meta-chip"><i class="bi bi-file-earmark"></i> Page ${clause.page}</span>` : '';
  const section = clause.section ? `<span class="meta-chip"><i class="bi bi-bookmark"></i> ${escapeHtml(clause.section)}</span>` : '';

  const modalHtml = `
    <div class="modal fade" id="clauseDetailModal" tabindex="-1">
      <div class="modal-dialog">
        <div class="modal-content" style="border-radius:var(--radius-md);">
          <div class="modal-header" style="border-color:var(--color-border);">
            <h5 class="modal-title" style="font-family:var(--font-body);">${escapeHtml(clause.name || 'Clause Detail')}</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <div class="d-flex gap-2 flex-wrap mb-3">
              ${clause.category ? `<span class="badge badge-primary">${escapeHtml(clause.category)}</span>` : ''}
              ${page} ${section}
            </div>
            ${clause.original_text ? `
              <div class="mb-3">
                <div class="fs-12 text-muted fw-600 mb-1 text-uppercase" style="letter-spacing:.05em;">Original Text</div>
                <div style="background:var(--bg-secondary); padding:12px; border-radius:8px; font-size:13px; font-family:var(--font-mono); color:var(--color-text-muted); border-left:3px solid var(--color-border);">
                  ${escapeHtml(clause.original_text)}
                </div>
              </div>` : ''}
            <div>
              <div class="fs-12 text-muted fw-600 mb-1 text-uppercase" style="letter-spacing:.05em;">Plain Language Explanation</div>
              <div style="font-size:14px; line-height:1.7;">${escapeHtml(clause.explanation || 'No explanation available.')}</div>
            </div>
          </div>
          <div class="modal-footer" style="border-color:var(--color-border);">
            <button class="btn btn-ghost btn-sm" onclick="speakText('${escapeHtml(clause.explanation || '')}')">
              <i class="bi bi-volume-up"></i> Listen
            </button>
            <button type="button" class="btn btn-ghost btn-sm" data-bs-dismiss="modal">Close</button>
          </div>
        </div>
      </div>
    </div>`;

  // Remove existing modal
  const existing = document.getElementById('clauseDetailModal');
  if (existing) existing.remove();

  document.body.insertAdjacentHTML('beforeend', modalHtml);
  new bootstrap.Modal(document.getElementById('clauseDetailModal')).show();
}

// ============================================================
// POINTS TO REVIEW
// ============================================================

function renderReviewPoints(points) {
  const container = document.getElementById('reviewPoints');
  const count = document.getElementById('reviewCount');
  if (!container) return;

  if (count) count.textContent = `${points.length} item${points.length !== 1 ? 's' : ''}`;

  if (!points.length) {
    container.innerHTML = '<div class="empty-state" style="padding:32px;"><div class="empty-icon" style="font-size:32px;"><i class="bi bi-check-circle"></i></div><p>No significant points to review were identified.</p></div>';
    return;
  }

  container.innerHTML = points.map(point => {
    const severity = point.severity || 'medium';
    const severityLabel = { high: '⚑ High', medium: '● Medium', low: '○ Low' }[severity] || 'Medium';
    const ref = point.section || '';

    return `
      <div class="review-card severity-${severity} mb-3 fade-in">
        <div class="d-flex align-items-start justify-content-between gap-3">
          <div style="flex:1;">
            <div class="d-flex align-items-center gap-2 mb-1">
              <span class="fw-600 fs-14">${escapeHtml(point.title || 'Review Item')}</span>
              <span class="badge ${severity === 'high' ? 'badge-accent' : severity === 'medium' ? 'badge-gold' : 'badge-success'}" style="font-size:10px;">${severityLabel}</span>
            </div>
            ${ref ? `<div class="fs-11 text-muted mb-2"><i class="bi bi-bookmark me-1"></i>${escapeHtml(ref)}</div>` : ''}
            <div class="fs-13" style="color:var(--color-text-muted);">${escapeHtml(point.description || '')}</div>
          </div>
          <button class="btn btn-ghost btn-sm" style="flex-shrink:0;" onclick="speakText('${escapeHtml(point.title || '')}. ${escapeHtml(point.description || '')}')">
            <i class="bi bi-volume-up"></i>
          </button>
        </div>
        <div class="mt-2 pt-2" style="border-top:1px solid var(--color-border);">
          <span class="fs-11 text-muted"><i class="bi bi-info-circle me-1"></i>Consider discussing this with a qualified legal professional.</span>
        </div>
      </div>`;
  }).join('');
}

// ============================================================
// OBLIGATIONS
// ============================================================

function renderObligations(obligations) {
  const container = document.getElementById('obligationsSection');
  if (!container) return;

  const partyA = obligations.party_a || {};
  const partyB = obligations.party_b || {};
  const oblA = partyA.obligations || [];
  const oblB = partyB.obligations || [];

  if (!oblA.length && !oblB.length) {
    container.innerHTML = '<div class="col-12"><p class="text-muted fs-13">No specific obligations could be identified.</p></div>';
    return;
  }

  const renderParty = (party, color) => `
    <div class="col-md-6">
      <div class="card h-100">
        <div class="card-header" style="border-left:3px solid ${color};">
          <div class="card-title">${escapeHtml(party.name || 'Party')}</div>
          <div class="card-subtitle">Obligations</div>
        </div>
        <div class="card-body">
          ${party.obligations && party.obligations.length ?
            `<ul style="list-style:none; padding:0; margin:0; display:flex; flex-direction:column; gap:8px;">
              ${party.obligations.map(ob => `
                <li style="display:flex; align-items:flex-start; gap:8px; font-size:13px;">
                  <i class="bi bi-arrow-right-circle-fill" style="color:${color}; flex-shrink:0; margin-top:2px;"></i>
                  <span>${escapeHtml(ob)}</span>
                </li>`).join('')}
            </ul>` :
            '<p class="text-muted fs-13">No specific obligations identified.</p>'
          }
        </div>
      </div>
    </div>`;

  container.innerHTML = `
    ${renderParty(partyA, 'var(--color-primary)')}
    ${renderParty(partyB, 'var(--color-accent)')}
  `;
}

// ============================================================
// DATES TIMELINE
// ============================================================

function renderDates(dates) {
  const container = document.getElementById('datesTimeline');
  const count = document.getElementById('datesCount');
  if (!container) return;

  if (count) count.textContent = `${dates.length} date${dates.length !== 1 ? 's' : ''}`;

  if (!dates.length) {
    container.innerHTML = '<p class="text-muted fs-13">No important dates were found.</p>';
    return;
  }

  container.innerHTML = dates.map(d => `
    <div class="timeline-item">
      <div class="timeline-dot"></div>
      <div class="timeline-content">
        <div class="date-label">${escapeHtml(d.label || 'Date')}</div>
        <div class="date-value">${escapeHtml(d.date || '—')}</div>
        ${d.context ? `<div class="date-context">${escapeHtml(d.context)}</div>` : ''}
      </div>
    </div>`).join('');
}

// ============================================================
// FINANCIAL TERMS
// ============================================================

function renderFinancial(terms) {
  const container = document.getElementById('financialTerms');
  const count = document.getElementById('financialCount');
  if (!container) return;

  if (count) count.textContent = `${terms.length} term${terms.length !== 1 ? 's' : ''}`;

  if (!terms.length) {
    container.innerHTML = '<p class="text-muted fs-13">No financial terms were found.</p>';
    return;
  }

  container.innerHTML = terms.map(t => `
    <div class="d-flex align-items-start gap-3 p-3 mb-2 rounded" style="background:var(--bg-secondary);">
      <div style="width:36px; height:36px; background:#D1FAE5; border-radius:8px; display:flex; align-items:center; justify-content:center; flex-shrink:0;">
        <i class="bi bi-currency-rupee" style="color:var(--color-success);"></i>
      </div>
      <div>
        <div class="fs-12 text-muted">${escapeHtml(t.label || 'Financial Term')}</div>
        <div class="fw-600 fs-15" style="color:var(--color-success);">${escapeHtml(t.amount || '—')}</div>
        ${t.context ? `<div class="fs-12 text-muted mt-1">${escapeHtml(t.context)}</div>` : ''}
      </div>
    </div>`).join('');
}

// ============================================================
// RUN ANALYSIS
// ============================================================

function runAnalysis() {
  const btn = document.getElementById('runAnalysisBtn');
  if (btn) btn.disabled = true;

  const overlay = document.getElementById('loadingOverlay');
  if (overlay) overlay.style.display = 'flex';

  const steps = [
    'Reading document...',
    'Understanding content...',
    'Identifying important clauses...',
    'Extracting dates and financial terms...',
    'Analyzing obligations...',
    'Preparing summary...',
    'Finalizing analysis...',
  ];
  let si = 0;
  const stepEl = document.getElementById('loadingStep');
  const stepInterval = setInterval(() => {
    si = (si + 1) % steps.length;
    if (stepEl) stepEl.textContent = steps[si];
  }, 2000);

  fetch(`/api/documents/${DOC_ID}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({})
  })
    .then(r => r.json())
    .then(data => {
      clearInterval(stepInterval);
      if (overlay) overlay.style.display = 'none';

      if (data.error) {
        showToast('error', data.error);
        if (btn) btn.disabled = false;
        return;
      }

      // Update UI
      const pendingState = document.getElementById('pendingState');
      const analysisSection = document.getElementById('analysisSection');
      const statusPill = document.getElementById('analysisStatusPill');

      if (pendingState) pendingState.style.display = 'none';
      if (analysisSection) analysisSection.style.display = 'block';
      if (statusPill) statusPill.innerHTML = '<i class="bi bi-check-circle-fill"></i> Analyzed';
      if (statusPill) statusPill.className = 'status-pill status-analyzed';
      if (btn) btn.style.display = 'none';

      analysisData = data.analysis;
      renderAnalysis(data.analysis);
      showToast('success', 'Analysis complete!');
    })
    .catch(err => {
      clearInterval(stepInterval);
      if (overlay) overlay.style.display = 'none';
      showToast('error', "We couldn't complete the AI analysis. Please try again.");
      if (btn) btn.disabled = false;
    });
}

// ============================================================
// DOCUMENT Q&A
// ============================================================

function setQuestion(text) {
  const input = document.getElementById('chatInput');
  if (input) input.value = text;
  input.focus();
}

function sendQuestion(bypassCache = false, questionText = null) {
  const input = document.getElementById('chatInput');
  const question = questionText || (input ? input.value : '').trim();
  if (!question) return;

  const lang = document.getElementById('qaLangSelect')?.value || 'en';
  const mode = localStorage.getItem('legalai_mode') || 'auto';

  // Add user bubble if not bypass re-trigger
  if (!questionText && input) {
    addChatBubble('user', question);
    input.value = '';
  }

  // Add thinking indicator
  const thinkingId = 'thinking-' + Date.now();
  addChatBubble('assistant', '<span style="opacity:0.5;">Searching document...</span>', thinkingId);

  const sendBtn = document.getElementById('sendBtn');
  if (sendBtn) sendBtn.disabled = true;

  fetch(`/api/documents/${DOC_ID}/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, mode, bypass_cache: bypassCache }),
  })
  .then(r => r.json())
  .then(async data => {
    document.getElementById(thinkingId)?.remove();

    let answer = data.answer || "I couldn't find this information in the uploaded document.";

    if (lang !== 'en') {
      const translated = await translateText(answer, lang);
      if (translated !== answer) answer = translated;
    }

    let badgeClass = 'badge-secondary';
    let badgeText = data.processing_badge || (data.mode === 'gemini' ? '🟢 Gemini AI' : '⚫ Offline Document Mode');
    if (data.mode === 'gemini') badgeClass = 'badge-success';
    else if (data.mode === 'offline_fallback') badgeClass = 'badge-warning';

    let answerHtml = `<div class="d-flex align-items-center justify-content-between gap-2 mb-2">
      <span class="badge ${badgeClass}" style="font-size:10px;">${escapeHtml(badgeText)}</span>
      ${data.cached ? `<span style="font-size:11px; color:var(--color-text-muted);" title="Answer served from temporary session cache"><i class="bi bi-lightning-charge"></i> Cached</span>` : ''}
    </div>
    <div style="line-height:1.65;">${escapeHtml(answer).replace(/\n/g, '<br>')}</div>`;

    if (data.sources && data.sources.length) {
      const sources = data.sources.map(s =>
        `<span class="source-tag"><i class="bi bi-bookmark-fill"></i> ${s.section ? escapeHtml(s.section) : (s.page ? `Page ${s.page}` : 'Document')}</span>`
      ).join('');
      answerHtml += `<div class="d-flex flex-wrap gap-1 mt-2">${sources}</div>`;
    }

    // Use data-attribute for fresh answer button to avoid XSS via JS string interpolation
    const freshBtnId = 'fresh-' + Date.now();
    answerHtml += `<div class="d-flex align-items-center justify-content-between mt-2 pt-1" style="border-top:1px dashed var(--color-border); font-size:11px;">
      <span style="color:var(--color-text-muted);"><i class="bi bi-info-circle me-1"></i>Document-grounded analysis</span>
      <button class="btn btn-ghost btn-sm py-0 px-1 fresh-answer-btn" style="font-size:11px;"
        data-question="${escapeHtml(question)}">
        <i class="bi bi-arrow-clockwise"></i> Get Fresh Answer
      </button>
    </div>`;

    addChatBubble('assistant', answerHtml);
    if (sendBtn) sendBtn.disabled = false;
  })
  .catch(err => {
    document.getElementById(thinkingId)?.remove();
    addChatBubble('assistant', 'Sorry, I encountered an error processing your question. Please try again.');
    if (sendBtn) sendBtn.disabled = false;
  });
}

function getFreshAnswer(question) {
  if (!question) return;
  addChatBubble('user', `&#8635; Refreshing answer for: "${escapeHtml(question)}"`);
  sendQuestion(true, question);
}

function addChatBubble(role, html, id) {
  const messages = document.getElementById('chatMessages');
  if (!messages) return;

  const bubble = document.createElement('div');
  bubble.className = `chat-bubble ${role} fade-in`;
  if (id) bubble.id = id;
  bubble.innerHTML = html;
  messages.appendChild(bubble);
  messages.scrollTop = messages.scrollHeight;

  // Event delegation for fresh-answer buttons (avoids inline onclick XSS)
  bubble.querySelectorAll('.fresh-answer-btn').forEach(btn => {
    btn.addEventListener('click', function() {
      const q = this.getAttribute('data-question');
      if (q) getFreshAnswer(q);
    });
  });
}

function loadChatHistory() {
  fetch(`/api/documents/${DOC_ID}/chat-history`)
    .then(r => r.json())
    .then(history => {
      if (!history.length) return;
      const messages = document.getElementById('chatMessages');
      if (!messages) return;
      // Clear default welcome message
      messages.innerHTML = '';
      history.forEach(item => {
        addChatBubble('user', escapeHtml(item.question));
        let answerHtml = `<div>${escapeHtml(item.answer)}</div>`;
        if (item.sources && item.sources.length) {
          const sources = item.sources.map(s =>
            `<span class="source-tag"><i class="bi bi-bookmark-fill"></i> ${s.page ? `Page ${s.page}` : 'Document'}</span>`
          ).join('');
          answerHtml += `<div class="d-flex flex-wrap gap-1 mt-2">${sources}</div>`;
        }
        addChatBubble('assistant', answerHtml);
      });
    })
    .catch(() => {});
}

// ============================================================
// VOICE INPUT
// ============================================================

function toggleVoiceInput() {
  const voiceBtn = document.getElementById('voiceBtn');

  if (isVoiceRecording) {
    stopVoice();
    return;
  }

  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    showToast('info', 'Voice input is not supported by this browser. You can type your question instead.');
    return;
  }

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRecognition();
  recognition.lang = 'en-US';
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    isVoiceRecording = true;
    voiceBtn.classList.add('recording');
    voiceBtn.innerHTML = '<i class="bi bi-mic-fill"></i>';
    showToast('info', 'Listening... Speak your question.');
  };

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    const input = document.getElementById('chatInput');
    if (input) input.value = transcript;
    stopVoice();
    sendQuestion();
  };

  recognition.onerror = (event) => {
    stopVoice();
    showToast('error', 'Voice recognition error. Please try again or type your question.');
  };

  recognition.onend = () => stopVoice();

  recognition.start();
}

function stopVoice() {
  isVoiceRecording = false;
  const voiceBtn = document.getElementById('voiceBtn');
  if (voiceBtn) {
    voiceBtn.classList.remove('recording');
    voiceBtn.innerHTML = '<i class="bi bi-mic"></i>';
  }
  if (recognition) {
    try { recognition.stop(); } catch (e) {}
  }
}

// ============================================================
// DOCUMENT SEARCH
// ============================================================

function searchDocument() {
  const query = document.getElementById('searchInput')?.value?.trim();
  if (!query) return;

  const resultsEl = document.getElementById('searchResults');
  if (resultsEl) resultsEl.innerHTML = '<div class="text-muted fs-12 mt-1">Searching...</div>';

  fetch(`/api/documents/${DOC_ID}/search?q=${encodeURIComponent(query)}`)
    .then(r => r.json())
    .then(data => {
      if (!resultsEl) return;
      if (!data.results || !data.results.length) {
        resultsEl.innerHTML = `<div class="text-muted fs-12 mt-1">No matches found for "${escapeHtml(query)}"</div>`;
        return;
      }
      resultsEl.innerHTML = `
        <div class="fs-12 text-muted mb-2 mt-1">${data.count} match${data.count !== 1 ? 'es' : ''} found</div>
        ${data.results.slice(0, 5).map(r => `
          <div class="search-result-item">
            ${r.page ? `<div class="result-page">Page ${r.page}</div>` : ''}
            <div>${highlightQuery(escapeHtml(r.snippet), escapeHtml(query))}</div>
          </div>`).join('')}
        ${data.count > 5 ? `<div class="fs-11 text-muted">... and ${data.count - 5} more matches</div>` : ''}`;
    })
    .catch(() => {
      if (resultsEl) resultsEl.innerHTML = '<div class="text-muted fs-12 mt-1">Search failed.</div>';
    });
}

function highlightQuery(text, query) {
  const re = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
  return text.replace(re, '<mark style="background:var(--color-primary-light); padding:0 2px; border-radius:3px;">$1</mark>');
}

// ============================================================
// LAWYER PREPARATION
// ============================================================

function generateLawyerPrep() {
  const btn = document.getElementById('genPrepBtn');
  const content = document.getElementById('lawyerPrepContent');
  if (btn) btn.disabled = true;
  if (content) content.innerHTML = `<div class="text-center py-4"><div class="loading-spinner mx-auto mb-3"></div><div class="text-muted fs-13">Generating consultation guide...</div></div>`;

  fetch(`/api/documents/${DOC_ID}/lawyer-prep`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({})
  })
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        content.innerHTML = `<div class="alert alert-danger"><i class="bi bi-exclamation-circle"></i> ${escapeHtml(data.error)}</div>`;
        if (btn) btn.disabled = false;
        return;
      }
      renderLawyerPrep(data);
      if (btn) btn.disabled = false;
    })
    .catch(err => {
      if (content) content.innerHTML = '<div class="alert alert-danger"><i class="bi bi-exclamation-circle"></i> Could not generate preparation guide. Please try again.</div>';
      if (btn) btn.disabled = false;
    });
}

function renderLawyerPrep(data) {
  const content = document.getElementById('lawyerPrepContent');
  if (!content) return;

  const section = (title, icon, items, isQA = false) => {
    if (!items || !items.length) return '';
    return `
      <div class="card mb-3">
        <div class="card-header">
          <div class="card-title"><i class="bi ${icon} me-2 text-primary"></i>${title}</div>
        </div>
        <div class="card-body">
          ${isQA ?
            items.map((q, i) => `
              <div class="mb-3 pb-3" style="${i < items.length - 1 ? 'border-bottom:1px solid var(--color-border);' : ''}">
                <div class="fw-600 fs-14 mb-1">${escapeHtml(q.question || q)}</div>
                ${q.context ? `<div class="fs-13 text-muted">${escapeHtml(q.context)}</div>` : ''}
              </div>`).join('') :
            `<ul style="list-style:none; padding:0; margin:0; display:flex; flex-direction:column; gap:8px;">
              ${items.map(item => `
                <li style="display:flex; align-items:flex-start; gap:8px; font-size:13px;">
                  <i class="bi bi-dot" style="color:var(--color-primary); font-size:20px; flex-shrink:0; margin-top:-2px;"></i>
                  <span>${escapeHtml(typeof item === 'string' ? item : JSON.stringify(item))}</span>
                </li>`).join('')}
            </ul>`
          }
        </div>
      </div>`;
  };

  content.innerHTML = `
    <div class="alert alert-info mb-3">
      <i class="bi bi-info-circle"></i>
      <div>This guide is for preparation purposes only and does not constitute legal advice. Always consult a qualified legal professional.</div>
    </div>
    ${section('Important Facts', 'bi-lightbulb', data.important_facts)}
    ${section('Questions to Ask Your Lawyer', 'bi-chat-square-quote', data.questions_for_lawyer, true)}
    ${section('Documents to Bring', 'bi-folder2-open', data.documents_to_bring)}
    ${section('Dates to Remember', 'bi-calendar-event', data.dates_to_remember)}
    ${section('Key Concerns', 'bi-exclamation-triangle', data.key_concerns)}
    ${(!data.important_facts?.length && !data.questions_for_lawyer?.length) ?
      '<p class="text-muted fs-13">No preparation guide could be generated. Please run document analysis first.</p>' : ''}
  `;
}

// ============================================================
// LEGAL BRIEF
// ============================================================

function generateBrief() {
  const modal = new bootstrap.Modal(document.getElementById('briefModal'));
  const body = document.getElementById('briefModalBody');
  if (body) body.innerHTML = '<div class="text-center py-4"><div class="loading-spinner mx-auto mb-3"></div><div class="text-muted fs-13">Generating legal brief...</div></div>';
  modal.show();

  fetch(`/api/documents/${DOC_ID}/brief`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({})
  })
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        body.innerHTML = `<div class="alert alert-danger">${escapeHtml(data.error)}</div>`;
        return;
      }
      renderBriefModal(data);
    })
    .catch(() => {
      body.innerHTML = '<div class="alert alert-danger">Could not generate legal brief. Please try again.</div>';
    });
}

function renderBriefModal(brief) {
  const body = document.getElementById('briefModalBody');
  if (!body) return;

  const section = (title, content) => {
    if (!content) return '';
    return `<div class="mb-4">
      <div class="fs-12 fw-600 text-muted text-uppercase mb-2" style="letter-spacing:.06em;">${escapeHtml(title)}</div>
      <div class="prose fs-14">${escapeHtml(typeof content === 'string' ? content : JSON.stringify(content))}</div>
    </div>`;
  };

  const parties = (brief.parties || []).join(', ');
  const questions = (brief.recommended_questions || []);

  body.innerHTML = `
    <div class="mb-3 pb-3" style="border-bottom:1px solid var(--color-border);">
      <div class="fs-12 text-muted text-uppercase mb-1" style="letter-spacing:.06em;">Document Type</div>
      <div class="fw-600">${escapeHtml(brief.document_type || '—')}</div>
    </div>
    ${parties ? `<div class="mb-3 pb-3" style="border-bottom:1px solid var(--color-border);">
      <div class="fs-12 text-muted text-uppercase mb-1" style="letter-spacing:.06em;">Parties</div>
      <div class="fw-600">${escapeHtml(parties)}</div>
    </div>` : ''}
    ${section('Purpose', brief.purpose)}
    ${section('Executive Summary', brief.executive_summary)}
    ${section('Obligations Summary', brief.obligations_summary)}
    ${section('Important Dates', brief.important_dates_summary)}
    ${section('Financial Summary', brief.financial_summary)}
    ${section('Points to Review', brief.points_to_review_summary)}
    ${questions.length ? `
      <div class="mb-4">
        <div class="fs-12 fw-600 text-muted text-uppercase mb-2" style="letter-spacing:.06em;">Recommended Questions for Lawyer</div>
        <ul style="list-style:none; padding:0; display:flex; flex-direction:column; gap:6px;">
          ${questions.map((q, i) => `<li style="font-size:13px;"><span class="fw-600 text-primary">${i+1}.</span> ${escapeHtml(q)}</li>`).join('')}
        </ul>
      </div>` : ''}
    <div class="alert alert-warning mb-0" style="font-size:12px;">
      <i class="bi bi-exclamation-triangle"></i> ${escapeHtml(brief.disclaimer || 'This brief is for informational purposes only.')}
    </div>`;
}

// ============================================================
// TTS - LISTEN TO SUMMARY
// ============================================================

function listenToSummary() {
  if (!analysisData) return;
  const text = analysisData.summary || '';
  speakText(text);
}

// ============================================================
// DELETE DOCUMENT
// ============================================================

function deleteDoc() {
  if (!confirm('Delete this document and all its analysis? This cannot be undone.')) return;
  fetch(`/api/documents/${DOC_ID}`, { method: 'DELETE' })
    .then(r => r.json())
    .then(d => {
      if (d.error) { showToast('error', d.error); return; }
      showToast('success', 'Document deleted.');
      setTimeout(() => location.href = '/dashboard', 800);
    })
    .catch(() => showToast('error', 'Delete failed.'));
}
