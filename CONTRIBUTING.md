# Contributing

SecretBox is a small personal project. Bug reports, security reports, and focused contributions are welcome.

## Before opening a change

- Describe the behavior you are changing and why.
- Keep changes scoped and follow the architecture constraints in [AGENTS.md](AGENTS.md).
- Write documentation, comments, CLI messages, and API errors in English.
- Do not include real server configuration, tokens, private age identities, transfer data, or personal deployment details.
- Update [contracts/openapi.yaml](contracts/openapi.yaml) and relevant documentation when changing the API.

## Deployment configuration

The tracked files server/.sisy.example.json, server/.htaccess.example, and server/.user.ini.example are sanitized examples. The real server/.sisy.json, server/.htaccess, and server/.user.ini are personal, untracked deployment files. Never replace the examples with those real files or commit them.

## Security issues

Do not report vulnerabilities in a public issue. Follow the private reporting instructions in [SECURITY.md](SECURITY.md).
