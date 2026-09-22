# Report the Authenticode state of every PE file in a release output directory,
# including the executables inside the unpacked app that the installer carries.
# Exit code 1 if any file we are responsible for is unsigned or signed by a
# different certificate.
param(
    [Parameter(Mandatory = $true)][string]$ReleaseDir,
    [string]$Unpacked = "",
    [string]$Thumbprint = "74C4795C67E81EFCCFFAAB2B946661F1003C7A3E"
)
$bad = 0
$targets = @(Get-ChildItem $ReleaseDir -File -Include *.exe -Recurse)
if ($Unpacked) {
    $targets += Get-Item (Join-Path $Unpacked 'iMPS Fault Detection.exe')
    $targets += Get-Item (Join-Path $Unpacked 'resources\elevate.exe')
    $targets += Get-Item (Join-Path $Unpacked 'resources\runtime\imps-fault-runtime.exe')
}
foreach ($t in $targets) {
    $s = Get-AuthenticodeSignature $t.FullName
    $thumb = $s.SignerCertificate.Thumbprint
    $ts = if ($s.TimeStamperCertificate) { 'timestamped' } else { 'NO TIMESTAMP' }
    # UnknownError is what a self-signed chain reports on a machine that has not
    # trusted the root yet; the signature itself is intact. Valid means trusted.
    $ok = ($thumb -eq $Thumbprint) -and ($s.Status -in 'Valid', 'UnknownError')
    if (-not $ok) { $bad++ }
    "{0,-6} {1,-13} {2,-13} {3}" -f $(if ($ok) { 'OK' } else { 'FAIL' }), $s.Status, $ts, $t.FullName
}
"`n$($targets.Count) files checked, $bad problem(s)"
exit $(if ($bad) { 1 } else { 0 })
