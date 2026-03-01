# Plan & Pseudocode: GitHub Repo Summarizer API

## 📋 Assignment Summary

Build a **FastAPI** service with a single `POST /summarize` endpoint that:
1. Accepts a GitHub repo URL
2. Fetches & intelligently filters the repo contents
3. Sends the most relevant content to an LLM
4. Returns a structured summary (summary, technologies, structure)

---

## 🏗️ Architecture Overview

```
Request (github_url)
    │
    ▼
┌──────────────┐
│  FastAPI App  │
│  /summarize   │
└──────┬───────┘
       │
       ▼
┌──────────────────┐
│  GitHub Fetcher   │  ← Uses GitHub API (or git clone)
│  (fetch repo tree │
│   + file contents)│
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│  Repo Processor   │  ← Filter, prioritize, truncate
│  (smart filtering │
│   & context mgmt) │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│  LLM Summarizer   │  ← Nebius Token Factory / OpenAI-compatible
│  (prompt + call)   │
└──────┬───────────┘
       │
       ▼
  Structured JSON Response
```

---

## 📁 Project Structure

```
project/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, endpoint definition
│   ├── github_fetcher.py    # Fetch repo tree & file contents from GitHub API
│   ├── repo_processor.py    # Filter files, prioritize, build context
│   ├── llm_client.py        # LLM API call wrapper
│   ├── prompt.py            # Prompt templates
│   └── models.py            # Pydantic request/response models
├── requirements.txt
├── README.md
└── .env.example
```

---

## 📦 Dependencies

```
fastapi
uvicorn
httpx            # async HTTP client (for GitHub API + LLM API)
pydantic
python-dotenv    # optional, for local .env loading
tiktoken         # optional, for token counting
```

---

## 🔧 Module-by-Module Pseudocode

### 1. `models.py` — Request/Response Schemas

```python
from pydantic import BaseModel, HttpUrl

class SummarizeRequest(BaseModel):
    github_url: str  # e.g. "https://github.com/psf/requests"

class SummarizeResponse(BaseModel):
    summary: str
    technologies: list[str]
    structure: str

class ErrorResponse(BaseModel):
    status: str = "error"
    message: str
```

### 2. `github_fetcher.py` — Fetch Repo Contents via GitHub API

**Strategy:** Use the GitHub REST API (no auth required for public repos, but rate-limited to 60 req/hr). Use the **Git Trees API** to get the full file tree in one call, then selectively fetch individual files.

```python
import httpx

def parse_github_url(url: str) -> tuple[str, str]:
    """
    Extract owner and repo name from URL.
    Handles: https://github.com/owner/repo[.git][/...]
    Raises ValueError if URL is not a valid GitHub repo URL.
    """
    # strip trailing slashes, .git suffix
    # parse path segments → (owner, repo)

async def fetch_repo_tree(owner: str, repo: str) -> dict:
    """
    GET https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1
    
    Steps:
    1. First call GET /repos/{owner}/{repo} to get default_branch name + metadata
    2. Then call the trees endpoint with ?recursive=1 to get full file listing
    
    Returns: {
        "repo_info": { name, description, language, topics, ... },
        "tree": [ { "path": "src/main.py", "type": "blob", "size": 1234 }, ... ]
    }
    """

async def fetch_file_content(owner: str, repo: str, path: str) -> str:
    """
    GET https://api.github.com/repos/{owner}/{repo}/contents/{path}
    
    Returns decoded file content (base64 → utf-8 text).
    Returns None if file is binary or too large.
    """

async def fetch_raw_file(owner: str, repo: str, branch: str, path: str) -> str:
    """
    Alternative: fetch from raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}
    Faster, no base64 decoding needed. Good for large files.
    """
```

**Rate limit note:** GitHub API without auth = 60 requests/hour. Consider:
- Using a `GITHUB_TOKEN` env var (optional) for 5000 req/hr
- Batching file fetches smartly (only fetch what we need)

### 3. `repo_processor.py` — The Core Logic (Key Challenge!)

This is where the interesting decisions happen. The goal is to build the **best possible context** for the LLM within token limits.

