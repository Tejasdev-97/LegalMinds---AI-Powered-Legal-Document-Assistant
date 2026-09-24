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
      return runComparison(data.document_1.id, data.document_2.id, fileA.name, fileB.name);
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

  // Header & Mode Badge
  const docsLabel = document.getElementById('compDocsLabel');
  if (docsLabel) {
    let badgeClass = 'badge-secondary';
    let badgeText = result.processing_badge || (result.mode === 'gemini' ? '🟢 Gemini AI' : '⚫ Offline Document Comparison');
    if (result.mode === 'gemini') badgeClass = 'badge-success';
    else if (result.mode === 'offline_fallback') badgeClass = 'badge-warning';

    docsLabel.innerHTML = `${escapeHtml(nameA || data.document_1)} vs ${escapeHtml(nameB || data.document_2)} <span class="badge ${badgeClass} ms-2" style="font-size:11px;">${escapeHtml(badgeText)}</span>`;
  }

  // Summary
  const summaryEl = document.getElementById('compSummary');
  if (summaryEl) summaryEl.textContent = result.summary || 'Comparison complete.';

  // Column headers
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
        const typeBadge = `<span class="badge badge-secondary" style="font-size:10px;">Factual Diff</span>`;
        return `<tr>
          <td>
            <div class="fw-600 fs-13">${catName}</div>
            ${diff.note ? `<div class="fs-11 text-muted mt-1">${escapeHtml(diff.note)}</div>` : ''}
          </td>
          <td class="fs-13">${escapeHtml(diff.document_a || '—')}</td>
          <td class="fs-13 diff-changed">${escapeHtml(diff.document_b || '—')}</td>
          <td>${typeBadge}</td>
        </tr>`;
      }).join('');
    } else {
      tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted fs-13 py-4">No differences found.</td></tr>';
    }
  }

  // Added / Removed
  const addedEl = document.getElementById('addedInB');
  const removedEl = document.getElementById('removedInB');
  const added = result.added_in_b || [];
  const removed = result.removed_in_b || [];

  if (addedEl) {
    addedEl.innerHTML = added.length
      ? added.map(a => `<div class="d-flex gap-2 align-items-start fs-13 mb-2"><i class="bi bi-plus-circle-fill text-success flex-shrink-0 mt-1"></i><span>${escapeHtml(a)}</span></div>`).join('')
      : '<span class="text-muted fs-13">None identified</span>';
  }
  if (removedEl) {
    removedEl.innerHTML = removed.length
      ? removed.map(r => `<div class="d-flex gap-2 align-items-start fs-13 mb-2"><i class="bi bi-dash-circle-fill text-danger flex-shrink-0 mt-1"></i><span>${escapeHtml(r)}</span></div>`).join('')
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
}
