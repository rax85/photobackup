import PhotoSwipeLightbox from './photoswipe-lightbox.esm.js';

// ==========================================================================
// Application State & Services
// ==========================================================================

const AppState = {
    allMedia: [],          // Raw array from API
    filteredMedia: [],     // Current filtered array
    settings: {},
    activeType: 'all',     // 'all' | 'image' | 'video'
    searchQuery: '',
    lightbox: null,
    scrollObserver: null,
};

// --------------------------------------------------------------------------
// Toast Notification Manager
// --------------------------------------------------------------------------
const Toast = {
    show(message, type = 'info', duration = 3500) {
        const container = document.getElementById('toastContainer');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `<span>${message}</span>`;
        container.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(20px)';
            toast.style.transition = 'all 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }
};

// --------------------------------------------------------------------------
// Theme Manager
// --------------------------------------------------------------------------
const ThemeManager = {
    init() {
        const savedTheme = localStorage.getItem('photobackup_theme');
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        const theme = savedTheme || (prefersDark ? 'dark' : 'light');
        this.setTheme(theme);

        const toggleBtn = document.getElementById('themeToggle');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => {
                const current = document.documentElement.dataset.theme;
                const next = current === 'dark' ? 'light' : 'dark';
                this.setTheme(next);
            });
        }
    },

    setTheme(theme) {
        document.documentElement.dataset.theme = theme;
        localStorage.setItem('photobackup_theme', theme);
        const iconDark = document.querySelector('.theme-icon-dark');
        const iconLight = document.querySelector('.theme-icon-light');
        if (iconDark && iconLight) {
            if (theme === 'dark') {
                iconDark.style.display = 'block';
                iconLight.style.display = 'none';
            } else {
                iconDark.style.display = 'none';
                iconLight.style.display = 'block';
            }
        }
    }
};

// --------------------------------------------------------------------------
// Statistics & Metadata Helpers
// --------------------------------------------------------------------------
function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

async function updateStatsBar() {
    const statsEl = document.getElementById('statsCount');
    if (!statsEl) return;

    try {
        const res = await fetch('/api/stats');
        if (res.ok) {
            const data = await res.json();
            statsEl.textContent = `${data.total_count} items (${data.image_count} photos, ${data.video_count} videos) · ${formatBytes(data.total_size_bytes)}`;
        }
    } catch {
        statsEl.textContent = `${AppState.filteredMedia.length} items`;
    }
}

// --------------------------------------------------------------------------
// Gallery Grouping & Rendering
// --------------------------------------------------------------------------
function groupMediaByMonthYear(items) {
    const groups = new Map();
    items.forEach(item => {
        let monthYearKey = 'Unknown Date';
        if (item.original_creation_date) {
            const date = new Date(item.original_creation_date * 1000);
            monthYearKey = date.toLocaleString('default', { month: 'long', year: 'numeric' });
        }
        if (!groups.has(monthYearKey)) {
            groups.set(monthYearKey, []);
        }
        groups.get(monthYearKey).push(item);
    });
    return groups;
}

