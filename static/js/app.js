/**
 * Theme management and global utilities
 */
(function () {
    const key = "edumaster_theme";
    const root = document.documentElement;
    const saved = localStorage.getItem(key);
    const initial = saved || "light";
    root.setAttribute("data-theme", initial);

    document.addEventListener("DOMContentLoaded", () => {
        const toggleBtn = document.getElementById("themeToggle");
        // Labels are usually passed via data attributes or just handled in basics
        // For simplicity, we assume the button text is handled or we toggle classes

        const setLabel = (mode) => {
            if (!toggleBtn) return;
            // The text content is localized in the template, so we might not want to hardcode it here
            // unless we pass it via data attributes.
            // For now, let's just handle the theme switching logic.
            const labelLight = toggleBtn.getAttribute("data-label-light") || "Mode clair";
            const labelDark = toggleBtn.getAttribute("data-label-dark") || "Mode sombre";
            const nextLabel = mode === "dark" ? labelLight : labelDark;
            const nextIcon = mode === "dark" ? "bi-sun-fill" : "bi-moon-stars-fill";
            const icon = toggleBtn.querySelector("[data-theme-icon]");
            const label = toggleBtn.querySelector("[data-theme-label]");

            if (icon) {
                icon.className = `bi ${nextIcon}`;
            }
            if (label) {
                label.textContent = nextLabel;
            } else {
                toggleBtn.textContent = nextLabel;
            }
            toggleBtn.setAttribute("aria-label", nextLabel);
            toggleBtn.setAttribute("title", nextLabel);
        };

        // Initial set if button exists (it might not if not logged in)
        if (toggleBtn) {
            setLabel(initial);
            toggleBtn.addEventListener("click", () => {
                const current = root.getAttribute("data-theme") || "light";
                const next = current === "dark" ? "light" : "dark";
                root.setAttribute("data-theme", next);
                localStorage.setItem(key, next);
                setLabel(next);
            });
        }
    });

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
