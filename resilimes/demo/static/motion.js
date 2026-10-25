// Micro-interactions that CSS cannot do alone: briefly wash a live number when its value changes.
// Views re-render whole subtrees, so values are matched by label and position, not by node identity.
// Purely visual; skipped entirely when the user prefers reduced motion.
(function () {
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)");
  const WATCH = ".kpi .value, .shift-kpis .value, .fx-tile strong, .fx-clock, .sl-head";
  let last = new Map();
  let frame = 0;

  function keyOf(node, index) {
    const label = node.parentElement && node.parentElement.firstElementChild;
    const name = label && label !== node ? label.textContent : "";
    return `${index}|${node.className}|${name}`;
  }

  function scan() {
    frame = 0;
    const next = new Map();
    const nodes = document.querySelectorAll(WATCH);
    nodes.forEach((node, index) => {
      const key = keyOf(node, index);
      const text = node.textContent;
      next.set(key, text);
      const before = last.get(key);
      if (before !== undefined && before !== text && node.offsetParent !== null) {
        node.classList.remove("tick");
        void node.offsetWidth; // restart the animation
        node.classList.add("tick");
      }
    });
    last = next;
  }

  const observer = new MutationObserver(() => {
    if (reduce && reduce.matches) return;
    if (!frame) frame = requestAnimationFrame(scan);
  });
  observer.observe(document.body, { subtree: true, childList: true, characterData: true });
  document.addEventListener("animationend", (event) => {
    if (event.animationName === "tick") event.target.classList.remove("tick");
  });
})();
