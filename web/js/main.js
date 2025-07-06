import PhotoSwipeLightbox from '/lib/photoswipe/photoswipe-lightbox.esm.js';
import PhotoSwipe from '/lib/photoswipe/photoswipe.esm.js';

document.addEventListener('DOMContentLoaded', () => {
    const galleryGrid = document.getElementById('gallery-grid');

    let mediaItems = []; // To store all media data from /list
    let lightbox;

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
                src: `/image/${sha256}`, // URL for full image
                thumbnail: `/thumbnail/${sha256}`, // URL for thumbnail
                width: itemData.width, // Expected from backend update
                height: itemData.height, // Expected from backend update
                alt: itemData.filename || 'Media file',
                ...itemData // Keep other data if needed (e.g., for captions if we add them later)
            }));
            // Sort by original creation date, newest first
            mediaItems.sort((a, b) => (b.original_creation_date || 0) - (a.original_creation_date || 0));
            displayMedia();
            initPhotoSwipe();
        } catch (error) {
            console.error("Error fetching media list:", error);
            galleryGrid.innerHTML = '<p>Error loading media. Please try again later.</p>';
        }
    }

    // Function to display media in the gallery
    function displayMedia() {
        if (!mediaItems.length) {
            galleryGrid.innerHTML = '<p>No media found.</p>';
            return;
        }

        galleryGrid.innerHTML = ''; // Clear previous items

        mediaItems.forEach((item) => {
            const galleryLink = document.createElement('a');
            galleryLink.href = item.src;
            galleryLink.dataset.pswpWidth = item.width || 1200; // Fallback width if not provided
            galleryLink.dataset.pswpHeight = item.height || 800; // Fallback height if not provided
            galleryLink.dataset.pswpType = item.content_type && item.content_type.startsWith('video/') ? 'video' : 'image'; // Basic type detection
            galleryLink.target = '_blank'; // Good practice for links
            galleryLink.className = 'gallery-item'; // Apply styling directly to the link

            const img = document.createElement('img');
            img.src = item.thumbnail;
            img.alt = item.alt;
            img.loading = 'lazy';

            galleryLink.appendChild(img);
            galleryGrid.appendChild(galleryLink);
        });
    }

    function initPhotoSwipe() {
        if (lightbox) {
            lightbox.destroy();
        }
        lightbox = new PhotoSwipeLightbox({
            gallery: '#gallery-grid',
            children: 'a',
            pswpModule: PhotoSwipe,
            // Optional: show hide opacity option, since we removed the old overlay
            showHideAnimationType: 'fade', /* default is 'zoom' */
            // Optional: adjust preloader
            preloaderDelay: 500, // Show preloader after 0.5s
        });

        // Optional: Add custom caption - PhotoSwipe 5 doesn't have built-in caption support in core
        // lightbox.on('uiRegister', function() {
        //   lightbox.pswp.ui.registerElement({
        //     name: 'custom-caption',
        //     order: 9,
        //     isButton: false,
        //     appendTo: 'root',
        //     html: 'Caption text',
        //     onInit: (el, pswp) => {
        //       lightbox.pswp.on('change', () => {
        //         const currSlideElement = lightbox.pswp.currSlide.data;
        //         el.innerHTML = currSlideElement.alt || '';
        //       });
        //     }
        //   });
        // });

        lightbox.init();
    }

    // Initial fetch
    fetchMediaList();
});
