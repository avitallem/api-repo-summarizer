import unittest
from unittest.mock import patch

from app.repo_processor import (
    build_context,
    filter_tree,
    format_directory_tree,
    format_repo_metadata,
    prioritize_files,
    should_skip_path,
)


class RepoProcessorPureTests(unittest.TestCase):
    def test_should_skip_path_filters_generated_and_binary_files(self):
        self.assertTrue(should_skip_path("node_modules/react/index.js"))
        self.assertTrue(should_skip_path("assets/logo.png"))
        self.assertTrue(should_skip_path("static/app.min.js"))
        self.assertFalse(should_skip_path("src/main.py"))

    def test_filter_tree_keeps_only_relevant_text_files(self):
        tree = [
            {"path": "README.md", "type": "blob", "size": 100},
            {"path": "node_modules/pkg/index.js", "type": "blob", "size": 100},
            {"path": "image.png", "type": "blob", "size": 100},
            {"path": "big.txt", "type": "blob", "size": 100_001},
            {"path": "src", "type": "tree"},
        ]

        filtered = filter_tree(tree)

        self.assertEqual(filtered, [{"path": "README.md", "type": "blob", "size": 100}])

    def test_prioritize_files_prefers_readme_then_manifest_then_entrypoint(self):
        filtered_tree = [
            {"path": "src/module.py"},
            {"path": "app/main.py"},
            {"path": "requirements.txt"},
            {"path": "README.md"},
        ]

        prioritized = [item["path"] for item in prioritize_files(filtered_tree)]

        self.assertEqual(prioritized[0], "README.md")
        self.assertEqual(prioritized[1], "requirements.txt")
        self.assertEqual(prioritized[2], "app/main.py")

    def test_format_helpers_render_metadata_and_tree(self):
        repo_info = {
            "full_name": "octocat/hello-world",
            "description": "Demo repo",
            "language": "Python",
            "topics": ["api", "fastapi"],
        }
        filtered_tree = [{"path": "app/main.py"}, {"path": "README.md"}]

        metadata = format_repo_metadata(repo_info)
        directory_tree = format_directory_tree(filtered_tree)

        self.assertIn("Name: octocat/hello-world", metadata)
        self.assertIn("Topics: api, fastapi", metadata)
        self.assertIn("- README.md (README.md)", directory_tree)
        self.assertIn("  - main.py (app/main.py)", directory_tree)


class BuildContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_context_uses_mocked_file_fetcher(self):
        repo_info = {
            "full_name": "octocat/hello-world",
            "description": "Demo repo",
            "language": "Python",
            "topics": [],
        }
        filtered_tree = [
            {"path": "README.md"},
            {"path": "app/main.py"},
        ]

        async def fake_fetch_file_content(owner, repo, path):
            contents = {
                "README.md": "# Hello\n",
                "app/main.py": "print('hello')\n",
            }
            return contents.get(path)

        with patch("app.repo_processor.fetch_file_content", new=fake_fetch_file_content):
            context = await build_context("octocat", "hello-world", repo_info, filtered_tree)

        self.assertIn("## Repository Info", context)
        self.assertIn("## Directory Structure", context)
        self.assertIn("=== README.md ===", context)
        self.assertIn("print('hello')", context)

    async def test_build_context_truncates_without_network(self):
        repo_info = {
            "full_name": "octocat/hello-world",
            "description": "Demo repo",
            "language": "Python",
            "topics": [],
        }
        filtered_tree = [{"path": "README.md"}]

        async def fake_fetch_file_content(owner, repo, path):
            return "A" * 400

        with patch("app.repo_processor.MAX_CONTEXT_TOKENS", 100):
            with patch("app.repo_processor.fetch_file_content", new=fake_fetch_file_content):
                context = await build_context("octocat", "hello-world", repo_info, filtered_tree)

        self.assertIn("[truncated]", context)
