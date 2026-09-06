[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z][a-z0-9-]{4,28}[a-z0-9]$')]
    [string]$ProjectId,

    [Parameter(Mandatory = $true)]
    [string]$GitHubOwner,

    [string]$BackendRepository = "CarmencitaExpress-Backend",
    [string]$FrontendRepository = "Front-Carmencita",
    [string]$BillingAccount = "",
    [string]$Region = "southamerica-west1",
    [string]$ArtifactRegistryRepository = "carmencita",
    [string]$CloudRunService = "carmencita-backend",
    [string]$BootstrapJob = "carmencita-db-bootstrap",
    [string]$CloudSqlInstance = "carmencita-postgres",
    [string]$DatabaseName = "carmencita_db",
    [string]$DatabaseUser = "carmencita",
    [decimal]$BudgetUsd = 0
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Gcloud {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $script:Gcloud @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "gcloud failed: gcloud $($Arguments -join ' ')"
    }
}

function Test-GcloudResource {
    param([string[]]$Arguments)
    & $script:Gcloud @Arguments *> $null
    return $LASTEXITCODE -eq 0
}

function ConvertTo-PlainText {
    param([Security.SecureString]$SecureValue)
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function Ensure-Secret {
    param([string]$Name, [string]$Prompt)

    if (-not (Test-GcloudResource @("secrets", "describe", $Name, "--project", $ProjectId))) {
        Invoke-Gcloud secrets create $Name --project $ProjectId --replication-policy automatic
    }

    $enabledVersion = & $script:Gcloud secrets versions list $Name --project $ProjectId --filter "state=ENABLED" --format "value(name)" --limit 1
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect Secret Manager versions for $Name"
    }
    if ($enabledVersion) {
        return
    }

    $secureValue = Read-Host $Prompt -AsSecureString
    $plainValue = ConvertTo-PlainText $secureValue
    $temporaryFile = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($temporaryFile, $plainValue, [Text.UTF8Encoding]::new($false))
        Invoke-Gcloud secrets versions add $Name --project $ProjectId --data-file $temporaryFile
    }
    finally {
        $plainValue = $null
        Remove-Item -LiteralPath $temporaryFile -Force -ErrorAction SilentlyContinue
    }
}

function Enable-Firebase {
    $accessToken = & $script:Gcloud auth print-access-token
    if ($LASTEXITCODE -ne 0 -or -not $accessToken) {
        throw "Unable to obtain an access token to initialize Firebase."
    }

    $headers = @{
        Authorization = "Bearer $accessToken"
        "x-goog-user-project" = $ProjectId
    }
    $projectUri = "https://firebase.googleapis.com/v1beta1/projects/$ProjectId"
    try {
        Invoke-RestMethod -Method Get -Uri $projectUri -Headers $headers | Out-Null
        return
    }
    catch {
        if (-not $_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne 404) {
            throw
        }
    }

    $operation = Invoke-RestMethod -Method Post -Uri "$projectUri`:addFirebase" -Headers $headers
    $operationUri = "https://firebase.googleapis.com/v1beta1/$($operation.name)"
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        Start-Sleep -Seconds 2
        $operation = Invoke-RestMethod -Method Get -Uri $operationUri -Headers $headers
        if ($operation.error) {
            throw "Firebase initialization failed: $($operation.error.message)"
        }
        if ($operation.done) {
            return
        }
    }
    throw "Firebase initialization did not finish within 60 seconds."
}

$gcloudCommand = Get-Command gcloud -ErrorAction SilentlyContinue
if (-not $gcloudCommand) {
    $wingetCommand = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $wingetCommand) {
        throw "Google Cloud CLI is required. Install it from https://cloud.google.com/sdk/docs/install-sdk#windows and rerun this script."
    }
    Write-Host "Google Cloud CLI was not found. Installing it with winget..."
    & winget install --exact --id Google.CloudSDK --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "Google Cloud CLI installation failed."
    }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"),
        (Join-Path $env:ProgramFiles "Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"),
        (Join-Path ${env:ProgramFiles(x86)} "Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd")
    )
    $candidate = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $candidate) {
        throw "gcloud was installed but is not available in this shell. Open a new PowerShell window and rerun the script."
    }
    $script:Gcloud = $candidate
}
else {
    $script:Gcloud = $gcloudCommand.Source
}

$activeAccount = & $script:Gcloud auth list --filter "status:ACTIVE" --format "value(account)" --limit 1
if (-not $activeAccount) {
    Invoke-Gcloud auth login
}

