/* URL state is deliberately tiny and shareable: a view hash plus search text. */
import {
  readDashboardRoute,
  writeDashboardRoute,
} from "/ai-radar-assets/ui-modules.js";

export const KNOWN_VIEWS = new Set([
  "recommended", "token", "gpu", "token-prices", "gpu-prices", "grant", "tips", "changes",
]);

const FILTER_KEYS = new Set([
  "verified", "no_card", "image", "mainland",
  "sort", "direction", "provider", "verification", "min_context",
  "max_typical", "max_input", "max_output", "cache", "gpu", "min_vram",
  "max_hourly", "billing", "tier", "price_mode", "hours", "advanced",
  "tip_status", "tip_category", "tip_risk", "tip_source", "tip_scope",
]);

export function readRoute() {
  const route = readDashboardRoute(KNOWN_VIEWS);
  const params = new URLSearchParams(window.location.search);
  route.filters = {};
  FILTER_KEYS.forEach((key) => {
    if (params.has(key)) route.filters[key] = params.get(key);
  });
  return route;
}

export function writeRoute(view, query, filters = {}) {
  writeDashboardRoute({ view, query });
  const url = new URL(window.location.href);
  FILTER_KEYS.forEach((key) => url.searchParams.delete(key));
  Object.entries(filters).forEach(([key, value]) => {
    if (FILTER_KEYS.has(key) && value !== "" && value !== null && value !== undefined) {
      url.searchParams.set(key, String(value));
    }
  });
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}
