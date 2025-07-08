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
        });

        // Add caption using PhotoSwipe's caption plugin (optional, requires more setup or using title attribute)
        // For simplicity, PhotoSwipe can use the 'alt' attribute of the <img> or a more complex setup.
        // The default behavior might be sufficient if 'alt' is descriptive.
        // Or, using a dynamic data source to provide titles explicitly.

        // Example for adding titles dynamically if needed, though might be complex
        // This would require using the dataSource option or PhotoSwipe's API
        lightbox.on('uiRegister', () => {
            lightbox.pswp.ui.registerElement({
                name: 'custom-caption',
                order: 9,
                isButton: false,
                appendTo: 'root',
                html: 'Caption text',
                onInit: (el, pswp) => {
                    pswp.on('change', () => {
                        const currSlideElement = pswp.currSlide.data.element;
                        let captionHTML = '';
                        if (currSlideElement) {
                            // Find the corresponding media item to get the filename
                            // This assumes your slides are <a> elements and you can trace back
                            const imgElement = currSlideElement.querySelector('img');
                            if (imgElement) {
                                captionHTML = imgElement.alt || '';
                            }
                        }
                        // el.innerHTML = captionHTML || ''; // This is a simple example
                        // A more robust way is to use PhotoSwipe's built-in caption elements
                        // or provide data.title in the dataSource
                        const item = mediaItems[pswp.currIndex];
                        if (item && item.filename) {
                           // This is a placeholder for how you might update a custom caption element.
                           // PhotoSwipe's own caption handling is preferred.
                           // For PhotoSwipe's built-in caption, ensure 'alt' on thumbnail or 'title' in dataSource.
                        }
                    });
                }
            });
        });


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
        sidebar.innerHTML = ''; // Clear previous links

        if (!groupedMedia || groupedMedia.size === 0) {
            sidebar.innerHTML = '<p>No dates to navigate.</p>'; // Or just leave it empty
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
                    const response = await fetch('/put', { // Endpoint as per user requirement
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
});
