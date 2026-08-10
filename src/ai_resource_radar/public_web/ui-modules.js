/* Dependency-free helpers shared by the public static entry point. */

export function readStaticRoute(validTabs, fallback = "recommended") {
  const params = new URLSearchParams(window.location.search);
  const value = params.get("tab") || "";
  return { tab: validTabs.has(value) ? value : fallback, query: params.get("q") || "" };
}
export function writeStaticRoute({ tab, query = "" }) {
  const url = new URL(window.location.href);
  if (tab && tab !== "recommended") url.searchParams.set("tab", tab);
  else url.searchParams.delete("tab");
  if (query.trim()) url.searchParams.set("q", query.trim());
  else url.searchParams.delete("q");
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

export function setDisclosureState(disclosure, expanded) {
  if (!disclosure) return;
  disclosure.open = Boolean(expanded);
  const summary = disclosure.querySelector("summary");
  if (summary) summary.setAttribute("aria-expanded", String(Boolean(expanded)));
}
