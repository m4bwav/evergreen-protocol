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
- linux: `curl -fsSL -o ollama-install.sh https://ollama.com/install.sh` then `sh ollama-install.sh` (admin)
- any: a model is a second step: `ollama pull <model>`; say its size first, models run to several gigabytes (large)

### uv

- windows: `winget install --id astral-sh.uv -e`
- brew: `brew install uv`
- linux: `curl -LsSf -o uv-install.sh https://astral.sh/uv/install.sh` then `sh uv-install.sh`
- pipx: `pipx install uv`

### claude

- windows: `powershell -c "irm https://claude.ai/install.ps1 -OutFile claude-install.ps1"` then `powershell -ExecutionPolicy Bypass -File claude-install.ps1`
- macos: `curl -fsSL -o claude-install.sh https://claude.ai/install.sh` then `bash claude-install.sh`
- linux: `curl -fsSL -o claude-install.sh https://claude.ai/install.sh` then `bash claude-install.sh`
- npm: `npm install -g @anthropic-ai/claude-code`
- any: then run `claude` once and sign in (manual)

## Access

Generic routes to read access; the probe that proves each belongs in the unit's Needs table, since it names the unit's own resource. Who grants it in a given organisation, and its internal links, go in the store book, never here.

### azure-signin

- any: sign in to Azure in a terminal of your own (manual)
  1. Run `az login` in your own terminal (on Windows it opens the account picker; with no browser use `az login --use-device-code`).
  2. Pick the subscription the resource lives in: `az account set --subscription <name or id>`.
  3. Re-run the check; the probe for this need is `az account show -o none`.

### appinsights-read

- any: get read access to the Application Insights resource (manual)
  1. Sign in to Azure first (`azure-signin`).
  2. Make sure the query command is installed: `az extension add --name application-insights` (it is an extension; its automatic install can stop on a prompt, so a probe that relies on it hangs).
  3. Ask the resource's owner, or anyone with Owner, User Access Administrator or Role Based Access Control Administrator on it, for Monitoring Reader on the Application Insights resource or its resource group (it reads telemetry and runs log queries, and writes nothing); for queries straight against a workspace-based resource's Log Analytics workspace, Log Analytics Reader on the workspace. `evergreen.py setup <unit> --request <id>` drafts the request.
  4. Query API keys were retired on 2026-03-31; use Entra ID sign-in, not a key.
  5. When the grant arrives (often within the hour, sometimes a ticket and days), re-run the check; role assignments can take a few minutes to apply.

### postgres-read

- any: get a read-only database login (manual, secret)
  1. Ask the database's owner for a read-only role on the database or schema the skill reads, not on the whole server.
  2. Put the connection in `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER` and the password in `~/.pgpass` (`%APPDATA%\postgresql\pgpass.conf` on Windows), never in the chat or a committed file.
  3. Reachability first: a host that does not answer is a network or VPN need, not a permission one.
  4. The probe is `psql -w -X -c "select 1"` (`-w` never prompts for a password).

### sqlserver-read

- any: get read access to an Azure SQL or SQL Server database (manual)
  1. Sign in to Azure first when the server uses Entra ID (`azure-signin`).
  2. Ask the database's owner to create a database user for your account and add it to `db_datareader` (read only) on that database.
  3. The probe is `sqlcmd -S <server> -d <database> --authentication-method ActiveDirectoryDefault -Q "select 1"` (`ActiveDirectoryInteractive` opens a browser, so it is not a probe).

### github-repo

- any: get read access to a private repository (manual)
  1. Sign in: `gh auth login` in your own terminal.
  2. Ask a repository or organisation admin to add your account (Read is enough to clone and query); for an organisation with SSO, authorise your token for it afterwards.
  3. The probe is `gh api repos/<owner>/<repo> --jq .full_name`.
