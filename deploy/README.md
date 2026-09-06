# Google Cloud deployment

The backend runs as a public Cloud Run service in `southamerica-west1`. Images
are stored in Artifact Registry and connect to PostgreSQL through the Cloud SQL
Unix socket. Secret Manager supplies the database, JWT, and initial admin
passwords. GitHub Actions authenticates with Workload Identity Federation; no
service-account JSON key is used.

## One-time bootstrap from Windows

Run PowerShell from the repository root:

```powershell
.\deploy\bootstrap-gcp.ps1 `
  -ProjectId "your-unique-project-id" `
  -GitHubOwner "StefanoYZ" `
  -BillingAccount "000000-000000-000000"
```

The script installs Google Cloud CLI with `winget` when necessary, opens the
normal interactive Google login when necessary, enables APIs, and creates:

- Artifact Registry Docker repository
- A shared-core, zonal Cloud SQL PostgreSQL 16 instance with 10 GB storage
- Runtime and GitHub deployment service accounts with least-purpose IAM roles
- Secret Manager secrets, whose first values are requested interactively
- A GitHub OIDC provider restricted to `CarmencitaExpress-Backend` and
  `Front-Carmencita`, plus their service-account bindings
- Firebase resources and the default Hosting site for the frontend
- An optional billing budget when `-BudgetUsd` is explicitly provided

The script is safe to rerun. Existing resources and enabled secret versions are
reused. It prints the exact GitHub repository variables required by the
workflow when complete. Set `CORS_ORIGINS` to the deployed frontend origin.

If `-BillingAccount` is omitted, the script uses the only open billing account.
Before creating Cloud SQL, it requires confirmation that the remaining
promotional credit and its expiration date were reviewed. An activated billing
account can charge its payment method after that credit expires or is exhausted.
This project already has a console budget, so the script does not create another
budget unless `-BudgetUsd` is supplied.

## Cost controls

Cloud Run is configured with minimum instances `0`, maximum instances `1`,
concurrency `4`, one CPU, and 512 MiB memory. Cloud SQL has no always-free tier.
The bootstrap therefore uses the smallest
shared-core tier, zonal availability, 10 GB storage, and disables storage
auto-growth. Budgets alert but do not automatically stop spending. Delete the
Cloud SQL instance when the environment is no longer needed.

Review current prices before proceeding:
`https://cloud.google.com/sql/pricing` and `https://cloud.google.com/run/pricing`.

## Continuous deployment

Pushes to `main` run tests, build `backend:<full-git-sha>`, and push that exact
tag to Artifact Registry. The workflow updates and executes the Cloud Run
database bootstrap Job before deploying the web service. The Job runs:

```text
python -m app.db_bootstrap
```

The web service uses `AUTO_CREATE_SCHEMA=false`; local development defaults it
to `true`. Deployment keeps `SUNAT_ENV=mock` and performs smoke tests against
`/health` and `/ready`.

Required GitHub repository variables are printed by `bootstrap-gcp.ps1`:

| Variable | Purpose |
|---|---|
| `GCP_PROJECT_ID` | Google Cloud project ID |
| `GCP_REGION` | Cloud Run, Artifact Registry, and Cloud SQL region |
| `GCP_ARTIFACT_REGISTRY_REPOSITORY` | Docker repository name |
| `GCP_CLOUD_RUN_SERVICE` | Public API service name |
| `GCP_CLOUD_RUN_BOOTSTRAP_JOB` | Database Job name |
| `GCP_CLOUD_SQL_INSTANCE` | Cloud SQL instance name |
| `GCP_RUNTIME_SERVICE_ACCOUNT` | Runtime service-account email |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | WIF deployment service-account email |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Full WIF provider resource name |
| `GCP_DB_USER` | PostgreSQL application user |
| `GCP_DB_NAME` | PostgreSQL database name |
| `CORS_ORIGINS` | Comma-separated allowed frontend origins |

The frontend repository uses the same project, provider, and deployment
service account. Set its `GCP_DEPLOY_SERVICE_ACCOUNT` variable to the value
printed by the bootstrap.

Runtime secret names are fixed by the workflow:

| Secret Manager secret | Environment variable |
|---|---|
| `carmencita-db-password` | `DB_PASSWORD` |
| `carmencita-secret-key` | `SECRET_KEY` |
| `carmencita-admin-password` | `DEFAULT_ADMIN_PASSWORD` |

No GitHub Actions secret containing Google credentials is needed.
