# Public release privacy

AI Resource Radar is published under a project identity, but GitHub and PyPI still receive the
account, network, authentication, and audit information required to operate those services. The
project does not promise platform-level anonymity.

## Public by design

- The repository, releases, Pages site, package name, source revision, and PyPI provenance are public.
- Future commits use a GitHub-provided `noreply` address and the author label `AI Resource Radar contributors`.
- The public site contains only normalized source evidence and does not upload local databases, logs,
  notifications, tips, posters, API keys, cookies, or account data.
- Screenshots are checked for PNG author, GPS, software, and EXIF-style metadata before release.

## Historical limits

The v0.7.2 release and earlier commits were published before the brand migration. Their commit
author metadata, GitHub repository identity, and PyPI provenance remain part of the public history.
We do not rewrite that history as part of ordinary privacy hardening. If a credential or genuinely
sensitive personal datum is ever committed, revoke it first and use GitHub's sensitive-data removal
process; deleting a file in a later commit is not sufficient.

## Maintenance controls

The repository's CI privacy gate checks new public text and package metadata for personal email
patterns, local paths, personal authors, and image metadata. GitHub email privacy and command-line
push blocking should remain enabled for maintainers.

For a correction or privacy concern, use the repository's private security advisory channel rather
than posting account data in a public issue.
