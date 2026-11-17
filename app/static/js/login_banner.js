// Dismiss buttons for the login banner. The server has already recorded that the notice was shown, so
// this only hides it on the current page.
(function () {
    "use strict";
    document.querySelectorAll(".login-banner-close").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var banner = btn.closest(".login-banner");
            var stack = btn.closest(".login-banner-stack");
            if (banner) banner.remove();
            if (stack && !stack.querySelector(".login-banner")) stack.remove();
        });
    });
})();
