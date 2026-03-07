import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


class SummarizeEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_summarize_success_without_network(self):
        repo_info = {"full_name": "octocat/hello-world", "description": "Demo repo", "language": "Python"}
        tree = [{"path": "README.md", "type": "blob", "size": 12}]
        llm_result = {
            "summary": "Summarized from mocks.",
            "technologies": ["Python", "FastAPI"],
            "structure": "App package.",
        }

        with patch("app.main.fetch_repo_tree", new=AsyncMock(return_value=(repo_info, tree, "main"))):
            with patch("app.main.build_context", new=AsyncMock(return_value="mock context")):
                with patch("app.main.call_llm", new=AsyncMock(return_value=llm_result)):
                    response = self.client.post("/summarize", json={"github_url": "https://github.com/octocat/hello-world"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), llm_result)

    def test_validation_error_stays_local(self):
        response = self.client.post("/summarize", json={})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "error")

