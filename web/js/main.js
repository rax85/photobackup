import PhotoSwipeLightbox from './photoswipe-lightbox.esm.js';

document.addEventListener('DOMContentLoaded', () => {
    const galleryGrid = document.getElementById('gallery-grid');
    let mediaItems = []; // To store all media data from /list
    let lightbox; // To store PhotoSwipe lightbox instance

    // Function to fetch media list
    async function fetchMediaList() {
        try {
            const response = await fetch('/list');
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            const data = await response.json();
            mediaItems = Object.entries(data).map(([sha256, itemData]) => ({
                sha256,
                ...itemData
            }));
            // Sort by original creation date, newest first
            mediaItems.sort((a, b) => (b.original_creation_date || 0) - (a.original_creation_date || 0));

            const groupedMedia = groupMediaByMonthYear(mediaItems);
            displayMedia(groupedMedia); // Pass grouped media to display function
            initializePhotoSwipe();
            displayNavigationSidebar(groupedMedia); // Call the new function
        } catch (error) {
            console.error("Error fetching media list:", error);
            if (galleryGrid) {
                galleryGrid.innerHTML = '<p>Error loading media. Please try again later.</p>';
            }
        }
    }

    // Function to group media by month and year
    function groupMediaByMonthYear(items) {
        const groups = new Map(); // Use Map to preserve insertion order (chronological)
        items.forEach(item => {
            if (item.original_creation_date === null || typeof item.original_creation_date === 'undefined') {
                console.warn('Item has no original_creation_date, placing in "Unknown Date" group:', item);
                const monthYearKey = "Unknown Date";
                 if (!groups.has(monthYearKey)) {
                    groups.set(monthYearKey, []);
                }
                groups.get(monthYearKey).push(item);
                return; // Skip to next item
            }
            const date = new Date(item.original_creation_date * 1000); // Convert Unix timestamp to milliseconds
            const monthYearKey = date.toLocaleString('default', { month: 'long', year: 'numeric' });

            if (!groups.has(monthYearKey)) {
                groups.set(monthYearKey, []);
            }
            groups.get(monthYearKey).push(item);
        });
        return groups;
    }

    // Function to display media in the gallery (now expects groupedMedia)
    function displayMedia(groupedMedia) { //parameter changed from mediaItems
        if (!galleryGrid) {
            console.error("Gallery grid element not found.");
            return;
        }
        // Check if groupedMedia is empty or not provided
        if (!groupedMedia || groupedMedia.size === 0) {
             // Check if mediaItems (the original flat list) is also empty
            if (!mediaItems || mediaItems.length === 0) {
                galleryGrid.innerHTML = '<p>No media found.</p>';
            } else {
                // This case means grouping failed or resulted in empty groups from non-empty items, which is unlikely with "Unknown Date" handling
                galleryGrid.innerHTML = '<p>No media groups to display. Check console for errors.</p>';
                console.warn("displayMedia called with empty/null groupedMedia, but mediaItems exist:", mediaItems);
            }
            return;
        }

        galleryGrid.innerHTML = ''; // Clear previous items for fresh rendering

        // Iterate over groupedMedia (Map) which preserves the order of months
        // (since mediaItems were pre-sorted and Map maintains insertion order)
        for (const [monthYear, itemsInGroup] of groupedMedia) {
            // Create a URL-friendly ID for the section. Handles spaces and various characters.
            const sectionId = `section-${monthYear.replace(/[^a-zA-Z0-9-_]/g, '-').toLowerCase()}`;

            const monthSectionDiv = document.createElement('div');
            monthSectionDiv.className = 'month-section';
            monthSectionDiv.id = sectionId; // ID for direct navigation

            const titleHeader = document.createElement('h2');
            titleHeader.className = 'month-year-divider-header'; // Class for styling the header
            titleHeader.textContent = monthYear;
            monthSectionDiv.appendChild(titleHeader);

            const hr = document.createElement('hr');
            hr.className = 'month-divider-line'; // Class for styling the <hr>
            monthSectionDiv.appendChild(hr);

            const monthGridDiv = document.createElement('div');
            // Apply 'photo-items-grid' for the grid layout of thumbnails.
            // 'gallery-grid-month' can be kept for any additional specific styling for these month-based grids.
            monthGridDiv.className = 'photo-items-grid gallery-grid-month';
            monthSectionDiv.appendChild(monthGridDiv);

            itemsInGroup.forEach((item) => {
                const link = document.createElement('a');
                link.href = `/image/${item.sha256}`;

                // Use actual dimensions if available and valid, otherwise let PhotoSwipe auto-detect (by setting to 0 or omitting)
                let pswpWidth = 0;
                let pswpHeight = 0;

                if (item.width && Number.isFinite(item.width) && item.width > 0) {
                    pswpWidth = item.width;
                } else {
                    console.warn(`Item ${item.sha256} missing or has invalid width: ${item.width}. PhotoSwipe will attempt to auto-detect.`);
                }

                if (item.height && Number.isFinite(item.height) && item.height > 0) {
                    pswpHeight = item.height;
                } else {
                    console.warn(`Item ${item.sha256} missing or has invalid height: ${item.height}. PhotoSwipe will attempt to auto-detect.`);
                }

                link.dataset.pswpWidth = pswpWidth;
                link.dataset.pswpHeight = pswpHeight;
                link.dataset.filename = item.filename || 'Media file';

                const img = document.createElement('img');
                img.src = `/thumbnail/${item.sha256}`;
                img.alt = item.filename || 'Media thumbnail';
                img.loading = 'lazy';
                link.appendChild(img);

                const galleryItemWrapper = document.createElement('div');
                galleryItemWrapper.className = 'gallery-item'; // This class styles individual items
                galleryItemWrapper.appendChild(link);
                monthGridDiv.appendChild(galleryItemWrapper); // Append item to the month-specific grid
            });
            galleryGrid.appendChild(monthSectionDiv); // Append the entire month section to the main gallery container
        }
    }

    function initializePhotoSwipe() {
        if (lightbox) {
            lightbox.destroy(); // Destroy existing instance if any
        }
        // The main galleryGrid element is the top-level container passed to PhotoSwipe.
        // The `children` selector tells PhotoSwipe where to find the <a> tags within that container.
        // Since <a> tags are now inside .gallery-item divs, this selector is more specific.
        lightbox = new PhotoSwipeLightbox({
            gallery: '#gallery-grid',
            children: '.gallery-item > a', // Find <a> tags that are direct children of .gallery-item
            pswpModule: () => import('./photoswipe.esm.js'),
            // Optional: Add caption plugin
            // dataSource: mediaItems.map(item => ({
            //     src: `/image/${item.sha256}`,
            //     w: item.width,
            //     h: item.height,
            //     title: item.filename || '' // For caption
            // })),
            // getThumbBoundsFn: (index) => {
            //     const thumbnail = galleryGrid.querySelectorAll('img')[index];
            //     if (!thumbnail) return null;
            //     const pageYScroll = window.pageYOffset || document.documentElement.scrollTop;
            //     const rect = thumbnail.getBoundingClientRect();
            //     return {x: rect.left, y: rect.top + pageYScroll, w: rect.width};
            // }
            initialZoomLevel: 'fit', // Ensure images fit within the viewport, maintaining aspect ratio
        });

        // The 'custom-caption' element that displayed "Caption text" has been removed.
        // PhotoSwipe can display captions if the 'alt' attribute of the thumbnail image (<img>)
        // is populated, or if a 'title' is provided in a dataSource.
        // The current code sets img.alt = item.filename || 'Media thumbnail';
        // which PhotoSwipe might use by default if its caption module is active.
        // If captions are desired, ensure item.filename is suitable or explore
        // PhotoSwipe's dedicated caption options further.

        lightbox.init();
        console.log("PhotoSwipe Lightbox initialized:", lightbox); // Basic check 1

        // Basic check 2: Verify data attributes on gallery items after a short delay
        setTimeout(() => {
            const galleryItems = galleryGrid.querySelectorAll('a');
            if (galleryItems.length > 0) {
                let allItemsHaveDimensions = true;
                galleryItems.forEach((item, index) => {
                    const hasWidth = item.dataset.pswpWidth && !isNaN(parseInt(item.dataset.pswpWidth));
                    const hasHeight = item.dataset.pswpHeight && !isNaN(parseInt(item.dataset.pswpHeight));
                    if (!hasWidth || !hasHeight) {
                        allItemsHaveDimensions = false;
                        console.warn(`Gallery item ${index} is missing pswpWidth or pswpHeight. Width: ${item.dataset.pswpWidth}, Height: ${item.dataset.pswpHeight}`);
                    }
                });
                if (allItemsHaveDimensions) {
                    console.log(`Verified ${galleryItems.length} gallery items: all have pswpWidth and pswpHeight attributes.`);
                } else {
                    console.error("Some gallery items are missing required PhotoSwipe dimension attributes.");
                }
            } else if (mediaItems.length > 0) { // mediaItems were fetched but not rendered as links
                 console.warn("Gallery items (<a> tags) not found for attribute check, but mediaItems exist. Check displayMedia function.");
            } else {
                // No media items, so no links to check, which is fine.
                console.log("No media items to check for PhotoSwipe attributes.");
            }
        }, 1000); // Delay to allow DOM update
    }

    function displayNavigationSidebar(groupedMedia) {
        const sidebar = document.getElementById('navigation-sidebar');
        if (!sidebar) {
            console.error("Navigation sidebar element not found.");
            return;
        }

        // Remove only the dynamic parts: the list of links (ul) and the "no dates" message (p)
        const existingNavList = sidebar.querySelector('ul');
        if (existingNavList) {
            existingNavList.remove();
        }
        const existingNoDatesMessage = sidebar.querySelector('p.no-dates-message'); // Add a class to target it
        if (existingNoDatesMessage) {
            existingNoDatesMessage.remove();
        }

        if (!groupedMedia || groupedMedia.size === 0) {
            const noDatesMessage = document.createElement('p');
            noDatesMessage.className = 'no-dates-message'; // Add class for specific removal
            noDatesMessage.textContent = 'No dates to navigate.';
            sidebar.appendChild(noDatesMessage);
            return;
        }

        const navList = document.createElement('ul'); // Use a list for semantic navigation links

        for (const monthYear of groupedMedia.keys()) {
            const listItem = document.createElement('li');
            const link = document.createElement('a');

            // Generate sectionId to match the one created in displayMedia
            const sectionId = `section-${monthYear.replace(/[^a-zA-Z0-9-_]/g, '-').toLowerCase()}`;
            link.href = `#${sectionId}`;
            link.textContent = monthYear;

            link.addEventListener('click', function(event) {
                event.preventDefault();
                const targetId = this.getAttribute('href').substring(1);
                const targetElement = document.getElementById(targetId);
                if (targetElement) {
                    targetElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
                } else {
                    console.warn(`Target element with ID '${targetId}' not found for sidebar navigation.`);
                }
            });

            listItem.appendChild(link);
            navList.appendChild(listItem);
        }
        sidebar.appendChild(navList);
    }

    // Initial fetch
    fetchMediaList();

    // Sidebar Toggle Functionality
    const sidebarToggleButton = document.getElementById('sidebarToggleButton');
    const navigationSidebar = document.getElementById('navigation-sidebar');
    const iconMenu = sidebarToggleButton ? sidebarToggleButton.querySelector('.icon-menu') : null;
    const iconClose = sidebarToggleButton ? sidebarToggleButton.querySelector('.icon-close') : null;
    const closeDrawerButton = document.getElementById('closeDrawerButton');
    // const body = document.body; // For overlay class

    function updateSidebarStateForScreenSize() {
        const isDesktop = window.innerWidth >= 768;

        if (isDesktop) {
            // Desktop: Ensure sidebar is visible (remove 'expanded' class, CSS handles desktop layout)
            // and button is correctly not managing it.
            if (navigationSidebar) {
                navigationSidebar.classList.remove('expanded'); // Should rely on default desktop styles
            }
            if (sidebarToggleButton) {
                 sidebarToggleButton.setAttribute('aria-expanded', 'true'); // Or 'false' if sidebar is considered 'closed' by default on desktop too
                 // Icon state for desktop if button were visible (it's hidden by CSS)
                 // if (iconMenu) iconMenu.style.display = 'none';
                 // if (iconClose) iconClose.style.display = 'block';
            }
            // if (body) body.classList.remove('sidebar-open-overlay');
        } else {
            // Mobile: Ensure sidebar is collapsed by default, button shows "open"
            // The 'expanded' class is what shows it. So, it should not be present initially.
            if (navigationSidebar && !navigationSidebar.classList.contains('expanded')) { // only adjust if not already expanded by user
                if (sidebarToggleButton) sidebarToggleButton.setAttribute('aria-expanded', 'false');
                if (iconMenu) {
                    iconMenu.classList.add('visible');
                    iconMenu.classList.remove('hidden');
                }
                if (iconClose) {
                    iconClose.classList.add('hidden');
                    iconClose.classList.remove('visible');
                }
            } else if (navigationSidebar && navigationSidebar.classList.contains('expanded')) {
                // If mobile and sidebar is expanded (e.g. user action, then resize)
                // Ensure icons reflect the expanded state
                if (sidebarToggleButton) sidebarToggleButton.setAttribute('aria-expanded', 'true');
                if (iconMenu) {
                    iconMenu.classList.add('hidden');
                    iconMenu.classList.remove('visible');
                }
                if (iconClose) {
                    iconClose.classList.add('visible');
                    iconClose.classList.remove('hidden');
                }
                // Or, force close:
                // navigationSidebar.classList.remove('expanded');
                // sidebarToggleButton.setAttribute('aria-expanded', 'false');
                // iconMenu.style.display = 'block';
                // iconClose.style.display = 'none';
            }
        }
    }

    if (sidebarToggleButton && navigationSidebar && iconMenu && iconClose) {
        sidebarToggleButton.addEventListener('click', () => {
            const isExpanded = navigationSidebar.classList.toggle('expanded');
            sidebarToggleButton.setAttribute('aria-expanded', String(isExpanded));
            // body.classList.toggle('sidebar-open-overlay', isExpanded);

            if (isExpanded) {
                iconMenu.classList.add('hidden');
                iconMenu.classList.remove('visible');
                iconClose.classList.add('visible');
                iconClose.classList.remove('hidden');
            } else {
                iconMenu.classList.add('visible');
                iconMenu.classList.remove('hidden');
                iconClose.classList.add('hidden');
                iconClose.classList.remove('visible');
            }
        });

        // Initial state based on screen size
        updateSidebarStateForScreenSize(); // Call on load

        // Update on resize
        window.addEventListener('resize', updateSidebarStateForScreenSize);

        // Close sidebar when a navigation link is clicked (on mobile)
        navigationSidebar.addEventListener('click', (event) => {
            if (window.innerWidth < 768 && event.target.tagName === 'A') {
                navigationSidebar.classList.remove('expanded');
                sidebarToggleButton.setAttribute('aria-expanded', 'false');
                // body.classList.remove('sidebar-open-overlay');
                iconMenu.classList.add('visible');
                iconMenu.classList.remove('hidden');
                iconClose.classList.add('hidden');
                iconClose.classList.remove('visible');
            }
        });

        if (closeDrawerButton) {
            closeDrawerButton.addEventListener('click', () => {
                if (navigationSidebar.classList.contains('expanded')) {
                    navigationSidebar.classList.remove('expanded');
                    sidebarToggleButton.setAttribute('aria-expanded', 'false');
                    // body.classList.remove('sidebar-open-overlay'); // if overlay was used
                    if (iconMenu && iconClose) {
                        iconMenu.classList.add('visible');
                        iconMenu.classList.remove('hidden');
                        iconClose.classList.add('hidden');
                        iconClose.classList.remove('visible');
                    }
                }
            });
        }

    } else {
        console.warn('Sidebar toggle button or navigation sidebar not found. Sidebar functionality disabled.');
        if (!iconMenu || !iconClose) {
            console.warn('Sidebar toggle icons not found.');
        }
    }


    // Upload functionality
    const uploadButton = document.getElementById('uploadButton');
    const fileInput = document.getElementById('fileInput');
    const uploadProgressOverlay = document.getElementById('uploadProgressOverlay');
    const uploadProgressText = document.getElementById('uploadProgressText');
    const progressBar = document.getElementById('progressBar');

    if (uploadButton && fileInput && uploadProgressOverlay && uploadProgressText && progressBar) {
        uploadButton.addEventListener('click', () => {
            fileInput.click(); // Trigger hidden file input
        });

        fileInput.addEventListener('change', async (event) => {
            const files = event.target.files;
            if (files.length === 0) {
                return;
            }

            uploadProgressOverlay.style.display = 'flex';
            let filesUploaded = 0;
            const totalFiles = files.length;
            uploadProgressText.textContent = `Preparing to upload ${totalFiles} file(s)...`;
            progressBar.style.width = '0%';

            for (let i = 0; i < totalFiles; i++) {
                const file = files[i];
                uploadProgressText.textContent = `Uploading ${file.name} (${filesUploaded + 1} of ${totalFiles})...`;

                const formData = new FormData();
                formData.append('file', file, file.name); // 'file' is a common field name, server must expect this

                try {
                    // Corrected endpoint: /image/filename
                    const response = await fetch(`/image/${encodeURIComponent(file.name)}`, {
                        method: 'PUT',
                        body: formData,
                        // Headers like 'Content-Type': 'multipart/form-data' are usually set automatically by fetch for FormData
                        // If the server expects 'Content-Disposition' or filename in a specific way, this might need adjustment
                    });

                    if (!response.ok) {
                        // Try to get error message from server response
                        let errorMsg = `HTTP error! status: ${response.status}`;
                        try {
                            const errorData = await response.json();
                            errorMsg = errorData.error || errorMsg;
                        } catch (e) { /* ignore if response is not json */ }
                        throw new Error(errorMsg);
                    }

                    // Assuming server returns JSON with a success message or details
                    // const result = await response.json();
                    // console.log(`Uploaded ${file.name}:`, result);

                    filesUploaded++;
                    const progressPercentage = (filesUploaded / totalFiles) * 100;
                    progressBar.style.width = `${progressPercentage}%`;
                    uploadProgressText.textContent = `Uploaded ${file.name} (${filesUploaded} of ${totalFiles}).`;

                } catch (error) {
                    console.error(`Error uploading ${file.name}:`, error);
                    uploadProgressText.textContent = `Error uploading ${file.name}: ${error.message}. Stopping.`;
                    // Optionally, allow user to close dialog or retry
                    // For now, just stop and leave the dialog open with the error
                    fileInput.value = ''; // Reset file input
                    return; // Stop uploading further files on error
                }
            }

            if (filesUploaded === totalFiles) {
                uploadProgressText.textContent = `Successfully uploaded ${totalFiles} file(s)!`;
                progressBar.style.width = '100%';
                fetchMediaList(); // Refresh gallery
            }

            setTimeout(() => {
                uploadProgressOverlay.style.display = 'none';
                progressBar.style.width = '0%'; // Reset progress bar
                uploadProgressText.textContent = 'Progress: 0/0'; // Reset text
            }, 3000); // Hide overlay after 3 seconds

            fileInput.value = ''; // Reset file input to allow selecting the same file again
        });
    } else {
        console.error('Upload UI elements not found. Upload functionality will not work.');
    }

    // Search functionality
    const searchInput = document.getElementById('searchInput');
    const searchButton = document.getElementById('searchButton');
    const resetButton = document.getElementById('resetButton');

    if (searchInput && searchButton && resetButton) {
        searchButton.addEventListener('click', handleSearch);
        searchInput.addEventListener('keyup', (event) => {
            if (event.key === 'Enter') {
                handleSearch();
            }
        });
        resetButton.addEventListener('click', () => {
            searchInput.value = '';
            fetchMediaList();
        });

        async function handleSearch() {
            const query = searchInput.value.trim();
            if (!query) {
                return;
            }

            let url;
            const parts = query.split(':').map(p => p.trim());
            const command = parts[0].toLowerCase();
            const value = parts[1];

            if (command === 'date' && value) {
                url = `/list/date/${value}`;
            } else if (command === 'between' && value) {
                const dates = value.split(',').map(d => d.trim());
                if (dates.length === 2) {
                    url = `/list/daterange/${dates[0]}/${dates[1]}`;
                }
            } else if (command === 'location' && value) {
                url = `/list/location/${value}`;
            } else {
                alert('Invalid query format. Use "date: YYYY-MM-DD", "between: YYYY-MM-DD, YYYY-MM-DD", or "location: city".');
                return;
            }

            if (url) {
                try {
                    const response = await fetch(url);
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    const data = await response.json();
                    const searchResultItems = Object.entries(data).map(([sha256, itemData]) => ({
                        sha256,
                        ...itemData
                    }));
                    searchResultItems.sort((a, b) => (b.original_creation_date || 0) - (a.original_creation_date || 0));

                    const groupedMedia = groupMediaByMonthYear(searchResultItems);
                    displayMedia(groupedMedia);
                    initializePhotoSwipe();
                    displayNavigationSidebar(groupedMedia);
                } catch (error) {
                    console.error("Error fetching search results:", error);
                    galleryGrid.innerHTML = '<p>Error loading search results. Please try again later.</p>';
                }
            }
        }
    }

    // Settings functionality
    const settingsButton = document.getElementById('settingsButton');
    const settingsOverlay = document.getElementById('settingsOverlay');
    const settingsForm = document.getElementById('settingsForm');
    const cancelSettingsButton = document.getElementById('cancelSettings');
    const settingsError = document.getElementById('settingsError');
    const saveSettingsButton = document.getElementById('saveSettings');
    const archivalBackend = document.getElementById('archivalBackend');
    const archivalBucket = document.getElementById('archivalBucket');

    function validateSettings() {
        if (saveSettingsButton && archivalBackend && archivalBucket) {
            const isArchivalOn = archivalBackend.value !== 'Off';
            const isBucketEmpty = archivalBucket.value.trim() === '';
            saveSettingsButton.disabled = isArchivalOn && isBucketEmpty;
        }
    }

    if (settingsButton && settingsOverlay && settingsForm && cancelSettingsButton && saveSettingsButton) {
        if (archivalBackend && archivalBucket) {
            archivalBackend.addEventListener('change', validateSettings);
            archivalBucket.addEventListener('input', validateSettings);
        }

        settingsButton.addEventListener('click', async () => {
            try {
                const response = await fetch('/api/settings');
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                const settings = await response.json();
                document.getElementById('rescanInterval').value = settings.rescan_interval;
                document.getElementById('taggingModel').value = settings.tagging_model;
                archivalBackend.value = settings.archival_backend;
                archivalBucket.value = settings.archival_bucket;
                validateSettings(); // Initial validation
                settingsOverlay.style.display = 'flex';
            } catch (error) {
                console.error('Error fetching settings:', error);
                alert('Could not load settings. Please try again later.');
            }
        });

        cancelSettingsButton.addEventListener('click', () => {
            settingsOverlay.style.display = 'none';
            settingsError.style.display = 'none';
        });

        settingsForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            const formData = new FormData(settingsForm);
            const settings = Object.fromEntries(formData.entries());
            settings.rescan_interval = parseInt(settings.rescan_interval, 10);

            try {
                const response = await fetch('/api/settings', {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(settings),
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.description || `HTTP error! status: ${response.status}`);
                }

                settingsOverlay.style.display = 'none';
                settingsError.style.display = 'none';
            } catch (error) {
                console.error('Error saving settings:', error);
                settingsError.textContent = `Error: ${error.message}`;
                settingsError.style.display = 'block';
            }
        });
    }
});
