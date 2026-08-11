/* Compatibility entry point. The host still serves /ai-resources.js. */
import { mountDashboard } from "/ai-radar-assets/modules/legacy-dashboard.js";
import * as api from "/ai-radar-assets/modules/api.js";
import * as router from "/ai-radar-assets/modules/state-router.js";
import * as formatters from "/ai-radar-assets/modules/formatters.js";
import * as components from "/ai-radar-assets/modules/components.js";
import * as recommended from "/ai-radar-assets/modules/views/recommended.js";
import * as resources from "/ai-radar-assets/modules/views/resources.js";
import * as pricing from "/ai-radar-assets/modules/views/pricing.js";
import * as tips from "/ai-radar-assets/modules/views/tips.js";
import * as changes from "/ai-radar-assets/modules/views/changes.js";

const viewModules = {
  recommended,
  token: resources,
  gpu: resources,
  grant: resources,
  "token-prices": pricing,
  "gpu-prices": pricing,
  resources,
  pricing,
  tips,
  changes,
};

mountDashboard({ api, router, formatters, components, viewModules });