function renderGallery(items) {
    const galleryGrid = document.getElementById('gallery-grid');
    if (!galleryGrid) return;

    if (!items || items.length === 0) {
        galleryGrid.innerHTML = `
            <div class="empty-state">
                <svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <rect x="3" y="3" width="18" height="18" rx="4" ry="4"></rect>
                    <circle cx="8.5" cy="8.5" r="1.5"></circle>
                    <polyline points="21 15 16 10 5 21"></polyline>
                </svg>
                <h3>No media found</h3>
                <p>Try searching for another keyword, date, or location, or upload new files.</p>
            </div>
        `;
        renderTimelineSidebar(new Map());
        return;
    }

    const groupedMedia = groupMediaByMonthYear(items);
    galleryGrid.innerHTML = '';

    for (const [monthYear, itemsInGroup] of groupedMedia) {
        const sectionId = `section-${monthYear.replace(/[^a-zA-Z0-9-_]/g, '-').toLowerCase()}`;
        const monthSection = document.createElement('section');
        monthSection.className = 'month-section';
        monthSection.id = sectionId;

        const header = document.createElement('h2');
        header.className = 'month-year-divider-header';
        header.textContent = monthYear;
        monthSection.appendChild(header);

        const gridDiv = document.createElement('div');
        gridDiv.className = 'photo-items-grid';

        itemsInGroup.forEach(item => {
            const isVideo = item.mime_type && item.mime_type.startsWith('video/');
            const card = document.createElement('div');
            card.className = 'gallery-item';

            const link = document.createElement('a');
            link.href = `/image/${item.sha256}`;
            link.dataset.sha256 = item.sha256;
            link.dataset.pswpWidth = item.width || 1920;
            link.dataset.pswpHeight = item.height || 1080;
            link.dataset.isVideo = isVideo ? 'true' : 'false';
            link.dataset.mimeType = item.mime_type || '';
            link.dataset.filename = item.filename || '';

            if (isVideo) {
                link.dataset.type = 'html';
            }

            // Thumbnail Image
            const img = document.createElement('img');
            img.src = `/thumbnail/${item.sha256}`;
            img.alt = item.filename || 'Media thumbnail';
            img.loading = 'lazy';
            link.appendChild(img);

            // Video indicator badge
            if (isVideo) {
                const videoBadge = document.createElement('div');
                videoBadge.className = 'video-indicator';
                videoBadge.innerHTML = `
                    <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                    <span>VIDEO</span>
                `;
                card.appendChild(videoBadge);
            }

            // Hover metadata card
            const overlay = document.createElement('div');
            overlay.className = 'card-overlay';

            const title = document.createElement('span');
            title.className = 'card-title';
            title.textContent = item.filename;
            overlay.appendChild(title);

            const meta = document.createElement('div');
            meta.className = 'card-meta';
            if (item.city) {
                meta.innerHTML += `<span>📍 ${item.city}</span>`;
            }
            if (item.original_creation_date) {
                const d = new Date(item.original_creation_date * 1000);
                meta.innerHTML += `<span>📅 ${d.toLocaleDateString()}</span>`;
            }
            overlay.appendChild(meta);

            // Tags
            if (item.tags) {
                try {
                    const parsed = JSON.parse(item.tags);
                    if (Array.isArray(parsed) && parsed.length > 0) {
                        const tagsDiv = document.createElement('div');
                        tagsDiv.className = 'card-tags';
                        parsed.slice(0, 3).forEach(t => {
                            const tagPill = document.createElement('span');
                            tagPill.className = 'card-tag-pill';
                            tagPill.textContent = `#${Array.isArray(t) ? t[0] : t}`;
                            tagsDiv.appendChild(tagPill);
                        });
                        overlay.appendChild(tagsDiv);
                    }
                } catch { /* ignore */ }
            }

            card.appendChild(link);
            card.appendChild(overlay);
            gridDiv.appendChild(card);
        });

        monthSection.appendChild(gridDiv);
        galleryGrid.appendChild(monthSection);
    }

    renderTimelineSidebar(groupedMedia);
    setupScrollSpy();
    initPhotoSwipe();
}

// --------------------------------------------------------------------------
// Timeline Sidebar & ScrollSpy
// --------------------------------------------------------------------------
function renderTimelineSidebar(groupedMedia) {
    const container = document.getElementById('timelineLinks');
    if (!container) return;

    container.innerHTML = '';
    if (groupedMedia.size === 0) {
        container.innerHTML = '<p class="sidebar-empty" style="padding: 12px; color: var(--text-muted); font-size: 0.8rem;">No dates available</p>';
        return;
    }

    const ul = document.createElement('ul');
    ul.className = 'timeline-list';

    for (const [monthYear, items] of groupedMedia) {
        const sectionId = `section-${monthYear.replace(/[^a-zA-Z0-9-_]/g, '-').toLowerCase()}`;
        const li = document.createElement('li');
        const a = document.createElement('a');
        a.className = 'timeline-link';
        a.href = `#${sectionId}`;
        a.dataset.sectionId = sectionId;
        a.innerHTML = `
            <span>${monthYear}</span>
            <span class="timeline-count-badge">${items.length}</span>
        `;

        a.addEventListener('click', (e) => {
            e.preventDefault();
            const target = document.getElementById(sectionId);
            if (target) {
                target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                if (window.innerWidth < 768) {
                    document.getElementById('navigation-sidebar')?.classList.remove('expanded');
                }
            }
        });

        li.appendChild(a);
        ul.appendChild(li);
    }
    container.appendChild(ul);
}

