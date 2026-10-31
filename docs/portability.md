# westlake-survival 环境可移植性与单机绑定排查审计报告

## 1. 审计范围与背景

为了确保 `westlake-survival` 工具包可以在任意西湖大学师生机器（Windows、macOS、Linux）以及纯净沙箱环境下开箱即用，全面排查代码库中是否存在**「仅在本机开发环境有效、其他用户无法使用」**的隐性绑定与缺陷。

排查重点覆盖以下 5 个维度：
1. **硬编码本机盘符与绝对路径**（如 `D:\westlake_survival`、`C:\Users\...`）；
2. **硬编码个人凭据或写死状态**（如特定测试学号、明文 token、写死特定 session）；
3. **平台与外部进程强绑定**（Windows 专有命令、PowerShell、缺少跨平台降级）；
4. **沙箱重定位机制完整性**（`WESTLAKE_HOME` 与 `WESTLAKE_NO_KEYRING` 是否贯穿所有模块）；
5. **内网边界与离校友好度**（对私有网段 10.x.x.x 的连通性与降级提示）。

---

## 2. 发现的隐患与修复落地

经过静态 AST 与正则全库扫描，共定位到 **3 处真实存在的可移植性缺陷**，已全部修复完成：

### ① 缺陷 1：MCP 接入示例硬编码绝对路径（已修复）
- **原状**：`src/westlake_survival/mcp_server.py` 的 docstring 中，给出的客户端配置示例写死了本地绝对路径：
  ```json
  "command": "/path/to/venv/python",
  "PYTHONPATH": "/path/to/src"
  ```
  外部用户若直接复制该配置接入 Claude Desktop 或 ZCode，会因找不到路径而直接启动失败。
- **修复**：改为跨平台标准命令 `"command": "westlake-mcp"`，并补充源码模式下的通用 `"python", "-m", "westlake_survival.mcp_server"` 示例。

### ② 缺陷 2：部分模块忽略沙箱变量 `WESTLAKE_HOME`（已修复）
- **原状**：
  `scholar.py`、`taskcenter.py`、`vpn.py` 中的 `PROFILE_DIR` 与 `COOKIES_PATH` 硬编码了 `Path.home() / ".westlake_survival"`，未遵循全库约定的 `config_root()`。
  导致在测试沙箱或指定 `WESTLAKE_HOME` 环境变量的环境中，这三个模块依然会往用户的真实主目录写文件，破坏了沙箱隔离。
- **修复**：全量统一改为 `config_root() / "..."`，保证在指定沙箱目录时 100% 隔离。

### ③ 缺陷 3：校外网络访问集群认证网关缺少明确引导（已修复）
- **原状**：
  西湖大学 HPC NewAPI 令牌网关 `ecs.westlake.edu.cn:30300` 与 API 接口 `hpc-api.westlake.edu.cn` 解析为校内私网地址 `10.28.0.22`。如果外部用户在校外未连 VPN 时运行 `westlake hpc sync-key`，原先会直接抛出底层的网络 `ConnectionError`，用户无法得知原因。
- **修复**：捕获网络异常并抛出标准 `OffCampusError`，明确提示：「集群 NewAPI 认证网关仅在校园网/VPN 内可达，请先连接西湖大学 VPN」。并在 `westlake hpc ai` 输出中明确标注 `仅校园网/VPN 可达`。

---

## 3. 已通过的无单机依赖核验项

除上述 3 处修复外，核心系统均已确认具备跨平台通用性：

| 检查维度 | 实测结论 | 依据与实现 |
|---|---|---|
| **解释器与环境一致性** | 跨平台通过 | `start.bat`（Windows）、`start.sh`（Linux）、`start.command`（macOS）均具备 Python 3.10+ 检测、venv 自愈及包依赖自动补齐 |
| **凭据单一存储（SSO）** | 跨平台通过 | keyring 优先加密存钥匙串；Linux 无桌面或无钥匙串环境自动降级为明文文件并报 `warn`；沙箱模式完全跳过系统钥匙串 |
| **会话持久化与权限** | 跨平台通过 | `sis_cookies.json` 与 `ams_cookies.json` 采用 `0600` 权限安全保存；Windows 下捕获 `OSError` 静默兜底 |
| **VPN 路由表探测** | 跨平台通过 | 严格按 `win32`（PowerShell Get-NetRoute）、`darwin`（netstat -rn）、`linux`（ip route）分支处理，非当前平台有空列表兜底 |
| **Windows 控制台编码** | 跨平台通过 | 仅在 `sys.platform == 'win32'` 时重配置 stdout 为 UTF-8，防止中文 Windows GBK 抛错；非 Windows 平台直接跳过 |
| **无头浏览器依赖** | 跨平台通过 | Playwright 浏览器为可选增强，未安装时 `doctor` 仅报 warning，核心命令均自动降级 |

---

## 4. 纯净沙箱端到端实测

配置纯净独立临时目录并强制屏蔽系统钥匙串：
```bash
WESTLAKE_HOME=<临时空目录> WESTLAKE_NO_KEYRING=1 westlake doctor --json
```
- **测试结果**：返回状态码 0，全量检测项中 `missing: []`，无任何硬编码阻断；
- **基础只读能力**：`calendar today`、`mirrors` 在零凭据、空沙箱下均 100% 正常响应。
