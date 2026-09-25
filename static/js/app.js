/**
 * app.js — Global utilities for LegalMinds
 * Sidebar toggle, toast notifications, theme switching, local translations, language settings, TTS
 */

// ---- Theme Switching (Light / Dark) ----
function applyTheme(theme) {
  const currentTheme = theme || localStorage.getItem('legalai_theme') || 'light';
  document.documentElement.setAttribute('data-theme', currentTheme);
  localStorage.setItem('legalai_theme', currentTheme);

  const icon = document.getElementById('themeToggleIcon');
  if (icon) {
    icon.className = currentTheme === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-stars';
  }
}

function toggleTheme() {
  const current = localStorage.getItem('legalai_theme') || 'light';
  const nextTheme = current === 'dark' ? 'light' : 'dark';
  applyTheme(nextTheme);
  showToast('info', `Switched to ${nextTheme.toUpperCase()} mode`);
}

// ---- Sidebar Toggle & Initialization ----
document.addEventListener('DOMContentLoaded', () => {
  applyTheme();

  const toggle = document.getElementById('sidebarToggle');
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebarBackdrop');

  if (toggle && sidebar) {
    toggle.addEventListener('click', () => {
      sidebar.classList.toggle('open');
      if (backdrop) backdrop.classList.toggle('show');
    });
    if (backdrop) {
      backdrop.addEventListener('click', () => {
        sidebar.classList.remove('open');
        backdrop.classList.remove('show');
      });
    }
  }

  // Language selector (global)
  const langSelect = document.getElementById('globalLangSelect');
  if (langSelect) {
    const saved = localStorage.getItem('legalai_language') || 'en';
    langSelect.value = saved;
    if (typeof applyLocalTranslations === 'function') {
      applyLocalTranslations(saved);
    }
    // Sync backend session language on init
    fetch('/api/set-language', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language: saved }),
    }).catch(() => {});

    langSelect.addEventListener('change', () => {
      const selected = langSelect.value;
      localStorage.setItem('legalai_language', selected);
      if (typeof applyLocalTranslations === 'function') {
        applyLocalTranslations(selected);
      }
      fetch('/api/set-language', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language: selected }),
      }).catch(() => {});
    });
  }
});

