// Styled replacement for the browser's window.confirm() on forms.
//
// Usage: add data attributes to any <form>; it will ask first, then submit normally.
//   <form method="POST" action="..."
//         data-confirm-title="Mark this job as completed?"
//         data-confirm-text="Optional explanation shown under the title."
//         data-confirm-yes="Yes, mark complete"      (optional button label)
//         data-confirm-tone="danger">                (optional; red icon + button. Default is green)

(() => {
    let dialog, iconEl, titleEl, textEl, yesBtn, cancelBtn;
    let pendingForm = null;
    let opener = null;

    const build = () => {
        dialog = document.createElement("div");
        dialog.className = "confirm-dialog";
        dialog.setAttribute("role", "dialog");
        dialog.setAttribute("aria-modal", "true");
        dialog.setAttribute("aria-labelledby", "confirmActionTitle");
        // Static markup only: all dynamic text is set with textContent below.
        dialog.innerHTML =
            '<div class="confirm-box">' +
            '<i class="bx confirm-icon" aria-hidden="true"></i>' +
            '<h3 id="confirmActionTitle"></h3>' +
            "<p></p>" +
            '<div class="confirm-actions">' +
            '<button type="button" class="mini-btn" data-yes></button>' +
            '<button type="button" class="mini-btn neutral" data-cancel>Cancel</button>' +
            "</div></div>";
        document.body.appendChild(dialog);

        iconEl = dialog.querySelector(".confirm-icon");
        titleEl = dialog.querySelector("h3");
        textEl = dialog.querySelector("p");
        yesBtn = dialog.querySelector("[data-yes]");
        cancelBtn = dialog.querySelector("[data-cancel]");

        yesBtn.addEventListener("click", () => {
            const form = pendingForm;
            if (!form) return;
            yesBtn.disabled = true;      // guard against double submits
            close(false);
            form.submit();               // does not re-fire the submit event
        });
        cancelBtn.addEventListener("click", () => close(true));
        dialog.addEventListener("click", (event) => {
            if (event.target === dialog) close(true);   // click on the dark backdrop
        });
    };

    const open = (form, trigger) => {
        if (!dialog) build();
        const danger = form.dataset.confirmTone === "danger";

        pendingForm = form;
        opener = trigger || null;

        titleEl.textContent = form.dataset.confirmTitle;
        textEl.textContent = form.dataset.confirmText || "";
        textEl.hidden = !form.dataset.confirmText;
        yesBtn.textContent = form.dataset.confirmYes || "Yes, continue";
        yesBtn.disabled = false;

        yesBtn.classList.toggle("cancel", danger);
        yesBtn.classList.toggle("confirm", !danger);
        iconEl.classList.toggle("is-success", !danger);
        iconEl.classList.toggle("bx-error-circle", danger);
        iconEl.classList.toggle("bx-check-circle", !danger);

        dialog.classList.add("show");
        (danger ? cancelBtn : yesBtn).focus();   // safest default button for each case
    };

    const close = (restoreFocus) => {
        if (!dialog) return;
        dialog.classList.remove("show");
        pendingForm = null;
        if (restoreFocus && opener && document.contains(opener)) opener.focus();
        opener = null;
    };

    document.addEventListener("submit", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || !form.dataset.confirmTitle) return;
        event.preventDefault();
        open(form, event.submitter);
    });

    document.addEventListener("keydown", (event) => {
        if (!dialog || !dialog.classList.contains("show")) return;
        if (event.key === "Escape") {
            close(true);
        } else if (event.key === "Tab") {
            // keep keyboard focus inside the dialog
            event.preventDefault();
            (document.activeElement === yesBtn ? cancelBtn : yesBtn).focus();
        }
    });
})();