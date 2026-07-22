# Security policy

## Supported versions

Security fixes are applied to the current major release on the `main` branch.

| Version | Supported |
|---|---|
| 4.x | Yes |
| 3.x and earlier | No |

## Reporting a vulnerability

Do not disclose a suspected vulnerability in a public issue.

Use GitHub's **Report a vulnerability** private security-advisory flow for this repository. Include:

- affected version or commit;
- deployment topology;
- reproduction steps;
- expected and observed behavior;
- logs or artifacts with secrets removed;
- impact assessment;
- proposed remediation, when available.

Reports concerning unauthorized targeting, evasion of the private-range boundary, credential theft, destructive behavior, denial of service, persistence, or host escape will be treated as security-sensitive.

## Operational security

- Keep `OPENAI_API_KEY` and runner tokens out of commits and logs.
- Do not expose the runner API or Docker socket to untrusted networks.
- Use a dedicated or rootless Docker host for serious deployments.
- Keep workspaces attached only to explicitly authorized private-range networks.
- Review generated findings and reproduction evidence before acting on them.
