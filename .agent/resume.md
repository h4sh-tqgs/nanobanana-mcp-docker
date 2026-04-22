# Current task
Mirror nanobanana MCP implementation to AWS Lambda (DONE)

# Goal
Users can use nanobanana-mcp as a remote MCP server hosted on AWS Lambda, with no
per-machine Docker/stdio setup. Claude Code connects via `"type": "http"` + URL +
bearer token. Existing Docker/stdio setup is preserved.

# Done
- Investigated upstream nanobanana-mcp-server: FASTMCP_TRANSPORT=http supported.
- Confirmed FastMCP 3.2 http_app(stateless_http=True, json_response=True) works for
  Lambda (no SSE streaming needed; single JSON request/response).
- Confirmed images come back as inline MCP content blocks (no S3 needed).
- lambda/app.py (Mangum + Starlette bearer-auth middleware, hmac.compare_digest).
- lambda/Dockerfile (public.ecr.aws/lambda/python:3.12 base).
- infra/template.yaml (SAM: container function + Function URL NONE-auth + CORS *).
- lambda/README.md with deploy + client-config + WSL2 DOCKER_CONFIG note.
- Verified locally via Lambda RIE: tools/list = 200, bad-auth = 401.
- Created IAM user `nanobanana-deployer` with AdministratorAccess, switched from
  root keys to IAM user keys.
- Worked around WSL2 Docker Desktop credsStore issue by pointing
  DOCKER_CONFIG=~/.docker-sam (empty config) for SAM builds/deploys.
- `sam build` + `sam deploy --guided` succeeded on ap-northeast-1.
- Live Function URL returns full tools/list over HTTPS with bearer auth.

# Next
- User pastes FunctionUrl + bearer token into their `.mcp.json` under
  `{"type":"http","url":".../mcp","headers":{"Authorization":"Bearer ..."}}`.
- Optional: revoke root access keys in AWS console (local backup already
  cleaned up per instructions).
- Optional: open PR from feat/aws-lambda-deployment into main once user confirms
  Claude Code successfully consumes the remote server.
- Optional cost guardrail: add ReservedConcurrentExecutions or a CloudWatch
  billing alarm if the user wants hard spend caps.

# Waiting
none

# Risks
- Bearer token is the only auth in front of the Function URL. If the token
  leaks, anyone can invoke the Lambda and burn Gemini API quota. Rotate by
  redeploying with a new McpAuthToken value.
- Root access keys should be disabled in the AWS console (manual step, CLI
  cannot touch own root keys).
- Lambda cold start for container images is ~2-5s; Gemini Pro 4K gen can
  approach 90s. Timeout set to 180s in template.yaml — raise if users see
  timeouts.

# Resume instruction
Implementation and deployment are complete. If the user comes back for
changes: edit lambda/app.py or infra/template.yaml, then from the infra/
directory run `DOCKER_CONFIG=~/.docker-sam sam build && DOCKER_CONFIG=~/.docker-sam sam deploy`.
samconfig.toml (gitignored) already has stack name / region / parameters so
subsequent deploys don't need --guided. For teardown run
`DOCKER_CONFIG=~/.docker-sam sam delete` from infra/.
