# SSO/Token → xai_credentials

把 xAI 的 SSO cookie 或已有 OAuth token，批量转换成 `xai-*.json` 凭证文件。

支持：

- 鉴权模式：`SSO cookie` → Device Flow 真鉴权 → `xai-*.json`
- 不鉴权模式：已有 `access_token` / JSON 凭证 → 仅格式转换
- 交互式 TUI（`tui.sh`）
- 并发处理
- 失败重试 + 重试间隔

## 文件说明

| 文件 | 作用 |
|---|---|
| `tui.sh` | 交互式入口：选模式 → 粘贴输入 → 并发 → 重试 → 输出目录 |
| `sso_to_auth_json.py` | 实际转换脚本，也可直接命令行调用 |

## 依赖

```bash
python3 -m pip install curl_cffi
```

> 鉴权模式需要 `curl_cffi`；不鉴权模式主要是本地解析。

## 快速开始（TUI）

```bash
chmod +x tui.sh
./tui.sh
```

流程：

1. 选择模式（鉴权 / 不鉴权）
2. 粘贴输入文本
3. 设置并发数
4. 设置失败重试次数 / 重试间隔（默认 `3` / `5s`）
5. 选择输出目录

## 命令行用法

### 鉴权模式

```bash
python3 sso_to_auth_json.py \
  --mode auth \
  --sso sso_list.txt \
  --out-dir ./xai_credentials \
  --workers 10 \
  --retries 3 \
  --retry-interval 5
```

输入格式（一行一个）：

```text
eyJ...sso.jwt...
邮箱----密码----eyJ...sso.jwt...
1. eyJ...sso.jwt...
```

### 不鉴权模式

```bash
python3 sso_to_auth_json.py \
  --mode noauth \
  --sso tokens.txt \
  --out-dir ./xai_credentials \
  --workers 20
```

输入格式：

```text
access_token
access_token----refresh_token
一整行 JSON 凭证
```

## 参数说明

| 参数 | 默认 | 说明 |
|---|---|---|
| `--mode` | `auth` | `auth` 鉴权 / `noauth` 仅转换 |
| `--sso` | - | 输入列表文件 |
| `--sso-cookie` | - | 单行输入 |
| `--out-dir` | `./xai_credentials` | 输出目录 |
| `--workers` | `8` | 并发数（1~64） |
| `--retries` | `3` | 失败重试次数（含首次） |
| `--retry-interval` | `5` | 重试间隔秒数 |
| `--email` | 空 | 统一写入 email（可选） |

## 输出

每个账号一个文件：

```text
xai-{email}.json
# 或
xai-{sub}.json
```

## 安全提醒

- `sso` / `token` / 生成的 `xai-*.json` 都是敏感凭证
- 不要提交到公开仓库
- 本仓库 `.gitignore` 已忽略常见本地输入输出文件

## License

MIT
