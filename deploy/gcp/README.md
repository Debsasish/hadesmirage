# Hades Mirage on Google Cloud: Cloud Run + IAP (Google Workspace) + Vertex AI Gemini

> **Status: prepared and locally tested, not deployed.** This delivery had no gcloud CLI and no
> Google Cloud credentials. Nothing was built by Cloud Build, deployed to Cloud Run, protected by
> IAP or sent to Vertex AI. The steps below are the intended procedure. Treat every cloud
> behaviour as unverified until you have run the checklist in [Verify after deploying](#verify-after-deploying).

## What gets deployed

| Piece | How it works |
| --- | --- |
| Build | `gcloud run deploy --source .` uploads the source; **Cloud Build builds the image remotely with Google Cloud buildpacks**. There is **no Dockerfile** and **no local Docker**. The buildpack reads `.python-version` (3.13), `requirements.txt` (which includes the exact pins in `requirements.lock`) and `Procfile` (`web: python -m mirage cloud`). |
| Runtime | One Cloud Run service with profile `P2-cloud`. `python -m mirage cloud` starts the signed synthetic backend on container loopback `127.0.0.1:8788` (unreachable from outside) and the API/console on `0.0.0.0:$PORT`. It checks both are ready, logs to stdout/stderr (Cloud Logging) and passes SIGTERM on to both child processes. |
| Sign-in | Google Workspace accounts through **Identity-Aware Proxy (IAP)** enabled directly on the Cloud Run service. The app trusts only the signed `x-goog-iap-jwt-assertion` header. It checks ES256, the IAP key set, issuer `https://cloud.google.com/iap`, audience, expiry, email and the Workspace domain. It ignores the unsigned `x-goog-authenticated-user-*` headers. Fixture login is disabled. |
| Roles | Roles come from operator configuration (`MIRAGE_IAP_ROLE_MAP`), never from the model. |
| AI | Vertex AI Gemini through `google-genai` with the service account's Application Default Credentials (`roles/aiplatform.user`). No API keys. The AI output is advisory only. The model has no signer, router, shell or backend credentials. |
| Data | Synthetic only. Labels in the console and logs say so. |

## Cost warning

This creates billable resources: Cloud Build minutes, an Artifact Registry image
(`cloud-run-source-deploy` repository), Cloud Run CPU/memory, Secret Manager versions and
access, and Vertex AI tokens. The defaults keep costs small: one instance at most, scale to zero,
CPU only during requests. `-KeepWarm` and `-WithTelegram` keep one instance running all the time,
and you pay for it continuously. Delete everything when the demo is over (see
[Rollback and deletion](#rollback-and-deletion)). Set a billing budget alert on the project.

## Prerequisites

1. A Google Cloud project with billing, **inside your Google Workspace organization**. IAP's
   Google-managed OAuth client admits only users of the same organization. External users need a
   custom OAuth client, configured in the console ("Outside org" in Google's IAP for Cloud Run
   documentation).
2. Your account needs Owner, or these roles: Cloud Run Admin, IAP Policy Admin, Service Account
   Admin + Service Account User, Project IAM Admin, Secret Manager Admin, Service Usage Admin and
   Cloud Build Editor.
3. [Google Cloud CLI](https://cloud.google.com/sdk/docs/install), recent enough to support
   `gcloud run deploy --iap` (`gcloud components update`), and Node.js/npm to build the console.

## Deploy (Windows PowerShell)

```powershell
gcloud auth login
cd C:\path\to\hades-mirage-blueprint

# If script execution is blocked, prefix with: powershell -ExecutionPolicy Bypass -File
.\deploy\gcp\deploy.ps1 `
    -ProjectId my-demo-project `
    -Region us-central1 `
    -AdminEmail alex@example.com `
    -AllowedDomain example.com `
    -ApproverEmails sam@example.com `
    -AnalystEmails jordan@example.com `
    -GeminiModel gemini-2.5-flash `
    -ApproveModelEgress
```

Parameters: `-ServiceName` (default `hades-mirage`), `-GeminiLocation` (default `global`),
`-GrantDomainAccess` (IAP admits the whole `-AllowedDomain`), `-DefaultAnalyst` (unmapped
accounts in that domain get `analyst` instead of 403), `-KeepWarm`, `-WithTelegram`,
`-TelegramMode polling|webhook` and `-SkipConsoleBuild`.

The script stops at the first error (`$ErrorActionPreference = 'Stop'`, validated parameters).
Re-running it is safe: it updates the same resources. In order, it:

1. Checks for `gcloud`, the active account and the project number. It builds the console
   (`npm.cmd run build` in `apps\dashboard`, running `npm.cmd ci` first if needed) and refuses to
   continue without `apps\dashboard\dist\index.html`. `.gcloudignore` uploads `dist` and
   excludes `.venv`, `node_modules`, `.local`, tests and secrets.
2. Enables `run`, `cloudbuild`, `artifactregistry`, `aiplatform`, `secretmanager` and `iap`, and
   creates the IAP service agent.
3. Creates the service account `<service>-sa` and grants it only `roles/aiplatform.user`
   (project) and `roles/secretmanager.secretAccessor` **on each secret it needs**. It also grants
   `roles/run.builder` to the Compute Engine default account, which is the role Google documents
   for source-deploy builds. If that grant fails, the script prints a warning and continues.
4. Generates the backend HMAC secret with a CSPRNG and stores it in Secret Manager as
   `<service>-backend-secret`. With `-WithTelegram`, it asks for the bot token with hidden input.
   Values go to gcloud through stdin and are never printed.
5. Deploys with the following command (the env file is generated, ignored for upload and deleted
   afterwards):

   ```text
   gcloud run deploy hades-mirage --source . --region=us-central1 --project=PROJECT
     --service-account=hades-mirage-sa@PROJECT.iam.gserviceaccount.com
     --no-allow-unauthenticated --iap --max-instances=1 --min-instances=0
     --concurrency=40 --cpu=1 --memory=1Gi --timeout=60
     --env-vars-file=deploy/gcp/.generated-env.yaml
     --set-secrets=MIRAGE_BACKEND_SECRET=hades-mirage-backend-secret:latest
     --labels=app=hades-mirage,profile=p2-cloud,data=synthetic --quiet
   ```

   The env file sets `MIRAGE_PROFILE=P2-cloud`, `MIRAGE_AUTH_MODE=iap`,
   `MIRAGE_LOCAL_LOGIN=false`, `MIRAGE_DATA_DIR=/tmp/mirage`, `MIRAGE_IAP_AUDIENCE`,
   `MIRAGE_IAP_ALLOWED_DOMAIN`, `MIRAGE_IAP_ROLE_MAP`, `MIRAGE_IAP_DEFAULT_ROLE`,
   `MIRAGE_ALLOWED_HOSTS`, `MIRAGE_ALLOWED_ORIGINS`, `MIRAGE_PUBLIC_URL`,
   `MIRAGE_MODEL_PROVIDER=gemini`, `MIRAGE_GEMINI_PROJECT/LOCATION/MODEL`,
   `MIRAGE_MODEL_EGRESS_APPROVED` and `MIRAGE_TELEGRAM_MODE`. A YAML file avoids PowerShell
   quoting problems with the JSON values.
6. Reads every service URL: the deterministic `https://SERVICE-PROJECT_NUMBER.REGION.run.app`
   and any legacy `*.a.run.app` URL. If there is more than one, it runs
   `gcloud run services update` so that all of them are allowed hosts and origins.
7. Grants `roles/run.invoker` to `service-PROJECT_NUMBER@gcp-sa-iap.iam.gserviceaccount.com` and
   `roles/iap.httpsResourceAccessor` to every mapped user, plus `domain:<AllowedDomain>` with
   `-GrantDomainAccess`. It uses `gcloud iap web add-iam-policy-binding --resource-type=cloud-run`.

**IAP audience.** For IAP on Cloud Run the JWT `aud` is
`/projects/PROJECT_NUMBER/locations/REGION/services/SERVICE_NAME`. The script computes it and
sets `MIRAGE_IAP_AUDIENCE`. The app refuses to start in IAP mode without it.

## Verify after deploying

1. `gcloud run services describe hades-mirage --region=REGION` shows `Iap Enabled: true`.
2. Open the console URL in a browser, sign in with a mapped Workspace account, and check that the
   header shows your email and roles (`GET /auth/me`).
3. A private window with an unmapped account: IAP denies it, or the app returns 403
   `IAP_ROLE_UNMAPPED`. `curl https://SERVICE-URL/v1/settings` without credentials does not reach
   the app.
4. In the AI settings, choose the Gemini model and run one investigation on a synthetic case. Then
   check `gcloud run services logs read hades-mirage --region=REGION --limit=50`.
5. Only after these pass can you claim "deployed on Cloud Run with IAP". Record the revision name
   and the date.

## Google Workspace roles

There are two separate gates:

- **IAP** decides who reaches the service (`roles/iap.httpsResourceAccessor`).
- **Hades Mirage** decides what that person may do. It reads `MIRAGE_IAP_ROLE_MAP`, a JSON object
  that maps an email to roles from `analyst`, `approver` and `security_admin`:

  ```json
  {"alex@example.com": ["analyst", "security_admin"], "sam@example.com": ["analyst", "approver"]}
  ```

  Emails are compared in lowercase. An empty list is an explicit denial. An unmapped user gets
  403 unless `MIRAGE_IAP_DEFAULT_ROLE=analyst`. When `MIRAGE_IAP_ALLOWED_DOMAIN` is set, the JWT
  `hd` claim **and** the email domain must both match it, so consumer accounts are refused.
- On first sign-in the app creates a human principal `iap-<first 16 hex of sha256(email)>` in
  `MIRAGE_IAP_TENANT` (default `tenant-demo`) and audits `auth.iap_principal_created`. Role
  changes update the row, increment `identity_epoch` and audit `auth.iap_roles_updated`. Approval
  separation and lineage checks work as they do for the local identities.
- To change roles, re-run `deploy.ps1` with new `-AdminEmail`, `-ApproverEmails` and
  `-AnalystEmails`.
- Browser changes still require an allowed `Origin` and `X-CSRF-Token`. In IAP mode the token is
  an HMAC of tenant, principal and UTC day under a key derived from the backend secret.
  `/auth/me` returns it, and the console already reads it from there.
- Sign-out: `POST /auth/logout` returns `iap_sign_out_url` (`/?gcp-iap-mode=CLEAR_LOGIN_COOKIE`).
- API clients can still use Mirage bearer tokens (`Authorization: Bearer ...`). Through IAP, send
  the Google identity token for IAP in `Proxy-Authorization`. Note that the fixture bearer tokens
  exist only inside the container (`/tmp/mirage/fixture-credentials.json`). There is no cloud
  process yet for issuing workload tokens.

## Vertex AI Gemini model selection

- Defaults come from the environment: `MIRAGE_MODEL_PROVIDER=gemini`,
  `MIRAGE_GEMINI_PROJECT=<project>`, `MIRAGE_GEMINI_LOCATION` (`-GeminiLocation`, default
  `global`) and `MIRAGE_GEMINI_MODEL` (`-GeminiModel`). Calls stay blocked until
  `MIRAGE_MODEL_EGRESS_APPROVED=true` (`-ApproveModelEgress`). Pass that switch only after
  approving that synthetic case data may be sent to Vertex AI.
- A `security_admin` can switch provider and model at runtime in the portal's AI settings. With
  SQLite, that choice lasts only for the life of the instance, and the environment defaults return
  after a restart.
- Which models are available depends on region and changes over time. Check the Vertex AI model
  list for your project before choosing one. Call budgets (`MIRAGE_MODEL_CALL_BUDGET`,
  `MIRAGE_MODEL_CASE_CALL_BUDGET`) still apply.

## Telegram in the cloud

- **Use polling.** IAP protects every path of the service, and Telegram cannot present Google
  credentials, so a webhook sent to this service never reaches the app. `-WithTelegram` stores
  the token in Secret Manager (`MIRAGE_TELEGRAM_BOT_TOKEN`) and sets
  `MIRAGE_TELEGRAM_MODE=polling`. It also adds `--no-cpu-throttling --min-instances=1` so the
  polling loop keeps running, which costs money continuously.
- `-TelegramMode webhook` creates a webhook secret (`MIRAGE_TELEGRAM_WEBHOOK_SECRET`) but does
  **not** call `setWebhook`. It is only useful once the webhook path has its own non-IAP ingress,
  for example an external HTTPS load balancer with IAP only on the console backend. That ingress is
  not provided or validated here. After it exists, register the webhook without putting secrets
  in shared history:

  ```powershell
  $token = Read-Host -AsSecureString 'Bot token'; $secret = Read-Host -AsSecureString 'Webhook secret'
  $plain = { param($s) [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)) }
  Invoke-RestMethod -Method Post -Uri ("https://api.telegram.org/bot" + (& $plain $token) + "/setWebhook") `
      -Body @{ url = 'https://YOUR-NON-IAP-HOST/<telegram webhook path>'; secret_token = (& $plain $secret) }
  ```

## Persistence and scaling limits

- State is SQLite under `/tmp/mirage`. Cloud Run's filesystem is in memory, so the state belongs to
  one instance. It is **lost on restart, redeploy and scale-to-zero** (with `--min-instances=0`
  an idle service stops after a while). Use `-KeepWarm` for a demo session.
- `--max-instances=1` is required. Each instance would otherwise have its own database, and the
  dispatch fencing is not shared.
- For persistence, point `MIRAGE_DATABASE_URL` at Cloud SQL for PostgreSQL. The PostgreSQL code
  path exists but has **not been runtime-validated**, and the script does not provision Cloud SQL,
  connectors or networking.
- Recorded laboratory scenarios and synthetic case purge are currently enabled only in
  `P1-native`. The cloud console therefore starts with the seeded tenants, identities and policy,
  but no replayed scenarios.

## Rollback and deletion

```powershell
# Roll back to an earlier revision
gcloud run revisions list --service=hades-mirage --region=REGION --project=PROJECT
gcloud run services update-traffic hades-mirage --to-revisions=REVISION_NAME=100 --region=REGION --project=PROJECT

# Remove one user's access immediately
gcloud iap web remove-iam-policy-binding --member=user:EMAIL --role=roles/iap.httpsResourceAccessor --region=REGION --resource-type=cloud-run --service=hades-mirage --project=PROJECT

# Delete everything this procedure created
gcloud run services delete hades-mirage --region=REGION --project=PROJECT
gcloud secrets delete hades-mirage-backend-secret --project=PROJECT
gcloud secrets delete hades-mirage-telegram-bot-token --project=PROJECT        # if created
gcloud secrets delete hades-mirage-telegram-webhook-secret --project=PROJECT   # if created
gcloud projects remove-iam-policy-binding PROJECT --member=serviceAccount:hades-mirage-sa@PROJECT.iam.gserviceaccount.com --role=roles/aiplatform.user
gcloud iam service-accounts delete hades-mirage-sa@PROJECT.iam.gserviceaccount.com --project=PROJECT
gcloud artifacts repositories delete cloud-run-source-deploy --location=REGION --project=PROJECT   # source-deploy images
```

## What was verified in this delivery, and what was not

Verified locally on Windows with Python 3.13:

- `tests/test_cloud.py`: IAP JWT verification against locally generated ES256 (P-256) keys, with
  only the key download replaced. Covered cases:
  - a valid assertion creates the principal with the mapped roles
  - wrong audience, wrong issuer, expired, wrong key, unknown key id, `alg: none`, a malformed
    token, a missing email or a missing header are refused with 401
  - a foreign domain, a missing `hd`, or an unmapped or explicitly empty role is refused with 403
  - forged `x-goog-authenticated-user-email` is ignored
  - CSRF and `Origin` are enforced for mutations, and the CSRF token is per user and per day
  - bearer tokens still work
  - fixture login returns 403 in `P2-cloud`
  - host allow-listing, key caching, and fail-closed key-fetch errors (503)
  - settings validation and launcher checks
- `python -m mirage cloud` with `PORT=8899`: `/health` returned 200 (`P2-cloud`), unauthenticated
  `/v1/settings` returned 401, forged unsigned identity headers returned 401, an unknown `Host`
  returned 400, fixture login returned 403, the console was served, the API listened on
  `0.0.0.0:8899` and the backend on `127.0.0.1:8898`.
- `deploy.ps1` parses with zero errors in Windows PowerShell 5.1. Its generated env file was loaded
  back into `Settings`.
- `pip install --dry-run` for Linux x86_64 / CPython 3.13 resolved every pin through
  `requirements.txt`.

Not verified: the Cloud Build buildpack build, the Cloud Run deployment, IAP behaviour and real
IAP JWTs, Secret Manager mapping, Vertex AI Gemini calls, Telegram, SIGTERM handling on Linux
(the test host was Windows) and PostgreSQL. The Python evaluator and this Cloud Run profile say
nothing about the Rust gateway (P3). Cloud Run ingress or IAP admission is not tool
authorization. Tool authorization stays in the application's policy and approval checks.
