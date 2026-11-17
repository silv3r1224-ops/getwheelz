(() => {
  "use strict";

  const labels = {
    processing: "Processing your order",
    printing: "Printing your receipt",
    complete: "Order complete"
  };

  const printingFrames = [
    "translateY(calc(-100% + 2px))", "translateY(-91%)", "translateY(-91%)",
    "translateY(-81%)", "translateY(-81%)", "translateY(-70%)", "translateY(-70%)",
    "translateY(-58%)", "translateY(-58%)", "translateY(-45%)", "translateY(-45%)",
    "translateY(-32%)", "translateY(-32%)", "translateY(-20%)", "translateY(-20%)",
    "translateY(-10%)", "translateY(-10%)", "translateY(-3%)", "translateY(-3%)",
    "translateY(0%)"
  ];
  const printingTimes = [
    0, .075, .105, .18, .21, .285, .315, .39, .42, .495,
    .525, .6, .63, .705, .735, .81, .84, .915, .945, 1
  ];

  class ReceiptPrinter {
    constructor(root) {
      this.root = root;
      this.feed = root.querySelector("[data-receipt-feed]");
      this.label = root.querySelector("[data-printer-label]");
      this.liveStatus = root.querySelector("[data-live-status]");
      this.receiptStatus = root.querySelector("[data-receipt-status]");
      this.stage = root.dataset.stage || "processing";
      this.feedMotion = root.dataset.feedMotion || "stepped";
      this.animate = root.dataset.animate !== "false";
      this.reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      this.setStage(this.stage, { initial: true });
      this.bindControls();
    }

    setStage(stage, options = {}) {
      if (!Object.hasOwn(labels, stage)) {
        console.warn(`ReceiptPrinter: unsupported stage "${stage}"`);
        return;
      }
      this.stage = stage;
      this.root.dataset.stage = stage;
      const label = labels[stage];
      if (this.label) this.label.textContent = label;
      if (this.liveStatus) this.liveStatus.textContent = label;
      if (this.receiptStatus) this.receiptStatus.textContent = stage.toUpperCase();

      if (!this.feed) return;
      this.feed.getAnimations().forEach(animation => animation.cancel());

      if (!this.animate || this.reduceMotion) {
        this.feed.style.opacity = stage === "processing" ? "0" : "1";
        this.feed.style.transform = stage === "processing"
          ? "translateY(calc(-100% + 2px))" : "translateY(0)";
        return;
      }

      if (stage === "processing") {
        this.feed.style.opacity = "0";
        this.feed.style.transform = "translateY(calc(-100% + 2px))";
      } else if (stage === "complete" || options.initial) {
        this.feed.style.opacity = "1";
        this.feed.style.transform = "translateY(0)";
      } else {
        this.feed.style.opacity = "1";
        if (this.feedMotion === "stepped") {
          this.feed.animate(
            printingFrames.map(transform => ({ transform })),
            { duration: 1750, easing: "linear", fill: "forwards" }
          );
        } else {
          this.feed.animate(
            [
              { transform: "translateY(calc(-100% + 2px))" },
              { transform: "translateY(0%)" }
            ],
            { duration: 1750, easing: "cubic-bezier(.77,0,.175,1)", fill: "forwards" }
          );
        }
      }
    }

    setFeedMotion(mode) {
      if (!["smooth", "stepped"].includes(mode)) return;
      this.feedMotion = mode;
      this.root.dataset.feedMotion = mode;
      if (this.stage === "printing") this.setStage("printing");
      this.updateButtons();
    }

    bindControls() {
      this.root.querySelectorAll("[data-stage-button]").forEach(button => {
        button.addEventListener("click", () => this.setStage(button.dataset.stageButton));
      });
      this.root.querySelectorAll("[data-feed-button]").forEach(button => {
        button.addEventListener("click", () => this.setFeedMotion(button.dataset.feedButton));
      });
      this.updateButtons();
    }

    updateButtons() {
      this.root.querySelectorAll("[data-stage-button]").forEach(button => {
        button.setAttribute("aria-pressed", String(button.dataset.stageButton === this.stage));
      });
      this.root.querySelectorAll("[data-feed-button]").forEach(button => {
        button.setAttribute("aria-pressed", String(button.dataset.feedButton === this.feedMotion));
      });
    }
  }

  document.querySelectorAll("[data-receipt-printer]").forEach(root => {
    const instance = new ReceiptPrinter(root);
    root.receiptPrinter = instance;
  });

  // Optional Flask JSON polling. Endpoint should return {"stage": "processing|printing|complete"}.
  const config = window.receiptPrinterConfig || {};
  if (config.endpoint && config.pollInterval > 0) {
    const root = document.querySelector("[data-receipt-printer]");
    const printer = root && root.receiptPrinter;
    if (printer) {
      const poll = async () => {
        try {
          const response = await fetch(config.endpoint, {
            headers: { "Accept": "application/json" },
            cache: "no-store"
          });
          if (!response.ok) throw new Error(`Status request failed: ${response.status}`);
          const data = await response.json();
          if (data.stage) printer.setStage(data.stage);
        } catch (error) {
          console.error("ReceiptPrinter status polling:", error);
        }
      };
      window.setInterval(poll, Number(config.pollInterval));
    }
  }
})();