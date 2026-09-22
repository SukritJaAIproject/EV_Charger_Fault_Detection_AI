# Report the Authenticode state of every PE file in a release output directory,
# including the executables inside the unpacked app that the installer carries.
# Files we build must carry the internal certificate; the bundled Wireshark
# executables must never carry it (a signed full build excludes them through
# win.signExts) and, where the vendor signed them, that signature must still
# verify. Exit code 1 on any problem.
param(
    [Parameter(Mandatory = $true)][string]$ReleaseDir,
    [string]$Unpacked = "",
    [string]$ProductName = "iMPS Fault Detection",
    [string]$Thumbprint = "74C4795C67E81EFCCFFAAB2B946661F1003C7A3E",
    [string]$ThirdPartySubject = "Wireshark Foundation"
)
$bad = 0
# a full build leaves win-unpacked inside the release directory; it is checked
# through -Unpacked, not as release output
$ours = @(Get-ChildItem $ReleaseDir -File -Include *.exe -Recurse | Where-Object { $_.FullName -notlike '*\win-unpacked\*' })
$theirs = @()
if ($Unpacked) {
    $ours += Get-Item (Join-Path $Unpacked "$ProductName.exe")
    $ours += Get-Item (Join-Path $Unpacked 'resources\elevate.exe')
    $ours += Get-Item (Join-Path $Unpacked 'resources\runtime\imps-fault-runtime.exe')
    $theirs = @(Get-ChildItem (Join-Path $Unpacked 'resources\runtime\wireshark') -File -Filter *.exe -Recurse -ErrorAction SilentlyContinue)
}
foreach ($t in $ours) {
    $s = Get-AuthenticodeSignature $t.FullName
    $thumb = $s.SignerCertificate.Thumbprint
    $ts = if ($s.TimeStamperCertificate) { 'timestamped' } else { 'NO TIMESTAMP' }
    # UnknownError is what a self-signed chain reports on a machine that has not
    # trusted the root yet; the signature itself is intact. Valid means trusted.
    $ok = ($thumb -eq $Thumbprint) -and ($s.Status -in 'Valid', 'UnknownError')
    if (-not $ok) { $bad++ }
    "{0,-6} {1,-13} {2,-13} {3}" -f $(if ($ok) { 'OK' } else { 'FAIL' }), $s.Status, $ts, $t.FullName
}
foreach ($t in $theirs) {
    $s = Get-AuthenticodeSignature $t.FullName
    $thumb = $s.SignerCertificate.Thumbprint
    $subject = if ($s.SignerCertificate) { $s.SignerCertificate.Subject } else { '(unsigned as shipped by the vendor)' }
    if ($thumb -eq $Thumbprint) { $ok = $false }                       # re-signed with our certificate: wrong
    elseif ($s.Status -eq 'NotSigned') { $ok = $true }                 # the vendor never signed this file
    else { $ok = ($s.Status -eq 'Valid') -and ($subject -like "*$ThirdPartySubject*") }
    if (-not $ok) { $bad++ }
    "{0,-6} {1,-13} {2,-13} {3}  signer: {4}" -f $(if ($ok) { 'OK' } else { 'FAIL' }), $s.Status, 'third-party', $t.FullName, $subject
}
"`n$($ours.Count) own + $($theirs.Count) third-party files checked, $bad problem(s)"
exit $(if ($bad) { 1 } else { 0 })
