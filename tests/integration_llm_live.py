import os
import unittest

from fastapi.testclient import TestClient

from app.llm_client import call_llm
from app.main import app

DEFAULT_REPO_URL = "https://github.com/psf/requests"


class LiveLlmIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def require_api_key(self) -> None:
        if not os.getenv("NEBIUS_API_KEY"):
            self.skipTest("NEBIUS_API_KEY is not set")

    async def test_call_llm_returns_structured_result_from_real_provider(self):
        self.require_api_key()

        system_prompt = (
            "You are validating JSON output. Respond only with valid JSON matching this exact schema: "
            '{"summary":"string","technologies":["string"],"structure":"string"}. '
            "The summary field must be a string. "
            "The technologies field must be an array of strings. "
            "The structure field must be a concise text string describing layout, not a list and not an object."
        )
        user_prompt = (
            "Use only these facts:\n"
            "- Project is a FastAPI service written in Python.\n"
            "- Important dependencies are FastAPI and httpx.\n"
            "- Structure includes app/main.py and app/llm_client.py.\n"
            "Return concise factual JSON.\n"
            "The structure value must be one short sentence, as a plain string."
        )

        result = await call_llm(system_prompt, user_prompt)

        self.assertIsInstance(result, dict)
        self.assertTrue(result["summary"].strip())
        self.assertTrue(result["structure"].strip())
        self.assertIsInstance(result["technologies"], list)
        self.assertGreaterEqual(len(result["technologies"]), 2)
        lowered = {item.lower() for item in result["technologies"]}
        self.assertIn("python", lowered)
        self.assertTrue(any("fastapi" in item for item in lowered))


class LiveEndToEndIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def require_api_key(self) -> None:
        if not os.getenv("NEBIUS_API_KEY"):
            self.skipTest("NEBIUS_API_KEY is not set")

    def test_summarize_endpoint_end_to_end_with_public_repo(self):
        self.require_api_key()

        repo_url = os.getenv("INTEGRATION_GITHUB_URL", DEFAULT_REPO_URL)
        response = self.client.post("/summarize", json={"github_url": repo_url})

        self.assertEqual(response.status_code, 200, response.text)

        payload = response.json()
        self.assertTrue(payload["summary"].strip())
        self.assertTrue(payload["structure"].strip())
        self.assertIsInstance(payload["technologies"], list)
        self.assertGreaterEqual(len(payload["technologies"]), 1)

        lowered = {item.lower() for item in payload["technologies"]}
        self.assertIn("python", lowered)
        self.assertTrue("requests" in payload["summary"].lower() or "http" in payload["summary"].lower())
