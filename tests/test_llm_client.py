import json
import unittest
from unittest.mock import AsyncMock, patch

from app.errors import AppError
from app.llm_client import call_llm
from tests.fakes import FakeAsyncClient, FakeResponse


class CallLlmTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_llm_requires_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(AppError) as ctx:
                await call_llm("system", "user")

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertIn("NEBIUS_API_KEY", ctx.exception.message)

    async def test_call_llm_uses_mocked_http_and_fake_env(self):
        record = {"get": [], "post": []}
        responses = [
            FakeResponse(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "summary": "A concise summary.",
                                        "technologies": ["Python", "FastAPI"],
                                        "structure": "Single app package.",
                                    }
                                )
                            }
                        }
                    ]
                },
            )
        ]

        with patch.dict("os.environ", {"NEBIUS_API_KEY": "test-key", "NEBIUS_MODEL": "fake-model"}, clear=True):
            with patch(
                "app.llm_client.httpx.AsyncClient",
                new=lambda **kwargs: FakeAsyncClient(post_responses=responses, record=record, **kwargs),
            ):
                result = await call_llm("system prompt", "user prompt")

        self.assertEqual(result["summary"], "A concise summary.")
        self.assertEqual(result["technologies"], ["Python", "FastAPI"])
        request_json = record["post"][0]["kwargs"]["json"]
        self.assertEqual(request_json["model"], "fake-model")
        self.assertEqual(request_json["messages"][0]["content"], "system prompt")

    async def test_call_llm_can_select_model_without_live_provider(self):
        responses = [
            FakeResponse(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"summary":"ok","technologies":["Python"],"structure":"ok"}'
                            }
                        }
                    ]
                },
            )
        ]

        with patch.dict("os.environ", {"NEBIUS_API_KEY": "test-key"}, clear=True):
            with patch("app.llm_client._list_models", new=AsyncMock(return_value=["meta-llama/Meta-Llama-3.1-8B-Instruct"])):
                with patch(
                    "app.llm_client.httpx.AsyncClient",
                    new=lambda **kwargs: FakeAsyncClient(post_responses=responses, **kwargs),
                ):
                    result = await call_llm("system", "user")

        self.assertEqual(result["technologies"], ["Python"])

    async def test_call_llm_maps_invalid_json(self):
        record = {"get": [], "post": []}
        responses = [FakeResponse(200, {"choices": [{"message": {"content": "not-json"}}]})]

        with patch.dict("os.environ", {"NEBIUS_API_KEY": "test-key", "NEBIUS_MODEL": "fake-model"}, clear=True):
            with patch(
                "app.llm_client.httpx.AsyncClient",
                new=lambda **kwargs: FakeAsyncClient(post_responses=responses, record=record, **kwargs),
            ):
                with self.assertRaises(AppError) as ctx:
                    await call_llm("system", "user")

        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("invalid JSON", ctx.exception.message)
        self.assertEqual(len(record["post"]), 1)

    async def test_call_llm_fails_fast_on_schema_errors(self):
        record = {"get": [], "post": []}
        responses = [
            FakeResponse(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "summary": "A concise summary.",
                                        "technologies": ["Python", "FastAPI"],
                                        "structure": ["app/main.py", "app/llm_client.py"],
                                    }
                                )
                            }
                        }
                    ]
                },
            )
        ]

        with patch.dict("os.environ", {"NEBIUS_API_KEY": "test-key", "NEBIUS_MODEL": "fake-model"}, clear=True):
            with patch(
                "app.llm_client.httpx.AsyncClient",
                new=lambda **kwargs: FakeAsyncClient(post_responses=responses, record=record, **kwargs),
            ):
                with self.assertRaises(AppError) as ctx:
                    await call_llm("system", "user")

        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("invalid 'structure' field", ctx.exception.message)
        self.assertEqual(len(record["post"]), 1)
