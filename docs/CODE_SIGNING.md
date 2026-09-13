# Code signing and SmartScreen

**Current decision: releases are unsigned.** This page keeps the options for
later.

QRes GUI's executables aren't signed, so Windows SmartScreen shows "Windows
protected your PC" to people who run a fresh download. Signing is what makes
that go away over time. Options, cheapest first:

## 1. SignPath Foundation (free for open source)

SignPath signs releases of open-source projects for free, using a certificate
issued to the SignPath Foundation (that's the publisher name Windows shows).

- Requirements: an OSI-approved license (MIT ✓), a public repository (✓), and
  releases built by CI from that repository (✓, GitHub Actions).
- Apply at <https://signpath.org> (open-source program). Once accepted, they
  give you an organisation ID, a project and a signing policy, and you add an
  API token as a GitHub Actions secret.
- CI then sends the built `QResGUI.exe` / `QResLauncher.exe` to SignPath with
  their GitHub Action and puts the signed files in the zip.

## 2. Azure Trusted Signing (about $10 a month)

Microsoft's own signing service; the publisher name is your verified identity.

- Needs an Azure subscription and identity validation (available to
  individual developers in supported countries).
- Create a Trusted Signing account and certificate profile in the Azure
  portal, then give GitHub Actions access (an app registration with the
  "Trusted Signing Certificate Profile Signer" role).
- CI signs with the `azure/trusted-signing-action` before zipping.

## 3. No certificate

- Each release can be submitted to Microsoft at
  <https://www.microsoft.com/wdsi/filesubmission> ("software developer",
  "incorrectly detected"). It's free and helps with Defender and SmartScreen
  reputation, but has to be repeated per release.
- Users can unblock the zip before extracting (right-click › Properties ›
  Unblock), or choose **More info › Run anyway** at the warning.

Signing doesn't make the warning vanish instantly: SmartScreen also weighs how
many people have run a signed file. It does let that reputation build up
across releases instead of starting from zero each time.

Once an account exists, the CI change is small: sign `dist\QResGUI\*.exe`
between the build and packaging steps.
