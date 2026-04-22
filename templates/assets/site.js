const dataEl = document.getElementById('script-data');
const searchEl = document.getElementById('search');
const tagEl = document.getElementById('tag-filter');
const emptyEl = document.getElementById('empty-state');
const cards = Array.from(document.querySelectorAll('[data-script-card]'));

if (dataEl && searchEl && tagEl) {
  const scripts = JSON.parse(dataEl.textContent || '[]');
  const tags = [...new Set(scripts.flatMap((script) => [...(script.tags || []), ...(script.platforms || [])]))].sort();
  for (const tag of tags) {
    const option = document.createElement('option');
    option.value = tag;
    option.textContent = tag;
    tagEl.appendChild(option);
  }

  const applyFilters = () => {
    const query = searchEl.value.trim().toLowerCase();
    const tag = tagEl.value;
    let visible = 0;
    for (const card of cards) {
      const matchesQuery = !query || card.dataset.search.includes(query);
      const matchesTag = !tag || card.dataset.tags.split(' ').includes(tag);
      const show = matchesQuery && matchesTag;
      card.hidden = !show;
      if (show) visible += 1;
    }
    emptyEl.hidden = visible !== 0;
  };

  searchEl.addEventListener('input', applyFilters);
  tagEl.addEventListener('change', applyFilters);
}

const copyButtons = Array.from(document.querySelectorAll('[data-copy-button]'));
for (const button of copyButtons) {
  button.addEventListener('click', async () => {
    const targetId = button.getAttribute('data-copy-target');
    if (!targetId) return;
    const source = document.getElementById(targetId);
    if (!source) return;
    const text = source.textContent || '';
    if (!text.trim()) return;
    try {
      await navigator.clipboard.writeText(text);
      const original = button.textContent;
      button.textContent = 'Copied';
      setTimeout(() => {
        button.textContent = original;
      }, 1400);
    } catch (_error) {
      button.textContent = 'Copy failed';
    }
  });
}

const activeTabCopyButton = document.querySelector('[data-copy-active-tab]');
if (activeTabCopyButton) {
  activeTabCopyButton.addEventListener('click', async () => {
    const activeTab = document.querySelector('#downloadTabs .nav-link.active');
    if (!activeTab) return;
    const target = activeTab.getAttribute('data-bs-target');
    if (!target) return;
    const source = document.querySelector(`${target} code`);
    if (!source) return;
    const text = source.textContent || '';
    if (!text.trim()) return;
    try {
      await navigator.clipboard.writeText(text);
      const original = activeTabCopyButton.textContent;
      activeTabCopyButton.textContent = 'Copied';
      setTimeout(() => {
        activeTabCopyButton.textContent = original;
      }, 1400);
    } catch (_error) {
      activeTabCopyButton.textContent = 'Copy failed';
    }
  });
}

if (window.hljs) {
  const blocks = document.querySelectorAll('pre code');
  for (const block of blocks) {
    window.hljs.highlightElement(block);
  }
}