if (-not (Test-GcloudResource @("projects", "describe", $ProjectId))) {
    Invoke-Gcloud projects create $ProjectId --name "Carmencita Express"
}

if (-not $BillingAccount) {
    $billingAccounts = @(& $script:Gcloud billing accounts list --filter "open=true" --format "value(name)")
    if ($LASTEXITCODE -ne 0 -or $billingAccounts.Count -ne 1) {
        throw "Pass -BillingAccount because exactly one open billing account could not be selected automatically."
    }
    $BillingAccount = $billingAccounts[0] -replace '^billingAccounts/', ''
}

Write-Warning "Cloud SQL consumes promotional credit while it remains available. This paid billing account can charge its payment method after the credit expires or is exhausted."
$confirmation = Read-Host "Type CREDITS-VERIFIED after checking the remaining credit and expiration date"
if ($confirmation -ne "CREDITS-VERIFIED") {
    throw "Bootstrap cancelled before billable resources were created."
}
Invoke-Gcloud billing projects link $ProjectId --billing-account $BillingAccount

Invoke-Gcloud config set project $ProjectId
$services = @(
    "artifactregistry.googleapis.com",
    "billingbudgets.googleapis.com",
    "cloudbilling.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "firebase.googleapis.com",
    "firebasehosting.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com",
    "sqladmin.googleapis.com",
    "sts.googleapis.com"
)
Invoke-Gcloud services enable @services --project $ProjectId

$runtimeAccountId = "carmencita-runtime"
$deployAccountId = "carmencita-github"
$runtimeAccount = "$runtimeAccountId@$ProjectId.iam.gserviceaccount.com"
$deployAccount = "$deployAccountId@$ProjectId.iam.gserviceaccount.com"

foreach ($account in @(
    @{ Id = $runtimeAccountId; Name = "Carmencita Cloud Run runtime" },
    @{ Id = $deployAccountId; Name = "Carmencita GitHub deployer" }
)) {
    if (-not (Test-GcloudResource @("iam", "service-accounts", "describe", "$($account.Id)@$ProjectId.iam.gserviceaccount.com", "--project", $ProjectId))) {
        Invoke-Gcloud iam service-accounts create $account.Id --project $ProjectId --display-name $account.Name
    }
}

foreach ($role in @("roles/cloudsql.client", "roles/secretmanager.secretAccessor")) {
    Invoke-Gcloud projects add-iam-policy-binding $ProjectId --member "serviceAccount:$runtimeAccount" --role $role --condition None --quiet
}
foreach ($role in @("roles/artifactregistry.writer", "roles/cloudsql.viewer", "roles/firebase.viewer", "roles/firebasehosting.admin", "roles/run.admin", "roles/secretmanager.viewer", "roles/serviceusage.serviceUsageConsumer")) {
    Invoke-Gcloud projects add-iam-policy-binding $ProjectId --member "serviceAccount:$deployAccount" --role $role --condition None --quiet
}
Invoke-Gcloud iam service-accounts add-iam-policy-binding $runtimeAccount --project $ProjectId --member "serviceAccount:$deployAccount" --role roles/iam.serviceAccountUser --quiet

if (-not (Test-GcloudResource @("artifacts", "repositories", "describe", $ArtifactRegistryRepository, "--project", $ProjectId, "--location", $Region))) {
    Invoke-Gcloud artifacts repositories create $ArtifactRegistryRepository --project $ProjectId --location $Region --repository-format docker --description "Carmencita backend images"
}

if (-not (Test-GcloudResource @("sql", "instances", "describe", $CloudSqlInstance, "--project", $ProjectId))) {
    Write-Warning "Creating the billable Cloud SQL instance with a shared-core, zonal, 10 GB configuration and storage auto-growth disabled."
    Invoke-Gcloud sql instances create $CloudSqlInstance --project $ProjectId --region $Region --database-version POSTGRES_16 --tier db-f1-micro --availability-type zonal --storage-type SSD --storage-size 10 --no-storage-auto-increase
}

if (-not (Test-GcloudResource @("sql", "databases", "describe", $DatabaseName, "--instance", $CloudSqlInstance, "--project", $ProjectId))) {
    Invoke-Gcloud sql databases create $DatabaseName --instance $CloudSqlInstance --project $ProjectId
}

Ensure-Secret "carmencita-db-password" "Enter the Cloud SQL application password"
Ensure-Secret "carmencita-secret-key" "Enter a long random JWT secret"
Ensure-Secret "carmencita-admin-password" "Enter the initial administrator password"