```python
# ---- CONFIGURATION ----
MAX_CONTEXT_TOKENS = 12_000  # leave room for prompt + response (~16K model)
                              # adjust based on chosen model's context window

# ---- FILE FILTERING ----

SKIP_DIRECTORIES = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "env", ".env", "dist", "build", ".next", ".nuxt",
    "vendor", ".idea", ".vscode", "coverage", ".tox",
    ".mypy_cache", ".pytest_cache", "egg-info",
    ".github/workflows",  # keep .github but skip workflows
}

SKIP_EXTENSIONS = {
    # Binary / media
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".woff", ".woff2", ".ttf", ".eot",
    ".exe", ".dll", ".so", ".dylib", ".o", ".a",
    ".pyc", ".pyo", ".class", ".jar",
    # Lock / generated
    ".lock", ".sum",
    ".min.js", ".min.css",
    ".map",
}

SKIP_FILENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Pipfile.lock", "poetry.lock", "composer.lock",
    "Gemfile.lock", "go.sum",
    ".DS_Store", "Thumbs.db",
    ".gitignore", ".gitattributes",
    ".eslintcache",
}

# ---- FILE PRIORITIZATION ----
# Priority tiers (lower number = higher priority)

PRIORITY_TIER_1 = [  # Always include — most informative
    "README.md", "README.rst", "README.txt", "README",
]

PRIORITY_TIER_2 = [  # Config / metadata — reveals tech stack
    "package.json", "pyproject.toml", "setup.py", "setup.cfg",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle",
    "Gemfile", "composer.json", "Makefile", "Dockerfile",
    "docker-compose.yml", "docker-compose.yaml",
    ".env.example", "requirements.txt",
    "tsconfig.json", "webpack.config.js", "vite.config.ts",
]

PRIORITY_TIER_3 = [  # Entry points / main files (by convention)
    "main.py", "app.py", "index.py", "server.py",
    "main.ts", "index.ts", "app.ts",
    "main.js", "index.js", "app.js",
    "main.go", "main.rs", "Main.java",
    "lib.rs", "mod.rs",
]

# ---- PROCESSING PIPELINE ----

def filter_tree(tree: list[dict]) -> list[dict]:
    """
    Remove files that match skip rules.
    Returns filtered list of file entries.
    """
    filtered = []
    for item in tree:
        if item["type"] != "blob":
            continue
        path = item["path"]
        filename = os.path.basename(path)
        directory_parts = set(Path(path).parts[:-1])
        
        # Skip if in excluded directory
        if directory_parts & SKIP_DIRECTORIES:
            continue
        # Skip by extension
        if any(path.endswith(ext) for ext in SKIP_EXTENSIONS):
            continue
        # Skip by exact filename
        if filename in SKIP_FILENAMES:
            continue
        # Skip very large files (>100KB likely not useful)
        if item.get("size", 0) > 100_000:
            continue
            
        filtered.append(item)
    return filtered

def prioritize_files(filtered_tree: list[dict]) -> list[dict]:
    """
    Sort files by importance. Return ordered list.
    
    Priority logic:
    1. README files
    2. Config / manifest files (package.json, pyproject.toml, etc.)
    3. Entry point files (main.py, index.js, etc.)
    4. Source files in root or src/ directory (shallow depth first)
    5. Everything else by path depth (shallower = more important)
    """
    def priority_score(item):
        filename = os.path.basename(item["path"])
        depth = item["path"].count("/")
        
        if filename.upper().startswith("README"):
            return (0, depth, filename)
        if filename in PRIORITY_TIER_2:
            return (1, depth, filename)
        if filename in PRIORITY_TIER_3:
            return (2, depth, filename)
        # Source files — prefer shallow
        return (3, depth, filename)
    
    return sorted(filtered_tree, key=priority_score)

async def build_context(owner, repo, repo_info, tree) -> str:
    """
    Build the text context to send to the LLM.
    
    Structure of context:
    ───────────────────
    ## Repository Info
    Name: {name}
    Description: {description}
    Primary Language: {language}
    Topics: {topics}
    
    ## Directory Structure
    (formatted tree of ALL filtered files — cheap in tokens, very informative)
    
    ## Key File Contents
    === README.md ===
    (full content)
    
    === package.json ===
    (full content)
    
    === src/main.py ===
    (truncated if needed)
    ...
    ───────────────────
    
    Algorithm:
    1. Start with repo info block
    2. Add directory tree (just paths, indented)
    3. Fetch & add files in priority order
    4. After each file, check token count
    5. Stop adding files when approaching MAX_CONTEXT_TOKENS
    6. For the last file that would exceed limit → truncate it
    """
    context_parts = []
    current_tokens = 0
    
    # Part 1: Repo metadata (small, always include)
    metadata_block = format_repo_metadata(repo_info)
    context_parts.append(metadata_block)
    current_tokens += count_tokens(metadata_block)
    
    # Part 2: Directory tree (file paths only — very token-efficient)
    tree_block = format_directory_tree(tree)
    context_parts.append(tree_block)
    current_tokens += count_tokens(tree_block)
    
    # Part 3: File contents in priority order
    prioritized = prioritize_files(tree)
    
    for file_entry in prioritized:
        if current_tokens >= MAX_CONTEXT_TOKENS:
            break
        
        content = await fetch_file_content(owner, repo, file_entry["path"])
        if content is None:
            continue  # binary or fetch failed
        
        file_block = f"\n=== {file_entry['path']} ===\n{content}\n"
        file_tokens = count_tokens(file_block)
        
        remaining = MAX_CONTEXT_TOKENS - current_tokens
        if file_tokens > remaining:
            # Truncate this file to fit
            file_block = truncate_to_tokens(file_block, remaining - 50)
            file_block += "\n... [truncated]"
        
        context_parts.append(file_block)
        current_tokens += count_tokens(file_block)
    
    return "\n".join(context_parts)


def count_tokens(text: str) -> int:
    """
    Approximate token count. Options:
    - Use tiktoken (accurate for OpenAI-compatible models)
    - Simple heuristic: len(text) / 4 (rough but works)
    """

def format_directory_tree(tree: list[dict]) -> str:
    """
    Format the file tree as an indented directory listing.
    Example:
        src/
            main.py
            utils/
                helpers.py
        tests/
            test_main.py
        README.md
        pyproject.toml
    """
```

