/**
 * compare.js — Document comparison page logic
 */

let modeUpload = true;
let fileASelected = false;
let fileBSelected = false;

function setMode(mode) {
  modeUpload = mode === 'upload';
  document.getElementById('uploadMode').style.display = modeUpload ? 'block' : 'none';
  document.getElementById('savedMode').style.display = modeUpload ? 'none' : 'block';
  document.getElementById('modeUploadBtn').className = modeUpload ? 'btn btn-primary btn-sm flex-fill' : 'btn btn-ghost btn-sm flex-fill';
  document.getElementById('modeSavedBtn').className = modeUpload ? 'btn btn-ghost btn-sm flex-fill' : 'btn btn-primary btn-sm flex-fill';
}

function previewFile(side) {
  const input = document.getElementById(`file${side}`);
  const nameEl = document.getElementById(`file${side}Name`);
  const zone = document.getElementById(`uploadZone${side}`);
  const file = input.files[0];
  if (!file) return;

  const ext = file.name.split('.').pop().toLowerCase();
  if (!['pdf', 'docx', 'txt'].includes(ext)) {
    showToast('error', 'Please upload a PDF, DOCX, or TXT file.');
    return;
  }

  if (nameEl) nameEl.textContent = file.name;
  if (zone) zone.style.borderColor = side === 'A' ? 'var(--color-primary)' : 'var(--color-accent)';

  if (side === 'A') fileASelected = true;
  else fileBSelected = true;

  const btn = document.getElementById('compareUploadBtn');
  if (btn) btn.disabled = !(fileASelected && fileBSelected);
}

function compareUploaded() {
  const fileA = document.getElementById('fileA')?.files[0];
  const fileB = document.getElementById('fileB')?.files[0];
  if (!fileA || !fileB) { showToast('error', 'Please select both documents.'); return; }

  showLoading('Uploading documents...');

  const formData = new FormData();
  formData.append('file1', fileA);
  formData.append('file2', fileB);

  fetch('/api/compare/upload', { method: 'POST', body: formData })
    .then(r => r.json())
    .then(data => {
      if (data.error) { showLoading(null); showToast('error', data.error); return; }
      // file1 maps to document_1 (A), file2 maps to document_2 (B)
      const nameA = data.document_1.name || fileA.name;
      const nameB = data.document_2.name || fileB.name;
      return runComparison(data.document_1.id, data.document_2.id, nameA, nameB);
    })
    .catch(err => { showLoading(null); showToast('error', 'Upload failed. Please try again.'); });
}

function compareSaved() {
  const docAId = document.getElementById('savedDocA')?.value;
  const docBId = document.getElementById('savedDocB')?.value;

  if (!docAId || !docBId) { showToast('error', 'Please select both documents.'); return; }
  if (docAId === docBId) { showToast('error', 'Please select two different documents.'); return; }

  // Get names from select options
  const selA = document.getElementById('savedDocA');
  const selB = document.getElementById('savedDocB');
  const nameA = selA.options[selA.selectedIndex].text;
  const nameB = selB.options[selB.selectedIndex].text;

  showLoading('Comparing documents...');
  runComparison(docAId, docBId, nameA, nameB);
}

function runComparison(docAId, docBId, nameA, nameB) {
  const mode = localStorage.getItem('legalai_mode') || 'auto';
  fetch('/api/compare', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ document_1_id: docAId, document_2_id: docBId, mode }),
  })
  .then(r => r.json())
  .then(data => {
    showLoading(null);
    if (data.error) { showToast('error', data.error); return; }
    renderComparison(data, nameA, nameB);
  })
  .catch(err => {
    showLoading(null);
    showToast('error', 'Comparison failed. Please try again.');
  });
}

function showLoading(message) {
  const initState = document.getElementById('compareInitState');
  const loadState = document.getElementById('compareLoadState');
  const results = document.getElementById('compareResults');

  if (message) {
    if (initState) initState.style.display = 'none';
    if (loadState) loadState.style.display = 'block';
    if (results) results.style.display = 'none';
  } else {
    if (loadState) loadState.style.display = 'none';
  }
}

