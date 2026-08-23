import PhotoSwipeLightbox from './photoswipe-lightbox.esm.js';

// ==========================================================================
// Application State & Services
// ==========================================================================

const AppState = {
    allMedia: [],          // Raw array of all media items
    filteredMedia: [],     // Current filtered media items
    settings: {},
    activeType: 'all',     // 'all' | 'image' | 'video'
    searchQuery: '',
    lightbox: null,
    scrollObserver: null,
    virtualizer: null,
    paginationController: null,
    deferGalleryRender: false,
};

// --------------------------------------------------------------------------
// HTML Sanitization Helper
// --------------------------------------------------------------------------
function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// --------------------------------------------------------------------------
// Toast Notification Manager
// --------------------------------------------------------------------------
const Toast = {
    MAX_TOASTS: 3,
    show(message, type = 'info', duration = 3500) {
        const container = document.getElementById('toastContainer');
        if (!container) return;

        while (container.children.length >= this.MAX_TOASTS) {
            container.firstElementChild?.remove();
        }

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        const msgSpan = document.createElement('span');
        msgSpan.textContent = message;
        toast.appendChild(msgSpan);
        container.appendChild(toast);

        const removeTimer = setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(20px)';
            toast.style.transition = 'all 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, duration);

        toast.addEventListener('click', () => {
            clearTimeout(removeTimer);
            toast.remove();
        });
    }
};

