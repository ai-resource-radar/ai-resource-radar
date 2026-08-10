import { element, safeLink } from "./dom.js";
import {
  actionUrl,
  benefitSummary,
  cardLabel,
  formatTime,
  kindLabel,
  mainlandLabel,
  quotaText,
  usageSteps,
  verificationLabel,
} from "./formatters.js";

const COPY = {
  "zh-CN": { get: "送什么", threshold: "门槛", how: "怎么领", evidence: "官方证据", claim: "去领取 ↗", details: "查看步骤", verified: "最近核验" },
  en: { get: "What you get", threshold: "Requirements", how: "How to claim", evidence: "Evidence", claim: "Claim ↗", details: "View steps", verified: "Verified" },
};

function providerInitials(provider) {
  return String(provider || "AI").split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase() || "AI";
}

export function createOfferCard(resource, options = {}) {
  const locale = options.locale === "en" ? "en" : "zh-CN";
  const copy = COPY[locale];
  const classes = ["radar-offer-card", options.className || "", options.primary ? "is-primary primary" : ""].filter(Boolean).join(" ");
  const card = element("article", classes);
  const header = element("div", "radar-card-header feature-identity");
  const provider = element("div", "radar-card-provider feature-provider");
  provider.append(
    element("span", "radar-card-provider-icon feature-provider-icon", providerInitials(resource.provider)),
    element("span", "", `${resource.provider || "AI"} · ${kindLabel(resource.kind, locale)}`),
  );
  const tier = element("span", "radar-card-tier feature-tier", resource.priority_tier || "—");
  tier.dataset.tier = resource.priority_tier || "";
  header.append(provider, tier);

  const benefit = element("section", "radar-card-benefit feature-benefit");
  benefit.append(
    element("span", "radar-card-label feature-label", copy.get),
    element("strong", "radar-card-amount feature-amount", quotaText(resource, locale)),
    element("p", "radar-card-summary feature-description", benefitSummary(resource, locale)),
  );

  const facts = element("div", "radar-card-facts");
  const steps = usageSteps(resource, locale);
  const evidence = resource.evidence || {};
  [
    [copy.threshold, `${cardLabel(resource.requires_card, locale)} · ${mainlandLabel(resource.mainland_status, locale)}`],
    [copy.how, steps[0] || (locale === "en" ? "Open the official page and follow its account steps." : "打开官方页面，按账号指引领取。")],
    [copy.evidence, `${verificationLabel(resource.verification_level, locale)} · ${copy.verified} ${formatTime(evidence.observed_at || resource.last_seen_at, locale)}`],
  ].forEach(([label, value]) => {
    const item = element("div", "radar-card-fact");
    item.append(element("span", "", label), element("p", "", value));
    facts.append(item);
  });

  const actions = element("div", "radar-card-actions feature-actions");
  const claim = safeLink(copy.claim, actionUrl(resource, locale), "radar-card-primary feature-claim");
  const source = safeLink(copy.evidence, evidence.source_url || resource.homepage_url, "radar-card-secondary radar-card-evidence");
  if (claim) actions.append(claim);
  if (source && (!claim || source.href !== claim.href)) actions.append(source);
  if (typeof options.onDetails === "function") {
    const details = element("button", "radar-card-secondary feature-details", options.detailsLabel || copy.details);
    details.type = "button";
    details.addEventListener("click", (event) => {
      event.stopPropagation();
      options.onDetails(resource, details);
    });
    actions.append(details);
  }

  card.append(header, benefit, facts, actions);
  return card;
}
