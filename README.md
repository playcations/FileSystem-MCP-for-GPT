
# MCP Filesystem + Codex-Style Server

This is a **Model Context Protocol (MCP) server** that exposes a set of tools for interacting with your local filesystem and running Codex-style developer workflows.

It supports **basic file management**, **patch application**, and **shell execution** inside a sandboxed directory, making it compatible with ChatGPT configured as an MCP server.

---

## 🚀 Features & Tools

### Codex-Style Tools

* **`shell`** – Execute shell commands in a sandboxed directory.
* **`apply_patch`** – Apply Codex-style multi-file patches (`*** Begin Patch` / `*** Update File:` / `*** End Patch`).

### Filesystem Tools

* **`search`** – Search for files or list the root directory.
* **`fetch`** – Fetch file contents or list directory contents.
* **`write_file`** – Write a UTF-8 text file (creates parent dirs if needed).
* **`create_directory`** – Create a directory (with parents).
* **`delete_file`** – Delete a file or directory (recursive).

---

## How to use


## 📦 Installation

Clone this repo and make the script executable:

```bash
git clone <your-repo-url>
cd <your-repo>
chmod +x fileSystemMCP.py
```

Requires **Python 3.9+** (tested on 3.10/3.11).

No third-party dependencies are required (uses only the Python standard library).

---

## ▶️ Running the Server

Run the server, restricted to a chosen working directory:

```bash
pip install fastmcp
python3 fileSystemMCP.py /path/to/your/workspace
```

Example:

```bash
python3 fileSystemMCP.py ~/projects/demo
```

You’ll see:

```
Starting MCP server restricted to: /Users/you/projects/demo
Server URL: http://localhost:8000
SSE URL for ChatGPT: http://localhost:8000/sse/
Server started. Use Ctrl+C to stop.
```

---


### 🌐 Exposing the Server to the Web

To use this as an MCP server with **ChatGPT** (or other cloud-based clients), you need to make it accessible from the internet. The easiest way is with [ngrok](https://ngrok.com/):

1. [Install ngrok](https://ngrok.com/download) and log in.

2. Forward your local server:

   ```bash
   ngrok http 8000
   ```

3. You’ll see an HTTPS forwarding URL, e.g.:

   ```
   Forwarding https://88952b488500.ngrok-free.app -> http://localhost:8000
   ```

   Your server is now publicly reachable at that URL.

---

### 🔗 Linking with ChatGPT as an MCP Server

1. Open ChatGPT settings → **Custom MCP Servers**.
2. Add a new MCP server with:

   * **Name**: `filesystem`
   * **URL**: the ngrok HTTPS URL (e.g. `https://88952b488500.ngrok-free.app/sse/`)
   * **Capabilities**: leave defaults.
3. Save and enable.

ChatGPT will now handshake with your MCP server and discover all 7 tools.

---


## Tools

### 🔧 Codex-style AI tools

1. **`shell`**
   Execute shell commands within the allowed workspace.

   * **Arguments**:

     * `command`: string or array of strings
     * `workdir`: working directory (relative or absolute inside allowed root)
     * `timeout`: optional integer (seconds)
   * **Returns**: exit code, stdout, stderr, timeout flag (mirrors Codex CLI behavior).

2. **`apply_patch`**
   Apply a multi-file patch in the Codex `*** Begin Patch` / `*** Update File: <path>` / `*** End Patch` format.

   * **Arguments**:

     * `patch`: string containing one or more patch blocks
   * **Returns**: list of updated file paths.

---

### 📁 Filesystem tools

3. **`search`**
   Search for files and directories (or list root if query is empty).

   * **Arguments**:

     * `query`: string
   * **Returns**: up to 20 matches with `id`, `title`, `url`.

4. **`fetch`**
   Fetch file contents or list directory contents.

   * **Arguments**:

     * `id`: file or directory path (relative or absolute inside allowed root)
   * **Returns**: file text (if <1 MB) or directory listing, plus metadata.

5. **`write_file`**
   Write a UTF-8 text file, creating parent directories if needed.

   * **Arguments**:

     * `path`: file path
     * `content`: string
   * **Returns**: confirmation with size written.

6. **`create_directory`**
   Create a directory (and parents) inside allowed root.

   * **Arguments**:

     * `path`: directory path
   * **Returns**: confirmation with path.

7. **`delete_file`**
   Delete a file or a directory (recursively).

   * **Arguments**:

     * `path`: path to file/directory
   * **Returns**: confirmation with type of deleted item.

---

✅ That gives you **7 tools in total**:

* `shell`
* `apply_patch`
* `search`
* `fetch`
* `write_file`
* `create_directory`
* `delete_file`

Would you like me to also extend this with the optional **`web_search`** tool Codex sometimes offered (behind a flag), or keep it strictly to these?