function setupScrollSpy() {
    if (AppState.scrollObserver) {
        AppState.scrollObserver.disconnect();
    }

    const sections = document.querySelectorAll('.month-section');
    if (!sections.length) return;

    AppState.scrollObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const id = entry.target.id;
                document.querySelectorAll('.timeline-link').forEach(link => {
                    if (link.dataset.sectionId === id) {
                        link.classList.add('active');
                    } else {
                        link.classList.remove('active');
                    }
                });
            }
        });
    }, {
        rootMargin: '-80px 0px -70% 0px',
        threshold: 0.1
    });

    sections.forEach(s => AppState.scrollObserver.observe(s));
}

// --------------------------------------------------------------------------
// PhotoSwipe v5 Lightbox & Video Player
// --------------------------------------------------------------------------
function initPhotoSwipe() {
    if (AppState.lightbox) {
        AppState.lightbox.destroy();
    }

    AppState.lightbox = new PhotoSwipeLightbox({
        gallery: '#gallery-grid',
        children: '.gallery-item > a',
        pswpModule: () => import('./photoswipe.esm.js'),
        initialZoomLevel: 'fit',
        secondaryZoomLevel: 1.5,
        maxZoomLevel: 3,
        showHideAnimationType: 'zoom',
    });

    // Custom Slide Content for Videos
    AppState.lightbox.addFilter('itemData', (itemData) => {
        const el = itemData.element;
        if (el && el.dataset.isVideo === 'true') {
            itemData.type = 'html';
            itemData.isVideo = true;
            itemData.videoSrc = el.href;
            itemData.mimeType = el.dataset.mimeType || 'video/mp4';
            itemData.html = `
                <div class="pswp-video-container">
                    <video class="pswp-video-player pswp-prevent-swipe" controls autoplay playsinline preload="metadata">
                        <source src="${el.href}" type="${itemData.mimeType}">
                        Your browser does not support HTML5 video.
                    </video>
                </div>
            `;
        }
        return itemData;
    });

    // Prevent zooming video slides
    AppState.lightbox.addFilter('isContentZoomable', (isZoomable, content) => {
        if (content && content.data && content.data.isVideo) {
            return false;
        }
        return isZoomable;
    });

    // Pause videos when changing slide or closing
    AppState.lightbox.on('change', () => {
        const pswp = AppState.lightbox.pswp;
        if (!pswp) return;
        document.querySelectorAll('.pswp-video-player').forEach(video => {
            const currElement = pswp.currSlide?.content?.element;
            if (!currElement || !currElement.contains(video)) {
                video.pause();
            } else {
                video.play().catch(() => {});
            }
        });
    });

    AppState.lightbox.on('close', () => {
        document.querySelectorAll('.pswp-video-player').forEach(video => {
            video.pause();
            video.src = '';
        });
    });

    // Custom Caption Overlay
    AppState.lightbox.on('uiRegister', () => {
        AppState.lightbox.pswp.ui.registerElement({
            name: 'custom-caption',
            order: 9,
            isButton: false,
            appendTo: 'root',
            onInit: (el, pswp) => {
                pswp.on('change', () => {
                    const currSlide = pswp.currSlide;
                    if (!currSlide || !currSlide.data.element) {
                        el.innerHTML = '';
                        return;
                    }

                    const sha256 = currSlide.data.element.dataset.sha256;
                    const item = AppState.allMedia.find(m => m.sha256 === sha256);
                    if (item) {
                        let parts = [];
                        if (item.filename) parts.push(`<strong>${item.filename}</strong>`);
                        if (item.original_creation_date) {
                            const d = new Date(item.original_creation_date * 1000);
                            parts.push(`<span class="pswp-caption-date">📅 ${d.toLocaleDateString()}</span>`);
                        }
                        if (item.city) {
                            parts.push(`<span class="pswp-caption-location">📍 ${item.city}${item.country ? ', ' + item.country : ''}</span>`);
                        }
                        if (item.tags) {
                            try {
                                const parsed = JSON.parse(item.tags);
                                if (Array.isArray(parsed) && parsed.length > 0) {
                                    const tagStr = parsed.map(t => `#${Array.isArray(t) ? t[0] : t}`).join(' ');
                                    parts.push(`<span class="pswp-caption-tags">${tagStr}</span>`);
                                }
                            } catch { /* ignore */ }
                        }
                        el.innerHTML = `<div class="pswp-custom-caption">${parts.join(' · ')}</div>`;
                    } else {
                        el.innerHTML = '';
                    }
                });
            }
        });
    });

    AppState.lightbox.init();
}

