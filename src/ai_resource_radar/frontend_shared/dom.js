/* Safe, dependency-free DOM helpers shared by both browser surfaces. */

export function element(tag, className = "", text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

export function safeUrl(value) {
  try {
    const url = new URL(String(value || ""), window.location.href);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}

export function safeLink(label, url, className = "") {
  const href = safeUrl(url);
  if (!href) return null;
  const link = element("a", className, label);
  link.href = href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.referrerPolicy = "no-referrer";
  link.addEventListener("click", (event) => event.stopPropagation());
  return link;
}
