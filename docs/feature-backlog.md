# Arcium feature backlog

Deferred product ideas. Entries here do not authorize implementation.

## Open sign-in redirects in Peek while preserving the original page

ID: ARCIUM-BACKLOG-PEEK-AUTH
Status: Backlog only. Implementation has not started.

An expired session can redirect the current tab through authentication and then land on a dashboard, losing the user's place. Add a simple opt-in option, preferably per site, that routes qualifying sign-in detours into Peek. The user completes login and closes Peek manually to resume the original page. Target authentication detours, not ordinary HTTP redirects. Manual close avoids inferring authentication completion from cookies.

Try these approaches in order and stop at the first one that passes acceptance:

1. Use existing Peek behavior without freezing. Keep the original live page and use the same profile and storage context for login. Verify that closing Peek restores the right page and location.
2. If the source changes, navigates, or loses its place, pause or freeze it for Peek's lifetime. Add navigation and discard protection as needed, then resume it on close.
3. If that still fails, capture the exact intended location before the authentication redirect and use it as a recovery fallback. Include the requested protected destination, query, hash, and scroll position where feasible. Avoid retry loops. URL recovery cannot guarantee restoration of unsaved application state held in memory.

Keep the interaction simple: one clear option, normal Peek close and Escape, no required cookie or token inspection, and no complex setup. Preserve profile and private-browsing isolation. Avoid unconditional reloads that erase unsaved work. Verify tab-scoped sessionStorage, OAuth/PKCE state, and tokens held in JavaScript memory where applicable; shared cookies alone do not prove the flow works. Provide a straightforward Continue in tab fallback for incompatible flows.

Verification should first look for an easy Okta-style simulation. If that requires a real tenant or awkward setup, build a deterministic local test site without production credentials. Model an authenticated deep page, session expiration, SSO/login detour, callback, and deliberately incorrect dashboard landing. Include an unsent draft and enough content to test scrolling. Follow existing Arcium scenario and test conventions. A mock SSO flow is sufficient initially; record the behaviors it represents and those it omits.

Required acceptance:

- After login completes and Peek closes, the original tab is at the correct deep page, query and hash survive, scroll is preserved, and authenticated requests work.
- For the live-page and freeze approaches, also verify DOM/page identity, unsent draft, and focus where feasible.
- Check cancel or close before login, login that redirects again, and absence of repeated Peek or recovery loops.
- Exercise a fallback only after the simpler approach fails.
- If the intended protected page never loaded, recover that destination rather than only the referring page.

Existing feasibility evidence supplied in the handoff:

- Core `patches/personal/arcium-peek.patch` creates a separate WebContents under the browser profile around line 613, retains the source behind Peek, and blocks source input around line 700. It currently neither freezes the source nor prevents its discard.
- `arcium-peek-pins.patch` already has navigation-routing hooks.
- Source-preservation tests live in `arcium-peek-source-close-cancellation.patch`.
- Shared behavior belongs in `/Users/daniel/Developer/Helium/helium-macos/helium-chromium`. Follow that workspace's AGENTS.md and `he agent` workflow when implementation is authorized.
