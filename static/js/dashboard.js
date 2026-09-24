/**
 * dashboard.js — Dashboard statistics loading
 */

function loadDashboardStats(docId) {
  if (!docId) return;

  fetch(`/api/documents/${docId}/analysis`)
    .then(r => r.json())
    .then(data => {
      if (data.error) return; // Analysis not run yet

      // Update stat numbers
      const clauses = (data.important_clauses || []).length;
      const points = (data.points_to_review || []).length;
      const dates = (data.important_dates || []).length;
      const financial = (data.financial_terms || []).length;

      const animateNumber = (el, target) => {
        if (!el) return;
        let current = 0;
        const step = Math.ceil(target / 20);
        const interval = setInterval(() => {
          current = Math.min(current + step, target);
          el.textContent = current;
          if (current >= target) clearInterval(interval);
        }, 40);
      };

      animateNumber(document.getElementById('statClauses'), clauses);
      animateNumber(document.getElementById('statPoints'), points);
      animateNumber(document.getElementById('statDates'), dates);
      animateNumber(document.getElementById('statFinancial'), financial);
    })
    .catch(() => {});
}