// --------------------------------------------------------------------------
// Theme Manager
// --------------------------------------------------------------------------
const ThemeManager = {
    init() {
        const savedTheme = localStorage.getItem('photobackup_theme');
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)');
        const initialTheme = savedTheme || (prefersDark.matches ? 'dark' : 'light');
        this.applyTheme(initialTheme);

        prefersDark.addEventListener('change', (e) => {
            if (!localStorage.getItem('photobackup_theme')) {
                this.applyTheme(e.matches ? 'dark' : 'light');
            }
        });

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
        try {
            localStorage.setItem('photobackup_theme', theme);
        } catch {}
        this.applyTheme(theme);
    },

    applyTheme(theme) {
        document.documentElement.dataset.theme = theme;
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
// Gallery Grouping & Viewport Virtualization
// --------------------------------------------------------------------------
function groupMediaByMonthYear(items) {
    const groups = new Map();
    items.forEach(item => {
        let monthYearKey = 'Unknown Date';
        if (item.original_creation_date !== null && item.original_creation_date !== undefined && !isNaN(item.original_creation_date)) {
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

function formatSlideData(item) {
    const isVideo = item.mime_type && item.mime_type.startsWith('video/');
    if (isVideo) {
        return {
            type: 'html',
            isVideo: true,
            width: item.width || 1920,
            height: item.height || 1080,
            w: item.width || 1920,
            h: item.height || 1080,
            sha256: item.sha256,
            mimeType: item.mime_type || 'video/mp4',
            videoSrc: `/image/${item.sha256}`,
            filename: item.filename,
            original_creation_date: item.original_creation_date,
            city: item.city,
            country: item.country,
            tags: item.tags,
            html: `
                <div class="pswp-video-container">
                    <video class="pswp-video-player" src="/image/${item.sha256}" poster="/thumbnail/${item.sha256}" controls playsinline preload="metadata"></video>
                </div>
            `,
        };
    }

    return {
        src: `/image/${item.sha256}`,
        msrc: `/thumbnail/${item.sha256}`,
        width: item.width || 1920,
        height: item.height || 1080,
        sha256: item.sha256,
        mimeType: item.mime_type || 'image/jpeg',
        filename: item.filename,
        original_creation_date: item.original_creation_date,
        city: item.city,
        country: item.country,
        tags: item.tags,
        alt: item.filename || 'Photo',
    };
}

// Card DOM Factory
function createCardElement(item) {
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

    link.addEventListener('click', (e) => {
        e.preventDefault();
        openLightboxAtSha(item.sha256);
    });

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
        const citySpan = document.createElement('span');
        citySpan.textContent = `📍 ${item.city}`;
        meta.appendChild(citySpan);
    }
    if (item.original_creation_date !== null && item.original_creation_date !== undefined) {
        const d = new Date(item.original_creation_date * 1000);
        const dateSpan = document.createElement('span');
        dateSpan.textContent = `📅 ${d.toLocaleDateString()}`;
        meta.appendChild(dateSpan);
    }
    overlay.appendChild(meta);

    // Tags
    if (item.tags) {
        try {
            const parsed = typeof item.tags === 'string' ? JSON.parse(item.tags) : item.tags;
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
    return card;
}

function openLightboxAtSha(targetSha) {
    if (!AppState.lightbox) return;
    const index = AppState.filteredMedia.findIndex(m => m.sha256 === targetSha);
    const validIndex = index >= 0 ? index : 0;
    const dataSource = AppState.filteredMedia.map(formatSlideData);
    AppState.lightbox.loadAndOpen(validIndex, dataSource);
}

// Section-level Viewport Virtualizer for 35,000+ items
const SectionVirtualizer = {
    observer: null,
    renderedSections: new Set(),
    sectionDataMap: new Map(),

    init() {
        if (this.observer) {
            this.observer.disconnect();
        }
        this.renderedSections.clear();
        this.sectionDataMap.clear();

        this.observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                const section = entry.target;
                const sectionId = section.id;
                if (entry.isIntersecting) {
                    this.mountSection(section, sectionId);
                } else {
                    if (this.renderedSections.size > 4) {
                        this.unmountSection(section, sectionId);
                    }
                }
            });
        }, {
            rootMargin: '1000px 0px 1000px 0px',
            threshold: 0
        });
    },

    register(sectionEl, sectionId, itemsInGroup) {
        this.sectionDataMap.set(sectionId, itemsInGroup);
        this.observer.observe(sectionEl);
    },

    mountSection(section, sectionId) {
        if (this.renderedSections.has(sectionId)) return;
        const items = this.sectionDataMap.get(sectionId);
        if (!items) return;

        const gridDiv = section.querySelector('.photo-items-grid');
        if (!gridDiv) return;

        gridDiv.innerHTML = '';
        const fragment = document.createDocumentFragment();
        items.forEach(item => {
            fragment.appendChild(createCardElement(item));
        });
        gridDiv.appendChild(fragment);
        this.renderedSections.add(sectionId);
        section.style.minHeight = `${section.offsetHeight}px`;
    },

    unmountSection(section, sectionId) {
        if (!this.renderedSections.has(sectionId)) return;
        const gridDiv = section.querySelector('.photo-items-grid');
        if (gridDiv) {
            section.style.minHeight = `${section.offsetHeight}px`;
            gridDiv.innerHTML = '';
        }
        this.renderedSections.delete(sectionId);
    }
};

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

    SectionVirtualizer.init();
    const groupedMedia = groupMediaByMonthYear(items);
    galleryGrid.innerHTML = '';

    let sectionIndex = 0;
    for (const [monthYear, itemsInGroup] of groupedMedia) {
        const safeSlug = monthYear.replace(/[^a-zA-Z0-9]/g, '_');
        const sectionId = `sec_${sectionIndex}_${safeSlug}`;
        const monthSection = document.createElement('section');
        monthSection.className = 'month-section';
        monthSection.id = sectionId;

        // Pre-set estimated minimum height to prevent scroll jumps
        const estimatedRows = Math.max(1, Math.ceil(itemsInGroup.length / 5));
        monthSection.style.minHeight = `${estimatedRows * 200 + 50}px`;

        const header = document.createElement('h2');
        header.className = 'month-year-divider-header';
        header.textContent = monthYear;
        monthSection.appendChild(header);

        const gridDiv = document.createElement('div');
        gridDiv.className = 'photo-items-grid';

        // Pre-render first 2 sections immediately for instant paint
        if (sectionIndex < 2) {
            const fragment = document.createDocumentFragment();
            itemsInGroup.forEach(item => {
                fragment.appendChild(createCardElement(item));
            });
            gridDiv.appendChild(fragment);
            SectionVirtualizer.renderedSections.add(sectionId);
        }

        monthSection.appendChild(gridDiv);
        galleryGrid.appendChild(monthSection);

        SectionVirtualizer.register(monthSection, sectionId, itemsInGroup);
        sectionIndex++;
    }

    renderTimelineSidebar(groupedMedia);
    setupScrollSpy();
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

    let sectionIndex = 0;
    for (const [monthYear, items] of groupedMedia) {
        const safeSlug = monthYear.replace(/[^a-zA-Z0-9]/g, '_');
        const sectionId = `sec_${sectionIndex}_${safeSlug}`;
        const li = document.createElement('li');
        const a = document.createElement('a');
        a.className = 'timeline-link';
        a.href = `#${sectionId}`;
        a.dataset.sectionId = sectionId;
        a.innerHTML = `
            <span>${escapeHtml(monthYear)}</span>
            <span class="timeline-count-badge">${items.length}</span>
        `;

        a.addEventListener('click', (e) => {
            e.preventDefault();
            const target = document.getElementById(sectionId);
            if (target) {
                SectionVirtualizer.mountSection(target, sectionId);
                target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                if (window.innerWidth <= 768) {
                    document.getElementById('navigation-sidebar')?.classList.remove('expanded');
                    document.getElementById('drawerBackdrop')?.classList.remove('active');
                    document.body.style.overflow = '';
                }
            }
        });

        li.appendChild(a);
        ul.appendChild(li);
        sectionIndex++;
    }
    container.appendChild(ul);
}

function setupScrollSpy() {
    if (AppState.scrollObserver) {
        AppState.scrollObserver.disconnect();
    }

    const sections = document.querySelectorAll('.month-section');
    if (!sections.length) return;

    const visibleSections = new Set();

    AppState.scrollObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                visibleSections.add(entry.target.id);
            } else {
                visibleSections.delete(entry.target.id);
            }
        });

        if (visibleSections.size > 0) {
            // Find topmost visible section in DOM order
            let topSectionId = null;
            for (const section of sections) {
                if (visibleSections.has(section.id)) {
                    topSectionId = section.id;
                    break;
                }
            }

            if (topSectionId) {
                document.querySelectorAll('.timeline-link').forEach(link => {
                    link.classList.toggle('active', link.dataset.sectionId === topSectionId);
                });
            }
        }
    }, {
        rootMargin: '-70px 0px -70% 0px',
        threshold: 0
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
        pswpModule: () => import('./photoswipe.esm.js'),
        initialZoomLevel: 'fit',
        secondaryZoomLevel: 1.5,
        maxZoomLevel: 3,
        showHideAnimationType: 'zoom',
    });

    // Prevent PhotoSwipe from capturing pointer/touch events on video player & controls
    AppState.lightbox.addFilter('preventPointerEvent', (preventPointerEvent, event) => {
        if (event.target && event.target.closest('.pswp-video-player, .pswp-video-container')) {
            return false;
        }
        return preventPointerEvent;
    });

    // Prevent zooming video slides
    AppState.lightbox.addFilter('isContentZoomable', (isZoomable, content) => {
        if (content && content.data && content.data.isVideo) {
            return false;
        }
        return isZoomable;
    });

    // Manage video playback lifecycle: only play active slide video, pause inactive
    AppState.lightbox.on('contentActivate', ({ content }) => {
        if (content && content.element) {
            const video = content.element.querySelector('.pswp-video-player');
            if (video) {
                video.play().catch(() => {});
            }
        }
    });

    AppState.lightbox.on('contentDeactivate', ({ content }) => {
        if (content && content.element) {
            const video = content.element.querySelector('.pswp-video-player');
            if (video) {
                video.pause();
            }
        }
    });

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

    // Clean up hardware video decoders and network buffers on content destroy
    AppState.lightbox.on('contentDestroy', ({ content }) => {
        if (content && content.element) {
            const video = content.element.querySelector('.pswp-video-player');
            if (video) {
                video.pause();
                video.removeAttribute('src');
                video.load();
            }
        }
    });

    AppState.lightbox.on('close', () => {
        document.querySelectorAll('.pswp-video-player').forEach(video => {
            video.pause();
            video.removeAttribute('src');
            video.load();
        });

        // Re-render gallery if new items arrived while lightbox was open
        if (AppState.deferGalleryRender) {
            AppState.deferGalleryRender = false;
            applyFilters();
        }
    });

    // Adjust image dimensions dynamically if natural dimensions differ (e.g., EXIF orientation)
    AppState.lightbox.on('loadComplete', (e) => {
        const { slide, content } = e;
        if (content && content.element && content.element instanceof HTMLImageElement) {
            const img = content.element;
            if (img.naturalWidth && img.naturalHeight) {
                if (slide && (slide.width !== img.naturalWidth || slide.height !== img.naturalHeight)) {
                    slide.width = img.naturalWidth;
                    slide.height = img.naturalHeight;
                    if (slide.data) {
                        slide.data.width = img.naturalWidth;
                        slide.data.height = img.naturalHeight;
                    }
                    if (slide.zoomLevels) {
                        slide.zoomLevels.update(slide.width, slide.height, slide.panAreaSize);
                        if (slide.currZoomLevel !== slide.zoomLevels.initial) {
                            slide.zoomTo(slide.zoomLevels.initial, null, 0);
                        }
                    }
                    slide.updateContentSize(true);
                }
            }
        }
    });

    // Custom Caption Overlay
    AppState.lightbox.on('uiRegister', () => {
        AppState.lightbox.pswp.ui.registerElement({
            name: 'custom-caption',
            order: 9,
            isButton: false,
            appendTo: 'root',
            onInit: (el, pswp) => {
                el.className = 'pswp__custom-caption pswp-custom-caption';

                const updateCaption = () => {
                    const item = AppState.filteredMedia[pswp.currIndex] || pswp.currSlide?.data;
                    if (item) {
                        let parts = [];
                        if (item.filename) parts.push(`<strong>${escapeHtml(item.filename)}</strong>`);
                        if (item.original_creation_date !== null && item.original_creation_date !== undefined) {
                            const d = new Date(item.original_creation_date * 1000);
                            parts.push(`<span class="pswp-caption-date">📅 ${escapeHtml(d.toLocaleDateString())}</span>`);
                        }
                        if (item.city) {
                            const loc = item.city + (item.country ? ', ' + item.country : '');
                            parts.push(`<span class="pswp-caption-location">📍 ${escapeHtml(loc)}</span>`);
                        }
                        if (item.tags) {
                            try {
                                const parsed = typeof item.tags === 'string' ? JSON.parse(item.tags) : item.tags;
                                if (Array.isArray(parsed) && parsed.length > 0) {
                                    const tagStr = parsed.map(t => `#${escapeHtml(Array.isArray(t) ? t[0] : t)}`).join(' ');
                                    parts.push(`<span class="pswp-caption-tags">${tagStr}</span>`);
                                }
                            } catch { /* ignore */ }
                        }
                        el.innerHTML = parts.join(' · ');
                        el.style.display = parts.length > 0 ? 'flex' : 'none';
                    } else {
                        el.innerHTML = '';
                        el.style.display = 'none';
                    }
                };

                pswp.on('change', updateCaption);
                updateCaption();
            }
        });
    });

    AppState.lightbox.init();
}

