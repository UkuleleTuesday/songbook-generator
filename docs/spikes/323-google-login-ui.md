# Spike #323 – Google login in the UI for user-based songbook editing

**Issue:** [#323 Spike: UI update for Google login to enable user-based songbook editing](https://github.com/UkuleleTuesday/songbook-generator/issues/323)

## Problem statement

The songbook generator UI currently has no user authentication.  All API
endpoints are publicly accessible, Drive operations run under service-account
credentials, and any user who can load the page can trigger songbook generation.
There is no concept of an "editor" who can create or modify songbook editions
through the UI — that workflow requires direct Drive access plus either a GitHub
Pull Request (config-based editions) or CLI access with service-account
credentials (Drive-based editions).

The hypothesis explored here is whether integrating Google login into the UI
could:

1. Allow users to create and modify Drive-based songbook editions using their
   own Google account credentials rather than shared service-account credentials.
2. Restrict write operations (edition creation, metadata edits, song list
   changes) to authenticated and authorised users.
3. Preserve the existing public read/generate workflow (no auth needed to list
   editions or generate a songbook).

---

## Findings

### 1. Current UI architecture

The frontend (`ui/index.html`) is a single static page:

- **Technology:** Vanilla JavaScript + Material Design Lite 1.3.0.
- **Hosting:** GitHub Pages (static files only; no server-side session support).
- **API communication:** Unauthenticated `fetch()` calls to a Cloud Functions
  URL.  The API base URL is resolved from `window.location.pathname` to support
  PR preview environments.
- **No auth state:** There is no login session, no token storage, and no
  conditional rendering based on user identity.

The only interactive "edit" affordance today is a Drive folder shortcut button
on Drive-based edition cards, which simply opens the relevant Google Drive
folder URL in a new tab.

### 2. Current API architecture

The API (`generator/api/main.py`) is an HTTP-triggered Cloud Function:

| Endpoint | Method | Auth today |
|---|---|---|
| `/` | `GET` | None (health check) |
| `/editions` | `GET` | None |
| `/` | `POST` | None (enqueue generation job) |
| `/{jobId}` | `GET` | None (poll job status) |

CORS headers allow cross-origin requests from any origin (`*`).  There is no
middleware to verify credentials or restrict access to any endpoint.

### 3. Current Drive access model

All Drive operations run under three dedicated service accounts:

| Service account | Scopes | Used by |
|---|---|---|
| `songbook-generator@…` | `drive.readonly`, `documents.readonly` | API, Worker, Drive Watcher |
| `songbook-metadata-writer@…` | `drive.metadata` | Tag Updater |
| `songbook-cache-updater@…` | `drive.readonly` | Cache Updater |

Credentials are obtained via `google.auth.default()` and optionally wrapped in
`impersonated_credentials.Credentials` (see `generator/worker/gcp.py`).
There is no mechanism for the API to act on behalf of an end-user.

### 4. GitHub Pages hosting constraints

Because the UI is hosted on GitHub Pages, it is a static site with no
server-side compute.  This rules out classic OAuth2 authorisation-code flows
(which require a server-side token exchange) unless a backend endpoint is
added solely to perform the exchange.

The relevant constraints for a Single-Page Application (SPA) are:

- **No `HttpOnly` cookies** can be set (no server to set them).
- **Token storage options:** In-memory (lost on page reload), `sessionStorage`
  (tab-scoped), or `localStorage` (persistent, XSS risk).
- **Recommended flow:** OAuth2 PKCE (Proof Key for Code Exchange) or the
  implicit-to-token exchange supported by Google Identity Services (GIS).

### 5. Available Google authentication libraries

| Library | Status | Approach | Notes |
|---|---|---|---|
| **Google Identity Services (GIS)** | Current / recommended | ID token + OAuth2 token in-browser | Ships with One Tap sign-in; replaces the deprecated `gapi.auth2` |
| **Firebase Authentication** | Current / recommended | Higher-level SDK over GIS | Adds persistent session management; requires a Firebase project |
| **Google Sign-In for Websites (`gapi.auth2`)** | **Deprecated** | Legacy implicit flow | Do not use for new integrations |
| **Google Cloud Identity-Aware Proxy (IAP)** | GA | Proxy-level auth | Redirects unauthenticated requests to Google sign-in before they reach the function |

### 6. Drive OAuth2 scopes needed for editing

The minimum viable set of scopes for authenticated editing is:

| Scope | Requirement |
|---|---|
| `openid profile email` | Identify the signed-in user |
| `https://www.googleapis.com/auth/drive.file` | Create and modify files/folders the app created on the user's behalf |
| `https://www.googleapis.com/auth/drive` | Required to add Drive shortcuts to existing song-sheet files owned by a different user/service-account — needed for building editions from the shared library |

The full `drive` scope should only be requested when the user attempts an
operation that genuinely requires it (incremental authorisation).  For
read-only browsing and generation, no Drive scope is needed.

### 7. Backend token verification

Cloud Functions can verify a Google ID token using the `google-auth` Python
library:

```python
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

def verify_user(request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[len("Bearer "):]
    try:
        info = id_token.verify_oauth2_token(
            token, google_requests.Request(), CLIENT_ID
        )
        return info  # contains sub, email, name, picture
    except ValueError:
        return None
```

This is a stateless, per-request check with no external session storage needed.

### 8. Firestore job schema today

Every job document records `job_id`, `status`, `params`, `progress`, and
`result_url`.  There is no `user_id` field.  A user-aware system would need
to record which user submitted each job and optionally scope job history
queries to the requesting user.

---

## Options

### Option A – Google Identity Services (GIS) with delegated Drive access ✅

**How it works:**

1. The UI loads the GIS JavaScript library and shows a Google Sign-In button.
2. The user signs in; GIS returns an ID token (for identity verification) and,
   on first authorisation, an OAuth2 access token scoped to the Drive
   permissions the user grants.
3. The access token is stored in memory (or `sessionStorage`) and attached as
   a `Bearer` header on mutating API calls.
4. A thin authentication middleware in the API verifies the ID token and
   extracts `email`/`sub` from it.
5. For Drive operations that require editing (e.g. creating a new edition
   folder), the API uses the **user's access token** rather than the service
   account, so the resulting files are owned by the user and subject to their
   existing Drive permissions.
6. Read operations (`GET /editions`, `GET /{jobId}`) and generation (`POST /`)
   for existing editions remain unauthenticated.

**UI changes:**
- Add a Google Sign-In button to the header/toolbar.
- Show the signed-in user's avatar and name when authenticated.
- Show an "Add edition" button visible only to authenticated users.
- Show an inline "Edit" panel for Drive editions the user has permission to
  modify (gated behind the user's Drive token).
- Handle token expiry (GIS provides a `requestAccessToken()` callback that can
  silently refresh).

**API changes:**
- Add `verify_user()` middleware (see §7).
- Add a `POST /editions` endpoint (authenticated) to create a new Drive folder
  with a `.songbook.yaml` scaffold, returning the new edition id.
- Add a `PATCH /editions/{id}` endpoint (authenticated) to modify the YAML
  config file inside the user's edition folder.
- On `POST /` for a Drive-based edition, record `user_id` in the Firestore
  job document.
- Update CORS headers to allow the `Authorization` request header.

**Pros:**
- No additional Google Cloud product required; uses existing Cloud Functions
  and Firestore.
- Stateless: the API verifies each request independently.
- Drive files created through the UI are owned by the user — natural permission
  boundary.
- GIS library is small and CDN-hosted; fits the existing vanilla-JS stack.
- Incremental authorisation: request only `openid profile email` on login;
  request `drive.file` / `drive` only when the user initiates an edit.

**Cons:**
- Access tokens expire after 1 hour; the UI must handle silent re-authorisation
  (GIS supports this but adds implementation complexity).
- `localStorage`/`sessionStorage` token storage is vulnerable to XSS — access
  tokens should live in memory only.
- Using the user's Drive token for all operations means the API cannot perform
  background/scheduled operations on behalf of the user (that still requires
  a service account).
- OAuth2 consent screen must be configured for the GCP project and reviewed by
  Google if the app is published externally.

---

### Option B – Firebase Authentication

**How it works:**

Firebase Authentication wraps GIS and other identity providers behind a
higher-level SDK that handles token refresh, persistence, and multi-provider
login.  The Firebase Admin SDK on the backend verifies Firebase ID tokens.

**Additional differences vs Option A:**
- Requires a Firebase project (can reuse the existing GCP project).
- Firebase ID tokens (used for backend verification) are distinct from Google
  OAuth2 access tokens (used for Drive API calls); both are needed.
- Session persistence is managed by the Firebase SDK — signed-in state survives
  page reloads without additional code.
- Firebase SDK footprint is larger (~200 KB gzipped) than the GIS library
  (~20 KB).
- Firebase Admin SDK (`firebase-admin`) is an additional Python dependency.

**Pros:**
- Persistent login across page reloads out of the box.
- Easier multi-provider expansion later (e.g. email/password, GitHub).
- Well-documented SDK for both frontend and backend.

**Cons:**
- Firebase project setup adds operational complexity.
- Larger frontend bundle size (though this may be negligible for an MDL site).
- Two token types to manage: Firebase ID token (auth) and Google OAuth2 token
  (Drive access) — developers must keep both concepts distinct.
- Unnecessary for a Google-only login; adds abstraction without clear benefit
  over Option A for this use case.

---

### Option C – Google Cloud Identity-Aware Proxy (IAP)

**How it works:**

IAP intercepts all requests to the Cloud Function at the Google network edge.
Unauthenticated requests are redirected to a Google sign-in page.  After
sign-in, IAP injects `X-Goog-Authenticated-User-Email` and
`X-Goog-IAP-JWT-Assertion` headers into the forwarded request; the API reads
these headers to identify the user.

**Pros:**
- Authentication is completely outside application code — no middleware to
  write or maintain.
- Works with any backend language/framework.
- Google Workspace domain restriction is built in.

**Cons:**
- IAP protects the entire function URL.  Read operations (`GET /editions`)
  would also require sign-in, breaking the public browsing workflow.  Separate
  unauthenticated and authenticated endpoints (different function URLs) would
  be needed.
- IAP cannot be used with GitHub Pages directly — the OAuth2 redirect URI
  would need to point to a Google-managed URL, and the browser would be
  redirected away from the GitHub Pages domain.
- Additional IAP configuration required in `deploy.yaml` for each environment
  (main and per-PR preview functions).
- Does not solve the Drive delegation problem — the API still runs under a
  service account regardless of who is authenticated.

---

### Option D – Restrict mutations to a Google Workspace domain

**How it works:**

Keep the existing service-account Drive access.  Add lightweight middleware
to the API that verifies the user's Google ID token and checks that their
email belongs to a specific Google Workspace domain (e.g. `ukuleletuesday.org`).
Users must sign in with their organisational account to access write endpoints,
but all Drive operations still run under the service account.

**Pros:**
- No Drive scope from the user needed — service account retains all Drive
  access.
- Simple to implement: one domain check in the middleware.
- Lowest risk of breaking existing behaviour.

**Cons:**
- Drive operations are not performed as the user — audit trail in Drive shows
  service account, not the individual.
- Anyone with an account in the domain can perform any write operation; no
  finer-grained permission enforcement.
- Does not enable users to operate on their own Drive files — the service
  account still needs folder access configured by an administrator.
- Does not address the case where collaborators do not share a common Workspace
  domain.

---

## Architecture overview (Option A)

```
┌─────────────────────────────────────────────────────────┐
│  Browser (GitHub Pages)                                  │
│                                                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │  index.html + GIS library                         │  │
│  │                                                   │  │
│  │  [Sign In with Google]                            │  │
│  │        │                                          │  │
│  │        ▼                                          │  │
│  │  GIS: ID token + OAuth2 access token              │  │
│  │  (memory / sessionStorage)                        │  │
│  │        │                                          │  │
│  │        ├─── GET /editions ──────────────────────► │  │
│  │        │    (no auth header needed)               │  │
│  │        │                                          │  │
│  │        ├─── POST /editions ─────────────────────► │  │
│  │        │    Authorization: Bearer <ID token>      │  │
│  │        │    X-Drive-Token: <OAuth2 access token>  │  │
│  │        │                                          │  │
│  │        └─── POST / ──────────────────────────────► │  │
│  │             (generate – no auth required)         │  │
│  └───────────────────────────────────────────────────┘  │
└──────────────────────────────────────┬──────────────────┘
                                       │ HTTPS
                             ┌─────────▼──────────┐
                             │  Cloud Function     │
                             │  (API)              │
                             │                     │
                             │  verify_user()      │
                             │  (google-auth lib)  │
                             │        │            │
                             │   ┌────▼────────┐   │
                             │   │ Drive API   │   │
                             │   │ (user token │   │
                             │   │  for writes)│   │
                             │   └─────────────┘   │
                             │        │            │
                             │   ┌────▼────────┐   │
                             │   │  Firestore  │   │
                             │   │  (jobs +    │   │
                             │   │   user_id)  │   │
                             │   └─────────────┘   │
                             └─────────────────────┘
                                       │
                             ┌─────────▼──────────┐
                             │  Cloud Function     │
                             │  (Worker)           │
                             │  (service account   │
                             │   for PDF gen)      │
                             └─────────────────────┘
```

The key design choice is a **split credential model**:

- **Write operations** (create/edit edition) → use the signed-in user's Drive
  OAuth2 access token, forwarded in a separate header (`X-Drive-Token`).
- **Read/generation operations** → continue to use service-account credentials
  as today.

This keeps the public generation pipeline intact while giving users natural
Drive permission boundaries for their own editions.

---

## Permission model

| Operation | Authentication required | Drive credential used |
|---|---|---|
| `GET /editions` (list) | No | Service account (readonly) |
| `GET /{jobId}` (poll) | No | Service account (Firestore read) |
| `POST /` (generate existing edition) | No | Service account |
| `POST /editions` (create edition) | **Yes** | User's access token |
| `PATCH /editions/{id}` (edit config) | **Yes** | User's access token |
| `POST /` (generate user's own edition) | **Yes** (recommended) | Service account (PDF gen); user token for Drive reads if file isn't cached |

---

## Risks and considerations

### Security

| Risk | Mitigation |
|---|---|
| XSS → access token theft from `localStorage` | Store access tokens in memory or `sessionStorage` only; rely on ID tokens for identity (short-lived, not reusable as Drive credentials) |
| Replayed/forged ID tokens | Verify `aud` (OAuth2 client ID) and `exp` on every authenticated request; use `google-auth` library, not manual JWT parsing |
| Open redirect during OAuth2 flow | Validate the `redirect_uri` against an allowlist; GitHub Pages domain and PR preview domains must all be registered as authorised redirect URIs in the GCP OAuth2 client |
| Over-privileged scopes | Request `drive.file` for edition creation (limits to app-created files); only escalate to full `drive` scope if the user attempts to add shortcuts to files they do not own |
| CSRF on `POST /editions` | The `Authorization` header requirement provides CSRF protection for `fetch()`-based calls; no additional token needed |
| Third-party scripts (MDL CDN, GIS CDN) | Add a Content Security Policy (`script-src`) that restricts sources to known CDN hashes or domains |

### Privacy

- The API will receive and store the user's `email` and Google `sub` (subject
  ID) in Firestore job documents.  This constitutes personal data under GDPR.
- A data-deletion mechanism (right to erasure) is needed: users must be able to
  request deletion of their job history.
- No personal data should be written to GCS bucket names, PDF file names, or
  Pub/Sub message payloads.
- The OAuth2 consent screen must accurately describe what data the application
  accesses.

### User experience

- Silent token refresh (GIS `requestAccessToken()`) must be implemented to
  avoid interrupting a generation in progress when a 1-hour access token
  expires.
- Users without access to the shared Drive song-sheets folders will receive an
  authorisation error when trying to add shortcuts to existing songs.  The UI
  must surface a clear error message and suggest requesting access from the
  folder owner.
- PR preview environments each need a separate OAuth2 authorised redirect URI
  (`https://ukuleletuesday.github.io/songbook-generator/pr-preview/pr-{N}/`).
  These cannot be pre-registered dynamically; an alternative is to use the
  production GitHub Pages URL as the single redirect URI and pass the PR number
  through the OAuth2 state parameter.

### Operational

- An OAuth2 client ID must be created in the GCP console and committed to the
  repository (or managed via a repository secret / workflow variable) as it is
  safe to expose in the frontend.  The client secret is never used in a SPA
  flow.
- The OAuth2 consent screen must be published (not left in "Testing" mode)
  before external users can sign in; Google requires a review for apps
  requesting sensitive scopes (`drive`).
- Per-PR Cloud Functions will share the same OAuth2 client ID as production.
  The redirect URI allowlist must include both the production URL and PR
  preview URLs, or the strategy described in §UX above (single redirect URI
  with state) must be adopted.
- No changes to `generate-songbooks.yaml` are required: the scheduled
  generation pipeline reads config-based editions only and never calls user-
  authenticated endpoints.

---

## Summary of changes required

### UI (`ui/index.html` / `ui/styles.css`)

- Load GIS JavaScript library from `accounts.google.com/gsi/client`.
- Add a sign-in button and a signed-in state indicator (avatar + name) in the
  page header.
- After sign-in, conditionally reveal an "Add edition" button and per-card
  "Edit" controls.
- Implement token refresh logic using `google.accounts.oauth2.initTokenClient()`.
- Attach `Authorization: Bearer <ID token>` and `X-Drive-Token: <access token>`
  headers to mutating API calls.

### API (`generator/api/main.py`)

- Add `verify_user(request)` helper using `google.oauth2.id_token`.
- Add `POST /editions` endpoint (authenticated): create Drive folder +
  `.songbook.yaml` scaffold using the user's access token; record the new
  edition in Firestore.
- Add `PATCH /editions/{id}` endpoint (authenticated): update the
  `.songbook.yaml` file in the user's edition folder.
- Update `POST /` to accept an optional auth header and record `user_id` in the
  Firestore job document when present.
- Update CORS headers to expose `Authorization` in `Access-Control-Allow-Headers`.

### Configuration / deployment (`.github/workflows/deploy.yaml`, `.env`)

- Add `OAUTH2_CLIENT_ID` as a repository variable; pass it to Cloud Functions
  as an environment variable and embed it in the UI at deploy time (or load it
  from a static `config.json` file alongside `index.html`).
- Register authorised JavaScript origins and redirect URIs in the GCP OAuth2
  client configuration for the production URL and the PR preview base URL.

### Firestore schema

- Add `user_id: str` (the Google `sub` claim) to job documents.
- Consider a new top-level `user_editions` collection to track which edition
  folders a user has created through the UI (for listing in "my editions").

---

## Recommendation

**Option A (Google Identity Services with delegated Drive access)** is the
recommended path.

It is the closest fit for this architecture: a static GitHub Pages frontend
and stateless Cloud Functions backend.  It requires no new Google Cloud
products, keeps the public generation workflow intact, and gives users natural
Drive-level permission boundaries for editions they create.

Option D (domain restriction) is a simpler short-term measure but does not
deliver the core goal of user-owned editions.  Option B (Firebase Auth) adds
unnecessary abstraction for a single-provider login.  Option C (IAP) breaks
the public read workflow without significant restructuring.

The suggested delivery sequence is:

1. **Authentication plumbing** — GIS sign-in button, token storage in memory,
   `verify_user()` in the API, CORS update, OAuth2 client registration.
2. **User job history** — record `user_id` on `POST /`; expose per-user history
   in `GET /{jobId}` responses.
3. **Edition creation** — `POST /editions` endpoint + UI "Add edition" flow
   using Drive folder creation with `.songbook.yaml` scaffold.
4. **Edition editing** — `PATCH /editions/{id}` + inline UI editing of song
   lists and metadata.
5. **Privacy / GDPR compliance** — data-deletion endpoint + consent screen
   review + privacy notice update.
