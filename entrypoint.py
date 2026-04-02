"""Wrapper entrypoint for nanobanana MCP server with custom instructions."""

import os
from nanobanana_mcp_server.server import main, create_wrapper_app, NanoBananaMCP

# Patch NanoBananaMCP.run to inject custom instructions before starting
_original_run = NanoBananaMCP.run

def _patched_run(self):
    host_output_dir = os.environ.get("HOST_OUTPUT_DIR", "c:/tmp")
    extra = (
        f"\n\n## File output behavior\n"
        f"Generated images are saved inside the Docker container at /output, "
        f"which is volume-mounted to the host path: {host_output_dir}\n"
        f"After every image generation, ALWAYS copy the file from "
        f"`{host_output_dir}/<filename>` to the user's current working directory. "
        f"Do not ask for confirmation; just do it automatically."
    )
    self.server.instructions = (self.server.instructions or "") + extra
    _original_run(self)

NanoBananaMCP.run = _patched_run
main()
