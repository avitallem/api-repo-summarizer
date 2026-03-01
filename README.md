# GitHub Repository Summarizer API

A FastAPI service that accepts a public GitHub repository URL and returns a structured summary using Nebius Token Factory.

## Tech Stack

- Python 3.10+
- FastAPI
- Nebius Token Factory (OpenAI-compatible API)
- httpx

## Model Choice

This implementation prefers `meta-llama/Llama-3.3-70B-Instruct` on Nebius and auto-selects an available model when needed (`NEBIUS_MODEL` override supported). This keeps the service resilient when model availability differs across accounts.

## Repository Processing Approach

The service does not send the whole repository to the LLM. It applies a prioritized, token-budgeted pipeline:

1. Fetch repository metadata and full tree from GitHub REST API.
2. Filter out low-signal files/directories:
   - binary/media/archive artifacts
   - lock files
   - build/cache/vendor folders
   - large files (>100KB)
3. Build context in this order:
   - repository metadata
   - filtered directory structure
   - prioritized file contents (README, manifest/config, entry points, shallow source files)
4. Enforce a hard context budget with truncation for very large repositories.

This keeps the prompt informative while staying within LLM context limits.

## Setup

1. Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Set environment variables:

```bash
cp .env.example .env
# Edit .env and set NEBIUS_API_KEY
```

Or export directly:

```bash
export NEBIUS_API_KEY="your_api_key"
```

## Run the server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API Endpoint

### `POST /summarize`

Request body:

```json
{
  "github_url": "https://github.com/psf/requests"
}
```

Success response:

```json
{
  "summary": "...",
  "technologies": ["..."],
  "structure": "..."
}
```

Error response format:

```json
{
  "status": "error",
  "message": "Description of what went wrong"
}
```

## Manual test with curl

```bash
curl -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url":"https://github.com/psf/requests"}'
```

## Notes

- Only public `github.com` URLs are supported.
- GitHub API is used without authentication by design (subject to public rate limits).
- The service is asynchronous and handles timeout/network/provider errors with explicit HTTP error responses.
- If your Nebius account uses a different API host, set `NEBIUS_API_BASE` (for example `https://api.tokenfactory.nebius.com/v1`).

## Known Limitations

- Unauthenticated GitHub API usage may hit rate limits on repeated requests.
- Large repositories are summarized with a strict context budget, so deep/low-priority files may be skipped or truncated.
- Summary quality depends on LLM output and may vary slightly across model versions available in Nebius.