// ---- Toast Notifications ----
function showToast(type, message, duration = 4000) {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const icons = {
    success: '<i class="bi bi-check-circle-fill" style="color:var(--color-success);"></i>',
    error: '<i class="bi bi-exclamation-circle-fill" style="color:var(--color-danger);"></i>',
    info: '<i class="bi bi-info-circle-fill" style="color:var(--color-primary);"></i>',
    warning: '<i class="bi bi-exclamation-triangle-fill" style="color:var(--color-gold);"></i>',
  };

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `${icons[type] || icons.info} <span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 350);
  }, duration);
}

// ---- HTML Escaping ----
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// ---- Tab Switching ----
function switchTab(tabName, btn) {
  // Hide all tab contents
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

  // Show selected
  const target = document.getElementById(`tab-${tabName}`);
  if (target) target.classList.add('active');
  if (btn) btn.classList.add('active');
}

// ---- Text-to-Speech ----
function speakText(text, language) {
  const lang = language || localStorage.getItem('legalai_language') || 'en';
  const ttsEnabled = JSON.parse(localStorage.getItem('legalai_settings') || '{}').tts !== false;

  if (!ttsEnabled) return;

  // Try Google TTS endpoint first
  fetch('/api/speak', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, language: lang }),
  })
  .then(r => r.json())
  .then(data => {
    if (data.use_browser_tts || !data.audio_base64) {
      browserSpeak(text, lang);
    } else {
      // Play audio from base64
      const audio = new Audio(`data:audio/mp3;base64,${data.audio_base64}`);
      audio.play().catch(() => browserSpeak(text, lang));
    }
  })
  .catch(() => browserSpeak(text, lang));
}

function browserSpeak(text, language) {
  if (!window.speechSynthesis) {
    showToast('info', 'Text-to-speech is not supported by this browser.');
    return;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text.slice(0, 3000));

  const langMap = {
    en: 'en-US', hi: 'hi-IN', kn: 'kn-IN', mr: 'mr-IN', ta: 'ta-IN', te: 'te-IN'
  };
  utterance.lang = langMap[language] || 'en-US';
  utterance.rate = 0.9;
  utterance.pitch = 1;
  window.speechSynthesis.speak(utterance);
}

// ---- Translation helper ----
async function translateText(text, targetLang) {
  if (!targetLang || targetLang === 'en') return text;
  try {
    const r = await fetch('/api/translate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, target_language: targetLang }),
    });
    const d = await r.json();
    if (d.success) return d.translated;
    return text; // fallback to original
  } catch {
    return text;
  }
}

// ---- Format date ----
function formatDate(isoString) {
  if (!isoString) return '—';
  try {
    return new Date(isoString).toLocaleDateString('en-IN', {
      year: 'numeric', month: 'short', day: 'numeric'
    });
  } catch {
    return isoString.slice(0, 10);
  }
}

// ---- Gemini AI Status Badge & Mode Management ----
function changeOperatingMode(newMode) {
  localStorage.setItem('legalai_mode', newMode);
  fetch('/api/set-mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: newMode }),
  })
  .then(r => r.json())
  .then(d => {
    showToast('info', d.message || `Mode updated to ${newMode.toUpperCase()}`);
    loadAiStatus();
  })
  .catch(() => showToast('error', 'Could not set operating mode.'));
}

function updateAiStatusBadge(data) {
  const dot  = document.getElementById('aiStatusDot');
  const text = document.getElementById('aiStatusText');
  const offlineBanner = document.getElementById('globalOfflineBanner');
  const modeSelect = document.getElementById('globalModeSelect');

  const currentMode = data.active_mode || localStorage.getItem('legalai_mode') || 'auto';
  if (modeSelect) modeSelect.value = currentMode;

  if (dot && text) {
    dot.className = 'ai-status-dot';

    // Offline mode takes priority — never show Gemini Active when explicitly offline
    if (currentMode === 'offline') {
      dot.classList.add('red');
      text.textContent = 'Offline Mode — Gemini Disabled';
      text.style.color = 'var(--color-danger)';
      if (offlineBanner) offlineBanner.style.display = 'none';
    } else if (data.status === 'active') {
      dot.classList.add('green');
      text.textContent = data.message || 'Gemini AI Active';
      text.style.color = 'var(--color-success)';
      if (offlineBanner) offlineBanner.style.display = 'none';
    } else if (data.status === 'limit_reached' || data.status === 'temp_unavailable') {
      dot.classList.add('orange');
      text.textContent = data.message || 'Gemini Limit Reached';
      text.style.color = 'var(--color-gold)';
      if (offlineBanner) {
        offlineBanner.style.display = 'flex';
        const bannerTextEl = document.getElementById('offlineBannerText');
        if (bannerTextEl) bannerTextEl.textContent = `🟠 OFFLINE — ${data.message || 'Gemini Limit Reached'}`;
      }
    } else {
      dot.classList.add('red');
      text.textContent = data.message || 'Gemini Not Configured';
      text.style.color = 'var(--color-danger)';
      if (offlineBanner) {
        offlineBanner.style.display = 'flex';
        const bannerTextEl = document.getElementById('offlineBannerText');
        if (bannerTextEl) bannerTextEl.textContent = `🔴 OFFLINE — ${data.message || 'Gemini unavailable'}`;
      }
    }
  }
}

async function loadAiStatus() {
  try {
    const r = await fetch('/api/key-status');
    const d = await r.json();
    updateAiStatusBadge(d);
  } catch {
    updateAiStatusBadge({ status: 'offline', message: 'Offline Demo Mode' });
  }
}

document.addEventListener('DOMContentLoaded', loadAiStatus);

// ---- Quick Key Modal ----
function openQuickKeyModal() {
  document.getElementById('quickKeyModalOverlay').style.display = 'block';
  document.getElementById('quickKeyModal').style.display = 'block';
  setTimeout(() => { const el = document.getElementById('quickGeminiKey'); if (el) el.focus(); }, 50);
}

function closeQuickKeyModal() {
  document.getElementById('quickKeyModalOverlay').style.display = 'none';
  document.getElementById('quickKeyModal').style.display = 'none';
}

async function quickTestKey() {
  const key = document.getElementById('quickGeminiKey').value.trim();
  const statusEl = document.getElementById('quickKeyStatus');
  if (!key) { statusEl.innerHTML = '<span style="color:var(--color-danger);">Enter a key first.</span>'; return; }
  statusEl.innerHTML = '<span style="color:var(--color-text-muted);">Testing…</span>';
  try {
    const r = await fetch('/api/test-gemini-key', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: key }),
    });
    const d = await r.json();
    if (d.valid) {
      statusEl.innerHTML = `<span style="color:var(--color-success);">✓ ${escapeHtml(d.message)}</span>`;
    } else {
      statusEl.innerHTML = `<span style="color:var(--color-danger);">✗ ${escapeHtml(d.message)}</span>`;
    }
  } catch {
    statusEl.innerHTML = '<span style="color:var(--color-danger);">Could not reach server.</span>';
  }
}

async function quickSaveKeys() {
  const key = document.getElementById('quickGeminiKey').value.trim();
  const statusEl = document.getElementById('quickKeyStatus');
  if (!key) { statusEl.innerHTML = '<span style="color:var(--color-danger);">Please enter a Gemini API key.</span>'; return; }
  try {
    const r = await fetch('/api/set-keys', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gemini_api_key: key }),
    });
    const d = await r.json();
    const gs = d.gemini_status || {};
    if (gs.valid) {
      statusEl.innerHTML = `<span style="color:var(--color-success);">✓ ${escapeHtml(gs.message || 'Key saved!')}</span>`;
      updateAiStatusBadge({ status: 'active', message: gs.message });
      showToast('success', 'Gemini API key saved! AI is now active.');
      setTimeout(closeQuickKeyModal, 1200);
    } else {
      statusEl.innerHTML = `<span style="color:var(--color-danger);">✗ Saved but test failed: ${escapeHtml(gs.message)}</span>`;
      updateAiStatusBadge({ status: 'offline', message: gs.message });
    }
  } catch {
    statusEl.innerHTML = '<span style="color:var(--color-danger);">Error saving key.</span>';
  }
}

async function quickClearKeys() {
  const statusEl = document.getElementById('quickKeyStatus');
  try {
    const r = await fetch('/api/clear-keys', { method: 'POST' });
    const d = await r.json();
    document.getElementById('quickGeminiKey').value = '';
    statusEl.innerHTML = '<span style="color:var(--color-text-muted);">Custom key cleared.</span>';
    const gs = d.gemini_status || {};
    updateAiStatusBadge({ status: gs.valid ? 'active' : 'offline', message: gs.message || 'Offline Demo Mode' });
    showToast('info', 'Custom key cleared.');
  } catch {
    statusEl.innerHTML = '<span style="color:var(--color-danger);">Error clearing key.</span>';
  }
}

document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeQuickKeyModal(); });
