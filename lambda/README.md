# nanobanana-mcp on AWS Lambda

Runs the same [nanobanana MCP server](https://github.com/ConechoAI/Nano-Banana-MCP)
behind a Lambda Function URL so Claude Code (or any HTTP MCP client) can use it
without a local Docker install.

## Architecture

```
Claude Code  ──HTTPS──▶  Lambda Function URL  ──▶  Lambda container
  type: http                  (AuthType: NONE)         nanobanana_mcp_server
  Authorization: Bearer <token>                        (FastMCP http, stateless)
                                                       IMAGE_OUTPUT_DIR=/tmp
                                                             │
                                                             ▼
                                                       Google Gemini API
```

Key differences from the Docker/stdio image:

| Concern | Docker image | Lambda |
|---|---|---|
| Transport | stdio (spawned by Claude) | Streamable HTTP (stateless, JSON mode) |
| Output files | `/output` bind-mounted to host | `/tmp/nanobanana` on Lambda, returned inline as MCP image blocks |
| Auth | none (local spawn) | bearer token (`MCP_AUTH_TOKEN`) |
| Startup | `docker run -i ...` | cold start ~2-5s, then warm |

Because images come back inline as MCP content blocks, there is no host-copy step
to inject into `instructions`; Claude Code receives the image directly.

## Prerequisites

- AWS account + credentials (`aws configure` or env vars)
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html)
- Docker (used by `sam build` to produce the image)
- `GEMINI_API_KEY`

## WSL2 + Docker Desktop note

On WSL2 with Docker Desktop, `~/.docker/config.json` often carries
`"credsStore": "desktop.exe"` which breaks `sam build`/`sam deploy` (they
invoke the Python Docker SDK from inside WSL, which can't launch the Windows
helper). Work around it by pointing SAM at an isolated, empty Docker config
directory — do this once per shell:

```bash
mkdir -p ~/.docker-sam
echo '{}' > ~/.docker-sam/config.json
export DOCKER_CONFIG=~/.docker-sam   # or prefix every sam command
```

The snippets below assume `DOCKER_CONFIG` is exported. Drop the line on
Linux/macOS without Docker Desktop.

## Deploy

```bash
cd infra

# one-time ECR repo + bucket bootstrap is handled by --resolve-image-repos
sam build

sam deploy --guided \
  --parameter-overrides \
    GeminiApiKey=YOUR_GEMINI_KEY \
    McpAuthToken=$(openssl rand -hex 32)
```

On success the stack prints `FunctionUrl`, e.g.
`https://abcd1234.lambda-url.ap-northeast-1.on.aws/`.

Re-deploying after code changes:

```bash
cd infra
sam build && sam deploy
```

## Client config (Claude Code)

`.mcp.json`:

```json
{
  "mcpServers": {
    "nanobanana": {
      "type": "http",
      "url": "https://abcd1234.lambda-url.ap-northeast-1.on.aws/mcp",
      "headers": {
        "Authorization": "Bearer PASTE_MCP_AUTH_TOKEN_HERE"
      }
    }
  }
}
```

Claude Code's `settings.json` `env` section is **not** used for the remote
variant — there is no `GEMINI_API_KEY` or `HOST_OUTPUT_DIR` to set on the
client. Everything lives in the Lambda env.

## Smoke test

```bash
URL="https://abcd1234.lambda-url.ap-northeast-1.on.aws/mcp"
TOKEN="..."

curl -sS -X POST "$URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

Expect a JSON list of tools (generate_image, upload_file, output_stats,
maintenance).

## Local end-to-end test

`sam local start-api` can run the container locally against Docker:

```bash
cd infra
sam local start-api \
  --parameter-overrides \
    GeminiApiKey=YOUR_KEY \
    McpAuthToken=local-dev-token
```

Then point a client at `http://127.0.0.1:3000/mcp` with the same bearer.

## Costs / limits

- **Memory**: default 2048 MB — tune via `MemorySize` param.
- **Timeout**: default 180 s — Gemini Pro 4K gen can approach 90 s; leave headroom.
- **Cold start**: container images start slower than zip; first request after
  idle is ~2-5 s before the actual tool call runs.
- **Concurrency**: no reserved concurrency is set. If you want to cap spend add
  `ReservedConcurrentExecutions` in the template.

## Teardown

```bash
cd infra
sam delete
```
