#Requires -Version 5.1
<#
.SYNOPSIS
    Deploys the Hades Mirage cloud demo (profile P2-cloud, synthetic data only) to Cloud Run.

.DESCRIPTION
    Source deploy with Google Cloud buildpacks: `gcloud run deploy --source .` uploads the
    source and Cloud Build builds the container image remotely. No Dockerfile is used and no
    local Docker is required. Sign-in is Google Workspace through Identity-Aware Proxy (IAP);
    Gemini runs on Vertex AI with the service account's own identity (no API keys).

    The script never prints secret values. It creates (when missing): a dedicated runtime
    service account, Secret Manager secrets, IAP access bindings and the Cloud Run service.
    Running it creates billable Google Cloud resources. See deploy/gcp/README.md.

.EXAMPLE
    .\deploy\gcp\deploy.ps1 -ProjectId my-demo-project -AdminEmail alex@example.com `
        -AllowedDomain example.com -ApproverEmails sam@example.com -ApproveModelEgress
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z][a-z0-9-]{4,28}[a-z0-9]$')]
    [string]$ProjectId,

    [ValidatePattern('^[a-z]+-[a-z]+[0-9]+$')]
    [string]$Region = 'us-central1',

    [ValidatePattern('^[a-z][a-z0-9-]{1,25}[a-z0-9]$')]
    [string]$ServiceName = 'hades-mirage',

    [ValidatePattern('^[A-Za-z0-9._-]{1,200}$')]
    [string]$GeminiModel = 'gemini-2.5-flash',

    [ValidatePattern('^[a-z0-9-]{1,100}$')]
    [string]$GeminiLocation = 'global',

    [ValidatePattern('^$|^[a-z0-9-]+(\.[a-z0-9-]+)+$')]
    [string]$AllowedDomain = '',

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')]
    [string]$AdminEmail,

    [ValidateScript({ $_ -match '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$' })]
    [string[]]$ApproverEmails = @(),

    [ValidateScript({ $_ -match '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$' })]
    [string[]]$AnalystEmails = @(),

    # Let IAP admit every account of -AllowedDomain (the app still requires a role).
    [switch]$GrantDomainAccess,

    # Unmapped accounts of -AllowedDomain get the read-only analyst role instead of HTTP 403.
    [switch]$DefaultAnalyst,

    # Explicit approval that synthetic case data may be sent to Vertex AI Gemini.
    [switch]$ApproveModelEgress,

    # Prompt (hidden input) for a Telegram bot token and store it in Secret Manager.
    [switch]$WithTelegram,

    [ValidateSet('polling', 'webhook')]
    [string]$TelegramMode = 'polling',

    # Keep one instance warm so the in-memory demo state survives idle periods (continuous cost).
    [switch]$KeepWarm,

    [switch]$SkipConsoleBuild
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$EnvFile = Join-Path $PSScriptRoot '.generated-env.yaml'
$OnWindows = [System.Environment]::OSVersion.Platform -eq 'Win32NT'

function Write-Step([string]$Message) {
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Gcloud([string[]]$Arguments) {
    # gcloud reports progress on stderr; success is decided by the exit code only.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & gcloud @Arguments
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) { throw "gcloud $($Arguments[0..2] -join ' ') failed (exit code $code)" }
}

function Get-GcloudOutput([string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & gcloud @Arguments
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) { throw "gcloud $($Arguments[0..2] -join ' ') failed (exit code $code)" }
    return ($output | Out-String).Trim()
}

function Test-Gcloud([string[]]$Arguments) {
    # Existence probes: failure is an expected answer, and their output is discarded.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & gcloud @Arguments 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $previous
    }
}

function New-RandomSecret {
    $bytes = New-Object byte[] 48
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Add-SecretVersion([string]$Name, [string]$Value) {
    # The value reaches gcloud byte-exact through stdin: never on a command line or the console.
    if (-not (Test-Gcloud @('secrets', 'describe', $Name, "--project=$ProjectId"))) {
        Invoke-Gcloud @('secrets', 'create', $Name, '--replication-policy=automatic',
            "--project=$ProjectId", '--quiet')
    }
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $arguments = "secrets versions add $Name --data-file=- --project=$ProjectId --quiet"
    if ($OnWindows) {
        $gcloudCmd = (Get-Command gcloud.cmd -CommandType Application | Select-Object -First 1).Source
        $info.FileName = $env:ComSpec
        $info.Arguments = "/d /c `"`"$gcloudCmd`" $arguments`""
    } else {
        $info.FileName = (Get-Command gcloud -CommandType Application | Select-Object -First 1).Source
        $info.Arguments = $arguments
    }
    $info.UseShellExecute = $false
    $info.RedirectStandardInput = $true
    $process = [System.Diagnostics.Process]::Start($info)
    $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($Value)
    $process.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
    $process.StandardInput.Close()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "Storing a version of secret $Name failed" }
}

