# Portable TShark third-party notices

The full iMPS Fault Detection desktop package may redistribute an unmodified,
64-bit Wireshark/TShark runtime together with the dSPACE dsV2Gshark dissector.
Those components are separate works and are not licensed under the iMPS
application's license.

## Wireshark and TShark

Wireshark/TShark is copyright its authors and is distributed under the GNU
General Public License, version 2 or (at your option) any later version. The
portable runtime must retain Wireshark's `COPYING.txt`, `README.txt`, and the
license/notices shipped with its libraries and plugins.

Project and source-code information: <https://www.wireshark.org/>

Anyone distributing the installer is responsible for satisfying the GPL's
corresponding-source requirements for the exact Wireshark binaries shipped in
that installer. Keeping this notice and `COPYING.txt` is necessary but does not
replace that obligation.

## dSPACE dsV2Gshark

dsV2Gshark is copyright dSPACE GmbH. The project states that it is licensed
under the MIT License, while files using the Wireshark API are licensed under
GPL-2.0; bundled third-party libraries have their own terms. The portable
runtime must retain all of the following upstream files verbatim:

- `dsV2Gshark_LICENSE.txt`
- `dsV2Gshark_OSSAcknowledgements.txt`
- `dsV2Gshark_README.txt`

Project and source-code information:
<https://github.com/dspace-group/dsV2Gshark>

`desktop/scripts/bundle-tshark.ps1` validates these notices before building and
copies the installed upstream files into the portable runtime. Do not remove
them from the installer.

## Microsoft Visual C++ Runtime

The portable TShark directory contains x64 Microsoft Visual C++ Runtime DLLs
copied from the `VC\Redist` directory of a licensed Visual Studio Build Tools
installation. They remain copyright Microsoft Corporation and are included as
application-local redistributable code so the desktop app does not require a
separate administrator-level prerequisite install.

Deployment information:
<https://learn.microsoft.com/en-us/cpp/windows/choosing-a-deployment-method>
