# Setup recipes (shared)

Install recipes for tools many skills need, so a unit's [SETUP.md](../templates/SETUP.md.template) lists only what is particular to it. `evergreen.py setup` reads this book after the unit's own SETUP.md and the store's private book (`EVERGREEN_HOME/setup/RECIPES.md`). Grammar and rules: [protocol/SETUP.md](../protocol/SETUP.md).

This book is public. A recipe here names no person, host, drive or private path, and is written so it works for anyone on that environment. Add one with `evergreen.py setup <unit> --record <id> --env <key> --how "..." --to plugin` and send it upstream as a pull request (PROTOCOL.md §10). A recipe without a `verified` tag is the vendor's documented route, not yet run by an evergreen install; the first install that runs it re-records it with `--verified`. The winget package ids below were confirmed to exist with `winget show --id <id> -e` on 2026-10-02.

### python

- windows: `winget install --id Python.Python.3.13 -e`
- macos: `brew install python`
- linux/apt: `sudo apt-get install -y python3` (admin)
- linux/dnf: `sudo dnf install -y python3` (admin)
- any: download from https://www.python.org/downloads/ and tick "Add python.exe to PATH" on Windows (manual)

### git

- windows: `winget install --id Git.Git -e`
- macos: `xcode-select --install` (manual)
- brew: `brew install git`
- linux/apt: `sudo apt-get install -y git` (admin)
- linux/dnf: `sudo dnf install -y git` (admin)

### gh

- windows: `winget install --id GitHub.cli -e`
- brew: `brew install gh`
- linux: follow https://github.com/cli/cli/blob/trunk/docs/install_linux.md (the distribution packages lag; the official repository is current) (admin)
- any: then `gh auth login` in a terminal of your own; the agent never handles the token (manual, secret)

### node

- windows: `winget install --id OpenJS.NodeJS.LTS -e`
- brew: `brew install node`
- linux: follow https://nodejs.org/en/download (a version manager such as nvm or fnm avoids sudo) (manual)

### ffmpeg

- windows: `winget install --id Gyan.FFmpeg -e`
- brew: `brew install ffmpeg`
- linux/apt: `sudo apt-get install -y ffmpeg` (admin)
- linux/dnf: `sudo dnf install -y ffmpeg-free` (admin)

### ollama

- windows: `winget install --id Ollama.Ollama -e`
- macos: download the app from https://ollama.com/download (manual)
- linux: `curl -fsSL https://ollama.com/install.sh | sh` (admin)
- any: a model is a second step: `ollama pull <model>`; say its size first, models run to several gigabytes (large)

### uv

- windows: `winget install --id astral-sh.uv -e`
- brew: `brew install uv`
- linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- pipx: `pipx install uv`

### claude

- windows: `powershell -ExecutionPolicy ByPass -c "irm https://claude.ai/install.ps1 | iex"`
- macos: `curl -fsSL https://claude.ai/install.sh | bash`
- linux: `curl -fsSL https://claude.ai/install.sh | bash`
- npm: `npm install -g @anthropic-ai/claude-code`
- any: then run `claude` once and sign in (manual)
