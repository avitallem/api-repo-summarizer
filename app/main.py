from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.errors import AppError
from app.github_fetcher import fetch_repo_tree, parse_github_url
from app.llm_client import call_llm
from app.models import ErrorResponse, SummarizeRequest, SummarizeResponse
from app.prompt import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from app.repo_processor import build_context, filter_tree

app = FastAPI(title="GitHub Repo Summarizer", version="1.0.0")


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(message=exc.message).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    message = exc.errors()[0].get("msg", "Invalid request") if exc.errors() else "Invalid request"
    return JSONResponse(
        status_code=400,
        content=ErrorResponse(message=message).model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(message="Internal server error").model_dump(),
    )


@app.post(
    "/summarize",
    response_model=SummarizeResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 500: {"model": ErrorResponse}, 502: {"model": ErrorResponse}, 504: {"model": ErrorResponse}},
)
async def summarize(request: SummarizeRequest) -> SummarizeResponse:
    owner, repo = parse_github_url(request.github_url)
    repo_info, tree, _default_branch = await fetch_repo_tree(owner, repo)

    filtered_tree = filter_tree(tree)
    if not filtered_tree:
        raise AppError(400, "Repository appears empty or contains no analyzable text files")

    context = await build_context(owner, repo, repo_info, filtered_tree)
    if not context.strip():
        raise AppError(400, "Repository appears empty or unreadable")

    result = await call_llm(SYSTEM_PROMPT, USER_PROMPT_TEMPLATE.format(context=context))
    return SummarizeResponse(**result)