### 4. `prompt.py` — Prompt Engineering

```python
SYSTEM_PROMPT = """You are a senior software engineer analyzing a GitHub repository.
You will receive repository metadata, its directory structure, and contents of key files.
Your job is to produce a structured summary of the project.

Respond ONLY with valid JSON in this exact format:
{
  "summary": "A clear, human-readable description of what this project does, its purpose, and key features. 2-4 sentences.",
  "technologies": ["List", "of", "main", "technologies", "languages", "frameworks", "libraries"],
  "structure": "A brief description of how the project is organized — main directories and their purposes. 1-3 sentences."
}

Guidelines:
- For "summary": Focus on WHAT the project does and WHY someone would use it. Be specific, not generic.
- For "technologies": Include the primary programming language(s), major frameworks, key dependencies. Don't list every tiny utility — focus on the important ones. Typically 3-10 items.
- For "structure": Describe the high-level layout. Mention key directories and what they contain.
- Base your analysis on the actual code and files provided, not assumptions.
"""

USER_PROMPT_TEMPLATE = """Analyze the following GitHub repository and provide a structured summary.

{context}

Remember: respond with ONLY valid JSON containing "summary", "technologies", and "structure" fields."""
```

### 5. `llm_client.py` — LLM API Wrapper

```python
import httpx
import os
import json

# Nebius Token Factory uses OpenAI-compatible API
NEBIUS_API_BASE = "https://api.studio.nebius.com/v1"
# or alternative: OpenAI, Anthropic, etc.

async def call_llm(system_prompt: str, user_prompt: str) -> dict:
    """
    Call the LLM API and parse the JSON response.
    
    Steps:
    1. Build the request payload
    2. POST to /chat/completions (OpenAI-compatible endpoint)
    3. Extract the response text
    4. Parse JSON from response
    5. Validate expected fields exist
    """
    api_key = os.environ.get("NEBIUS_API_KEY")
    if not api_key:
        raise ValueError("NEBIUS_API_KEY environment variable not set")
    
    payload = {
        "model": "meta-llama/Meta-Llama-3.1-70B-Instruct",  # or chosen model
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,       # low temp for factual/structured output
        "max_tokens": 1500,
        "response_format": {"type": "json_object"},  # if supported
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{NEBIUS_API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
    
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    
    # Parse JSON from LLM response (handle possible markdown fences)
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    
    result = json.loads(content)
    
    # Validate fields
    assert "summary" in result
    assert "technologies" in result
    assert "structure" in result
    
    return result
```