// --------------------------------------------------------------------------
// API Fetching & Search Engine
// --------------------------------------------------------------------------
async function fetchMediaList() {
    const galleryGrid = document.getElementById('gallery-grid');
    if (galleryGrid) {
        galleryGrid.innerHTML = `
            <div class="photo-items-grid">
                ${Array(8).fill('<div class="skeleton-card"></div>').join('')}
            </div>
        `;
    }

    try {
        const res = await fetch('/list');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        AppState.allMedia = Object.entries(data).map(([sha256, info]) => ({
            sha256,
            ...info
        }));
        AppState.allMedia.sort((a, b) => (b.original_creation_date || 0) - (a.original_creation_date || 0));
        applyFilters();
        updateStatsBar();
    } catch (err) {
        console.error('Error loading media:', err);
        Toast.show('Error loading media library. Check server connection.', 'error');
        if (galleryGrid) {
            galleryGrid.innerHTML = '<p class="empty-state">Could not connect to media server.</p>';
        }
    }
}

function applyFilters() {
    let result = [...AppState.allMedia];

    // Filter by Media Type (All / Photos / Videos)
    if (AppState.activeType === 'image') {
        result = result.filter(item => item.mime_type && item.mime_type.startsWith('image/'));
    } else if (AppState.activeType === 'video') {
        result = result.filter(item => item.mime_type && item.mime_type.startsWith('video/'));
    }

    // Local Search Filter if active
    const q = AppState.searchQuery.trim().toLowerCase();
    if (q) {
        result = result.filter(item => {
            const filename = (item.filename || '').toLowerCase();
            const city = (item.city || '').toLowerCase();
            const country = (item.country || '').toLowerCase();
            const tags = (item.tags || '').toLowerCase();
            return filename.includes(q) || city.includes(q) || country.includes(q) || tags.includes(q);
        });
    }

    AppState.filteredMedia = result;
    renderGallery(result);
}

