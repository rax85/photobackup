import PhotoSwipeLightbox from './lib/photoswipe/dist/photoswipe-lightbox.esm.js';

document.addEventListener('DOMContentLoaded', () => {
    const galleryGrid = document.getElementById('gallery-grid');
    let mediaItems = []; // To store all media data from /list

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
            console.error('Gallery grid not found');
            return;
        }
        if (!mediaItems.length) {
            galleryGrid.innerHTML = '<p>No media found.</p>';
            return;
        }

        galleryGrid.innerHTML = ''; // Clear previous items

        mediaItems.forEach((item) => {
            // Ensure width and height are available and are numbers
            if (typeof item.width !== 'number' || typeof item.height !== 'number' || item.width <= 0 || item.height <= 0) {
                console.warn('Missing or invalid dimensions for item:', item.filename, item.sha256, `Dims: ${item.width}x${item.height}`);
                // Optionally skip this item or use default dimensions
                // For now, we'll skip it to avoid PhotoSwipe errors
                return;
            }

            const galleryLink = document.createElement('a');
            galleryLink.href = `/image/${item.sha256}`;
            galleryLink.dataset.pswpWidth = item.width;
            galleryLink.dataset.pswpHeight = item.height;
            galleryLink.dataset.cropped = 'true'; // Assuming thumbnails might be cropped
            galleryLink.target = '_blank'; // Fallback for no JS or PhotoSwipe error
            galleryLink.className = 'gallery-item'; // Use existing styling for the link container

            const img = document.createElement('img');
            img.src = `/thumbnail/${item.sha256}`;
            img.alt = item.filename || 'Media thumbnail';
            img.loading = 'lazy';

            galleryLink.appendChild(img);
            galleryGrid.appendChild(galleryLink);
        });
    }

    function initializePhotoSwipe() {
        if (!galleryGrid) return;

        const lightbox = new PhotoSwipeLightbox({
            gallery: '#gallery-grid',
            children: 'a',
            pswpModule: () => import('./lib/photoswipe/dist/photoswipe.esm.js'),
            // Optional: Add a little margin around the image
            padding: { top: 20, bottom: 20, left: 20, right: 20 }
        });
        lightbox.init();
    }

    // Initial fetch
    fetchMediaList();
});
