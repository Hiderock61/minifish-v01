# MiniFish G4c-3 isolated diagnostic

This Draft-only branch extends fixed PR #46 head 903769a with an Actions workflow and a hashed synthetic-test payload. The runner extracts the payload, applies the PR41 scripted patch then the G4c CDP browser patch to a temporary checkout only, and independently verifies 54 + PR40/41 + full pytest + 27 G4b/c local tests. No live Cloudflare, personal logins, API key access or production writes. DO NOT MERGE.
