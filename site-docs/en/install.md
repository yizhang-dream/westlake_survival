# Installation & Quick Start

## From PyPI (Recommended)

```bash
pip install westlake-survival      # full base install (WebUI + encrypted keyring included)
westlake                           # launch the local web dashboard
westlake calendar today            # public queries run without credentials
westlake --help
```

Optional extra: `pip install 'westlake-survival[browser]'` followed by `playwright install chromium` enables headless browser features: OneDrive/SharePoint shared notes indexing, deep client-side rendering for campus hosts, and off-campus CARSI SSO renewal.

## GUI-Only Launch (No Terminal Required)

Windows: double-click `start.bat`; macOS: double-click `start.command`; Linux: execute `./start.sh`. On the first run, the script installs dependencies and automatically opens your browser to the **Settings** page. Enter your student ID and unified password once; upon successful verification, the main dashboard loads. Subsequent runs skip setup and open the dashboard directly.

## First-Time Configuration

- A single institutional password authenticates across SIS, Canvas, AMS, venue booking, sports facilities, cloud printing, and the campus portal. Canvas also supports personal access tokens configured directly in the web UI.
- Passwords are entered securely through the local browser UI; the CLI avoids storing or requesting plaintext credentials in standard terminal sessions (`westlake setup --terminal` is provided for headless environments).
- Credentials are stored exclusively on the local machine in your OS keychain (Windows Credential Manager, macOS Keychain, or Linux Secret Service) and are never synced across devices.

## Environment Diagnostics

```bash
westlake doctor        # comprehensive environment diagnostics with copy-paste remediation commands
westlake doctor --json # structured JSON output for scripts and agents
```

Comprehensive technical documentation is maintained in the [GitHub repository documentation](https://github.com/yizhang-dream/westlake_survival/tree/main/docs).
