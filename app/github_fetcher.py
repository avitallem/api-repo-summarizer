import base64
import os
from urllib.parse import urlparse

import httpx

from app.errors import AppError

GITHUB_API_BASE = "https://api.github.com"


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "api-repo-summarizer",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _is_rate_limited(response: httpx.Response) -> bool:
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False

    headers = {str(key).lower(): str(value) for key, value in getattr(response, "headers", {}).items()}
    if headers.get("x-ratelimit-remaining") == "0":
        return True

    try:
        payload = response.json()
    except Exception:
        return False

    if isinstance(payload, dict):
        message = str(payload.get("message", "")).lower()
        return "rate limit" in message
    return False


def parse_github_url(url: str) -> tuple[str, str]:
    try:
        parsed = urlparse(url.strip())
    except Exception as exc:
        raise AppError(400, "Invalid URL format") from exc

    if parsed.scheme not in {"http", "https"}:
        raise AppError(400, "GitHub URL must start with http:// or https://")
    if parsed.netloc.lower() != "github.com":
        raise AppError(400, "Only github.com repository URLs are supported")

    if parsed.query or parsed.fragment:
        raise AppError(400, "GitHub URL must be a repository root URL without query parameters or fragments")

    parts = [p for p in parsed.path.strip("/").split("/")]
    if len(parts) < 2:
        raise AppError(400, "GitHub URL must include owner and repository name")
    if len(parts) != 2:
        raise AppError(400, "GitHub URL must be a repository root URL like https://github.com/<owner>/<repo>")

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
        headers=_github_headers(),
    )
    return response


async def fetch_repo_tree(owner: str, repo: str) -> tuple[dict, list[dict], str]:
    timeout = httpx.Timeout(30.0, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            repo_resp = await _github_get(client, f"/repos/{owner}/{repo}")
            if repo_resp.status_code == 404:
                raise AppError(404, "Repository not found or not public")
            if _is_rate_limited(repo_resp):
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
            if _is_rate_limited(tree_resp):
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
            if _is_rate_limited(response):
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
