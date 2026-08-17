# Configuration policy

Only sanitized, dry-run-only configurations belong here. Exchange secrets,
Telegram tokens, API credentials, database files, and private overrides must
remain outside version control. The canary configuration must keep the API
server disabled and must not contain order-capable credentials.
