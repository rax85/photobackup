document.addEventListener('DOMContentLoaded', () => {
    const galleryGrid = document.getElementById('gallery-grid');
    const overlayViewer = document.getElementById('overlay-viewer');
    const overlayImage = document.getElementById('overlay-image');
    const closeBtn = overlayViewer.querySelector('.close-btn');
    const prevBtn = overlayViewer.querySelector('.prev-btn');
    const nextBtn = overlayViewer.querySelector('.next-btn');
    const captionDiv = overlayViewer.querySelector('.caption');

    let mediaItems = []; // To store all media data from /list
    let currentImageIndex = -1;

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

        mediaItems.forEach((item, index) => {
            const galleryItem = document.createElement('div');
            galleryItem.className = 'gallery-item';
            galleryItem.dataset.index = index; // Store index for easy lookup

            const img = document.createElement('img');
            // Use a placeholder or loading indicator if desired
            // For now, directly set the thumbnail URL
            img.src = `/thumbnail/${item.sha256}`;
            img.alt = item.filename || 'Media thumbnail';
            // Consider adding lazy loading for images here if performance becomes an issue
            img.loading = 'lazy';

            galleryItem.appendChild(img);
            galleryGrid.appendChild(galleryItem);

            galleryItem.addEventListener('click', () => {
                openOverlay(index);
            });
        });
    }

    // Function to open the overlay viewer
    function openOverlay(index) {
        if (index < 0 || index >= mediaItems.length) {
            console.error("Invalid index for overlay:", index);
            return;
        }
        currentImageIndex = index;
        const item = mediaItems[currentImageIndex];

        overlayImage.src = `/image/${item.sha256}`;
        overlayImage.alt = item.filename || 'Full-sized media';
        captionDiv.textContent = item.filename || '';

        // overlayViewer.style.display = 'flex'; // Replaced by class toggle
        overlayViewer.classList.add('visible');
        document.body.style.overflow = 'hidden'; // Prevent background scrolling
        updateNavButtons();
    }

    // Function to close the overlay viewer
    function closeOverlay() {
        // overlayViewer.style.display = 'none'; // Replaced by class toggle
        overlayViewer.classList.remove('visible');
        document.body.style.overflow = ''; // Restore background scrolling
        overlayImage.src = ''; // Clear image to free memory
        currentImageIndex = -1;
    }

    // Function to show the previous image
    function showPrevImage() {
        if (currentImageIndex > 0) {
            openOverlay(currentImageIndex - 1);
        }
    }

    // Function to show the next image
    function showNextImage() {
        if (currentImageIndex < mediaItems.length - 1) {
            openOverlay(currentImageIndex + 1);
        }
    }

    // Function to update visibility of nav buttons
    function updateNavButtons() {
        prevBtn.style.display = currentImageIndex > 0 ? 'flex' : 'none';
        nextBtn.style.display = currentImageIndex < mediaItems.length - 1 ? 'flex' : 'none';
    }

    // Event Listeners
    closeBtn.addEventListener('click', closeOverlay);
    prevBtn.addEventListener('click', showPrevImage);
    nextBtn.addEventListener('click', showNextImage);

    // Keyboard navigation for overlay
    document.addEventListener('keydown', (e) => {
        if (overlayViewer.classList.contains('visible')) {
            if (e.key === 'Escape') {
                closeOverlay();
            } else if (e.key === 'ArrowLeft') {
                showPrevImage();
            } else if (e.key === 'ArrowRight') {
                showNextImage();
            }
        }
    });

    // Initial fetch
    fetchMediaList();
});
