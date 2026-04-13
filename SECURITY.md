# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅ Yes    |

## Reporting a Vulnerability

**Please do not open public GitHub issues for security vulnerabilities.**

To report a security vulnerability, email: **arunrajiah@gmail.com**

Include:
- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fixes (optional)

You will receive a response within **72 hours**. We take all security reports seriously.

## Security Considerations

### Credential storage
- Never commit `config/config.yaml` (it's in `.gitignore`)
- Use environment variables for API keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`)
- CCTV system passwords in config are stored in plaintext — restrict file permissions: `chmod 600 config/config.yaml`

### Network exposure
- The REST API has no authentication by default — **do not expose it to the public internet**
- Use a reverse proxy (nginx, Caddy) with authentication if you need external access
- Restrict Docker port binding to localhost: `127.0.0.1:8000:8000` in docker-compose

### LLM data privacy
- With Ollama, all queries stay on your local network
- With OpenAI/Anthropic, your query text (but not video/images) is sent to their APIs
- Do not use cloud LLMs if your queries contain sensitive information

### ONVIF credentials
- Use a dedicated read-only account for cctvQL on your NVR
- ONVIF connections are typically over plain HTTP — use only on a trusted local network
