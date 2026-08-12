# Public release privacy

AI Resource Radar is published under a project identity, but GitHub and PyPI still receive the
account, network, authentication, and audit information required to operate those services. The
project does not promise platform-level anonymity.

## Public by design

- The repository, releases, Pages site, package name, source revision, and PyPI provenance are public.
- Current maintainer commits use the author/committer label `Larry` and the project's
  GitHub-provided `115380064+larrynode@users.noreply.github.com` address. GitHub automation
  identities use their own `noreply` addresses, and external contributors may retain their
  real commit address.
- The public site contains only normalized source evidence and does not upload local databases, logs,
  notifications, tips, posters, API keys, cookies, or account data.
- The six bilingual scenario pages and four Atom/RSS endpoints are static discovery surfaces. Feed
  entries use stable hash IDs and bounded public facts; they do not expose local row IDs, request
  headers, cookies, account fields, or per-user reading history.
- Production Pages may use Google Search Console site verification. The repository secret is mapped
  to `AI_RADAR_GOOGLE_SITE_VERIFICATION_TOKEN` only for the build process and rendered in Google's
  required public homepage verification marker. It is not copied to JSON, XML feeds, logs, workflow
  output, or package artifacts. Search Console reports aggregate indexing and search performance for
  the verified property, not individual user identities.
- Screenshots are checked for PNG author, GPS, software, and EXIF-style metadata before release.

## History and limits

The public commit history, GitHub repository identity, and PyPI provenance remain public. The
release checks verify every commit added by a push or pull request, while ordinary privacy
hardening does not rewrite existing history. If a credential or genuinely sensitive personal
datum is ever committed, revoke it first and use GitHub's sensitive-data removal process; deleting
a file in a later commit is not sufficient.

The 30-day public discovery experiment stores only the start date (`experiment_started_at`) and
aggregate success checks: 10 of 12 scenario pages indexed, exposure in three intent categories,
and at least one click or bounded confirmation signal. A confirmation is not an exact signup,
purchase, or conversion event, and the project does not claim user-level attribution from it.

## Maintenance controls

The repository's CI privacy gate checks new public text and package metadata for personal email
patterns, local paths, personal authors, and image metadata. It also checks the complete commit
range and requires Larry's exact GitHub identity whenever a commit claims that name. GitHub email
privacy and command-line push blocking should remain enabled for maintainers.

For a correction or privacy concern, use the repository's private security advisory channel rather
than posting account data in a public issue.
