/* Food Bridge — progressive enhancement */
(function () {
    "use strict";

    // ------------------------------------------------------------------
    // Dashboard sidebar
    // ------------------------------------------------------------------
    const body = document.body;
    const sidebar = document.getElementById("dashSidebar");

    function closeSidebar() {
        body.classList.remove("sidebar-open");
        document.querySelectorAll("[data-sidebar-toggle]").forEach((btn) =>
            btn.setAttribute("aria-expanded", "false")
        );
    }

    document.querySelectorAll("[data-sidebar-toggle]").forEach((button) => {
        button.setAttribute("aria-expanded", "false");
        button.addEventListener("click", () => {
            const open = body.classList.toggle("sidebar-open");
            button.setAttribute("aria-expanded", open ? "true" : "false");
        });
    });
    document.querySelectorAll("[data-sidebar-close]").forEach((el) =>
        el.addEventListener("click", closeSidebar)
    );
    if (sidebar) {
        sidebar.querySelectorAll("a").forEach((link) =>
            link.addEventListener("click", () => {
                if (window.innerWidth < 992) closeSidebar();
            })
        );
    }
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closeSidebar();
    });
    window.addEventListener("resize", () => {
        if (window.innerWidth >= 992) closeSidebar();
    });

    // ------------------------------------------------------------------
    // Flash messages: dismiss after a while
    // ------------------------------------------------------------------
    document.querySelectorAll(".flash-alert").forEach((alert, index) => {
        window.setTimeout(() => {
            if (window.bootstrap && window.bootstrap.Alert) {
                window.bootstrap.Alert.getOrCreateInstance(alert).close();
            }
        }, 6500 + index * 500);
    });

    // ------------------------------------------------------------------
    // Tooltips
    // ------------------------------------------------------------------
    if (window.bootstrap && window.bootstrap.Tooltip) {
        document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
            new window.bootstrap.Tooltip(el);
        });
    }

    // ------------------------------------------------------------------
    // Confirmation on destructive / workflow actions
    // ------------------------------------------------------------------
    document.addEventListener("submit", (event) => {
        const form = event.target;
        const message = form.getAttribute("data-confirm");
        if (message && !window.confirm(message)) {
            event.preventDefault();
            return;
        }
        // Prevent accidental double submission of workflow forms.
        if (form.hasAttribute("data-submit-once") && form.dataset.submitting === "1") {
            event.preventDefault();
            return;
        }
        if (form.hasAttribute("data-submit-once")) {
            form.dataset.submitting = "1";
            const button = form.querySelector("button[type=submit]");
            if (button) {
                button.disabled = true;
                const original = button.innerHTML;
                button.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Working…';
                // Re-enable if the browser prevents navigation (e.g. server validation).
                window.setTimeout(() => {
                    button.disabled = false;
                    button.innerHTML = original;
                    form.dataset.submitting = "0";
                }, 8000);
            }
        }
    });

    // ------------------------------------------------------------------
    // Image upload preview
    // ------------------------------------------------------------------
    document.querySelectorAll("[data-image-input]").forEach((input) => {
        const zone = input.closest(".upload-zone");
        if (!zone) return;
        const preview = zone.querySelector(".upload-preview");
        zone.addEventListener("click", (event) => {
            if (event.target !== input) input.click();
        });
        input.addEventListener("change", () => {
            const file = input.files && input.files[0];
            if (!file || !preview) return;
            const url = URL.createObjectURL(file);
            preview.innerHTML = '<img alt="Selected food image">';
            preview.querySelector("img").src = url;
        });
    });

    // ------------------------------------------------------------------
    // Registration role-specific fields
    // ------------------------------------------------------------------
    const registerForm = document.querySelector("[data-register-form]");
    if (registerForm) {
        const roleInputs = registerForm.querySelectorAll('input[name="role"]');
        const groups = registerForm.querySelectorAll("[data-role-fields]");
        function syncRoleFields() {
            const selected = registerForm.querySelector('input[name="role"]:checked');
            const role = selected ? selected.value : "donor";
            groups.forEach((group) => {
                const show = group.dataset.roleFields === role;
                group.hidden = !show;
                group.querySelectorAll("input, select").forEach((input) => {
                    if (show && input.dataset.wasRequired === "1") input.required = true;
                    if (!show) {
                        if (input.required) input.dataset.wasRequired = "1";
                        input.required = false;
                    }
                });
            });
        }
        roleInputs.forEach((input) => input.addEventListener("change", syncRoleFields));
        syncRoleFields();
    }

    // ------------------------------------------------------------------
    // Expiry countdowns (updates every 30 seconds)
    // ------------------------------------------------------------------
    function renderCountdown(el) {
        const timestamp = el.getAttribute("data-expires-at");
        if (!timestamp) return;
        const expiry = new Date(timestamp).getTime();
        if (Number.isNaN(expiry)) return;
        const diff = expiry - Date.now();
        if (diff <= 0) {
            el.textContent = "Expired";
            el.classList.add("text-danger");
            return;
        }
        const totalMinutes = Math.floor(diff / 60000);
        const days = Math.floor(totalMinutes / 1440);
        const hours = Math.floor((totalMinutes % 1440) / 60);
        const minutes = totalMinutes % 60;
        let text;
        if (days > 0) text = days + "d " + hours + "h left";
        else if (hours > 0) text = hours + "h " + minutes + "m left";
        else text = Math.max(1, minutes) + "m left";
        el.textContent = text;
        if (totalMinutes <= 120) el.classList.add("text-danger");
    }
    function refreshCountdowns() {
        document.querySelectorAll("[data-expires-at]").forEach(renderCountdown);
    }
    refreshCountdowns();
    window.setInterval(refreshCountdowns, 30000);

    // ------------------------------------------------------------------
    // Live donation status polling (actual AJAX polling, not a mock)
    // ------------------------------------------------------------------
    const statusTracker = document.querySelector("[data-donation-status]");
    if (statusTracker) {
        const endpoint = statusTracker.getAttribute("data-status-url");
        const initialStatus = statusTracker.getAttribute("data-current-status");
        const activeStatuses = [
            "available",
            "requested",
            "accepted",
            "assigned",
            "picked_up",
            "delivered",
        ];
        let polling = false;
        async function pollStatus() {
            if (polling || document.hidden || !endpoint) return;
            if (activeStatuses.indexOf(initialStatus) === -1) return;
            polling = true;
            try {
                const response = await fetch(endpoint, {
                    headers: { Accept: "application/json" },
                    credentials: "same-origin",
                });
                if (!response.ok) return;
                const data = await response.json();
                if (data.status !== initialStatus) {
                    // A workflow transition happened: reload so all role-specific
                    // actions, forms and permissions reflect the new state.
                    window.location.reload();
                }
            } catch (error) {
                // Network hiccups are non-fatal; the next poll retries.
            } finally {
                polling = false;
            }
        }
        window.setInterval(pollStatus, 25000);
        document.addEventListener("visibilitychange", () => {
            if (!document.hidden) pollStatus();
        });
    }

    // ------------------------------------------------------------------
    // Reveal-on-scroll for landing page sections
    // ------------------------------------------------------------------
    const reveals = document.querySelectorAll(".reveal");
    if (reveals.length && "IntersectionObserver" in window) {
        const observer = new IntersectionObserver(
            (entries, obs) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add("visible");
                        obs.unobserve(entry.target);
                    }
                });
            },
            { threshold: 0.12, rootMargin: "0px 0px -30px 0px" }
        );
        reveals.forEach((el) => observer.observe(el));
    } else {
        reveals.forEach((el) => el.classList.add("visible"));
    }
})();