function renderComparison(data, nameA, nameB) {
  const results = document.getElementById('compareResults');
  const initState = document.getElementById('compareInitState');
  if (results) results.style.display = 'block';
  if (initState) initState.style.display = 'none';

  const result = data.result || {};
  const activeMode = localStorage.getItem('legalai_mode') || 'auto';

  // Header & Mode Badge — respect active mode for badge display
  const docsLabel = document.getElementById('compDocsLabel');
  if (docsLabel) {
    let badgeClass = 'badge-secondary';
    let badgeText = result.processing_badge || '⚫ Offline Document Comparison';

    if (activeMode === 'offline') {
      // Override: never show "Gemini AI" when offline mode is active
      badgeText = '⚫ Offline Document Comparison';
      badgeClass = 'badge-secondary';
    } else if (result.mode === 'gemini') {
      badgeClass = 'badge-success';
      badgeText = result.processing_badge || '🟢 Gemini AI Comparison';
    } else if (result.mode === 'offline_fallback') {
      badgeClass = 'badge-warning';
    }

    docsLabel.innerHTML = `${escapeHtml(nameA || data.document_1)} vs ${escapeHtml(nameB || data.document_2)} <span class="badge ${badgeClass} ms-2 comp-mode-badge">${escapeHtml(badgeText)}</span>`;
  }

  // Similarity note
  const simPct = result.similarity_pct;
  const summaryEl = document.getElementById('compSummary');
  if (summaryEl) {
    let summaryText = result.summary || 'Comparison complete.';
    if (simPct !== undefined && simPct !== null) {
      summaryText += ` (Textual similarity: ${simPct}% — this is a text-match metric, not a legal quality score.)`;
    }
    summaryEl.textContent = summaryText;
  }

  // Column headers — always A for file1/docAId, B for file2/docBId
  const colA = document.getElementById('colHeaderA');
  const colB = document.getElementById('colHeaderB');
  if (colA) colA.textContent = nameA || 'Document A';
  if (colB) colB.textContent = nameB || 'Document B';

  // Differences table
  const differences = result.differences || [];
  const diffCount = document.getElementById('diffCount');
  if (diffCount) diffCount.textContent = `${differences.length} difference${differences.length !== 1 ? 's' : ''}`;

  const tbody = document.getElementById('diffTableBody');
  if (tbody) {
    if (differences.length) {
      tbody.innerHTML = differences.map(diff => {
        const catName = escapeHtml(diff.category || 'Difference');
        // "Factual Diff" badge — dark text for readability
        const typeBadge = `<span class="badge badge-factual-diff">Factual Diff</span>`;
        return `<tr>
          <td>
            <div class="fw-600 fs-13">${catName}</div>
            ${diff.note ? `<div class="fs-11 text-muted mt-1">${escapeHtml(diff.note)}</div>` : ''}
          </td>
          <td class="fs-13 comp-cell-wrap">${escapeHtml(diff.document_a || '—')}</td>
          <td class="fs-13 diff-changed comp-cell-wrap">${escapeHtml(diff.document_b || '—')}</td>
          <td>${typeBadge}</td>
        </tr>`;
      }).join('');
    } else {
      tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted fs-13 py-4">No differences found.</td></tr>';
    }
  }

  // Present only in Doc A = lines removed from B perspective (lines_a NOT in lines_b)
  // Present only in Doc B = lines added in B perspective (lines_b NOT in lines_a)
  // Backend: removed_in_b = lines only in A; added_in_b = lines only in B
  const onlyInAEl = document.getElementById('onlyInDocA');
  const onlyInBEl = document.getElementById('onlyInDocB');
  const onlyInATitle = document.getElementById('onlyInDocATitle');
  const onlyInBTitle = document.getElementById('onlyInDocBTitle');

  if (onlyInATitle) onlyInATitle.textContent = `Present only in ${nameA || 'Document A'}`;
  if (onlyInBTitle) onlyInBTitle.textContent = `Present only in ${nameB || 'Document B'}`;

  // removed_in_b = only in A; added_in_b = only in B
  const onlyInA = result.removed_in_b || [];
  const onlyInB = result.added_in_b || [];

  if (onlyInAEl) {
    onlyInAEl.innerHTML = onlyInA.length
      ? onlyInA.map(a => `<div class="comp-only-item"><i class="bi bi-file-earmark text-primary flex-shrink-0 mt-1"></i><span>${escapeHtml(a)}</span></div>`).join('')
      : '<span class="text-muted fs-13">None identified</span>';
  }
  if (onlyInBEl) {
    onlyInBEl.innerHTML = onlyInB.length
      ? onlyInB.map(b => `<div class="comp-only-item"><i class="bi bi-file-earmark text-accent flex-shrink-0 mt-1"></i><span>${escapeHtml(b)}</span></div>`).join('')
      : '<span class="text-muted fs-13">None identified</span>';
  }

  // Recommendation
  const rec = result.recommendation;
  const recEl = document.getElementById('compRecommendation');
  const recText = document.getElementById('compRecommendationText');
  if (recEl && rec) {
    recEl.style.display = 'block';
    if (recText) recText.textContent = rec;
  }

  // Store for PDF export
  window._lastComparisonData = { result, nameA: nameA || data.document_1, nameB: nameB || data.document_2 };
}

function exportComparisonPdf() {
  const comp = window._lastComparisonData;
  if (!comp || !comp.result) {
    if (typeof showToast === 'function') showToast('warning', 'Please perform a comparison first.');
    return;
  }

  if (typeof showToast === 'function') showToast('info', 'Generating comparison PDF report...');

  fetch('/api/compare/pdf', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      result: comp.result,
      name_a: comp.nameA || 'Document A',
      name_b: comp.nameB || 'Document B'
    })
  })
  .then(res => {
    if (!res.ok) throw new Error('PDF export failed');
    return res.blob();
  })
  .then(blob => {
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `Comparison_Report_${(comp.nameA || 'DocA').replace(/[^a-zA-Z0-9]/g, '_')}_vs_${(comp.nameB || 'DocB').replace(/[^a-zA-Z0-9]/g, '_')}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
    if (typeof showToast === 'function') showToast('success', 'Comparison PDF downloaded successfully!');
  })
  .catch(err => {
    console.error(err);
    if (typeof showToast === 'function') showToast('error', 'Could not generate comparison PDF.');
  });
}

