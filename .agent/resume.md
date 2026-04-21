# Current task
Mirror nanobanana MCP implementation to AWS Lambda

# Goal
Users can use nanobanana-mcp as a remote MCP server hosted on AWS Lambda, with no
per-machine Docker/stdio setup. Claude Code connects via `"type": "http"` + URL +
bearer token. Existing Docker/stdio setup is preserved (not replaced).

# Done
- Investigated upstream nanobanana-mcp-server: confirmed FASTMCP_TRANSPORT=http supported.
- Confirmed FastMCP 3.2 http_app(stateless_http=True, json_response=True) returns a
  Starlette ASGI app suitable for Lambda (no SSE streaming required).
- Confirmed images are returned as inline MCP content blocks so S3 is not required;
  use /tmp/nanobanana as scratch IMAGE_OUTPUT_DIR on Lambda.
- Created branch feat/aws-lambda-deployment.

# Next
- Write lambda/app.py (Mangum + Starlette app + bearer-auth middleware).
- Write lambda/Dockerfile (public.ecr.aws/lambda/python:3.12 base, installs
  nanobanana-mcp-server + mangum).
- Write infra/template.yaml (AWS SAM: Lambda container image + Function URL +
  memory/timeout tuned for image generation).
- Add lambda/README.md with deploy + client-config snippet.
- Verify by running `sam build` locally once SAM CLI present (user may deploy).

# Waiting
User may need to:
  1. have AWS credentials + SAM CLI installed
  2. choose bearer token value (generated during deploy)
  3. set GEMINI_API_KEY as Lambda env var (do not bake into image)
Non-blocking - we can ship all infra code without AWS access.

# Risks
- Lambda cold start ~2-5s for container image; first MCP call will be slow.
- Gemini image generation can take 30-90s; Lambda timeout must be >=120s.
- Bearer token via env var is the only practical MCP client auth; document that
  the Function URL is otherwise public.
- Stateless HTTP MCP: every request is a fresh session, so any tool that relies
  on server-side session state will break. nanobanana tools are single-shot so
  this is fine.

# Resume instruction
Continue by implementing lambda/ and infra/ files per the Next list. Keep the
existing Docker/stdio path intact. If user reports issues with Mangum + FastMCP
ASGI streaming, fall back to non-stream json_response=True (already the plan).
After implementation, commit per file-group milestone and push to
feat/aws-lambda-deployment.
