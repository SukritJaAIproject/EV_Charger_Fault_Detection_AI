# Code signing (internal certificate)

The installers and every executable we build (`iMPS Fault Detection.exe`, the
NSIS installers and uninstaller, `elevate.exe`, the Python sidecar
`imps-fault-runtime.exe`) are signed with a **self-signed** certificate:

| | |
|---|---|
| Subject | `CN=iMPS Fault Detection (EGAT internal, self-signed), O=EGAT iMPS Project, C=TH` |
| Thumbprint (SHA-1) | `74C4795C67E81EFCCFFAAB2B946661F1003C7A3E` |
| Key | RSA 3072, SHA-256 signatures, RFC 3161 timestamp from DigiCert |
| Valid | 2026-09-22 → 2031-09-22 |
| Public certificate | `iMPS-Fault-Detection-internal-codesign.cer` (this folder, also attached to each release) |

The private key never leaves the build machine's Windows certificate store.
Wireshark's own binaries inside the package keep their Wireshark Foundation
signature.

## What this does and does not do

- On a machine that **trusts the certificate**, `Get-AuthenticodeSignature`
  reports `Valid`, the installer's publisher shows as the subject above, and
  application-control policies (AppLocker / WDAC) can allow-list the publisher.
- On any other machine the signature is intact but the chain ends in an
  untrusted root, so **Windows SmartScreen still warns** ("Unknown publisher").
  Removing that warning for the public requires a certificate from a CA that
  Windows trusts (Azure Trusted Signing, DigiCert, Sectigo, …) plus reputation;
  this internal certificate is not a substitute for that.

## Trusting the certificate on EGAT machines

One machine, current user (no admin needed):

```powershell
certutil -user -addstore -f Root .\iMPS-Fault-Detection-internal-codesign.cer
certutil -user -addstore -f TrustedPublisher .\iMPS-Fault-Detection-internal-codesign.cer
```

All users on a machine (administrator prompt):

```powershell
certutil -addstore -f Root .\iMPS-Fault-Detection-internal-codesign.cer
certutil -addstore -f TrustedPublisher .\iMPS-Fault-Detection-internal-codesign.cer
```

Fleet-wide: import the `.cer` into a Group Policy object under
*Computer Configuration → Windows Settings → Security Settings → Public Key
Policies → Trusted Root Certification Authorities* and *Trusted Publishers*.

Verify on a trusting machine:

```powershell
Get-AuthenticodeSignature '.\iMPS-Fault-Detection-Offline-Setup-1.2.0.exe' | Format-List Status, SignerCertificate, TimeStamperCertificate
```

`Status` must read `Valid` and the thumbprint must match the table above; if it
reads `UnknownError` the certificate has not been trusted on that machine yet.

## Building signed installers

Signing is opt-in so that builds without the certificate still work:

```powershell
$env:IMPS_SIGN_CERT_SHA1 = '74C4795C67E81EFCCFFAAB2B946661F1003C7A3E'   # thumbprint in Cert:\CurrentUser\My
$env:IMPS_ONLINE_PACKAGE_URL = 'https://github.com/SukritJaAIproject/EV_Charger_Fault_Detection_AI/releases/download/<tag>/<payload>.nsis.7z'
npm run desktop:build
```

`desktop/electron-builder.installers.cjs` then passes `signtoolOptions` to
electron-builder. In a full build it signs the app executable, the extra
resources it copies (`resources\elevate.exe`, the Python sidecar
`resources\runtime\imps-fault-runtime.exe`), the uninstaller and both
installers. The bundled Wireshark executables are excluded: the config lists
every `.exe` in the runtime's `wireshark` directory as a `!name` entry in
`win.signExts`, so they keep their Wireshark Foundation signature instead of
being re-signed with ours.

When packaging from an already unpacked directory (`--prepackaged`),
electron-builder only signs the installers and the uninstaller; sign the app
executable, `elevate.exe` and the sidecar in that directory first:

```powershell
$st = "${env:ProgramFiles(x86)}\Windows Kits\10\bin\10.0.19041.0\x64\signtool.exe"
& $st sign /sha1 74C4795C67E81EFCCFFAAB2B946661F1003C7A3E /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
    '.\dist-desktop\release\win-unpacked\iMPS Fault Detection.exe' `
    '.\dist-desktop\release\win-unpacked\resources\runtime\imps-fault-runtime.exe' `
    '.\dist-desktop\release\win-unpacked\resources\elevate.exe'
```

Check a finished build with `Verify-Signatures.ps1` (this folder): every file
we build must carry the thumbprint above and every Wireshark executable must
still verify as Wireshark Foundation's. Pass `-ProductName` for an edition
built under another name (see *Editions* in `desktop/README.md`):

```powershell
.\Verify-Signatures.ps1 -ReleaseDir .\dist-desktop\release -Unpacked .\dist-desktop\release\win-unpacked
.\Verify-Signatures.ps1 -ReleaseDir .\dist-desktop\release-snapshot -Unpacked .\dist-desktop\release-snapshot\win-unpacked `
    -ProductName 'iMPS Fault Detection Snapshot 2026-09-12'
```

`Test-Coexistence.ps1` installs the current line and the snapshot edition side
by side into a sandbox, checks that Windows sees two applications (two
uninstall entries, two `%APPDATA%` folders, both running at once) and removes
them again.

To renew or replace the certificate, create a new one and update the
thumbprint here and in the release notes:

```powershell
New-SelfSignedCertificate -Type CodeSigningCert -Subject 'CN=iMPS Fault Detection (EGAT internal, self-signed), O=EGAT iMPS Project, C=TH' `
  -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 -KeyExportPolicy Exportable `
  -CertStoreLocation Cert:\CurrentUser\My -NotAfter (Get-Date).AddYears(5)
```
