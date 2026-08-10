/* Local Dashboard API boundary. Every view uses this dependency-free helper. */
import {
  isAbortError,
  requestJson,
} from "/ai-radar-assets/ui-modules.js";

let viewController = null;

export function beginViewRequest() {
  viewController?.abort();
  viewController = new AbortController();
  return viewController.signal;
}

export function viewSignal() {
  return viewController?.signal;
}

export function fetchJson(path, options = {}) {
  return requestJson(path, options);
}

export function fetchViewJson(path, options = {}) {
  return requestJson(path, { ...options, signal: viewSignal() });
}

export { isAbortError };
