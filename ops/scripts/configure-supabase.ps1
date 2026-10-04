[CmdletBinding()]
param(
    [string]$ProjectRef = "xyzjnlkufyzzgcnkcjsh",
    [string]$PoolerHost = "aws-0-ap-northeast-1.pooler.supabase.com"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$templatePath = Join-Path $projectRoot "ops\.env.example"
$environmentPath = Join-Path $projectRoot "ops\.env"

if (-not (Test-Path -LiteralPath $environmentPath)) {
    Copy-Item -LiteralPath $templatePath -Destination $environmentPath
}

$securePassword = Read-Host "Supabase database password" -AsSecureString
$passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    $encodedPassword = [Uri]::EscapeDataString($plainPassword)
    $databaseUrl = "postgresql://postgres.$ProjectRef`:$encodedPassword@$PoolerHost`:5432/postgres?sslmode=require"

    $lines = [Collections.Generic.List[string]](Get-Content -LiteralPath $environmentPath)
    $existingIndex = -1
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match '^CLINICAL_DATABASE_URL=') {
            $existingIndex = $index
            break
        }
    }
    if ($existingIndex -ge 0) {
        $lines[$existingIndex] = "CLINICAL_DATABASE_URL=$databaseUrl"
    } else {
        $lines.Insert(0, "CLINICAL_DATABASE_URL=$databaseUrl")
    }
    Set-Content -LiteralPath $environmentPath -Value $lines -Encoding utf8
    Write-Host "Saved the Supabase connection in ignored file ops/.env. The password was not printed."
} finally {
    if ($passwordPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
    $plainPassword = $null
    $encodedPassword = $null
    $databaseUrl = $null
    $securePassword = $null
}
