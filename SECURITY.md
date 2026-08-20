# Security Policy

## Reporting a vulnerability

Please do not publish security-sensitive details in a public issue.

Use GitHub's private vulnerability reporting for this repository when it is enabled.
If it is not enabled, contact the repository maintainer through the GitHub profile and include:

1. affected version or commit
2. reproducible steps
3. expected and actual behavior
4. impact assessment
5. a suggested disclosure timeline

Do not include credentials, personal data, or live listing contents in a report.

## Deployment boundary

The web application exposes public read endpoints and protects mutating POST and PATCH endpoints with HTTP Basic Auth when `CORVETTE_TRACKER_ADMIN_USER` and `CORVETTE_TRACKER_ADMIN_PASSWORD` are configured.

Do not expose mutating endpoints without TLS and authentication.
