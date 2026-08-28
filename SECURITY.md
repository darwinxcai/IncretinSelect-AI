# Security policy

## Supported version

Security fixes are applied to the latest release on the default branch.

| Version | Supported |
|:---|:---:|
| 0.9.x | Yes |
| Earlier versions | No |

## Reporting a vulnerability

Please report a suspected vulnerability privately through the repository's
**Security** tab by opening a private security advisory. Include the affected
version, a minimal reproduction, the likely impact, and any proposed mitigation.
Do not place exploit details, sensitive sequences, credentials, or private data in
a public issue.

If private advisory reporting is unavailable, open a public issue containing only
enough information to request a private follow-up. Acknowledgement is targeted
within seven days. No guaranteed remediation timeline is offered for this
research-use software.

## Scope

The public browser application performs local, static inference and has no account,
analytics, or sequence-processing backend. Security reports are still relevant for
file handling, generated downloads, packaged command-line tools, dependencies,
deployment configuration, and any behavior that contradicts the documented
local-processing boundary.

Model accuracy, biological validity, and unsupported inputs are scientific-quality
issues rather than security vulnerabilities unless they arise from a software flaw
that crosses a trust or data boundary.