// --------------------------------------------------------------------------
// API Fetching & Progressive Loading
// --------------------------------------------------------------------------
async function fetchMediaList() {
    if (AppState.paginationController) {
        AppState.paginationController.abort();
    }
    AppState.paginationController = new AbortController();
    const signal = AppState.paginationController.signal;

    const galleryGrid = document.getElementById('gallery-grid');
    if (galleryGrid && (!AppState.allMedia || AppState.allMedia.length === 0)) {
        galleryGrid.innerHTML = `
            <div class="photo-items-grid">
                ${Array(8).fill('<div class="skeleton-card"></div>').join('')}
            </div>
        `;
    }

    try {
        const initialRes = await fetch('/api/media?limit=200&offset=0', { signal });
        if (initialRes.ok) {
            const initialData = await initialRes.json();
            if (initialData.items && initialData.items.length > 0) {
                AppState.allMedia = initialData.items.map(item => ({
                    sha256: item.sha256_hex,
                    ...item
                }));
                applyFilters();
                updateStatsBar();

                if (initialData.has_more) {
                    fetchRemainingMedia(signal);
                    return;
                }
            }
        }

        // Full fetch fallback
        const res = await fetch('/list', { signal });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        AppState.allMedia = Object.entries(data).map(([sha256, info]) => ({
            sha256,
            ...info
        }));
        AppState.allMedia.sort((a, b) => (b.original_creation_date ?? -Infinity) - (a.original_creation_date ?? -Infinity));
        applyFilters();
        updateStatsBar();
    } catch (err) {
        if (err.name === 'AbortError') return;
        console.error('Error loading media:', err);
        Toast.show('Error loading media library. Check server connection.', 'error');
        if (galleryGrid && (!AppState.allMedia || AppState.allMedia.length === 0)) {
            galleryGrid.innerHTML = '<p class="empty-state">Could not connect to media server.</p>';
        }
    }
}

