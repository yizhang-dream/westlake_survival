# Install & quick start

## From PyPI (recommended)

```bash
pip install westlake-survival      # full base install (WebUI + encrypted keyring included)
westlake                           # start the web app and open a browser
westlake calendar today            # public features need no account
westlake --help
```

Optional extra: `pip install 'westlake-survival[browser]'` then `playwright install chromium` — enables OneDrive lecture notes, hosts deep rendering, and CARSI off-campus SSO.

## No terminal at all

Windows: double-click `start.bat`; macOS: `start.command`; Linux: `./start.sh`. The first run installs dependencies and opens the browser on the **Settings** page — you type your student ID and unified password once; after verification the dashboard loads.

## First-time setup

- One unified password covers SIS / Canvas / AMS / booking / sports / printing / portal; Canvas also accepts a personal token (settable in the web UI).
- Passwords are typed in the web form only; the terminal never asks by default (`westlake setup --terminal` is the no-GUI fallback).
- Credentials stay on this machine (keychain first), never synced across machines.

## Environment check

```bash
westlake doctor        # item-by-item check with a copy-paste fix for each gap
westlake doctor --json # machine-readable
```

Full docs (Chinese-first) live on [GitHub](https://github.com/yizhang-dream/westlake_survival/tree/main/docs).
