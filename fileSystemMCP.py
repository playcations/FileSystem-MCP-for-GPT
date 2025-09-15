#!/usr/bin/env python3
"""
MCP Server with Codex-style tools
- Adds 'shell' (exec) and 'apply_patch' similar to Codex CLI behavior
- Keeps your search/fetch/write/create/delete tools
- Correct SSE behavior, CORS preflight, JSON-RPC error id echo
"""

import os
import sys
import json
import time
import shlex
import subprocess
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

PROTOCOL_VERSION = "2024-11-05"
# Reasonable execution limits for 'shell'
DEFAULT_TIMEOUT_SEC = 30
MAX_STDOUT_CHARS = 200_000
MAX_STDERR_CHARS = 200_000

class MCPSSEHandler(BaseHTTPRequestHandler):
    def __init__(self, allowed_directory: Path, *args, **kwargs):
        self.allowed_directory = allowed_directory
        super().__init__(*args, **kwargs)

    # -------- utilities --------
    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, status: int, payload: dict):
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    # -------- HTTP verbs --------
    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == "/sse/":
            self.handle_sse_connection()
        elif self.path == "/":
            self._send_json(200, {
                "jsonrpc": "2.0",
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "Local Filesystem Server", "version": "1.1.0"},
                },
            })
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        if self.path in ("/", "/sse/"):
            self.handle_mcp_message()
        else:
            self.send_error(404, "Not Found")

    # -------- SSE --------
    def handle_sse_connection(self):
        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        # Non-initialization notification
        self.send_sse_event("message", {
            "jsonrpc": "2.0",
            "method": "notifications/server/ready",
            "params": {"message": "SSE stream established"},
        })
        try:
            while True:
                time.sleep(30)
                self.send_sse_event("ping", {"type": "ping"})
        except Exception:
            pass

    def send_sse_event(self, event_type: str, data: dict):
        try:
            self.wfile.write(f"event: {event_type}\n".encode("utf-8"))
            self.wfile.write(f"data: {json.dumps(data)}\n\n".encode("utf-8"))
            self.wfile.flush()
        except Exception:
            pass

    # -------- JSON-RPC --------
    def handle_mcp_message(self):
        message = None
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length <= 0:
                self._send_json(400, {
                    "jsonrpc": "2.0", "id": None,
                    "error": {"code": -32600, "message": "No content"},
                })
                return
            raw = self.rfile.read(content_length).decode("utf-8")
            message = json.loads(raw)
            response = self.process_mcp_message(message)
            self._send_json(200, response)
        except Exception as e:
            msg_id = None
            try:
                msg_id = message.get("id")  # best effort
            except Exception:
                pass
            self._send_json(500, {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32603, "message": str(e)},
            })

    def process_mcp_message(self, message: dict) -> dict:
        method = message.get("method")
        params = message.get("params", {}) or {}
        msg_id = message.get("id")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "Local Filesystem Server", "version": "1.1.0"},
                },
            }

        elif method == "tools/list":
            # Expose Codex-like tools + your originals
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": [
                        # --- Codex-style tools ---
                        {
                            "name": "shell",
                            "description": "Execute shell commands within the allowed workspace (Codex-style)",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "command": {
                                        "oneOf": [
                                            {"type": "string", "description": "Command string (will be shlex-split)"},
                                            {"type": "array", "items": {"type": "string"}, "description": "Command argv"}
                                        ]
                                    },
                                    "workdir": {"type": "string", "description": "Working directory (relative or absolute within allowed root)"},
                                    "timeout": {"type": "integer", "description": "Timeout (seconds)"}
                                },
                                "required": ["command", "workdir"]
                            }
                        },
                        {
                            "name": "apply_patch",
                            "description": "Apply a multi-file patch in the common Codex '*** Begin Patch' format",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "patch": {"type": "string", "description": "Patch text (*** Begin Patch / *** Update File: path / *** End Patch)"},
                                },
                                "required": ["patch"]
                            }
                        },

                        # --- Filesystem tools you already had ---
                        {
                            "name": "search",
                            "description": "Search for files and directories",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string", "description": "Search query (empty = list root)"}
                                },
                                "required": ["query"]
                            }
                        },
                        {
                            "name": "fetch",
                            "description": "Fetch file or directory contents",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string", "description": "File or directory path"}
                                },
                                "required": ["id"]
                            }
                        },
                        {
                            "name": "write_file",
                            "description": "Write a UTF-8 text file (creates parents)",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string"},
                                    "content": {"type": "string"}
                                },
                                "required": ["path", "content"]
                            }
                        },
                        {
                            "name": "create_directory",
                            "description": "Create a directory (and parents)",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"path": {"type": "string"}},
                                "required": ["path"]
                            }
                        },
                        {
                            "name": "delete_file",
                            "description": "Delete a file or directory (recursive for directories)",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"path": {"type": "string"}},
                                "required": ["path"]
                            }
                        }
                    ]
                }
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {}) or {}
            try:
                if tool_name == "shell":
                    result = self.handle_shell(tool_args)
                elif tool_name == "apply_patch":
                    result = self.handle_apply_patch(tool_args.get("patch", ""))
                elif tool_name == "search":
                    result = self.handle_search(tool_args.get("query", ""))
                elif tool_name == "fetch":
                    result = self.handle_fetch(tool_args.get("id", ""))
                elif tool_name == "write_file":
                    result = self.handle_write_file(tool_args.get("path", ""), tool_args.get("content", ""))
                elif tool_name == "create_directory":
                    result = self.handle_create_directory(tool_args.get("path", ""))
                elif tool_name == "delete_file":
                    result = self.handle_delete_file(tool_args.get("path", ""))
                else:
                    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}}

                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2), "mimeType": "application/json"}
                        ]
                    }
                }
            except Exception as e:
                return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32000, "message": str(e)}}

        else:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}

    # -------- Codex-style tool impls --------
    def handle_shell(self, args: dict) -> dict:
        """
        Execute a shell command similar to Codex CLI's 'shell' tool:
        - command: str | [str]
        - workdir: required; must resolve inside allowed_directory
        - timeout: optional; default DEFAULT_TIMEOUT_SEC
        """
        if "command" not in args or "workdir" not in args:
            raise ValueError("shell requires 'command' and 'workdir'")

        # Resolve working directory safely
        workdir = self.validate_path(args.get("workdir", ""))
        if not workdir.exists() or not workdir.is_dir():
            raise ValueError(f"Invalid workdir: {workdir}")

        # Build argv
        cmd = args["command"]
        if isinstance(cmd, str):
            argv = shlex.split(cmd)
        elif isinstance(cmd, list):
            if not all(isinstance(x, str) for x in cmd):
                raise ValueError("command array must contain only strings")
            argv = cmd
        else:
            raise ValueError("command must be string or array of strings")
        if not argv:
            raise ValueError("command cannot be empty")

        # Enforce sandbox: only run inside allowed_directory
        if not str(workdir.resolve()).startswith(str(self.allowed_directory)):
            raise PermissionError("workdir outside allowed directory")

        timeout = int(args.get("timeout", DEFAULT_TIMEOUT_SEC))
        try:
            proc = subprocess.run(
                argv,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._restricted_env(),
            )
        except subprocess.TimeoutExpired as te:
            return {
                "ok": False,
                "exitCode": None,
                "timedOut": True,
                "stdout": (te.stdout or "")[:MAX_STDOUT_CHARS],
                "stderr": (te.stderr or f"Timed out after {timeout}s")[:MAX_STDERR_CHARS],
            }

        # Truncate outputs to keep responses manageable
        out = (proc.stdout or "")[:MAX_STDOUT_CHARS]
        err = (proc.stderr or "")[:MAX_STDERR_CHARS]
        return {"ok": proc.returncode == 0, "exitCode": proc.returncode, "timedOut": False, "stdout": out, "stderr": err}

    def handle_apply_patch(self, patch_text: str) -> dict:
        """
        Minimal 'apply_patch' compatible with Codex-style patches:

        Expected shape:
          *** Begin Patch
          *** Update File: path/to/file.ext
          <new file content...>
          *** End Patch

        Multiple *** Update File sections inside one Begin/End block are supported.
        We *overwrite* each file's content with the block's body. This mirrors how
        Codex agents commonly provide full-file replacements rather than hunks.
        """
        if not patch_text or "*** Begin Patch" not in patch_text:
            raise ValueError("Patch missing '*** Begin Patch'")

        updated = []
        begin = "*** Begin Patch"
        end = "*** End Patch"
        update_hdr = "*** Update File:"

        # We allow multiple Begin/End blocks; process each independently
        idx = 0
        while True:
            start = patch_text.find(begin, idx)
            if start == -1:
                break
            stop = patch_text.find(end, start)
            if stop == -1:
                raise ValueError("Unclosed patch block (missing '*** End Patch')")
            block = patch_text[start + len(begin):stop].strip("\n")
            idx = stop + len(end)

            # Parse all "*** Update File: <path>" sections in this block
            pos = 0
            while True:
                uh = block.find(update_hdr, pos)
                if uh == -1:
                    break
                # find next update or end
                next_uh = block.find(update_hdr, uh + len(update_hdr))
                file_block = block[uh: next_uh if next_uh != -1 else len(block)]
                # Extract path first line
                first_line_end = file_block.find("\n")
                if first_line_end == -1:
                    raise ValueError("Malformed update header (no newline after file path)")
                header = file_block[:first_line_end].strip()
                if not header.startswith(update_hdr):
                    raise ValueError("Malformed update header")
                rel_path = header[len(update_hdr):].strip()
                # remaining lines are the new file content
                new_content = file_block[first_line_end + 1:]
                # Write file safely
                file_path = self.validate_path(rel_path)
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(new_content, encoding="utf-8")
                updated.append(str(file_path.relative_to(self.allowed_directory)))
                pos = next_uh if next_uh != -1 else len(block)

        return {"success": True, "updated": updated}

    def _restricted_env(self):
        """Environment stripped down; PATH preserved for common tools."""
        env = os.environ.copy()
        # You can further lock this down—e.g., remove proxies/creds
        for k in list(env.keys()):
            if k.upper().startswith(("AWS_", "GCP_", "AZURE_", "DOCKER_", "KUBECONFIG", "SSH_")):
                env.pop(k, None)
        return env

    # -------- Filesystem tools --------
    def handle_search(self, query: str) -> dict:
        results = []
        q = (query or "").lower().strip()
        if not q:
            target = self.allowed_directory
            if target.exists() and target.is_dir():
                for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                    rel = item.relative_to(self.allowed_directory)
                    results.append({"id": str(rel), "title": f"{'[DIR] ' if item.is_dir() else ''}{item.name}", "url": f"file://{item.resolve()}"})
        else:
            for path in self.allowed_directory.rglob("*"):
                try:
                    rel = path.relative_to(self.allowed_directory)
                    if q in path.name.lower() or q in str(rel).lower():
                        results.append({"id": str(rel), "title": f"{'[DIR] ' if path.is_dir() else ''}{path.name}", "url": f"file://{path.resolve()}"})
                except Exception:
                    continue
        return {"results": results[:20]}

    def handle_fetch(self, file_id: str) -> dict:
        if not file_id:
            raise ValueError("File ID is required")
        path = self.validate_path(file_id)
        if not path.exists():
            raise ValueError(f"Not found: {file_id}")
        if path.is_dir():
            items = []
            for item in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                items.append(f"{'[DIR] ' if item.is_dir() else ''}{item.name}")
            content = f"Directory: {file_id}\n\nContents:\n" + "\n".join(items)
            return {"id": file_id, "title": path.name, "text": content, "url": f"file://{path.resolve()}", "metadata": {"type": "directory"}}
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("File too large (limit 1MB)")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = f"[Binary file: {path.suffix or 'unknown'}]"
        return {"id": file_id, "title": path.name, "text": text, "url": f"file://{path.resolve()}", "metadata": {"type": "file", "size": path.stat().st_size}}

    def handle_write_file(self, dest: str, content: str) -> dict:
        if not dest:
            raise ValueError("File path is required")
        path = self.validate_path(dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"success": True, "message": f"Wrote {len(content)} bytes to {dest}", "path": dest}

    def handle_create_directory(self, p: str) -> dict:
        if not p:
            raise ValueError("Directory path is required")
        path = self.validate_path(p)
        path.mkdir(parents=True, exist_ok=True)
        return {"success": True, "message": f"Created directory: {p}", "path": p}

    def handle_delete_file(self, p: str) -> dict:
        if not p:
            raise ValueError("Path is required")
        path = self.validate_path(p)
        if not path.exists():
            raise ValueError(f"Path does not exist: {p}")
        if path.is_dir():
            import shutil
            shutil.rmtree(path)
            return {"success": True, "message": f"Deleted directory: {p}", "path": p, "type": "directory"}
        path.unlink()
        return {"success": True, "message": f"Deleted file: {p}", "path": p, "type": "file"}

    # -------- security --------
    def validate_path(self, user_path: str) -> Path:
        abs_path = Path(user_path).resolve() if os.path.isabs(user_path) else (self.allowed_directory / user_path).resolve()
        if not str(abs_path).startswith(str(self.allowed_directory)):
            raise PermissionError("Path outside allowed directory")
        return abs_path


def create_handler(allowed_directory: Path):
    def handler(*args, **kwargs):
        return MCPSSEHandler(allowed_directory, *args, **kwargs)
    return handler


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 basic_mcp_server.py <directory_path>")
        sys.exit(1)

    allowed_directory = Path(sys.argv[1]).resolve()
    if not allowed_directory.exists() or not allowed_directory.is_dir():
        print(f"Error: {allowed_directory} is not a valid directory")
        sys.exit(1)

    print(f"Starting MCP server restricted to: {allowed_directory}")
    print("Server URL: http://localhost:8000")
    print("SSE URL for ChatGPT: http://localhost:8000/sse/")

    with HTTPServer(("localhost", 8000), create_handler(allowed_directory)) as server:
        print("Server started. Use Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped")


if __name__ == "__main__":
    main()