// --------------------------------------------------------------------------
// Batch Upload Manager & Drag-Drop
// --------------------------------------------------------------------------
const UploadManager = {
    init() {
        const uploadBtn = document.getElementById('uploadButton');
        const fileInput = document.getElementById('fileInput');
        const dropOverlay = document.getElementById('dropzoneOverlay');

        if (uploadBtn && fileInput) {
            uploadBtn.addEventListener('click', () => fileInput.click());
            fileInput.addEventListener('change', (e) => {
                if (e.target.files && e.target.files.length > 0) {
                    this.uploadFiles(Array.from(e.target.files));
                    fileInput.value = '';
                }
            });
        }

        // Drag & Drop
        if (dropOverlay) {
            let dragCounter = 0;
            window.addEventListener('dragenter', (e) => {
                e.preventDefault();
                dragCounter++;
                dropOverlay.style.display = 'flex';
            });

            window.addEventListener('dragleave', (e) => {
                e.preventDefault();
                dragCounter--;
                if (dragCounter <= 0) {
                    dragCounter = 0;
                    dropOverlay.style.display = 'none';
                }
            });

            window.addEventListener('dragover', (e) => e.preventDefault());

            window.addEventListener('drop', (e) => {
                e.preventDefault();
                dragCounter = 0;
                dropOverlay.style.display = 'none';
                if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                    this.uploadFiles(Array.from(e.dataTransfer.files));
                }
            });
        }

        document.getElementById('uploadDockClose')?.addEventListener('click', () => {
            document.getElementById('uploadDock').style.display = 'none';
        });
    },

    async uploadFiles(files) {
        const dock = document.getElementById('uploadDock');
        const dockTitle = document.getElementById('uploadDockTitle');
        const dockProgress = document.getElementById('dockProgressBar');
        const dockList = document.getElementById('uploadDockList');

        if (!dock || !files.length) return;
        dock.style.display = 'block';
        dockList.innerHTML = '';

        const total = files.length;
        let completed = 0;
        let successCount = 0;

        dockTitle.textContent = `Uploading ${total} file(s)...`;
        dockProgress.style.width = '0%';

        for (let i = 0; i < total; i++) {
            const file = files[i];
            const itemRow = document.createElement('div');
            itemRow.className = 'dock-item';
            itemRow.innerHTML = `
                <span class="dock-item-name">${file.name}</span>
                <span class="dock-item-status" id="status-${i}">Uploading...</span>
            `;
            dockList.appendChild(itemRow);

            const formData = new FormData();
            formData.append('file', file, file.name);

            try {
                const res = await fetch(`/image/${encodeURIComponent(file.name)}`, {
                    method: 'PUT',
                    body: formData,
                });

                const statusEl = document.getElementById(`status-${i}`);
                if (res.ok) {
                    successCount++;
                    if (statusEl) {
                        statusEl.textContent = '✓ Done';
                        statusEl.className = 'dock-item-status success';
                    }
                } else {
                    if (statusEl) {
                        statusEl.textContent = '✕ Failed';
                        statusEl.className = 'dock-item-status error';
                    }
                }
            } catch {
                const statusEl = document.getElementById(`status-${i}`);
                if (statusEl) {
                    statusEl.textContent = '✕ Error';
                    statusEl.className = 'dock-item-status error';
                }
            }

            completed++;
            const pct = Math.round((completed / total) * 100);
            dockProgress.style.width = `${pct}%`;
            dockTitle.textContent = `Uploaded ${completed}/${total} files (${pct}%)`;
        }

        Toast.show(`Uploaded ${successCount} of ${total} file(s) successfully!`, 'success');
        fetchMediaList();

        setTimeout(() => {
            if (completed === total) {
                dock.style.display = 'none';
            }
        }, 5000);
    }
};

