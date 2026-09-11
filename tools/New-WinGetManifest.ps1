param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string] $Version,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9A-Fa-f]{64}$')]
    [string] $InstallerSha256,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^https://')]
    [string] $InstallerUrl,

    [Parameter(Mandatory = $true)]
    [string] $OutputDirectory
)

$ErrorActionPreference = 'Stop'
$packageIdentifier = 'PiSaucer.Toolbox'
$schemaVersion = '1.10.0'

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

@"
# yaml-language-server: `$schema=https://aka.ms/winget-manifest.version.$schemaVersion.schema.json
PackageIdentifier: $packageIdentifier
PackageVersion: $Version
DefaultLocale: en-US
ManifestType: version
ManifestVersion: $schemaVersion
"@ | Set-Content -Encoding utf8 "$OutputDirectory\$packageIdentifier.yaml"

@"
# yaml-language-server: `$schema=https://aka.ms/winget-manifest.installer.$schemaVersion.schema.json
PackageIdentifier: $packageIdentifier
PackageVersion: $Version
InstallerType: portable
Commands:
  - toolbox
Installers:
  - Architecture: x64
    InstallerUrl: $InstallerUrl
    InstallerSha256: $($InstallerSha256.ToUpperInvariant())
    Commands:
      - toolbox
ManifestType: installer
ManifestVersion: $schemaVersion
"@ | Set-Content -Encoding utf8 "$OutputDirectory\$packageIdentifier.installer.yaml"

@"
# yaml-language-server: `$schema=https://aka.ms/winget-manifest.defaultLocale.$schemaVersion.schema.json
PackageIdentifier: $packageIdentifier
PackageVersion: $Version
PackageLocale: en-US
Publisher: PiSaucer
PublisherUrl: https://github.com/PiSaucer
PublisherSupportUrl: https://github.com/PiSaucer/toolbox/issues
PackageName: Toolbox
PackageUrl: https://github.com/PiSaucer/toolbox
License: MIT
LicenseUrl: https://github.com/PiSaucer/toolbox/blob/v$Version/LICENSE
ShortDescription: Browse, download, verify, and run utility scripts.
Moniker: toolbox
Tags:
  - cli
  - scripts
  - utilities
ReleaseNotesUrl: https://github.com/PiSaucer/toolbox/releases/tag/v$Version
ManifestType: defaultLocale
ManifestVersion: $schemaVersion
"@ | Set-Content -Encoding utf8 "$OutputDirectory\$packageIdentifier.locale.en-US.yaml"
