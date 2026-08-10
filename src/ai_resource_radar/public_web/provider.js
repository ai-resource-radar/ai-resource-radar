async function copySnippet(target) {
  const text = target.textContent || "";
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to a selection-based copy for local previews and browsers
      // that block the asynchronous Clipboard API.
    }
  }
  const range = document.createRange();
  range.selectNodeContents(target);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  target.tabIndex = -1;
  target.focus({ preventScroll: true });
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  }
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy-target]");
  if (!button) return;
  const target = document.getElementById(button.dataset.copyTarget || "");
  if (!target) return;
  const copied = await copySnippet(target);
  const previous = button.textContent;
  button.textContent = copied
    ? (document.documentElement.lang === "en" ? "Copied" : "已复制")
    : (document.documentElement.lang === "en" ? "Selected — press Ctrl/Cmd+C" : "已选中，请按 ⌘/Ctrl+C");
  window.setTimeout(() => { button.textContent = previous; }, copied ? 1400 : 2600);
});
