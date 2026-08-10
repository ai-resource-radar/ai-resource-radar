/* Small browser-native modules shared by the local dashboard entry point. */

const pendingRequests = new Map();

/**
 * Fetch a JSON API response and optionally cancel the previous request in the
 * same view.  Keeping cancellation here means the view renderer never has to
 * guess which late response is still current.
 */
export async function requestJson(path, options = {}) {
  const {
    requestKey,
    cancelPrevious = false,
    signal: suppliedSignal,
    ...requestOptions
  } = options;
  let controller = null;
  let signal = suppliedSignal;
  if (cancelPrevious && requestKey) {
    pendingRequests.get(requestKey)?.abort();
    controller = new AbortController();
    pendingRequests.set(requestKey, controller);
    signal = controller.signal;
  }
  try {
    const response = await fetch(path, {
      ...requestOptions,
      ...(signal ? { signal } : {}),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || "request_failed");
    return payload;
  } finally {
    if (controller && pendingRequests.get(requestKey) === controller) {
      pendingRequests.delete(requestKey);
    }
  }
}

export function isAbortError(error) {
  return error?.name === "AbortError";
}

export function cancelRequest(requestKey) {
  pendingRequests.get(requestKey)?.abort();
  pendingRequests.delete(requestKey);
}

/** Read a stable dashboard route from either the hash or query string. */
export function readDashboardRoute(knownViews, fallback = "recommended") {
  const params = new URLSearchParams(window.location.search);
  const hash = window.location.hash.replace(/^#/, "");
  const view = params.get("view") || params.get("tab") || hash;
  return {
    view: knownViews.has(view) ? view : fallback,
    query: params.get("q") || "",
  };
}

/** Keep deep links shareable without creating a history entry per keystroke. */
export function writeDashboardRoute({ view, query = "" }) {
  const url = new URL(window.location.href);
  url.searchParams.delete("tab");
  url.searchParams.delete("view");
  if (query.trim()) url.searchParams.set("q", query.trim());
  else url.searchParams.delete("q");
  url.hash = view && view !== "recommended" ? view : "";
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

/**
 * Native dialog focus management: remember the trigger, keep Tab inside the
 * modal, focus the close control, and restore focus when it closes.
 */
export function createDialogController(dialog, closeButton, detailRoot) {
  let returnFocus = null;
  const schedule = (callback) => typeof window.requestAnimationFrame === "function"
    ? window.requestAnimationFrame(callback)
    : window.setTimeout(callback, 0);
  const focusableSelector = [
    "a[href]", "button:not([disabled])", "input:not([disabled])",
    "select:not([disabled])", "textarea:not([disabled])", "[tabindex]:not([tabindex='-1'])",
  ].join(",");

  function syncTitle() {
    const title = detailRoot?.querySelector("h2, [data-dialog-title]");
    if (title) {
      title.id = title.id || "offer-dialog-title";
      dialog.setAttribute("aria-labelledby", title.id);
    }
  }

  function open(trigger = document.activeElement) {
    returnFocus = trigger && typeof trigger.focus === "function" ? trigger : null;
    syncTitle();
    if (!dialog.open) dialog.showModal();
    schedule(() => closeButton?.focus());
  }

  function close() {
    if (dialog.open) dialog.close();
  }

  dialog.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const nodes = [...dialog.querySelectorAll(focusableSelector)].filter((node) => node.offsetParent !== null);
    if (!nodes.length) {
      event.preventDefault();
      closeButton?.focus();
      return;
    }
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  dialog.addEventListener("close", () => {
    const target = returnFocus;
    returnFocus = null;
    if (target && document.contains(target)) schedule(() => target.focus());
  });
  return { open, close, syncTitle };
}
