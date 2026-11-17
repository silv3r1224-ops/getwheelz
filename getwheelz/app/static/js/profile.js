// Profile page controls and owner/mechanic profile cards.

(() => {
    const init = () => {
        // Profile/settings tabs
        const profileCard = document.getElementById("profileCard");
        const editToggleBtn = document.getElementById("editToggleBtn");
        const cancelEditBtn = document.getElementById("cancelEditBtn");
        const profileTab = document.getElementById("profileTab");
        const settingsTab = document.getElementById("settingsTab");
        const tabBtns = document.querySelectorAll("[data-tab-btn]");

        tabBtns.forEach((btn) => {
            btn.addEventListener("click", (event) => {
                event.preventDefault();
                const targetId = btn.getAttribute("data-tab-btn");
                tabBtns.forEach((item) => item.classList.toggle("active", item === btn));
                if (!profileTab || !settingsTab) return;
                const showSettings = targetId === "settingsTab";
                profileTab.classList.toggle("active", !showSettings);
                settingsTab.classList.toggle("active", showSettings);
            });
        });

        editToggleBtn?.addEventListener("click", () => profileCard?.classList.add("is-editing"));
        cancelEditBtn?.addEventListener("click", () => profileCard?.classList.remove("is-editing"));

        // Profile picture modal (exists only on the account profile page)
        const pictureModal = document.getElementById("profilePictureModal");
        window.openProfilePicture = () => pictureModal?.classList.add("active");
        window.closeProfilePicture = () => pictureModal?.classList.remove("active");
        pictureModal?.addEventListener("click", (event) => {
            if (event.target === pictureModal) window.closeProfilePicture();
        });

        // Delete-account confirmation (exists only on the account profile page)
        const deleteBtn = document.getElementById("deleteAccountBtn");
        const deleteForm = document.getElementById("deleteAccountForm");
        const cancelBtn = document.getElementById("cancelDeleteBtn");
        deleteBtn?.addEventListener("click", (event) => {
            event.preventDefault();
            if (!deleteForm) return;
            deleteBtn.style.display = "none";
            deleteForm.classList.add("active");
        });
        cancelBtn?.addEventListener("click", () => {
            deleteForm?.classList.remove("active");
            if (deleteBtn) deleteBtn.style.display = "inline-block";
        });

        // Owner/mechanic card popup. If this page has no popup markup, navigate directly.
        const modal = document.getElementById("profilePop");
        const avatar = document.getElementById("ppAvatar");
        const name = document.getElementById("ppName");
        const role = document.getElementById("ppRole");
        const details = document.getElementById("ppDetails");
        const link = document.getElementById("ppLink");

        const openProfile = (card) => {
            const url = card?.dataset.url;
            if (!url) {
                console.error("Profile card is missing its data-url attribute:", card);
                return;
            }

            // Mechanic dashboard currently has owner cards but no popup markup.
            if (!modal || !avatar || !name || !role || !details || !link) {
                window.location.assign(url);
                return;
            }

            name.textContent = card.dataset.name || "User";
            role.textContent = card.dataset.role || "Member";
            details.replaceChildren();
            avatar.replaceChildren();

            if (card.dataset.picture) {
                const img = document.createElement("img");
                img.src = card.dataset.picture;
                img.alt = name.textContent;
                avatar.appendChild(img);
            } else {
                avatar.textContent = (name.textContent.trim().charAt(0) || "U").toUpperCase();
            }

            const fields = [
                ["Experience", card.dataset.experience],
                ["Status", card.dataset.status],
                ["Member since", card.dataset.since],
                ["Workshops", card.dataset.workshops],
                ["Contact", card.dataset.contact]
            ];
            fields.forEach(([label, value]) => {
                if (!value) return;
                const item = document.createElement("li");
                const labelSpan = document.createElement("span");
                labelSpan.textContent = label;
                const valueSpan = document.createElement("span");
                valueSpan.textContent = value;
                item.append(labelSpan, valueSpan);
                details.appendChild(item);
            });

            link.href = url;
            modal.classList.add("is-open");
        };

        document.addEventListener("click", (event) => {
            const target = event.target;
            if (!(target instanceof Element)) return;
            const card = target.closest(".profile-trigger");
            if (card) { openProfile(card); return; }
            if (modal && (target === modal || target.closest("#profilePop [data-close]"))) {
                modal.classList.remove("is-open");
            }
        });

        document.addEventListener("keydown", (event) => {
            const focused = document.activeElement;
            if ((event.key === "Enter" || event.key === " ") && focused?.matches(".profile-trigger")) {
                event.preventDefault();
                openProfile(focused);
            }
            if (event.key === "Escape") modal?.classList.remove("is-open");
        });
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
        init();
    }
})();
