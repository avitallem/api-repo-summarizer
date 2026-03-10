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

3. Configure environment variables:

```bash
cp .env.example .env
# Edit .env
```

## Environment Variables

Required:

- `NEBIUS_API_KEY`: API key used for Nebius chat completion requests.

Optional:

- `NEBIUS_MODEL`: overrides automatic model selection.
- `NEBIUS_API_BASE`: overrides the default Nebius API base URL.
- `GITHUB_TOKEN`: adds authenticated GitHub API requests and raises GitHub rate limits compared with anonymous requests.
- `INTEGRATION_GITHUB_URL`: optional public repository URL used by the live integration test module. If unset, the live tests use `https://github.com/psf/requests`.

Environment loading behavior:

- The app calls `load_dotenv()` from `python-dotenv` in `app.main`, so values in a local `.env` file are loaded automatically when the app starts.
- Already-exported environment variables still take precedence over values in `.env`.
- Tests that patch `os.environ` do not rely on `.env`.

You can also export variables directly instead of using `.env`:

```bash
export NEBIUS_API_KEY="your_api_key"
export GITHUB_TOKEN="your_github_token"  # optional
```

## Run the server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The server reads `.env` when `app.main` is imported. No extra flag is required for local configuration loading.

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

## Testing

Default offline test suite:

```bash
python -m unittest discover -v
```

Purpose:

- Covers parsing, repository filtering, context building, FastAPI endpoint behavior, and LLM/GitHub integration boundaries with mocks or fakes.
- Does not require real API keys or live network access.
- This is the default suite for normal local development and CI.

Live integration tests:

```bash
python -m unittest tests.integration_llm_live -v
```

Purpose:

- Verifies that a real Nebius credential works with the current `call_llm()` implementation.
- Verifies that the `/summarize` endpoint can complete end-to-end against a real public GitHub repository.

Requirements:

- `NEBIUS_API_KEY` must be set.
- The live module skips cleanly if `NEBIUS_API_KEY` is missing.
- `INTEGRATION_GITHUB_URL` can override the default public test repository.

Use the live tests sparingly:

- They make real provider calls.
- They may consume paid LLM usage.
- They depend on external network availability and current upstream API behavior.

## Notes

- Only public repository-root `github.com` URLs are supported, such as `https://github.com/owner/repo` or `https://github.com/owner/repo.git`.
- GitHub requests are unauthenticated unless `GITHUB_TOKEN` is set.
- The service is asynchronous and maps timeout/network/provider errors to explicit HTTP error responses.
- If your Nebius account uses a different API host, set `NEBIUS_API_BASE` (for example `https://api.tokenfactory.nebius.com/v1`).

## Known Limitations

- Unauthenticated GitHub API usage may hit rate limits quickly. Even with `GITHUB_TOKEN`, repeated or larger requests can still hit GitHub limits.
- Repository content is fetched file-by-file from GitHub. Large repositories can be slow to summarize and can consume many GitHub API requests per call.
- Large repositories are summarized with a strict context budget, so deep/low-priority files may be skipped or truncated.
- Summary quality depends on LLM output and may vary across model versions available in Nebius.
- Live integration tests are not free: they use the real Nebius API and can incur cost.
