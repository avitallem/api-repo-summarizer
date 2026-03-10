import base64
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.errors import AppError
from app.github_fetcher import _github_get, fetch_file_content, fetch_repo_tree, parse_github_url
from tests.fakes import FakeResponse


class ParseGitHubUrlTests(unittest.TestCase):
    def test_parse_valid_url(self):
        owner, repo = parse_github_url(" https://github.com/octocat/hello-world.git ")
        self.assertEqual((owner, repo), ("octocat", "hello-world"))

    def test_parse_valid_root_url_with_trailing_slash(self):
        owner, repo = parse_github_url("https://github.com/octocat/hello-world/")

        self.assertEqual((owner, repo), ("octocat", "hello-world"))

    def test_rejects_non_github_host(self):
        with self.assertRaises(AppError) as ctx:
            parse_github_url("https://example.com/octocat/hello-world")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Only github.com", ctx.exception.message)

    def test_rejects_extra_path_segments(self):
        with self.assertRaises(AppError) as ctx:
            parse_github_url("https://github.com/octocat/hello-world/issues/1")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("repository root URL", ctx.exception.message)

    def test_rejects_tree_url(self):
        with self.assertRaises(AppError) as ctx:
            parse_github_url("https://github.com/octocat/hello-world/tree/main")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("repository root URL", ctx.exception.message)

    def test_rejects_query_string(self):
        with self.assertRaises(AppError) as ctx:
            parse_github_url("https://github.com/octocat/hello-world?tab=readme")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("repository root URL", ctx.exception.message)

    def test_rejects_fragment(self):
        with self.assertRaises(AppError) as ctx:
            parse_github_url("https://github.com/octocat/hello-world#readme")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("repository root URL", ctx.exception.message)

    def test_rejects_missing_repo(self):
        with self.assertRaises(AppError) as ctx:
            parse_github_url("https://github.com/octocat/")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("owner and repository name", ctx.exception.message)

    def test_rejects_empty_repo_segment(self):
        with self.assertRaises(AppError) as ctx:
            parse_github_url("https://github.com/octocat/.git")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("missing owner or repository", ctx.exception.message)


class FetchRepoTreeTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_repo_tree_success(self):
        repo_response = FakeResponse(
            200,
            {"full_name": "octocat/hello-world", "default_branch": "main"},
        )
        tree_response = FakeResponse(200, {"tree": [{"path": "README.md", "type": "blob", "size": 12}]})

        with patch("app.github_fetcher._github_get", new=AsyncMock(side_effect=[repo_response, tree_response])):
            repo_info, tree, default_branch = await fetch_repo_tree("octocat", "hello-world")

        self.assertEqual(repo_info["full_name"], "octocat/hello-world")
        self.assertEqual(tree[0]["path"], "README.md")
        self.assertEqual(default_branch, "main")

    async def test_fetch_repo_tree_maps_not_found(self):
        not_found = FakeResponse(404, {"message": "Not Found"})

        with patch("app.github_fetcher._github_get", new=AsyncMock(return_value=not_found)):
            with self.assertRaises(AppError) as ctx:
                await fetch_repo_tree("octocat", "missing")

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_fetch_repo_tree_maps_rate_limit_to_429(self):
        rate_limited = FakeResponse(429, {"message": "API rate limit exceeded"})

        with patch("app.github_fetcher._github_get", new=AsyncMock(return_value=rate_limited)):
            with self.assertRaises(AppError) as ctx:
                await fetch_repo_tree("octocat", "hello-world")

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("rate limit exceeded", ctx.exception.message)

    async def test_fetch_repo_tree_maps_timeout_to_504(self):
        timeout = httpx.ReadTimeout("timed out")

        with patch("app.github_fetcher._github_get", new=AsyncMock(side_effect=timeout)):
            with self.assertRaises(AppError) as ctx:
                await fetch_repo_tree("octocat", "hello-world")

        self.assertEqual(ctx.exception.status_code, 504)
        self.assertIn("timed out", ctx.exception.message)


class FetchFileContentTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_file_content_decodes_base64(self):
        payload = {
            "type": "file",
            "encoding": "base64",
            "content": base64.b64encode(b"print('hello')\n").decode("ascii"),
        }

        with patch("app.github_fetcher._github_get", new=AsyncMock(return_value=FakeResponse(200, payload))):
            content = await fetch_file_content("octocat", "hello-world", "main.py")

        self.assertEqual(content, "print('hello')\n")

    async def test_fetch_file_content_returns_none_for_missing_file(self):
        with patch("app.github_fetcher._github_get", new=AsyncMock(return_value=FakeResponse(404, {"message": "Not Found"}))):
            content = await fetch_file_content("octocat", "hello-world", "missing.py")

        self.assertIsNone(content)

    async def test_fetch_file_content_maps_rate_limit_to_429(self):
        rate_limited = FakeResponse(403, {"message": "API rate limit exceeded"})
        rate_limited.headers = {"x-ratelimit-remaining": "0"}

        with patch("app.github_fetcher._github_get", new=AsyncMock(return_value=rate_limited)):
            with self.assertRaises(AppError) as ctx:
                await fetch_file_content("octocat", "hello-world", "main.py")

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("rate limit exceeded", ctx.exception.message)

    async def test_fetch_file_content_maps_timeout_to_504(self):
        timeout = httpx.ReadTimeout("timed out")

        with patch("app.github_fetcher._github_get", new=AsyncMock(side_effect=timeout)):
            with self.assertRaises(AppError) as ctx:
                await fetch_file_content("octocat", "hello-world", "main.py")

        self.assertEqual(ctx.exception.status_code, 504)
        self.assertIn("timed out", ctx.exception.message)


class GitHubHeadersTests(unittest.IsolatedAsyncioTestCase):
    async def test_github_get_includes_auth_header_when_token_present(self):
        captured = {}

        class DummyClient:
            async def get(self, url, params=None, headers=None):
                captured["url"] = url
                captured["params"] = params
                captured["headers"] = headers
                return FakeResponse(200, {})

        with patch.dict("os.environ", {"GITHUB_TOKEN": "test-token"}, clear=True):
            await _github_get(DummyClient(), "/repos/octocat/hello-world")

        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-token")
        self.assertEqual(captured["headers"]["Accept"], "application/vnd.github+json")

    async def test_github_get_omits_auth_header_when_token_missing(self):
        captured = {}

        class DummyClient:
            async def get(self, url, params=None, headers=None):
                captured["headers"] = headers
                return FakeResponse(200, {})

        with patch.dict("os.environ", {}, clear=True):
            await _github_get(DummyClient(), "/repos/octocat/hello-world")

        self.assertNotIn("Authorization", captured["headers"])
