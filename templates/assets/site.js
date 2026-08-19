const themeStorageKey = 'toolbox-theme';
const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
const themeOptions = Array.from(document.querySelectorAll('[data-theme-value]'));
const themeLabel = document.querySelector('[data-theme-label]');
const themeIcon = document.querySelector('[data-theme-icon]');
const themeMeta = document.querySelector('meta[name="theme-color"]');

const getThemePreference = () => {
  const savedTheme = localStorage.getItem(themeStorageKey);
  return savedTheme === 'light' || savedTheme === 'dark' ? savedTheme : 'system';
};

const applyTheme = (preference) => {
  const resolvedTheme = preference === 'system'
    ? (systemTheme.matches ? 'dark' : 'light')
    : preference;
  const labels = { light: 'Light', dark: 'Dark', system: 'System' };
  const icons = { light: 'bi-sun', dark: 'bi-moon-stars', system: 'bi-circle-half' };

  document.documentElement.dataset.bsTheme = resolvedTheme;
  document.documentElement.dataset.themePreference = preference;
  if (themeLabel) themeLabel.textContent = labels[preference];
  if (themeIcon) themeIcon.className = `bi ${icons[preference]} me-1`;
  if (themeMeta) themeMeta.content = resolvedTheme === 'dark' ? '#101214' : '#ffffff';

  for (const option of themeOptions) {
    const isActive = option.dataset.themeValue === preference;
    option.classList.toggle('active', isActive);
    option.setAttribute('aria-pressed', String(isActive));
  }
};

for (const option of themeOptions) {
  option.addEventListener('click', () => {
    const preference = option.dataset.themeValue;
    if (preference === 'system') {
      localStorage.removeItem(themeStorageKey);
    } else {
      localStorage.setItem(themeStorageKey, preference);
    }
    applyTheme(preference);
  });
}

systemTheme.addEventListener('change', () => {
  if (getThemePreference() === 'system') applyTheme('system');
});

applyTheme(getThemePreference());

const isAppleMobileDevice = /iPad|iPhone|iPod/.test(navigator.userAgent)
  || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

const desktopDownload = document.querySelector('[data-desktop-download]');
if (desktopDownload && isAppleMobileDevice) {
  const label = desktopDownload.querySelector('[data-desktop-download-label]');
  const icon = desktopDownload.querySelector('i');
  if (label) label.textContent = 'Share';
  if (icon) icon.className = 'bi bi-box-arrow-up me-2';
  desktopDownload.setAttribute('aria-label', 'Share this script to the Apple Shortcut');
  desktopDownload.href = '#';

  desktopDownload.addEventListener('click', async (event) => {
    event.preventDefault();
    if (!navigator.share) {
      window.alert('Sharing is not available in this browser. Open this page in Safari to share it.');
      return;
    }
    try {
      await navigator.share({
        url: desktopDownload.dataset.shareUrl,
      });
    } catch (error) {
      if (error.name !== 'AbortError') console.error('Unable to open the share sheet.', error);
    }
  });
}

const detectedOsBadge = document.querySelector('[data-detected-os]');
const osName = (() => {
  const userAgentDataPlatform = navigator.userAgentData && navigator.userAgentData.platform
    ? navigator.userAgentData.platform
    : '';
  const platform = `${userAgentDataPlatform} ${navigator.platform || ''} ${navigator.userAgent || ''}`.toLowerCase();
  if (platform.includes('win')) return 'windows';
  if (platform.includes('mac')) return 'macos';
  if (platform.includes('linux') || platform.includes('x11')) return 'linux';
  return '';
})();
const osLabels = { macos: 'macOS detected', linux: 'Linux detected', windows: 'Windows detected' };
const detectedOsTab = osName ? document.querySelector(`[data-os-tab="${osName}"]`) : null;
if (detectedOsBadge) detectedOsBadge.textContent = osLabels[osName] || 'Choose your OS';
if (detectedOsTab && window.bootstrap && window.bootstrap.Tab) {
  window.bootstrap.Tab.getOrCreateInstance(detectedOsTab).show();
}

const installerDownload = document.querySelector('[data-installer-download]');
if (installerDownload && osName) {
  const title = installerDownload.querySelector('[data-installer-download-title]');
  const detail = installerDownload.querySelector('[data-installer-download-detail]');
  const icon = installerDownload.querySelector('[data-installer-download-icon]');

  if (osName === 'windows') {
    if (title) title.textContent = 'Download Installer';
    if (detail) detail.textContent = 'PowerShell | Coming soon';
    if (icon) icon.className = 'bi bi-clock-history fs-4';
    installerDownload.removeAttribute('href');
    installerDownload.removeAttribute('download');
    installerDownload.classList.add('disabled');
    installerDownload.setAttribute('aria-disabled', 'true');
    installerDownload.setAttribute('aria-label', 'Windows PowerShell installer is not available yet');
  } else {
    const platformLabel = osName === 'macos' ? 'MacOS' : 'Linux';
    if (title) title.textContent = 'Download Installer';
    if (detail) detail.textContent = `install.sh | ${platformLabel}`;
    installerDownload.setAttribute('aria-label', `Download the ${platformLabel} shell installer, install.sh`);
  }
}

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

const activeTabCopyButtons = Array.from(document.querySelectorAll('[data-copy-active-tab]'));
for (const activeTabCopyButton of activeTabCopyButtons) {
  activeTabCopyButton.addEventListener('click', async () => {
    const tabListSelector = activeTabCopyButton.dataset.tabList || '#downloadTabs';
    const activeTab = document.querySelector(`${tabListSelector} .nav-link.active`);
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