async function fetchRemainingMedia(signal) {
    try {
        let offset = AppState.allMedia.length;
        const limit = 500;
        let hasMore = true;
        const knownShas = new Set(AppState.allMedia.map(m => m.sha256));

        while (hasMore) {
            if (signal?.aborted) return;
            const res = await fetch(`/api/media?limit=${limit}&offset=${offset}`, { signal });
            if (!res.ok) break;
            const data = await res.json();
            if (!data.items || data.items.length === 0) break;

            let addedCount = 0;
            for (const item of data.items) {
                const sha = item.sha256_hex;
                if (!knownShas.has(sha)) {
                    knownShas.add(sha);
                    AppState.allMedia.push({
                        sha256: sha,
                        ...item
                    });
                    addedCount++;
                }
            }

            offset += data.items.length;
            hasMore = Boolean(data.has_more) && addedCount > 0;
        }

        AppState.allMedia.sort((a, b) => (b.original_creation_date ?? -Infinity) - (a.original_creation_date ?? -Infinity));

        if (AppState.lightbox?.pswp?.isOpen) {
            AppState.deferGalleryRender = true;
        } else {
            applyFilters();
        }
        updateStatsBar();
    } catch (err) {
        if (err.name === 'AbortError') return;
        /* background fetch failed silently */
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
            const tags = (typeof item.tags === 'string' ? item.tags : JSON.stringify(item.tags || '')).toLowerCase();
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
    ALLOWED_EXTENSIONS: ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif', '.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v'],
    queue: [],
    isProcessing: false,
    CONCURRENCY: 3,
    totalQueued: 0,
    completedCount: 0,
    successCount: 0,

    init() {
        const uploadBtn = document.getElementById('uploadButton');
        const fileInput = document.getElementById('fileInput');
        const dropOverlay = document.getElementById('dropzoneOverlay');

        if (uploadBtn && fileInput) {
            uploadBtn.addEventListener('click', () => fileInput.click());
            fileInput.addEventListener('change', (e) => {
                if (e.target.files && e.target.files.length > 0) {
                    this.enqueueFiles(Array.from(e.target.files));
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
                    this.enqueueFiles(Array.from(e.dataTransfer.files));
                }
            });
        }

        document.getElementById('uploadDockClose')?.addEventListener('click', () => {
            document.getElementById('uploadDock').style.display = 'none';
        });
    },

    enqueueFiles(files) {
        const validFiles = files.filter(file => {
            const ext = '.' + file.name.split('.').pop().toLowerCase();
            return this.ALLOWED_EXTENSIONS.includes(ext);
        });

        if (validFiles.length < files.length) {
            Toast.show(`Skipped ${files.length - validFiles.length} unsupported file(s).`, 'info');
        }

        if (!validFiles.length) return;

        const dock = document.getElementById('uploadDock');
        const dockList = document.getElementById('uploadDockList');
        if (dock) dock.style.display = 'block';

        if (!this.isProcessing) {
            this.totalQueued = 0;
            this.completedCount = 0;
            this.successCount = 0;
            if (dockList) dockList.innerHTML = '';
        }

        validFiles.forEach(file => {
            const index = this.totalQueued++;
            const itemRow = document.createElement('div');
            itemRow.className = 'dock-item';

            const nameSpan = document.createElement('span');
            nameSpan.className = 'dock-item-name';
            nameSpan.textContent = file.name;

            const statusSpan = document.createElement('span');
            statusSpan.className = 'dock-item-status';
            statusSpan.id = `dock-status-${index}`;
            statusSpan.textContent = 'Queued...';

            itemRow.appendChild(nameSpan);
            itemRow.appendChild(statusSpan);
            dockList?.appendChild(itemRow);

            this.queue.push({ file, index });
        });

        this.updateDockProgress();
        this.processQueue();
    },

    updateDockProgress() {
        const dockTitle = document.getElementById('uploadDockTitle');
        const dockProgress = document.getElementById('dockProgressBar');
        const pct = this.totalQueued > 0 ? Math.round((this.completedCount / this.totalQueued) * 100) : 0;
        if (dockProgress) dockProgress.style.width = `${pct}%`;
        if (dockTitle) dockTitle.textContent = `Uploaded ${this.completedCount}/${this.totalQueued} files (${pct}%)`;
    },

    async processQueue() {
        if (this.isProcessing) return;
        this.isProcessing = true;

        const workers = Array(this.CONCURRENCY).fill(0).map(async () => {
            while (this.queue.length > 0) {
                const item = this.queue.shift();
                if (!item) break;
                await this.uploadSingle(item.file, item.index);
            }
        });

        await Promise.all(workers);
        this.isProcessing = false;

        Toast.show(`Uploaded ${this.successCount} of ${this.totalQueued} file(s) successfully!`, 'success');
        fetchMediaList();

        setTimeout(() => {
            if (!this.isProcessing && this.completedCount === this.totalQueued) {
                const dock = document.getElementById('uploadDock');
                if (dock) dock.style.display = 'none';
            }
        }, 5000);
    },

    async uploadSingle(file, index) {
        const statusEl = document.getElementById(`dock-status-${index}`);
        if (statusEl) statusEl.textContent = 'Uploading...';

        const formData = new FormData();
        formData.append('file', file, file.name);

        try {
            const res = await fetch(`/image/${encodeURIComponent(file.name)}`, {
                method: 'PUT',
                body: formData,
            });

            if (res.status === 200) {
                this.successCount++;
                if (statusEl) {
                    statusEl.textContent = '✓ Exists';
                    statusEl.className = 'dock-item-status duplicate';
                }
            } else if (res.ok) {
                this.successCount++;
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
            if (statusEl) {
                statusEl.textContent = '✕ Error';
                statusEl.className = 'dock-item-status error';
            }
        }

        this.completedCount++;
        this.updateDockProgress();
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

        const closeModal = () => {
            overlay.style.display = 'none';
        };

        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeModal();
        });

        cancelBtn?.addEventListener('click', closeModal);
        modalCancelBtn?.addEventListener('click', closeModal);

        btn.addEventListener('click', async () => {
            try {
                const res = await fetch('/api/settings');
                if (res.ok) {
                    const data = await res.json();
                    document.getElementById('rescanInterval').value = data.rescan_interval;
                    document.getElementById('taggingModel').value = data.tagging_model;
                    document.getElementById('archivalBackend').value = data.archival_backend;
                    document.getElementById('archivalBucket').value = data.archival_bucket;
                    if (errorBox) errorBox.style.display = 'none';
                    if (successBox) successBox.style.display = 'none';
                    overlay.style.display = 'flex';
                }
            } catch {
                Toast.show('Could not fetch server settings.', 'error');
            }
        });

        testBtn?.addEventListener('click', async () => {
            testBtn.textContent = 'Testing...';
            testBtn.disabled = true;
            try {
                const backend = document.getElementById('archivalBackend')?.value || 'Off';
                const bucket = document.getElementById('archivalBucket')?.value || '';
                const res = await fetch('/api/archival/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ archival_backend: backend, archival_bucket: bucket })
                });
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
            const rawInterval = document.getElementById('rescanInterval')?.value;
            const rescanInterval = rawInterval === '' ? 0 : parseInt(rawInterval, 10);
            if (isNaN(rescanInterval) || rescanInterval < 0) {
                if (errorBox) {
                    errorBox.textContent = 'Rescan interval must be a non-negative number.';
                    errorBox.style.display = 'block';
                }
                return;
            }

            const payload = {
                rescan_interval: rescanInterval,
                tagging_model: document.getElementById('taggingModel')?.value || 'Off',
                archival_backend: document.getElementById('archivalBackend')?.value || 'Off',
                archival_bucket: document.getElementById('archivalBucket')?.value?.trim() || '',
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
                    if (errorBox) {
                        errorBox.textContent = err.error || 'Failed to save settings.';
                        errorBox.style.display = 'block';
                    }
                }
            } catch (err) {
                if (errorBox) {
                    errorBox.textContent = err.message;
                    errorBox.style.display = 'block';
                }
            }
        });
    }
};

