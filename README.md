# nanobanana-mcp-docker

Docker image for [Nano Banana MCP server](https://github.com/ConechoAI/Nano-Banana-MCP) with custom entrypoint that injects file output instructions into the MCP protocol.

## What this does

The upstream nanobanana MCP server generates images inside the Docker container. This wrapper adds MCP `instructions` telling the AI agent to automatically copy generated files from the host-mounted output directory to the user's working directory.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Google Gemini API key |
| `HOST_OUTPUT_DIR` | No | Host path where `/output` is mounted (default: `c:/tmp`) |
| `IMAGE_OUTPUT_DIR` | No | Container-internal output path (default: `/output`) |
| `LOG_LEVEL` | No | Log level (default: `INFO`) |

## Usage with Claude Code

### .mcp.json

```json
{
  "mcpServers": {
    "nanobanana": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "c:/tmp:/output",
        "-e", "GEMINI_API_KEY",
        "-e", "LOG_LEVEL=ERROR",
        "-e", "IMAGE_OUTPUT_DIR=/output",
        "-e", "HOST_OUTPUT_DIR",
        "hasshi7965/nanobanana-mcp"
      ],
      "type": "stdio"
    }
  }
}
```

### settings.json

Set `GEMINI_API_KEY` and `HOST_OUTPUT_DIR` in the `env` section:

```json
{
  "env": {
    "GEMINI_API_KEY": "your-gemini-api-key",
    "HOST_OUTPUT_DIR": "c:/tmp"
  }
}
```

## Build

```bash
docker build -t hasshi7965/nanobanana-mcp .
docker push hasshi7965/nanobanana-mcp
```