$databasePassword = & $script:Gcloud secrets versions access latest --secret "carmencita-db-password" --project $ProjectId
if ($LASTEXITCODE -ne 0) {
    throw "Unable to read the database password secret."
}
$databaseUserExists = & $script:Gcloud sql users list --instance $CloudSqlInstance --project $ProjectId --filter "name=$DatabaseUser" --format "value(name)" --limit 1
if ($databaseUserExists) {
    Invoke-Gcloud sql users set-password $DatabaseUser --instance $CloudSqlInstance --project $ProjectId --password $databasePassword
}
else {
    Invoke-Gcloud sql users create $DatabaseUser --instance $CloudSqlInstance --project $ProjectId --password $databasePassword
}
$databasePassword = $null

$poolId = "github-actions"
$providerId = "github"
if (-not (Test-GcloudResource @("iam", "workload-identity-pools", "describe", $poolId, "--project", $ProjectId, "--location", "global"))) {
    Invoke-Gcloud iam workload-identity-pools create $poolId --project $ProjectId --location global --display-name "GitHub Actions"
}
$repositoryCondition = "assertion.repository=='$GitHubOwner/$BackendRepository' || assertion.repository=='$GitHubOwner/$FrontendRepository'"
if (Test-GcloudResource @("iam", "workload-identity-pools", "providers", "describe", $providerId, "--project", $ProjectId, "--location", "global", "--workload-identity-pool", $poolId)) {
    Invoke-Gcloud iam workload-identity-pools providers update-oidc $providerId --project $ProjectId --location global --workload-identity-pool $poolId --issuer-uri "https://token.actions.githubusercontent.com" --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" --attribute-condition $repositoryCondition
}
else {
    Invoke-Gcloud iam workload-identity-pools providers create-oidc $providerId --project $ProjectId --location global --workload-identity-pool $poolId --display-name "Carmencita GitHub repositories" --issuer-uri "https://token.actions.githubusercontent.com" --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" --attribute-condition $repositoryCondition
}

$projectNumber = & $script:Gcloud projects describe $ProjectId --format "value(projectNumber)"
foreach ($repository in @($BackendRepository, $FrontendRepository)) {
    $principal = "principalSet://iam.googleapis.com/projects/$projectNumber/locations/global/workloadIdentityPools/$poolId/attribute.repository/$GitHubOwner/$repository"
    Invoke-Gcloud iam service-accounts add-iam-policy-binding $deployAccount --project $ProjectId --member $principal --role roles/iam.workloadIdentityUser --quiet
}

Enable-Firebase

if ($BudgetUsd -gt 0) {
    $budgetName = & $script:Gcloud billing budgets list --billing-account $BillingAccount --filter "displayName=Carmencita Free Trial guardrail" --format "value(name)" --limit 1
    if (-not $budgetName) {
        Invoke-Gcloud billing budgets create --billing-account $BillingAccount --display-name "Carmencita Free Trial guardrail" --budget-amount "${BudgetUsd}USD" --filter-projects "projects/$projectNumber" --threshold-rule percent=0.5 --threshold-rule percent=0.9 --threshold-rule percent=1.0
    }
}

$providerName = "projects/$projectNumber/locations/global/workloadIdentityPools/$poolId/providers/$providerId"
Write-Host ""
Write-Host "Bootstrap complete. Configure these GitHub repository variables:"
Write-Host "GCP_PROJECT_ID=$ProjectId"
Write-Host "GCP_REGION=$Region"
Write-Host "GCP_ARTIFACT_REGISTRY_REPOSITORY=$ArtifactRegistryRepository"
Write-Host "GCP_CLOUD_RUN_SERVICE=$CloudRunService"
Write-Host "GCP_CLOUD_RUN_BOOTSTRAP_JOB=$BootstrapJob"
Write-Host "GCP_CLOUD_SQL_INSTANCE=$CloudSqlInstance"
Write-Host "GCP_RUNTIME_SERVICE_ACCOUNT=$runtimeAccount"
Write-Host "GCP_DEPLOY_SERVICE_ACCOUNT=$deployAccount"
Write-Host "GCP_WORKLOAD_IDENTITY_PROVIDER=$providerName"
Write-Host "GCP_DB_USER=$DatabaseUser"
Write-Host "GCP_DB_NAME=$DatabaseName"
Write-Host "CORS_ORIGINS=https://$ProjectId.web.app,https://$ProjectId.firebaseapp.com"
Write-Host "Frontend repository: set GCP_DEPLOY_SERVICE_ACCOUNT=$deployAccount"
Write-Host ""
Write-Host "No Google service-account key or GitHub JSON secret is required."