// --------------------------------------------------------------------------
// Slideshow Manager (Random Images, 5-Second Timer, Subtle Progress Indicator)
// --------------------------------------------------------------------------
const SlideshowManager = {
    overlay: null,
    progressFill: null,
    counter: null,
    imageEl: null,
    captionEl: null,
    playPauseBtn: null,
    prevBtn: null,
    nextBtn: null,
    closeBtn: null,

    isOpen: false,
    isPlaying: true,
    slideDuration: 5000,
    timerId: null,
    startTime: 0,
    remainingTime: 5000,

    pool: [],
    currentIndex: -1,
    history: [],
    historyCursor: -1,

    init() {
        this.overlay = document.getElementById('slideshowOverlay');
        this.progressFill = document.getElementById('slideshowProgressFill');
        this.counter = document.getElementById('slideshowCounter');
        this.imageEl = document.getElementById('slideshowImage');
        this.captionEl = document.getElementById('slideshowCaption');
        this.playPauseBtn = document.getElementById('slideshowPlayPause');
        this.prevBtn = document.getElementById('slideshowPrev');
        this.nextBtn = document.getElementById('slideshowNext');
        this.closeBtn = document.getElementById('slideshowClose');

        const triggerBtn = document.getElementById('slideshowButton');
        triggerBtn?.addEventListener('click', () => this.start());

        this.closeBtn?.addEventListener('click', () => this.close());
        this.prevBtn?.addEventListener('click', () => this.prev());
        this.nextBtn?.addEventListener('click', () => this.next());
        this.playPauseBtn?.addEventListener('click', () => this.togglePlayPause());

        // Touch swipe gestures
        let touchStartX = 0;
        this.overlay?.addEventListener('touchstart', (e) => {
            if (e.changedTouches && e.changedTouches[0]) {
                touchStartX = e.changedTouches[0].screenX;
            }
        }, { passive: true });

        this.overlay?.addEventListener('touchend', (e) => {
            if (e.changedTouches && e.changedTouches[0]) {
                const touchEndX = e.changedTouches[0].screenX;
                const diff = touchEndX - touchStartX;
                if (Math.abs(diff) > 40) {
                    if (diff > 0) {
                        this.prev();
                    } else {
                        this.next();
                    }
                }
            }
        }, { passive: true });
    },

    start() {
        const sourceList = (AppState.filteredMedia && AppState.filteredMedia.length > 0)
            ? AppState.filteredMedia
            : AppState.allMedia;

        const images = sourceList.filter(item => {
            return !item.mime_type || !item.mime_type.startsWith('video/');
        });

        if (!images || images.length === 0) {
            Toast.show('No images found for slideshow.', 'info');
            return;
        }

        // Randomize images
        this.pool = [...images];
        for (let i = this.pool.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [this.pool[i], this.pool[j]] = [this.pool[j], this.pool[i]];
        }

        this.history = [];
        this.historyCursor = -1;
        this.currentIndex = -1;
        this.isOpen = true;
        this.isPlaying = true;
        this.updatePlayPauseIcon();

        if (this.overlay) {
            this.overlay.style.display = 'flex';
            this.overlay.focus();
        }
        document.body.style.overflow = 'hidden';

        this.next();
    },

    close() {
        if (!this.isOpen) return;
        this.isOpen = false;
        this.clearTimer();
        if (this.overlay) {
            this.overlay.style.display = 'none';
        }
        document.body.style.overflow = '';
    },

    next() {
        if (!this.isOpen || this.pool.length === 0) return;

        if (this.historyCursor < this.history.length - 1) {
            this.historyCursor++;
            this.showSlide(this.history[this.historyCursor]);
        } else {
            this.currentIndex = (this.currentIndex + 1) % this.pool.length;
            this.history.push(this.currentIndex);
            this.historyCursor = this.history.length - 1;
            this.showSlide(this.currentIndex);
        }
    },

    prev() {
        if (!this.isOpen || this.pool.length === 0) return;

        if (this.historyCursor > 0) {
            this.historyCursor--;
            this.showSlide(this.history[this.historyCursor]);
        } else {
            this.currentIndex = (this.currentIndex - 1 + this.pool.length) % this.pool.length;
            this.history.unshift(this.currentIndex);
            this.historyCursor = 0;
            this.showSlide(this.currentIndex);
        }
    },

    togglePlayPause() {
        if (!this.isOpen) return;
        if (this.isPlaying) {
            this.pause();
        } else {
            this.resume();
        }
    },

    pause() {
        this.isPlaying = false;
        this.updatePlayPauseIcon();
        this.pauseTimer();
    },

    resume() {
        this.isPlaying = true;
        this.updatePlayPauseIcon();
        this.resumeTimer();
    },

    updatePlayPauseIcon() {
        const pauseIcon = this.playPauseBtn?.querySelector('.icon-pause');
        const playIcon = this.playPauseBtn?.querySelector('.icon-play');
        if (pauseIcon && playIcon) {
            pauseIcon.style.display = this.isPlaying ? 'block' : 'none';
            playIcon.style.display = this.isPlaying ? 'none' : 'block';
            this.playPauseBtn.setAttribute('aria-label', this.isPlaying ? 'Pause slideshow' : 'Resume slideshow');
        }
    },

    showSlide(poolIndex) {
        const item = this.pool[poolIndex];
        if (!item) return;

        if (this.counter) {
            this.counter.textContent = `${this.historyCursor + 1} / ${this.pool.length}`;
        }

        if (this.captionEl) {
            let parts = [];
            if (item.filename) parts.push(`<strong>${escapeHtml(item.filename)}</strong>`);
            if (item.original_creation_date !== null && item.original_creation_date !== undefined) {
                const d = new Date(item.original_creation_date * 1000);
                parts.push(`📅 ${escapeHtml(d.toLocaleDateString())}`);
            }
            if (item.city) {
                const loc = item.city + (item.country ? ', ' + item.country : '');
                parts.push(`📍 ${escapeHtml(loc)}`);
            }
            if (item.tags) {
                try {
                    const parsed = typeof item.tags === 'string' ? JSON.parse(item.tags) : item.tags;
                    if (Array.isArray(parsed) && parsed.length > 0) {
                        const tagStr = parsed.map(t => `#${escapeHtml(Array.isArray(t) ? t[0] : t)}`).join(' ');
                        parts.push(tagStr);
                    }
                } catch {}
            }
            this.captionEl.innerHTML = parts.join(' · ');
            this.captionEl.classList.toggle('visible', parts.length > 0);
        }

        if (this.imageEl) {
            this.imageEl.classList.remove('active');
            const newSrc = `/image/${item.sha256}`;
            this.imageEl.src = newSrc;
            this.imageEl.alt = item.filename || 'Photo';

            if (this.imageEl.complete) {
                this.imageEl.classList.add('active');
            } else {
                this.imageEl.onload = () => {
                    if (this.isOpen) {
                        this.imageEl.classList.add('active');
                    }
                };
            }
        }

        this.resetTimer();
    },

    resetTimer() {
        this.clearTimer();
        if (!this.isPlaying) return;

        this.remainingTime = this.slideDuration;
        this.startTime = Date.now();

        if (this.progressFill) {
            this.progressFill.classList.remove('animating');
            this.progressFill.style.width = '0%';
            // Trigger reflow to restart CSS transition
            void this.progressFill.offsetWidth;
            this.progressFill.classList.add('animating');
            this.progressFill.style.width = '100%';
        }

        this.timerId = setTimeout(() => {
            if (this.isOpen && this.isPlaying) {
                this.next();
            }
        }, this.slideDuration);
    },

    clearTimer() {
        if (this.timerId) {
            clearTimeout(this.timerId);
            this.timerId = null;
        }
        if (this.progressFill) {
            this.progressFill.classList.remove('animating');
            this.progressFill.style.width = '0%';
        }
    },

    pauseTimer() {
        if (this.timerId) {
            clearTimeout(this.timerId);
            this.timerId = null;
            const elapsed = Date.now() - this.startTime;
            this.remainingTime = Math.max(0, this.slideDuration - elapsed);
            if (this.progressFill) {
                const computedWidth = (elapsed / this.slideDuration) * 100;
                this.progressFill.classList.remove('animating');
                this.progressFill.style.width = `${computedWidth}%`;
            }
        }
    },

    resumeTimer() {
        if (this.remainingTime <= 0) {
            this.next();
            return;
        }
        this.startTime = Date.now();
        if (this.progressFill) {
            this.progressFill.classList.add('animating');
            this.progressFill.style.transitionDuration = `${this.remainingTime}ms`;
            this.progressFill.style.width = '100%';
        }
        this.timerId = setTimeout(() => {
            if (this.isOpen && this.isPlaying) {
                this.next();
            }
        }, this.remainingTime);
    }
};

