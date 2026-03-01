import base64
from urllib.parse import urlparse

import httpx

from app.errors import AppError

GITHUB_API_BASE = "https://api.github.com"


def parse_github_url(url: str) -> tuple[str, str]:
    try:
        parsed = urlparse(url.strip())
    except Exception as exc:
        raise AppError(400, "Invalid URL format") from exc

    if parsed.scheme not in {"http", "https"}:
        raise AppError(400, "GitHub URL must start with http:// or https://")
    if parsed.netloc.lower() != "github.com":
        raise AppError(400, "Only github.com repository URLs are supported")

    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        raise AppError(400, "GitHub URL must include owner and repository name")

    owner = parts[0]
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]

    if not owner or not repo:
        raise AppError(400, "GitHub URL is missing owner or repository")

    return owner, repo


async def _github_get(client: httpx.AsyncClient, path: str, params: dict | None = None) -> httpx.Response:
    response = await client.get(
        f"{GITHUB_API_BASE}{path}",
        params=params,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "api-repo-summarizer",
        },
    )
    return response


async def fetch_repo_tree(owner: str, repo: str) -> tuple[dict, list[dict], str]:
    timeout = httpx.Timeout(30.0, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            repo_resp = await _github_get(client, f"/repos/{owner}/{repo}")
            if repo_resp.status_code == 404:
                raise AppError(404, "Repository not found or not public")
            if repo_resp.status_code in {403, 429}:
                raise AppError(429, "GitHub API rate limit exceeded")
            if repo_resp.status_code >= 400:
                raise AppError(502, f"GitHub API error: HTTP {repo_resp.status_code}")

            repo_info = repo_resp.json()
            default_branch = repo_info.get("default_branch")
            if not default_branch:
                raise AppError(502, "Failed to resolve repository default branch")

            tree_resp = await _github_get(
                client,
                f"/repos/{owner}/{repo}/git/trees/{default_branch}",
                params={"recursive": 1},
            )
            if tree_resp.status_code in {403, 429}:
                raise AppError(429, "GitHub API rate limit exceeded")
            if tree_resp.status_code >= 400:
                raise AppError(502, f"Failed to fetch repository tree: HTTP {tree_resp.status_code}")

            tree_json = tree_resp.json()
            tree = tree_json.get("tree", [])
            return repo_info, tree, default_branch

    except httpx.TimeoutException as exc:
        raise AppError(504, "GitHub request timed out") from exc
    except httpx.NetworkError as exc:
        raise AppError(502, "Failed to connect to GitHub") from exc


async def fetch_file_content(owner: str, repo: str, path: str) -> str | None:
    timeout = httpx.Timeout(30.0, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await _github_get(client, f"/repos/{owner}/{repo}/contents/{path}")
            if response.status_code in {403, 429}:
                raise AppError(429, "GitHub API rate limit exceeded")
            if response.status_code == 404:
                return None
            if response.status_code >= 400:
                return None

            payload = response.json()
            if isinstance(payload, list):
                return None
            if payload.get("type") != "file":
                return None

            encoding = payload.get("encoding")
            content = payload.get("content", "")
            if encoding != "base64" or not content:
                return None

            decoded = base64.b64decode(content, validate=False)
            text = decoded.decode("utf-8")
            return text

    except (UnicodeDecodeError, ValueError, base64.binascii.Error):
        return None
    except httpx.TimeoutException as exc:
        raise AppError(504, "GitHub request timed out") from exc
    except httpx.NetworkError as exc:
        raise AppError(502, "Failed to connect to GitHub") from exc
