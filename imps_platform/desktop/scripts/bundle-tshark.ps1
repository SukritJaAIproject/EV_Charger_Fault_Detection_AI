[CmdletBinding()]
param(
    [string]$SourceDirectory = "C:\Program Files\Wireshark",
    [string]$DestinationDirectory = "",
    [string]$GoldenPcap = "G:\pcap_downloads\001_7Eleven_Banklangmueang\connector1\ethlog12.pcap",
    [string]$VCRuntimeDirectory = "",
    [switch]$SkipSmokeTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-NormalizedDirectoryPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    return [System.IO.Path]::GetFullPath($Path).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
}

function Remove-ExactTemporaryDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedParent
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $normalizedPath = Get-NormalizedDirectoryPath -Path $Path
    $normalizedParent = Get-NormalizedDirectoryPath -Path $ExpectedParent
    $actualParent = Get-NormalizedDirectoryPath -Path ([System.IO.Directory]::GetParent($normalizedPath).FullName)

    if ($actualParent -ine $normalizedParent) {
        throw "Refusing to remove unexpected directory: $normalizedPath"
    }

    Remove-Item -LiteralPath $normalizedPath -Recurse -Force
}

function Invoke-TShark {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $output = @(& $Executable @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $details = ($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
        throw "TShark failed with exit code $exitCode.$([Environment]::NewLine)$details"
    }

    return $output | ForEach-Object { $_.ToString() }
}

function Find-VCRuntimeDirectory {
    param([string]$ConfiguredDirectory)

    $requiredNames = @(
        "concrt140.dll",
        "msvcp140.dll",
        "msvcp140_1.dll",
        "msvcp140_2.dll",
        "msvcp140_atomic_wait.dll",
        "msvcp140_codecvt_ids.dll",
        "vccorlib140.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll"
    )
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($ConfiguredDirectory)) {
        $candidates += Get-NormalizedDirectoryPath -Path $ConfiguredDirectory
    }
    if (-not [string]::IsNullOrWhiteSpace($env:VCToolsRedistDir)) {
        $candidates += Get-NormalizedDirectoryPath -Path (
            Join-Path $env:VCToolsRedistDir "x64\Microsoft.VC142.CRT"
        )
        $candidates += Get-NormalizedDirectoryPath -Path (
            Join-Path $env:VCToolsRedistDir "x64\Microsoft.VC143.CRT"
        )
    }
    foreach ($visualStudioRoot in @(
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio",
        "$env:ProgramFiles\Microsoft Visual Studio"
    )) {
        if (-not [string]::IsNullOrWhiteSpace($visualStudioRoot) -and
            (Test-Path -LiteralPath $visualStudioRoot -PathType Container)) {
            $candidates += @(
                Get-ChildItem -LiteralPath $visualStudioRoot -Recurse -Directory `
                    -Filter "Microsoft.VC*.CRT" -ErrorAction SilentlyContinue |
                    Where-Object {
                        $_.FullName -match '[\\/]x64[\\/]Microsoft\.VC' -and
                        $_.FullName -notmatch '[\\/]onecore[\\/]'
                    } |
                    ForEach-Object { $_.FullName }
            )
        }
    }

    $validCandidates = foreach ($candidate in @($candidates | Select-Object -Unique)) {
        if ([string]::IsNullOrWhiteSpace($candidate) -or
            -not (Test-Path -LiteralPath $candidate -PathType Container)) {
            continue
        }
        $missing = @($requiredNames | Where-Object {
            -not (Test-Path -LiteralPath (Join-Path $candidate $_) -PathType Leaf)
        })
        if ($missing.Count -eq 0) {
            $versionText = (Get-Item -LiteralPath (Join-Path $candidate "vcruntime140.dll")).VersionInfo.FileVersion
            $versionMatch = [Regex]::Match($versionText, '\d+\.\d+\.\d+\.\d+')
            if ($versionMatch.Success) {
                [pscustomobject]@{
                    Directory = Get-NormalizedDirectoryPath -Path $candidate
                    Version = [Version]$versionMatch.Value
                }
            }
        }
    }
    $selected = @($validCandidates | Sort-Object Version -Descending | Select-Object -First 1)
    if ($selected.Count -ne 1) {
        throw "A redistributable x64 Microsoft Visual C++ CRT folder was not found. Install Visual Studio Build Tools or pass -VCRuntimeDirectory."
    }
    return [pscustomobject]@{
        Directory = $selected[0].Directory
        Version = $selected[0].Version.ToString()
        Files = $requiredNames
    }
}

$scriptDirectory = Get-NormalizedDirectoryPath -Path $PSScriptRoot
$repositoryRoot = Get-NormalizedDirectoryPath -Path (Join-Path $scriptDirectory "..\..")
$runtimeRoot = Get-NormalizedDirectoryPath -Path (Join-Path $repositoryRoot ".desktop-build\runtime")

if ([string]::IsNullOrWhiteSpace($DestinationDirectory)) {
    $DestinationDirectory = Join-Path $runtimeRoot "wireshark"
}

$source = Get-NormalizedDirectoryPath -Path $SourceDirectory
$vcRuntime = Find-VCRuntimeDirectory -ConfiguredDirectory $VCRuntimeDirectory
$destination = Get-NormalizedDirectoryPath -Path $DestinationDirectory
$allowedDestination = Get-NormalizedDirectoryPath -Path (Join-Path $runtimeRoot "wireshark")

# This helper replaces a directory recursively. Keep that operation pinned to the
# repository's disposable desktop build output, even when a caller supplies a path.
if ($destination -ine $allowedDestination) {
    throw "Destination must be exactly '$allowedDestination'. Received '$destination'."
}

if (-not (Test-Path -LiteralPath $source -PathType Container)) {
    throw "Wireshark installation was not found: $source"
}

$requiredRelativeFiles = @(
    "tshark.exe",
    "libwireshark.dll",
    "libwiretap.dll",
    "libwsutil.dll",
    "lua54.dll",
    "COPYING.txt",
    "README.txt",
    "dsV2Gshark_LICENSE.txt",
    "dsV2Gshark_OSSAcknowledgements.txt",
    "dsV2Gshark_README.txt",
    "v2gLib_52.dll",
    "v2gLib_54.dll",
    "plugins\v2gcommon.lua",
    "plugins\v2ghpscs.lua",
    "plugins\v2gmsg.lua",
    "plugins\v2gsdp.lua",
    "plugins\v2gtlssecret.lua",
    "plugins\v2gtp.lua"
)

# Installer leftovers that serve no purpose inside a portable runtime and would
# only offer to remove the build machine's own Wireshark installation.
# unins000.exe is the unsigned Inno Setup uninstaller of the dsV2Gshark plugin
# (unins000.dat is its uninstall log); uninstall-wireshark.exe is Wireshark's
# NSIS uninstaller. The plugin's uninstaller is the only executable in the
# installed tree without an Authenticode signature.
$excludedFileNames = @(
    "unins000.exe",
    "unins000.dat",
    "uninstall-wireshark.exe"
)

$missingFiles = @(
    $requiredRelativeFiles | Where-Object {
        -not (Test-Path -LiteralPath (Join-Path $source $_) -PathType Leaf)
    }
)
if ($missingFiles.Count -gt 0) {
    throw "Wireshark/dsV2Gshark installation is incomplete. Missing: $($missingFiles -join ', ')"
}

if (-not $SkipSmokeTest -and -not (Test-Path -LiteralPath $GoldenPcap -PathType Leaf)) {
    throw "Golden PCAP was not found: $GoldenPcap"
}

New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
$stagingName = ".wireshark-staging-$([Guid]::NewGuid().ToString('N'))"
$staging = Join-Path $runtimeRoot $stagingName
$smokeProfile = Join-Path ([System.IO.Path]::GetTempPath()) "imps-tshark-smoke-$([Guid]::NewGuid().ToString('N'))"

$previousAppData = $env:APPDATA
$previousConfigDirectory = $env:WIRESHARK_CONFIG_DIR
$stagingPromoted = $false

try {
    New-Item -ItemType Directory -Path $staging -Force | Out-Null

    # Copy the complete installed tree. TShark loads protocol data, Lua, native
    # dissectors, and DLLs relative to this tree; retaining all of it is more
    # reliable than maintaining a fragile hand-written DLL allow-list. The only
    # exception is the upstream uninstallers, excluded by file name with /XF.
    $robocopyArguments = @(
        $source, $staging,
        "/E", "/COPY:DAT", "/DCOPY:DAT", "/R:2", "/W:1", "/XJ",
        "/NFL", "/NDL", "/NJH", "/NJS", "/NP",
        "/XF"
    ) + $excludedFileNames
    & robocopy.exe @robocopyArguments | Out-Null
    $robocopyExitCode = $LASTEXITCODE
    if ($robocopyExitCode -gt 7) {
        throw "Robocopy failed with exit code $robocopyExitCode."
    }

    $leakedFiles = @(
        Get-ChildItem -LiteralPath $staging -Recurse -File |
            Where-Object { $excludedFileNames -contains $_.Name } |
            ForEach-Object { $_.FullName.Substring($staging.Length + 1) }
    )
    if ($leakedFiles.Count -gt 0) {
        throw "Bundled runtime still contains excluded installer files: $($leakedFiles -join ', ')"
    }

    # App-local deployment avoids a second UAC prompt and lets TShark run on a
    # clean Windows machine without a preinstalled VC++ Redistributable.
    foreach ($runtimeName in $vcRuntime.Files) {
        $runtimeSource = Join-Path $vcRuntime.Directory $runtimeName
        $signature = Get-AuthenticodeSignature -LiteralPath $runtimeSource
        if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid -or
            $null -eq $signature.SignerCertificate -or
            $signature.SignerCertificate.Subject -notmatch "Microsoft Corporation") {
            throw "VC++ runtime file is not validly signed by Microsoft: $runtimeSource"
        }
        Copy-Item -LiteralPath $runtimeSource -Destination (Join-Path $staging $runtimeName) -Force
    }

    $projectNotice = Join-Path $repositoryRoot "desktop\licenses\THIRD_PARTY_NOTICES.md"
    if (-not (Test-Path -LiteralPath $projectNotice -PathType Leaf)) {
        throw "Project third-party notice is missing: $projectNotice"
    }
    Copy-Item -LiteralPath $projectNotice -Destination (Join-Path $staging "iMPS-THIRD-PARTY-NOTICES.md") -Force

    foreach ($relativePath in $requiredRelativeFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $staging $relativePath) -PathType Leaf)) {
            throw "Bundled runtime is missing required file: $relativePath"
        }
    }

    $stagedTShark = Join-Path $staging "tshark.exe"
    $versionOutput = Invoke-TShark -Executable $stagedTShark -Arguments @("--version")
    $versionLine = @($versionOutput | Where-Object { $_ -match '^TShark \(Wireshark\)' } | Select-Object -First 1)
    if ($versionLine.Count -ne 1 -or $versionLine[0] -notmatch '(?<version>\d+\.\d+\.\d+)') {
        throw "Unable to identify the bundled TShark version."
    }
    $wiresharkVersion = $Matches.version
    $versionText = $versionOutput -join "`n"
    if ($versionText -notmatch 'Compiled \(64-bit\)' -or $versionText -notmatch 'with Lua') {
        throw "Bundled TShark is not a 64-bit build with Lua support."
    }

    $pluginVersion = "not-tested"
    $decodedMessages = @()
    if (-not $SkipSmokeTest) {
        New-Item -ItemType Directory -Path $smokeProfile -Force | Out-Null

        # Isolate the check from the developer's personal Wireshark plugins.
        # Successful decoding therefore proves that the copied global plugin is
        # self-contained inside the portable runtime.
        $env:APPDATA = $smokeProfile
        $env:WIRESHARK_CONFIG_DIR = $smokeProfile

        $pluginOutput = Invoke-TShark -Executable $stagedTShark -Arguments @("-G", "plugins")
        $requiredLuaPlugins = @(
            "v2gcommon.lua",
            "v2ghpscs.lua",
            "v2gmsg.lua",
            "v2gsdp.lua",
            "v2gtlssecret.lua",
            "v2gtp.lua"
        )
        foreach ($pluginName in $requiredLuaPlugins) {
            if (-not ($pluginOutput | Where-Object { $_ -match "^$([Regex]::Escape($pluginName))\s" })) {
                throw "Bundled TShark did not load required Lua plugin: $pluginName"
            }
        }

        $v2gMessagePlugin = @(
            $pluginOutput | Where-Object { $_ -match '^v2gmsg\.lua\s+(?<version>\S+)\s+lua script\s+' }
        )
        if ($v2gMessagePlugin.Count -ne 1) {
            throw "Expected exactly one isolated v2gmsg.lua plugin, found $($v2gMessagePlugin.Count)."
        }
        [void]($v2gMessagePlugin[0] -match '^v2gmsg\.lua\s+(?<version>\S+)\s+lua script\s+')
        $pluginVersion = $Matches.version

        $decodeOutput = Invoke-TShark -Executable $stagedTShark -Arguments @(
            "-r", (Get-NormalizedDirectoryPath -Path $GoldenPcap),
            "-T", "fields",
            "-e", "v2gmsg.msgname"
        )
        $decodedMessages = @(
            $decodeOutput |
                ForEach-Object { $_.Trim() } |
                Where-Object { $_.Length -gt 0 }
        )
        if ($decodedMessages.Count -eq 0) {
            throw "Bundled dsV2Gshark produced no v2gmsg.msgname values for the golden PCAP."
        }
        if ($decodedMessages -notcontains "supportedAppProtocolReq" -or
            $decodedMessages -notcontains "SessionSetupReq") {
            throw "Golden PCAP decode did not contain the expected V2G handshake messages."
        }
    }

    $payloadFiles = @(Get-ChildItem -LiteralPath $staging -Recurse -File)
    $payloadBytes = [Int64](($payloadFiles | Measure-Object -Property Length -Sum).Sum)
    $manifest = [ordered]@{
        schemaVersion = 1
        createdAt = [DateTime]::UtcNow.ToString("o")
        sourceDirectory = $source
        wiresharkVersion = $wiresharkVersion
        architecture = "x64"
        luaEnabled = $true
        appLocalVCRuntime = [ordered]@{
            version = $vcRuntime.Version
            sourceDirectory = $vcRuntime.Directory
            files = @($vcRuntime.Files)
        }
        dsV2GsharkVersion = $pluginVersion
        smokeTest = [ordered]@{
            skipped = [bool]$SkipSmokeTest
            goldenPcap = if ($SkipSmokeTest) { $null } else { [System.IO.Path]::GetFileName($GoldenPcap) }
            field = "v2gmsg.msgname"
            decodedMessageCount = $decodedMessages.Count
            sample = @($decodedMessages | Select-Object -First 12)
        }
        payloadFileCount = $payloadFiles.Count
        payloadBytesBeforeManifest = $payloadBytes
        excludedInstallerFiles = @($excludedFileNames)
        licenses = @(
            "COPYING.txt",
            "README.txt",
            "dsV2Gshark_LICENSE.txt",
            "dsV2Gshark_OSSAcknowledgements.txt",
            "dsV2Gshark_README.txt",
            "iMPS-THIRD-PARTY-NOTICES.md"
        )
    }
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $staging "imps-tshark-bundle.json") -Encoding UTF8

    if (Test-Path -LiteralPath $destination) {
        Remove-ExactTemporaryDirectory -Path $destination -ExpectedParent $runtimeRoot
    }
    Move-Item -LiteralPath $staging -Destination $destination
    $stagingPromoted = $true

    $finalFiles = @(Get-ChildItem -LiteralPath $destination -Recurse -File)
    $finalBytes = [Int64](($finalFiles | Measure-Object -Property Length -Sum).Sum)

    [pscustomobject]@{
        Destination = $destination
        WiresharkVersion = $wiresharkVersion
        DsV2GsharkVersion = $pluginVersion
        VCRuntimeVersion = $vcRuntime.Version
        FileCount = $finalFiles.Count
        SizeBytes = $finalBytes
        SizeMiB = [Math]::Round($finalBytes / 1MB, 2)
        SmokeTest = if ($SkipSmokeTest) { "SKIPPED" } else { "PASS" }
        DecodedMessages = $decodedMessages.Count
    } | Format-List
}
finally {
    if ($null -eq $previousAppData) {
        Remove-Item Env:APPDATA -ErrorAction SilentlyContinue
    }
    else {
        $env:APPDATA = $previousAppData
    }

    if ($null -eq $previousConfigDirectory) {
        Remove-Item Env:WIRESHARK_CONFIG_DIR -ErrorAction SilentlyContinue
    }
    else {
        $env:WIRESHARK_CONFIG_DIR = $previousConfigDirectory
    }

    if (Test-Path -LiteralPath $smokeProfile) {
        $tempParent = Get-NormalizedDirectoryPath -Path ([System.IO.Path]::GetTempPath())
        Remove-ExactTemporaryDirectory -Path $smokeProfile -ExpectedParent $tempParent
    }

    if (-not $stagingPromoted -and (Test-Path -LiteralPath $staging)) {
        Remove-ExactTemporaryDirectory -Path $staging -ExpectedParent $runtimeRoot
    }
}