### 6. `main.py` — FastAPI Application

```python
from fastapi import FastAPI, HTTPException
from models import SummarizeRequest, SummarizeResponse, ErrorResponse

app = FastAPI(title="GitHub Repo Summarizer")

@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(request: SummarizeRequest):
    try:
        # 1. Parse & validate GitHub URL
        owner, repo = parse_github_url(request.github_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"status": "error", "message": str(e)})
    
    try:
        # 2. Fetch repo tree & metadata
        repo_info, tree = await fetch_repo_tree(owner, repo)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(404, {"status": "error", "message": "Repository not found"})
        elif e.response.status_code == 403:
            raise HTTPException(403, {"status": "error", "message": "GitHub API rate limit exceeded"})
        raise HTTPException(502, {"status": "error", "message": "Failed to fetch repository"})
    
    try:
        # 3. Filter & build context
        filtered_tree = filter_tree(tree)
        if not filtered_tree:
            raise HTTPException(400, {"status": "error", "message": "Repository appears empty"})
        
        context = await build_context(owner, repo, repo_info, filtered_tree)
    except Exception as e:
        raise HTTPException(500, {"status": "error", "message": f"Error processing repository: {e}"})
    
    try:
        # 4. Call LLM
        result = await call_llm(SYSTEM_PROMPT, USER_PROMPT_TEMPLATE.format(context=context))
        return SummarizeResponse(**result)
    except json.JSONDecodeError:
        raise HTTPException(502, {"status": "error", "message": "LLM returned invalid JSON"})
    except Exception as e:
        raise HTTPException(502, {"status": "error", "message": f"LLM error: {e}"})


# Entry point
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

## 🧠 Key Design Decisions (for README)

### Model Choice
**Meta-Llama-3.1-70B-Instruct** (via Nebius Token Factory) — good balance of quality and cost. Large enough to produce accurate summaries, instruction-tuned for structured output. Alternative: any model available on Nebius with ≥8K context window.

### Repo Processing Strategy
1. **Directory tree first** — Always include the full filtered file tree. It's cheap (tokens) and gives the LLM a bird's-eye view of the project structure.
2. **Priority-based file selection** — README → config/manifest → entry points → source files (shallow first). This mimics how a human developer would explore an unfamiliar repo.
3. **Skip noise** — Binary files, lock files, `node_modules/`, build outputs, caches, etc.
4. **Token budget** — Track token count as we add files; truncate/stop when approaching the limit.
5. **Graceful degradation** — For huge repos, we still get README + configs + tree, which is usually enough for a good summary.

---

## ⚠️ Error Handling Checklist

| Scenario | HTTP Code | Handling |
|---|---|---|
| Invalid URL (not GitHub) | 400 | Validate URL format before fetching |
| Repo not found / private | 404 | Catch 404 from GitHub API |
| GitHub rate limit hit | 403/429 | Return meaningful error message |
| Empty repository | 400 | Check if tree is empty |
| LLM API key missing | 500 | Check env var on startup or request |
| LLM returns invalid JSON | 502 | Retry once, then return error |
| LLM timeout | 504 | Set reasonable timeout (60s) |
| Network errors | 502 | Catch connection errors |

---

## 🚀 Optional Enhancements (if time permits)

1. **Caching** — Cache GitHub API responses (in-memory or Redis) to avoid re-fetching
2. **GitHub Token** — Support optional `GITHUB_TOKEN` env var for higher rate limits
3. **Retry logic** — Retry LLM calls on transient failures
4. **Streaming** — Stream LLM response for faster perceived latency
5. **Multiple LLM calls** — For very large repos, summarize sections separately then combine
6. **Language detection** — Use GitHub API's language stats to inform the summary

---

## 🏃 Estimated Implementation Time

| Phase | Time |
|---|---|
| Project setup + models | 15 min |
| GitHub fetcher | 45 min |
| Repo processor (filtering + context) | 60 min |
| LLM client + prompt | 30 min |
| FastAPI endpoint + error handling | 30 min |
| Testing + debugging | 45 min |
| README + docs | 20 min |
| **Total** | **~4 hours** |
