# 安装与快速开始

## PyPI 直装（推荐）

```bash
pip install westlake-survival      # 基础安装包含 WebUI 与钥匙串存储
westlake                           # 启动本地服务并打开浏览器
westlake calendar today            # 校历等公开功能无需账号
westlake --help
```

可选增强：执行 `pip install 'westlake-survival[browser]'` 与 `playwright install chromium`，支持 OneDrive 讲义解析、子站深度渲染及 CARSI 校外 SSO 联动。

## 图形化快捷启动

Windows 环境运行仓库根目录 `start.bat`，macOS 运行 `start.command`，Linux 执行 `./start.sh`。首次运行时会自动安装依赖并在浏览器中打开「设置」页面；用户填入统一身份认证凭据并通过验证后，将自动进入仪表盘。

## 首次配置

- 统一身份认证密码适用于 SIS、Canvas、AMS、场地预约、体育系统、自助打印与校内门户；Canvas 同时支持配置个人访问令牌。
- 密码在本地网页表单中输入，终端默认不提示输入明文密码（无桌面环境可通过 `westlake setup --terminal` 完成配置）。
- 凭据仅保存在当前设备（优先使用系统钥匙串），不进行跨设备同步。

## 环境自检

若遇到依赖缺失或环境路径不一致，可执行环境自检：

```bash
westlake doctor        # 逐项检查运行环境并输出修复建议
westlake doctor --json # 输出结构化检查结果
```

详见 [GitHub 文档](https://github.com/yizhang-dream/westlake_survival/tree/main/docs)。
