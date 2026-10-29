# Sites & systems

## Search & inventory

```bash
westlake search <keyword>        # full-site search
westlake sites list|site|detail  # sites and sections
westlake hosts list              # subdomain inventory
westlake hosts mine              # frequently used
westlake probe                   # service reachability check
westlake probe scan --full       # subdomain census
```

## WikiLake (student wiki)

```bash
westlake wiki list               # entry list
westlake wiki search club        # in-site search (the site itself has none)
westlake wiki page <entry>       # read any entry
```

## Lecture notes (share, needs the [browser] extra)

```bash
westlake share add dsa https://...   # register an OneDrive/SharePoint share once
westlake share files dsa
westlake share download --match slides
```

Reads account-free when the link allows "anyone in the organization".

## VPN & diagnostics

```bash
westlake vpn status               # Sangfor VPN status
westlake vpn login                # login (CAPTCHA typed by the human in the web UI)
westlake vpn resources            # tunnel routes
westlake doctor                   # nine-item environment check
westlake find borrow              # ask which command fits a need
```

## Credentials

The web Settings page (run `westlake` and the browser opens there) is where the user types credentials; keychain first, stored exactly once, never asked in the terminal. Sandboxed testing: `WESTLAKE_HOME` or `WESTLAKE_NO_KEYRING=1`. Design: [credential_single_store](https://github.com/yizhang-dream/westlake_survival/blob/main/docs/credential_single_store.md) (Chinese).
