document.addEventListener("DOMContentLoaded", function () {
    const root = document.documentElement;
    const btn = document.getElementById("theme-toggle");
    const savedTheme = localStorage.getItem("nexus-theme");
    const backBtn = document.getElementById("go-back-btn");

    if (savedTheme === "dark") {
        root.classList.add("dark");
        updateThemeButton("dark");
    } else {
        updateThemeButton("light");
    }

    if (btn) {
        btn.addEventListener("click", function () {
            root.classList.toggle("dark");
            const isDark = root.classList.contains("dark");

            if (isDark) {
                localStorage.setItem("nexus-theme", "dark");
                updateThemeButton("dark");
            } else {
                localStorage.setItem("nexus-theme", "light");
                updateThemeButton("light");
            }
        });
    }

    if (backBtn) {
        backBtn.addEventListener("click", function () {
            if (window.history.length > 1) {
                window.history.back();
            } else {
                window.location.href = "/";
            }
        });
    }

    function updateThemeButton(theme) {
        if (!btn) return;

        if (theme === "dark") {
            btn.innerHTML = `
                <svg class="theme-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <circle cx="12" cy="12" r="4"></circle>
                    <path d="M12 2v2"></path>
                    <path d="M12 20v2"></path>
                    <path d="m4.93 4.93 1.41 1.41"></path>
                    <path d="m17.66 17.66 1.41 1.41"></path>
                    <path d="M2 12h2"></path>
                    <path d="M20 12h2"></path>
                    <path d="m6.34 17.66-1.41 1.41"></path>
                    <path d="m19.07 4.93-1.41 1.41"></path>
                </svg>
                <span>Modo claro</span>
            `;
        } else {
            btn.innerHTML = `
                <svg class="theme-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M21 12.79A9 9 0 1 1 11.21 3A7 7 0 0 0 21 12.79z"></path>
                </svg>
                <span>Modo escuro</span>
            `;
        }
    }

    function updateDateTime() {
        const dateEl = document.getElementById("live-date");
        const timeEl = document.getElementById("live-time");

        if (!dateEl || !timeEl) return;

        const now = new Date();

        const dias = [
            "Domingo", "Segunda-feira", "Terça-feira",
            "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado"
        ];

        const diaSemana = dias[now.getDay()];
        const dia = String(now.getDate()).padStart(2, "0");
        const mes = String(now.getMonth() + 1).padStart(2, "0");
        const ano = now.getFullYear();

        const horas = String(now.getHours()).padStart(2, "0");
        const minutos = String(now.getMinutes()).padStart(2, "0");
        const segundos = String(now.getSeconds()).padStart(2, "0");

        dateEl.textContent = `${diaSemana}, ${dia}/${mes}/${ano}`;
        timeEl.textContent = `${horas}:${minutos}:${segundos}`;
    }

    updateDateTime();
    setInterval(updateDateTime, 1000);

    document.querySelectorAll(".toast").forEach(function (toast, index) {
        setTimeout(function () {
            closeToast(toast);
        }, 3400 + index * 250);
    });

    document.querySelectorAll(".toast-close").forEach(function (button) {
        button.addEventListener("click", function () {
            const toast = button.closest(".toast");
            if (toast) closeToast(toast);
        });
    });

    function closeToast(toast) {
        toast.classList.add("toast-hide");
        setTimeout(function () {
            toast.remove();
        }, 260);
    }

    const confirmModal = document.getElementById("confirm-delete-modal");
    const confirmText = document.getElementById("confirm-delete-text");
    const confirmProceed = document.getElementById("confirm-delete-proceed");
    const confirmCancelButtons = document.querySelectorAll(".js-close-confirm-modal");
    let currentDeleteForm = null;

    document.querySelectorAll(".js-confirm-delete").forEach(function (form) {
        form.addEventListener("submit", function (event) {
            if (!confirmModal || form.dataset.confirmed === "true") {
                form.dataset.confirmed = "false";
                return;
            }

            event.preventDefault();
            currentDeleteForm = form;

            const message = form.dataset.confirmMessage || "Deseja continuar?";
            if (confirmText) {
                confirmText.textContent = message;
            }

            confirmModal.classList.add("active");
        });
    });

    if (confirmProceed) {
        confirmProceed.addEventListener("click", function () {
            if (currentDeleteForm) {
                currentDeleteForm.dataset.confirmed = "true";
                currentDeleteForm.submit();
            }
        });
    }

    confirmCancelButtons.forEach(function (button) {
        button.addEventListener("click", function () {
            if (confirmModal) {
                confirmModal.classList.remove("active");
            }
            currentDeleteForm = null;
        });
    });

    if (confirmModal) {
        confirmModal.addEventListener("click", function (event) {
            if (event.target === confirmModal) {
                confirmModal.classList.remove("active");
                currentDeleteForm = null;
            }
        });
    }
});