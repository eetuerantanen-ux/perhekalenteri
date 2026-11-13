<#
.SYNOPSIS
    Stores the Vesiportaali local-account credentials in the Raspberry Pi's
    secrets.env without putting the password on a command line, in shell
    history, in this repository, or in chat.

.DESCRIPTION
    The portal only exposes consumption data behind an ASP.NET Identity
    session. fetch-water.py logs in with the local account (email + password)
    that you create under My Account; this script delivers that password to
    /home/pi/perhekalenteri/secrets.env as VESI_EMAIL / VESI_PASSWORD /
    VESI_PROVIDER, mode 600.

    The password is read with Read-Host -AsSecureString, embedded in a
    base64 payload and piped to `python3 -` over SSH on stdin. It never
    appears in an argv, a file on this machine, or the console.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\tools\provision-vesi.ps1

.NOTES
    Requires key-based SSH access to the Pi (already configured for this
    workstation).
#>

[CmdletBinding()]
param(
    [string]$PiHost = "pi@192.168.1.243",
    [string]$Email,
    [string]$Provider = "vesiportaali.kouvolanvesi.fi",
    [string]$SecretsPath = "/home/pi/perhekalenteri/secrets.env"
)

$ErrorActionPreference = "Stop"

if (-not $Email) { $Email = Read-Host "Vesiportaali email" }
if (-not $Email) { throw "Email is required." }

$secure = Read-Host "Vesiportaali password" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
if (-not $plain) { throw "Password is required." }
if ($plain -match "[\r\n]" -or $plain -ne $plain.Trim()) {
    throw "Password must not contain line breaks or leading/trailing spaces (secrets.env is line based and trims values)."
}

$payload = @{
    email    = $Email
    password = $plain
    provider = $Provider
    secrets  = $SecretsPath
    backup   = "/home/pi/secrets.env.bak"
} | ConvertTo-Json -Compress
$plain = $null

$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($payload))

$remote = @"
import base64, json, os, shutil, stat

data = json.loads(base64.b64decode("$b64").decode("utf-8"))
path = data["secrets"]
updates = {
    "VESI_EMAIL": data["email"],
    "VESI_PASSWORD": data["password"],
    "VESI_PROVIDER": data["provider"],
}

if os.path.exists(path):
    shutil.copyfile(path, data["backup"])
    os.chmod(data["backup"], 0o600)

lines = []
if os.path.exists(path):
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()

seen = set()
out = []
for line in lines:
    key = line.split("=", 1)[0].strip()
    if key in updates:
        out.append(key + "=" + updates[key])
        seen.add(key)
    else:
        out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(key + "=" + value)

tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as handle:
    handle.write("\n".join(out).rstrip("\n") + "\n")
os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
os.replace(tmp, path)
print("OK: updated", ", ".join(sorted(updates)), "in", path)
"@

# Normalise line endings: PowerShell here-strings may carry CRLF and the
# remote interpreter should see plain LF.
$remote = $remote -replace "`r`n", "`n"

$remote | & ssh -o BatchMode=yes -o UpdateHostKeys=no $PiHost "python3 -"
if ($LASTEXITCODE -ne 0) { throw "Provisioning over SSH failed (exit $LASTEXITCODE)." }

Write-Host ""
Write-Host "Stored on the Pi. Nothing was written to disk on this machine."
Write-Host "Next: run on the Pi  ->  python3 /home/pi/perhekalenteri/fetch-water.py --login-test"
