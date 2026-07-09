/**
 * Global interface utilities
 */
(function () {
    // Global spinner for forms
    document.addEventListener("submit", (e) => {
        const form = e.target;
        // Skip if form has 'no-loader' class
        if (form.classList.contains("no-loader")) return;

        const btn = form.querySelector('button[type="submit"]');
        if (btn && !btn.classList.contains("no-loader")) {
            // Check if already submitting
            if (btn.classList.contains("disabled")) {
                e.preventDefault();
                return;
            }

            const w = btn.offsetWidth;
            btn.style.width = `${w}px`; // Maintain width
            btn.classList.add("disabled");
            // Save original text if needed, but for now just replace
            btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';
        }
    });
})();