function Grant-SecretAccess([string]$Name) {
    Invoke-Gcloud @('secrets', 'add-iam-policy-binding', $Name, "--project=$ProjectId",
        "--member=serviceAccount:$ServiceAccount", '--role=roles/secretmanager.secretAccessor',
        '--quiet')
}

function ConvertTo-YamlValue([string]$Value) {
    return "'" + $Value.Replace("'", "''") + "'"
}

function Write-EnvFile([string[]]$Urls) {
    $hosts = @($Urls | ForEach-Object { ([Uri]$_).Host } | Select-Object -Unique)
    $values = [ordered]@{
        MIRAGE_PROFILE               = 'P2-cloud'
        MIRAGE_AUTH_MODE             = 'iap'
        MIRAGE_LOCAL_LOGIN           = 'false'
        MIRAGE_DATA_DIR              = '/tmp/mirage'
        MIRAGE_IAP_AUDIENCE          = $Audience
        MIRAGE_IAP_ALLOWED_DOMAIN    = $AllowedDomain
        MIRAGE_IAP_ROLE_MAP          = $RoleMapJson
        MIRAGE_IAP_DEFAULT_ROLE      = $(if ($DefaultAnalyst) { 'analyst' } else { 'none' })
        MIRAGE_ALLOWED_HOSTS         = (ConvertTo-Json -InputObject $hosts -Compress)
        MIRAGE_ALLOWED_ORIGINS       = (ConvertTo-Json -InputObject @($Urls) -Compress)
        MIRAGE_PUBLIC_URL            = $Urls[0]
        MIRAGE_MODEL_PROVIDER        = 'gemini'
        MIRAGE_GEMINI_PROJECT        = $ProjectId
        MIRAGE_GEMINI_LOCATION       = $GeminiLocation
        MIRAGE_GEMINI_MODEL          = $GeminiModel
        MIRAGE_MODEL_EGRESS_APPROVED = $(if ($ApproveModelEgress) { 'true' } else { 'false' })
        MIRAGE_TELEGRAM_MODE         = $(if ($WithTelegram) { $TelegramMode } else { 'disabled' })
    }
    $lines = foreach ($key in $values.Keys) { "${key}: $(ConvertTo-YamlValue ([string]$values[$key]))" }
    [System.IO.File]::WriteAllText($EnvFile, ($lines -join "`n") + "`n",
        (New-Object System.Text.UTF8Encoding($false)))
}

function Get-ServiceUrls {
    $described = Get-GcloudOutput @('run', 'services', 'describe', $ServiceName,
        "--region=$Region", "--project=$ProjectId", '--format=json') | ConvertFrom-Json
    $urls = New-Object System.Collections.Generic.List[string]
    $urls.Add($DeterministicUrl)
    $metadata = $described.PSObject.Properties['metadata']
    if ($null -ne $metadata -and $null -ne $metadata.Value.PSObject.Properties['annotations']) {
        $annotation = $metadata.Value.annotations.PSObject.Properties['run.googleapis.com/urls']
        if ($null -ne $annotation) {
            foreach ($url in @($annotation.Value | ConvertFrom-Json)) { $urls.Add([string]$url) }
        }
    }
    $status = $described.PSObject.Properties['status']
    if ($null -ne $status -and $null -ne $status.Value.PSObject.Properties['url']) {
        $urls.Add([string]$status.Value.url)
    }
    return @($urls | Where-Object { $_ } | ForEach-Object { $_.TrimEnd('/') } | Select-Object -Unique)
}

# ---------------------------------------------------------------------------------------------
Write-Step 'Checking prerequisites (gcloud account, project, console build)'
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    throw 'gcloud CLI not found. Install the Google Cloud CLI, then run: gcloud auth login'
}
$Account = Get-GcloudOutput @('config', 'get-value', 'account')
if (-not $Account) { throw 'No active gcloud account. Run: gcloud auth login' }
Write-Host "Deploying as $Account to project $ProjectId ($Region). This creates billable resources."

$ProjectNumber = Get-GcloudOutput @('projects', 'describe', $ProjectId, '--format=value(projectNumber)')
if ($ProjectNumber -notmatch '^[0-9]+$') { throw "Could not read the project number of $ProjectId" }
$ServiceAccountId = "$ServiceName-sa"
$ServiceAccount = "$ServiceAccountId@$ProjectId.iam.gserviceaccount.com"
$Audience = "/projects/$ProjectNumber/locations/$Region/services/$ServiceName"
$DeterministicUrl = "https://$ServiceName-$ProjectNumber.$Region.run.app"
$BackendSecretName = "$ServiceName-backend-secret"
$TelegramTokenName = "$ServiceName-telegram-bot-token"
$TelegramWebhookName = "$ServiceName-telegram-webhook-secret"