// --------------------------------------------------------------------------
// Main Initialization on DOM Load
// --------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    ThemeManager.init();
    UploadManager.init();
    SettingsModal.init();
    SlideshowManager.init();

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
            }, 200);
        });

        resetBtn.addEventListener('click', () => {
            searchInput.value = '';
            resetBtn.style.display = 'none';
            AppState.searchQuery = '';
            applyFilters();
        });
    }

    // Keyboard Shortcuts ('/' to focus search, 'Esc' to clear/close modals, Arrow keys for slideshow)
    window.addEventListener('keydown', (e) => {
        const active = document.activeElement;
        const isInputFocused = active && (['INPUT', 'TEXTAREA', 'SELECT'].includes(active.tagName) || active.isContentEditable);

        if (SlideshowManager.isOpen) {
            if (e.key === 'Escape') {
                e.preventDefault();
                SlideshowManager.close();
            } else if (e.key === 'ArrowLeft') {
                e.preventDefault();
                SlideshowManager.prev();
            } else if (e.key === 'ArrowRight') {
                e.preventDefault();
                SlideshowManager.next();
            } else if (e.key === ' ' || e.code === 'Space') {
                e.preventDefault();
                SlideshowManager.togglePlayPause();
            }
            return;
        }

        if (e.key === '/' && !isInputFocused) {
            e.preventDefault();
            searchInput?.focus();
        } else if (e.key === 'Escape') {
            const settingsOverlay = document.getElementById('settingsOverlay');
            if (settingsOverlay && settingsOverlay.style.display === 'flex') {
                settingsOverlay.style.display = 'none';
            } else if (searchInput && active === searchInput) {
                searchInput.blur();
                searchInput.value = '';
                if (resetBtn) resetBtn.style.display = 'none';
                AppState.searchQuery = '';
                applyFilters();
            }
        }
    });

    // Manual Rescan Trigger Button with Polling
    const rescanBtn = document.getElementById('rescanButton');
    if (rescanBtn) {
        rescanBtn.addEventListener('click', async () => {
            rescanBtn.disabled = true;
            rescanBtn.style.opacity = '0.5';
            Toast.show('Starting library rescan...', 'info');

            try {
                const res = await fetch('/api/scan', { method: 'POST' });
                if (!res.ok) throw new Error('Rescan request failed');

                const pollRescan = async () => {
                    try {
                        const statusRes = await fetch('/api/scan/status', { cache: 'no-store' });
                        if (statusRes.ok) {
                            const status = await statusRes.json();
                            if (status.is_scanning) {
                                setTimeout(pollRescan, 500);
                                return;
                            }
                        }
                    } catch {}

                    rescanBtn.disabled = false;
                    rescanBtn.style.opacity = '1';
                    Toast.show('Rescan complete! Updating library...', 'success');
                    fetchMediaList();
                };

                setTimeout(pollRescan, 500);
            } catch {
                rescanBtn.disabled = false;
                rescanBtn.style.opacity = '1';
                Toast.show('Failed to trigger rescan.', 'error');
            }
        });
    }

    // Mobile Sidebar Drawer Toggle & Backdrop
    const sidebarToggle = document.getElementById('sidebarToggleButton');
    const closeDrawer = document.getElementById('closeDrawerButton');
    const sidebar = document.getElementById('navigation-sidebar');
    const backdrop = document.getElementById('drawerBackdrop');

    const openDrawer = () => {
        sidebar?.classList.add('expanded');
        backdrop?.classList.add('active');
        document.body.style.overflow = 'hidden';
    };

    const closeDrawerFn = () => {
        sidebar?.classList.remove('expanded');
        backdrop?.classList.remove('active');
        document.body.style.overflow = '';
    };

    sidebarToggle?.addEventListener('click', openDrawer);
    closeDrawer?.addEventListener('click', closeDrawerFn);
    backdrop?.addEventListener('click', closeDrawerFn);

    // Initial Lightbox & Media Load
    initPhotoSwipe();
    fetchMediaList();
});
