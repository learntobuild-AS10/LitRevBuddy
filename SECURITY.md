# Security

## Reporting a security issue

Please do not publish API keys, tokens, private datasets, credentials, or other sensitive information in an issue.

For non-sensitive security bugs, open a GitHub issue and label the report clearly.

For a vulnerability that would expose credentials, private data, or permit abuse, use GitHub's private vulnerability reporting feature if it is available for this repository.

## Current security and privacy posture

The public LitRevBuddy site is static and does not maintain LitRevBuddy user accounts or a user database.

The public frontend is designed to avoid:

- analytics and advertising trackers
- payment or subscription SDKs
- cookies
- persistent browser storage for visitor activity
- persistent storage of uploaded PDFs or extracted paper text
- persistent storage of user-supplied API keys

The CI workflow includes checks intended to catch accidental introduction of common tracking, payment, cookie, and persistent-storage mechanisms.

Third-party destinations such as GitHub, publishers, arXiv, OpenReview, and OpenRouter operate under their own security and privacy policies.