$RoleMap = [ordered]@{}
foreach ($email in $AnalystEmails) { $RoleMap[$email.ToLowerInvariant()] = @('analyst') }
foreach ($email in $ApproverEmails) { $RoleMap[$email.ToLowerInvariant()] = @('analyst', 'approver') }
$RoleMap[$AdminEmail.ToLowerInvariant()] = @('analyst', 'security_admin')
$RoleMapJson = ConvertTo-Json -InputObject $RoleMap -Compress -Depth 4
if ($AllowedDomain) {
    foreach ($email in $RoleMap.Keys) {
        if (-not $email.EndsWith("@$AllowedDomain")) {
            throw "$email is outside -AllowedDomain $AllowedDomain; the application would refuse it"
        }
    }
} elseif ($GrantDomainAccess -or $DefaultAnalyst) {
    throw '-GrantDomainAccess and -DefaultAnalyst require -AllowedDomain'
}

if (-not $SkipConsoleBuild) {
    $Npm = if ($OnWindows) { 'npm.cmd' } else { 'npm' }
    Push-Location (Join-Path $Root 'apps\dashboard')
    try {
        if (-not (Test-Path 'node_modules')) {
            & $Npm ci
            if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
        }
        & $Npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Console build failed' }
    } finally {
        Pop-Location
    }
}
if (-not (Test-Path (Join-Path $Root 'apps\dashboard\dist\index.html'))) {
    throw 'apps\dashboard\dist\index.html is missing: build the console before deploying'
}

Write-Step 'Enabling the required Google Cloud APIs'
Invoke-Gcloud @('services', 'enable', 'run.googleapis.com', 'cloudbuild.googleapis.com',
    'artifactregistry.googleapis.com', 'aiplatform.googleapis.com',
    'secretmanager.googleapis.com', 'iap.googleapis.com', "--project=$ProjectId", '--quiet')
if (-not (Test-Gcloud @('services', 'identity', 'create', '--service=iap.googleapis.com',
            "--project=$ProjectId"))) {
    Invoke-Gcloud @('beta', 'services', 'identity', 'create', '--service=iap.googleapis.com',
        "--project=$ProjectId")
}

Write-Step "Runtime service account $ServiceAccount (least privilege)"
if (-not (Test-Gcloud @('iam', 'service-accounts', 'describe', $ServiceAccount, "--project=$ProjectId"))) {
    Invoke-Gcloud @('iam', 'service-accounts', 'create', $ServiceAccountId,
        '--display-name=Hades Mirage Cloud Run runtime', "--project=$ProjectId")
}
Invoke-Gcloud @('projects', 'add-iam-policy-binding', $ProjectId,
    "--member=serviceAccount:$ServiceAccount", '--role=roles/aiplatform.user',
    '--condition=None', '--quiet')
try {
    # Documented role for source-deploy builds that run as the Compute Engine default account.
    Invoke-Gcloud @('projects', 'add-iam-policy-binding', $ProjectId,
        "--member=serviceAccount:$ProjectNumber-compute@developer.gserviceaccount.com",
        '--role=roles/run.builder', '--condition=None', '--quiet')
} catch {
    Write-Warning 'Could not grant roles/run.builder to the Compute default account; the build may need it.'
}

Write-Step 'Secret Manager (values are generated or read hidden, never displayed)'
$Secrets = New-Object System.Collections.Generic.List[string]
if (-not (Test-Gcloud @('secrets', 'versions', 'describe', 'latest', "--secret=$BackendSecretName",
            "--project=$ProjectId"))) {
    Add-SecretVersion $BackendSecretName (New-RandomSecret)
}
Grant-SecretAccess $BackendSecretName
$Secrets.Add("MIRAGE_BACKEND_SECRET=${BackendSecretName}:latest")
if ($WithTelegram) {
    $secure = Read-Host -AsSecureString 'Telegram bot token (input hidden)'
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    if ($token -notmatch '^[0-9]{3,20}:[A-Za-z0-9_-]{20,120}$') {
        throw 'That does not look like a Telegram bot token; nothing was stored'
    }
    Add-SecretVersion $TelegramTokenName $token
    $token = $null
    Grant-SecretAccess $TelegramTokenName
    $Secrets.Add("MIRAGE_TELEGRAM_BOT_TOKEN=${TelegramTokenName}:latest")
    if ($TelegramMode -eq 'webhook') {
        if (-not (Test-Gcloud @('secrets', 'versions', 'describe', 'latest',
                    "--secret=$TelegramWebhookName", "--project=$ProjectId"))) {
            Add-SecretVersion $TelegramWebhookName (New-RandomSecret)
        }
        Grant-SecretAccess $TelegramWebhookName
        $Secrets.Add("MIRAGE_TELEGRAM_WEBHOOK_SECRET=${TelegramWebhookName}:latest")
    }
}
$SecretSpec = $Secrets -join ','

