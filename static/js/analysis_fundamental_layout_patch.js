(() => {
  "use strict";

  // This patch is intentionally scoped to the Analysis page only.
  if (!window.location.pathname.startsWith("/analysis")) return;

  const REMOVE_TITLES = new Set([
    "Breakdown điểm cơ bản",
    "Đánh giá cơ bản của hệ thống",
  ]);

  const BALANCE_TITLE = "Bảng cân đối kế toán";
  const INCOME_TITLE = "Kết quả kinh doanh các kỳ gần nhất";

  const normalize = (value) =>
    String(value ?? "").replace(/\s+/g, " ").trim();

  const exactText = (el, expected) =>
    el && normalize(el.textContent) === expected;

  function candidateTextElements(root) {
    return root.querySelectorAll(
      "h1,h2,h3,h4,h5,h6,.card-title,.section-title,.panel-title," +
      ".analysis-title,.fundamental-title,strong,b,[data-title]"
    );
  }

  function findExactText(root, text) {
    if (!root) return null;

    for (const el of candidateTextElements(root)) {
      if (exactText(el, text)) return el;
    }

    // Narrow fallback for projects that render titles in plain div/span elements.
    for (const el of root.querySelectorAll("div,span,p")) {
      if (el.children.length === 0 && exactText(el, text)) return el;
    }
    return null;
  }

  function containsExactText(root, text) {
    return Boolean(findExactText(root, text));
  }

  function findFundamentalPanel() {
    // First prefer explicit fundamental-panel selectors if the project has them.
    const explicitSelectors = [
      "#fundamental",
      "#fundamental-tab",
      "#tab-fundamental",
      "#fundamental-content",
      "[data-tab-panel='fundamental']",
      "[data-tab-content='fundamental']",
      "[data-panel='fundamental']",
      ".tab-pane[data-tab='fundamental']",
      ".analysis-tab-panel[data-tab='fundamental']",
    ];

    for (const selector of explicitSelectors) {
      const el = document.querySelector(selector);
      if (
        el &&
        containsExactText(el, BALANCE_TITLE) &&
        containsExactText(el, INCOME_TITLE)
      ) {
        return el;
      }
    }

    // Fallback: use the two unique surviving headings to locate the smallest
    // common ancestor. This avoids touching same-name cards elsewhere.
    const balance = findExactText(document, BALANCE_TITLE);
    const income = findExactText(document, INCOME_TITLE);
    if (!balance || !income) return null;

    const incomeAncestors = new Set();
    for (let node = income; node; node = node.parentElement) {
      incomeAncestors.add(node);
    }

    for (let node = balance; node; node = node.parentElement) {
      if (!incomeAncestors.has(node)) continue;

      // Prefer a reasonably local analysis/tab container rather than body/main.
      if (
        node !== document.body &&
        node !== document.documentElement &&
        node.querySelectorAll("*").length < 2500
      ) {
        return node;
      }
    }
    return null;
  }

  function containsProtectedContent(node, targetTitle) {
    const protectedTitles = [BALANCE_TITLE, INCOME_TITLE];
    for (const title of protectedTitles) {
      if (title !== targetTitle && containsExactText(node, title)) {
        return true;
      }
    }

    // Never let one removal swallow the other target as part of a larger grid.
    for (const title of REMOVE_TITLES) {
      if (title !== targetTitle && containsExactText(node, title)) {
        return true;
      }
    }
    return false;
  }

  function findSafeBlock(panel, heading, targetTitle) {
    if (!panel || !heading) return null;

    let node = heading;
    let best = heading.parentElement;

    while (node && node !== panel) {
      if (containsProtectedContent(node, targetTitle)) break;

      const className =
        typeof node.className === "string" ? node.className.toLowerCase() : "";
      const looksLikeBlock =
        ["SECTION", "ARTICLE"].includes(node.tagName) ||
        /(card|panel|box|section|block|grid-item|content-card)/.test(className);

      if (looksLikeBlock) best = node;

      // A direct child of the scoped panel is the outermost safe block we want.
      if (node.parentElement === panel) {
        best = node;
        break;
      }

      node = node.parentElement;
    }
    return best;
  }

  function removeTargetCard(panel, title) {
    const heading = findExactText(panel, title);
    if (!heading) return false;

    const block = findSafeBlock(panel, heading, title);
    if (!block || block === panel) return false;

    block.remove();
    return true;
  }

  function makeSectionFullWidth(panel, title) {
    const heading = findExactText(panel, title);
    if (!heading) return;

    const block = findSafeBlock(panel, heading, title);
    if (!block || block === panel) return;

    block.classList.add("fundamental-layout-full-width");
    block.style.gridColumn = "1 / -1";
    block.style.width = "100%";
    block.style.maxWidth = "none";
    block.style.justifySelf = "stretch";
  }

  function cleanEmptyLayoutWrappers(panel) {
    // Only remove truly empty wrappers left after deleting the two target cards.
    for (const el of panel.querySelectorAll(
      ".row,.grid,.analysis-grid,.fundamental-grid,.card-grid,[class*='grid']"
    )) {
      if (!el.children.length && !normalize(el.textContent)) {
        el.remove();
      }
    }
  }

  let applying = false;

  function applyPatch() {
    if (applying) return;
    applying = true;

    try {
      const panel = findFundamentalPanel();
      if (!panel) return;

      panel.dataset.fundamentalLayoutPatch = "active";

      for (const title of REMOVE_TITLES) {
        removeTargetCard(panel, title);
      }

      // After Breakdown is removed, the balance-sheet card should not remain
      // stranded in a half-width column. Keep its contents unchanged.
      makeSectionFullWidth(panel, BALANCE_TITLE);
      makeSectionFullWidth(panel, INCOME_TITLE);

      cleanEmptyLayoutWrappers(panel);
    } finally {
      applying = false;
    }
  }

  let scheduled = false;
  function schedulePatch() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      applyPatch();
    });
  }

  // Dynamic API rendering can recreate the fundamental panel, so observe only
  // for DOM changes and re-apply the same scoped patch idempotently.
  const observer = new MutationObserver(schedulePatch);
  observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
  });

  document.addEventListener("DOMContentLoaded", schedulePatch);
  window.addEventListener("load", schedulePatch);

  // Re-apply when the user clicks the Fundamental tab.
  document.addEventListener("click", (event) => {
    const target = event.target.closest("button,a,[role='tab']");
    if (!target) return;
    if (normalize(target.textContent) === "Phân tích cơ bản") {
      setTimeout(schedulePatch, 0);
      setTimeout(schedulePatch, 150);
    }
  });

  schedulePatch();
})();