// --------------------------------------------------------------------------
// Settings Modal Handler
// --------------------------------------------------------------------------
const SettingsModal = {
    init() {
        const btn = document.getElementById('settingsButton');
        const overlay = document.getElementById('settingsOverlay');
        const form = document.getElementById('settingsForm');
        const cancelBtn = document.getElementById('cancelSettings');
        const modalCancelBtn = document.getElementById('modalCancelBtn');
        const testBtn = document.getElementById('testArchivalBtn');
        const errorBox = document.getElementById('settingsError');
        const successBox = document.getElementById('settingsSuccess');

        if (!btn || !overlay || !form) return;

        btn.addEventListener('click', async () => {
            try {
                const res = await fetch('/api/settings');
                if (res.ok) {
                    const data = await res.json();
                    document.getElementById('rescanInterval').value = data.rescan_interval;
                    document.getElementById('taggingModel').value = data.tagging_model;
                    document.getElementById('archivalBackend').value = data.archival_backend;
                    document.getElementById('archivalBucket').value = data.archival_bucket;
                    errorBox.style.display = 'none';
                    successBox.style.display = 'none';
                    overlay.style.display = 'flex';
                }
            } catch {
                Toast.show('Could not fetch server settings.', 'error');
            }
        });

        const closeModal = () => {
            overlay.style.display = 'none';
        };

        cancelBtn?.addEventListener('click', closeModal);
        modalCancelBtn?.addEventListener('click', closeModal);

        testBtn?.addEventListener('click', async () => {
            testBtn.textContent = 'Testing...';
            testBtn.disabled = true;
            try {
                const res = await fetch('/api/archival/test', { method: 'POST' });
                const data = await res.json();
                if (data.connected) {
                    Toast.show(data.message || 'Archival test passed!', 'success');
                } else {
                    Toast.show(data.message || 'Archival test failed.', 'error');
                }
            } catch (e) {
                Toast.show(`Test connection failed: ${e.message}`, 'error');
            } finally {
                testBtn.textContent = 'Test Connection';
                testBtn.disabled = false;
            }
        });

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(form);
            const payload = {
                rescan_interval: parseInt(formData.get('rescan_interval'), 10),
                tagging_model: formData.get('tagging_model'),
                archival_backend: formData.get('archival_backend'),
                archival_bucket: formData.get('archival_bucket') || '',
            };

            try {
                const res = await fetch('/api/settings', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });

                if (res.ok) {
                    Toast.show('Settings saved successfully!', 'success');
                    closeModal();
                } else {
                    const err = await res.json();
                    errorBox.textContent = err.error || 'Failed to save settings.';
                    errorBox.style.display = 'block';
                }
            } catch (err) {
                errorBox.textContent = err.message;
                errorBox.style.display = 'block';
            }
        });
    }
};

// --------------------------------------------------------------------------
// Main Initialization on DOM Load
// --------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    ThemeManager.init();
    UploadManager.init();
    SettingsModal.init();

    // Type Filter Buttons (All / Photos / Videos)
    document.querySelectorAll('.filter-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            AppState.activeType = pill.dataset.type;
            applyFilters();
        });
    });

    // Search Input with Debounce & Clear
    const searchInput = document.getElementById('searchInput');
    const resetBtn = document.getElementById('resetButton');
    let searchDebounce = null;

    if (searchInput && resetBtn) {
        searchInput.addEventListener('input', (e) => {
            const val = e.target.value;
            resetBtn.style.display = val ? 'block' : 'none';
            clearTimeout(searchDebounce);
            searchDebounce = setTimeout(() => {
                AppState.searchQuery = val;
                applyFilters();
            }, 250);
        });

        resetBtn.addEventListener('click', () => {
            searchInput.value = '';
            resetBtn.style.display = 'none';
            AppState.searchQuery = '';
            applyFilters();
        });
    }

    // Keyboard Shortcut ('/' to focus search, 'Esc' to clear)
    window.addEventListener('keydown', (e) => {
        if (e.key === '/' && document.activeElement !== searchInput) {
            e.preventDefault();
            searchInput?.focus();
        } else if (e.key === 'Escape') {
            if (searchInput && document.activeElement === searchInput) {
                searchInput.blur();
                searchInput.value = '';
                resetBtn.style.display = 'none';
                AppState.searchQuery = '';
                applyFilters();
            }
        }
    });

    // Manual Rescan Trigger Button
    document.getElementById('rescanButton')?.addEventListener('click', async () => {
        try {
            const res = await fetch('/api/scan', { method: 'POST' });
            if (res.ok) {
                Toast.show('Rescan triggered! Refreshing...', 'info');
                setTimeout(() => fetchMediaList(), 1500);
            }
        } catch {
            Toast.show('Failed to trigger rescan.', 'error');
        }
    });

    // Mobile Sidebar Drawer Toggle
    const sidebarToggle = document.getElementById('sidebarToggleButton');
    const closeDrawer = document.getElementById('closeDrawerButton');
    const sidebar = document.getElementById('navigation-sidebar');

    sidebarToggle?.addEventListener('click', () => {
        sidebar?.classList.toggle('expanded');
    });

    closeDrawer?.addEventListener('click', () => {
        sidebar?.classList.remove('expanded');
    });

    // Initial Load
    fetchMediaList();
});
