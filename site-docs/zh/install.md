# 安装与快速开始

## PyPI 直装（推荐）

```bash
pip install westlake-survival      # 基础即全功能（含 WebUI 与钥匙串加密存储）
westlake                           # 起网页并打开浏览器
westlake calendar today            # 校历等公开功能无需账号
westlake --help
```

可选增强：`pip install 'westlake-survival[browser]'` 再 `playwright install chromium`（OneDrive 讲义 / hosts 渲染深挖 / CARSI 校外 SSO 三条链路用）。

## 双击启动（不想开终端）

Windows 双击仓库根目录 `start.bat`，macOS 双击 `start.command`，Linux 跑 `./start.sh`。首次运行自动装依赖，浏览器直达「设置」页——**本人**填一次学号与统一密码，验证通过自动进仪表盘。

## 首次配置

- 一个统一密码通吃 SIS / Canvas / AMS / 预约 / 体育 / 打印 / 门户；Canvas 另兼容个人令牌（网页可存可清）。
- 密码只在网页表单里敲，终端默认不问（SSH 等无图形环境才 `westlake setup --terminal`）。
- 凭据只存本机（钥匙串优先），不跨机器同步。

## 环境体检

装了却用不了、缺依赖、命令和解释器不同环境时，先跑：

```bash
westlake doctor        # 逐项体检，缺什么给一条能直接抄的修复命令
westlake doctor --json # 给程序判断
```

详见 [GitHub 文档](https://github.com/yizhang-dream/westlake_survival/tree/main/docs)（中文为主）。