$RunCommand = @('run')
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$deployHelp = (& gcloud run deploy --help 2>$null) | Out-String
$ErrorActionPreference = $previousPreference
if ($deployHelp -notmatch '--\[no-\]iap|--iap') {
    Write-Warning 'This gcloud release has no GA --iap flag for Cloud Run; using gcloud beta (or run: gcloud components update).'
    $RunCommand = @('beta', 'run')
}

$DeployArgs = $RunCommand + @('deploy', $ServiceName, '--source', '.', "--region=$Region",
    "--project=$ProjectId", "--service-account=$ServiceAccount", '--no-allow-unauthenticated',
    '--iap', '--max-instances=1', '--concurrency=40', '--cpu=1', '--memory=1Gi', '--timeout=60',
    "--env-vars-file=$EnvFile", "--set-secrets=$SecretSpec",
    '--labels=app=hades-mirage,profile=p2-cloud,data=synthetic', '--quiet')
if ($WithTelegram -and $TelegramMode -eq 'polling') {
    # Long polling needs CPU outside requests and one warm instance: this is a continuous cost.
    $DeployArgs += @('--no-cpu-throttling', '--min-instances=1')
} elseif ($KeepWarm) {
    $DeployArgs += @('--min-instances=1')
} else {
    $DeployArgs += @('--min-instances=0')
}

$Urls = @($DeterministicUrl)
Push-Location $Root
try {
    Write-Step "Cloud Build (buildpacks, remote) and Cloud Run deploy of $ServiceName - no Docker"
    Write-EnvFile $Urls
    Invoke-Gcloud $DeployArgs

    $Urls = Get-ServiceUrls
    if ($Urls.Count -gt 1) {
        Write-Step 'Allowing every service URL as host and browser origin'
        Write-EnvFile $Urls
        Invoke-Gcloud ($RunCommand + @('services', 'update', $ServiceName, "--region=$Region",
                "--project=$ProjectId", "--env-vars-file=$EnvFile", "--set-secrets=$SecretSpec",
                '--quiet'))
    }
} finally {
    Remove-Item -LiteralPath $EnvFile -Force -ErrorAction SilentlyContinue
    Pop-Location
}

Write-Step 'Letting IAP invoke the service and granting sign-in access'
Invoke-Gcloud @('run', 'services', 'add-iam-policy-binding', $ServiceName, "--region=$Region",
    "--project=$ProjectId",
    "--member=serviceAccount:service-$ProjectNumber@gcp-sa-iap.iam.gserviceaccount.com",
    '--role=roles/run.invoker', '--quiet')
$Members = New-Object System.Collections.Generic.List[string]
foreach ($email in $RoleMap.Keys) { $Members.Add("user:$email") }
if ($GrantDomainAccess) { $Members.Add("domain:$AllowedDomain") }
foreach ($member in $Members) {
    Invoke-Gcloud @('iap', 'web', 'add-iam-policy-binding', "--member=$member",
        '--role=roles/iap.httpsResourceAccessor', "--region=$Region", '--resource-type=cloud-run',
        "--service=$ServiceName", "--project=$ProjectId", '--quiet')
}

Write-Step 'Deployment commands finished - now verify in a browser (see README checklist)'
Write-Host "Console URL(s):     $($Urls -join ', ')"
Write-Host "IAP JWT audience:   $Audience"
Write-Host "Runtime identity:   $ServiceAccount (roles/aiplatform.user + per-secret accessor)"
Write-Host "Role map:           $RoleMapJson"
Write-Host "Gemini (Vertex AI): $GeminiModel in $GeminiLocation; egress approved: $([bool]$ApproveModelEgress)"
Write-Host 'State:              synthetic SQLite in /tmp; lost on restart; single instance.'
Write-Host "IAP check:          gcloud run services describe $ServiceName --region=$Region --project=$ProjectId  (expect: Iap Enabled: true)"
Write-Host "Logs:               gcloud run services logs read $ServiceName --region=$Region --project=$ProjectId --limit=50"
Write-Host 'Rollback/deletion:  deploy/gcp/README.md'
if ($WithTelegram -and $TelegramMode -eq 'webhook') {
    Write-Warning ('IAP protects every path of this service, so Telegram cannot deliver webhooks to it. ' +
        'Use -TelegramMode polling, or give the webhook path a separate non-IAP ingress first ' +
        '(see deploy/gcp/README.md). setWebhook was NOT called.')
}
