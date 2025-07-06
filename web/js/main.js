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
            displayMedia();
            initializePhotoSwipe();
        } catch (error) {
            console.error("Error fetching media list:", error);
            if (galleryGrid) {
                galleryGrid.innerHTML = '<p>Error loading media. Please try again later.</p>';
            }
        }
    }

    // Function to display media in the gallery
    function displayMedia() {
        if (!galleryGrid) {
            console.error("Gallery grid element not found.");
            return;
        }
        if (!mediaItems.length) {
            galleryGrid.innerHTML = '<p>No media found.</p>';
            return;
        }

        galleryGrid.innerHTML = ''; // Clear previous items

        mediaItems.forEach((item) => {
            // Create the <a> tag for PhotoSwipe
            const link = document.createElement('a');
            link.href = `/image/${item.sha256}`;
            link.dataset.pswpWidth = item.width;
            link.dataset.pswpHeight = item.height;
            // link.target = '_blank'; // Optional: open in new tab if JS fails

            // Create the <img> thumbnail
            const img = document.createElement('img');
            img.src = `/thumbnail/${item.sha256}`;
            img.alt = item.filename || 'Media thumbnail';
            img.loading = 'lazy';

            link.appendChild(img);

            // Create a div wrapper for styling if needed (like the old .gallery-item)
            const galleryItemWrapper = document.createElement('div');
            galleryItemWrapper.className = 'gallery-item'; // Keep existing class for styling grid
            galleryItemWrapper.appendChild(link);

            galleryGrid.appendChild(galleryItemWrapper);
        });
    }

    function initializePhotoSwipe() {
        if (lightbox) {
            lightbox.destroy(); // Destroy existing instance if any
        }
        lightbox = new PhotoSwipeLightbox({
            gallery: '#gallery-grid', // Parent element of slides
            children: 'a',          // Children elements that trigger PhotoSwipe
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

    // Initial fetch
    fetchMediaList();
});
