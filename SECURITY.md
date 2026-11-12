# Security policy

## Supported versions

This project is finished: the dice and the demo get no new features. Security
problems are still fixed, on the `main` branch only.

| Version | Supported |
| --- | --- |
| `main` | yes (security fixes) |
| older copies or forks | no |

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub. Open the repository's
**Security** tab and choose **Report a vulnerability**. This uses GitHub's
private vulnerability reporting, so only you and the maintainer can see the
report.

Do not open a public issue for a security problem. Please include the browser
and its version, the file involved and the steps that show the problem.

## Security model

- **Static files only.** The demo is plain HTML and JavaScript with no build
  step and no server code. It only fetches its own files (models, pictures,
  `vendor/` libraries) from the folder it is served from, and makes no other
  network requests.
- **Browser storage.** The demo keeps the throw tally and the texture choice
  in `localStorage`; nothing is sent anywhere.
- **Vendored libraries.** three.js and cannon-es are copied into `vendor/`
  (versions in `THIRD_PARTY_NOTICES.md`). A security fix in either of them is
  a reason to update the copy here.
- **Tools run locally.** `tools/dice3d.py` runs inside Blender on your own
  machine; `tools/glb_tiers.py` and `tools/stamp_xmp.py` read and write files
  you name. Only run them on files you trust.
- **Model files.** The `.glb` files are standard glTF 2.0 binaries with
  embedded JPEG textures and no scripts.
