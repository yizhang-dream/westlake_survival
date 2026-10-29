# Systems, Infrastructure & Diagnostics

## Campus Directory & Host Probing

```bash
westlake search <keyword>        # unified campus-wide keyword search
westlake sites list|site|detail  # index of institutional portals and content sections
westlake hosts list              # catalog of university subdomains
westlake hosts mine              # user-curated shortcuts and frequently accessed endpoints
westlake probe                   # automated health check and reachability verification
westlake probe scan --full       # comprehensive network census across internal subdomains
```

## WikiLake (Community Encyclopedia)

```bash
westlake wiki list               # browse all article titles in the student wiki
westlake wiki search club        # local full-text search (compensates for lack of native site search)
westlake wiki page <entry>       # render any wiki article in markdown format
```

## Shared Course Folders (Requires [browser] Extra)

```bash
westlake share add dsa https://...   # register an organizational OneDrive/SharePoint shared link
westlake share files dsa             # list files in a registered shared directory
westlake share download --match slides # filter and download matching course resources
```

Accesses public organizational shares without requiring individual personal credentials when links are configured for tenant-wide access.

## VPN Connectivity & Diagnostics

```bash
westlake vpn status               # check Sangfor SSL VPN tunnel state
westlake vpn login                # initiate VPN authentication (CAPTCHA solved via the local web UI)
westlake vpn resources            # list accessible routing tables and subnet targets
westlake doctor                   # comprehensive 9-point environment and connectivity audit
westlake find borrow              # discover relevant CLI commands using plain-language keywords
```

## Credential Security & Storage

Users configure credentials strictly through the local web Settings interface (accessible by running `westlake`). Authentication secrets are prioritized in your native operating system keychain, stored exactly once, and never solicited via plaintext terminal input. For CI/CD or sandboxed environments, configure `WESTLAKE_HOME` or set `WESTLAKE_NO_KEYRING=1`. For architectural rationale, refer to [credential_single_store.md](https://github.com/yizhang-dream/westlake_survival/blob/main/docs/credential_single_store.md) (Chinese).
