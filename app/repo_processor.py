import os
from pathlib import Path

from app.github_fetcher import fetch_file_content

MAX_CONTEXT_TOKENS = 12000

SKIP_DIRECTORIES = {
    ".git",
    "node_modules",
    "dist",
    "build",
    "vendor",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    ".tox",
    ".idea",
    ".vscode",
    ".next",
    ".nuxt",
    ".cache",
    ".github/workflows",
}

SKIP_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".svg",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".7z",
    ".rar",
    ".mp3",
    ".mp4",
    ".wav",
    ".mov",
    ".ttf",
    ".woff",
    ".woff2",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".class",
    ".jar",
    ".o",
    ".a",
    ".pyc",
    ".pyo",
    ".lock",
    ".map",
}

SKIP_FILENAMES = {
    ".ds_store",
    "thumbs.db",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "pipfile.lock",
    "poetry.lock",
    "composer.lock",
    "go.sum",
}

PRIORITY_TIER_2 = {
    "package.json",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "gemfile",
    "composer.json",
    "makefile",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    ".env.example",
    "tsconfig.json",
    "vite.config.ts",
    "webpack.config.js",
}

PRIORITY_TIER_3 = {
    "main.py",
    "app.py",
    "server.py",
    "index.py",
    "main.ts",
    "index.ts",
    "app.ts",
    "main.js",
    "index.js",
    "app.js",
    "main.go",
    "main.rs",
    "main.java",
    "lib.rs",
}


def count_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    approx_chars = max_tokens * 4
    return text[:approx_chars]


def should_skip_path(path: str) -> bool:
    lowered = path.lower()
    file_name = os.path.basename(lowered)

    if file_name in SKIP_FILENAMES:
        return True

    suffix = Path(lowered).suffix
    if suffix in SKIP_EXTENSIONS:
        return True

    if file_name.endswith(".min.js") or file_name.endswith(".min.css"):
        return True

    parts = Path(lowered).parts
    for idx in range(len(parts) - 1):
        seg = parts[idx]
        if seg in SKIP_DIRECTORIES:
            return True
        if idx < len(parts) - 2:
            joined = f"{seg}/{parts[idx + 1]}"
            if joined in SKIP_DIRECTORIES:
                return True

    return False


def filter_tree(tree: list[dict]) -> list[dict]:
    result: list[dict] = []
    for item in tree:
        if item.get("type") != "blob":
            continue

        path = item.get("path")
        if not isinstance(path, str) or not path.strip():
            continue

        size = item.get("size", 0)
        if isinstance(size, int) and size > 100_000:
            continue

        if should_skip_path(path):
            continue

        result.append(item)

    return result


def priority_score(path: str) -> tuple[int, int, str]:
    file_name = os.path.basename(path)
    file_name_l = file_name.lower()
    depth = path.count("/")

    if file_name_l.startswith("readme"):
        return (0, depth, path)
    if file_name_l in PRIORITY_TIER_2:
        return (1, depth, path)
    if file_name_l in PRIORITY_TIER_3:
        return (2, depth, path)

    if path.startswith("src/") or path.startswith("app/"):
        return (3, depth, path)

    return (4, depth, path)


def prioritize_files(filtered_tree: list[dict]) -> list[dict]:
    return sorted(filtered_tree, key=lambda item: priority_score(item["path"]))


def format_repo_metadata(repo_info: dict) -> str:
    topics = repo_info.get("topics") or []
    if not isinstance(topics, list):
        topics = []

    return (
        "## Repository Info\n"
        f"Name: {repo_info.get('full_name', 'unknown')}\n"
        f"Description: {repo_info.get('description') or 'N/A'}\n"
        f"Primary Language: {repo_info.get('language') or 'N/A'}\n"
        f"Topics: {', '.join(str(t) for t in topics) if topics else 'N/A'}\n"
    )


def format_directory_tree(filtered_tree: list[dict], max_entries: int = 800) -> str:
    paths = sorted(item["path"] for item in filtered_tree)[:max_entries]
    lines = ["## Directory Structure"]

    for path in paths:
        depth = path.count("/")
        indent = "  " * depth
        lines.append(f"{indent}- {os.path.basename(path)} ({path})")

    if len(filtered_tree) > max_entries:
        lines.append(f"... ({len(filtered_tree) - max_entries} more files omitted)")

    return "\n".join(lines)


async def build_context(owner: str, repo: str, repo_info: dict, filtered_tree: list[dict]) -> str:
    context_parts: list[str] = []

    metadata_block = format_repo_metadata(repo_info)
    tree_block = format_directory_tree(filtered_tree)
    context_parts.append(metadata_block)
    context_parts.append(tree_block)

    current_tokens = count_tokens(metadata_block) + count_tokens(tree_block)

    prioritized = prioritize_files(filtered_tree)
    for entry in prioritized:
        if current_tokens >= MAX_CONTEXT_TOKENS:
            break

        path = entry["path"]
        content = await fetch_file_content(owner, repo, path)
        if not content:
            continue

        file_block = f"\n=== {path} ===\n{content}\n"
        file_tokens = count_tokens(file_block)
        remaining = MAX_CONTEXT_TOKENS - current_tokens

        if file_tokens > remaining:
            truncated = truncate_to_tokens(file_block, max(0, remaining - 40))
            if truncated.strip():
                context_parts.append(f"{truncated}\n... [truncated]")
            break

        context_parts.append(file_block)
        current_tokens += file_tokens

    return "\n".join(context_parts)
