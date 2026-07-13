#!/usr/bin/env bash
# tui.sh - SSO/Token → xai_credentials
# 流程: 选模式 → 粘贴文本 → 并发数 → 重试配置 → 输出目录
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_SCRIPT="${SCRIPT_DIR}/sso_to_auth_json.py"
DEFAULT_OUT_DIR="${SCRIPT_DIR}/xai_credentials"
DEFAULT_WORKERS=10
DEFAULT_RETRIES=3
DEFAULT_RETRY_INTERVAL=5
TMP_DIR=""
SSO_FILE=""
OUT_DIR=""
WORKERS="$DEFAULT_WORKERS"
RETRIES="$DEFAULT_RETRIES"
RETRY_INTERVAL="$DEFAULT_RETRY_INTERVAL"
MODE="auth"   # auth | noauth

cleanup() {
  if [[ -n "${TMP_DIR}" && -d "${TMP_DIR}" ]]; then
    rm -rf "${TMP_DIR}"
  fi
}
trap cleanup EXIT

die() { echo "错误: $*" >&2; exit 1; }

expand_path() {
  local p="$1"
  [[ "$p" == ~* ]] && p="${p/#\~/${HOME}}"
  printf '%s' "$p"
}

abs_path() {
  local p
  p="$(expand_path "$1")"
  if command -v realpath >/dev/null 2>&1; then
    realpath -m "$p"
  elif [[ "$p" = /* ]]; then
    printf '%s' "$p"
  else
    printf '%s/%s' "$(pwd)" "$p"
  fi
}

prompt_default() {
  local tip="$1" def="${2-}" ans
  if [[ -n "$def" ]]; then
    read -r -p "${tip} [${def}]: " ans || true
    REPLY="${ans:-$def}"
  else
    read -r -p "${tip}: " ans || true
    REPLY="$ans"
  fi
}

count_lines() {
  local file="$1"
  [[ -f "$file" ]] || { echo 0; return; }
  awk '
    {
      gsub(/\r/, "")
      line=$0
      sub(/^[[:space:]]+/,"",line)
      sub(/[[:space:]]+$/,"",line)
      if(line=="" || line ~ /^#/) next
      c++
    }
    END{print c+0}
  ' "$file"
}

banner() {
  printf '\033[2J\033[H'
  cat <<'B'
========================================
  SSO/Token → xai_credentials
========================================
B
}

check_deps() {
  command -v python3 >/dev/null || die "缺少 python3"
  [[ -f "$PY_SCRIPT" ]] || die "找不到 $PY_SCRIPT"
  if ! python3 -c 'import curl_cffi' 2>/dev/null; then
    echo "警告: 未安装 curl_cffi（鉴权模式需要）"
    prompt_default "仍继续?" "y"
    case "${REPLY,,}" in y|yes|是|"") ;; *) exit 1 ;; esac
  fi
}

input_mode() {
  banner
  echo "【1/5】选择模式"
  echo
  echo "  1) 鉴权（推荐）"
  echo "     SSO cookie → Device Flow 真鉴权 → xai-*.json"
  echo
  echo "  2) 不鉴权"
  echo "     已有 access_token / JSON 凭证 → 仅格式转换 → xai-*.json"
  echo
  echo "  0) 退出"
  echo
  while true; do
    prompt_default "请输入 1 或 2" "1"
    case "${REPLY}" in
      1|auth|鉴权) MODE="auth"; break ;;
      2|noauth|不鉴权) MODE="noauth"; break ;;
      0) echo "已退出"; exit 0 ;;
      *) echo "  无效选项，请输入 1 或 2" ;;
    esac
  done
}

input_text() {
  banner
  echo "【2/5】粘贴输入文本"
  echo
  if [[ "$MODE" == "auth" ]]; then
    echo "  当前模式: 鉴权"
    echo "  输入格式: 一行一个 SSO cookie"
    echo "            支持 177. eyJ... / 邮箱----密码----sso"
  else
    echo "  当前模式: 不鉴权（仅转换）"
    echo "  输入格式: 一行一个 access_token"
    echo "            或 access----refresh"
    echo "            或一整行 JSON 凭证"
  fi
  echo
  echo "  粘贴完后: 再按一次回车（空行）结束；或 Ctrl+D"
  echo
  echo "----------------------------------------"

  TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sso-tui.XXXXXX")"
  SSO_FILE="${TMP_DIR}/input_list.txt"

  {
    local line got_any=0
    while IFS= read -r line || [[ -n "$line" ]]; do
      line="${line//$'\r'/}"
      if [[ -z "$line" ]]; then
        (( got_any )) && break
        continue
      fi
      got_any=1
      printf '%s\n' "$line"
    done
  } >"$SSO_FILE"

  echo "----------------------------------------"
  local n
  n="$(count_lines "$SSO_FILE")"
  (( n > 0 )) || die "没有读到有效内容"
  echo
  echo "  已读取 ${n} 条"
  echo
  echo "  说明: 这里只是可选保存『输入原文列表』，方便下次复用。"
  echo "        真正的 xai-*.json 凭证会在第 5 步输出到文件夹。"
  echo
  prompt_default "是否保存输入列表? y=保存 / n=不保存" "n"
  case "${REPLY,,}" in
    y|yes|是)
      local def_name
      if [[ "$MODE" == "auth" ]]; then
        def_name="${SCRIPT_DIR}/sso_list.txt"
      else
        def_name="${SCRIPT_DIR}/token_list.txt"
      fi
      prompt_default "输入列表保存路径" "$def_name"
      local save
      save="$(abs_path "$(expand_path "${REPLY}")")"
      mkdir -p "$(dirname "$save")"
      cp -f "$SSO_FILE" "$save"
      SSO_FILE="$save"
      cleanup
      TMP_DIR=""
      echo "  已保存输入列表: $SSO_FILE"
      ;;
    *)
      echo "  跳过保存输入列表（不影响后续转换）"
      ;;
  esac
}

input_workers() {
  banner
  echo "【3/5】并发数"
  echo
  if [[ "$MODE" == "auth" ]]; then
    echo "  鉴权模式建议 5~15，过大可能限流"
  else
    echo "  不鉴权模式可开高一点，如 20~40"
  fi
  echo "  当前条目: $(count_lines "$SSO_FILE")"
  echo
  local def="$DEFAULT_WORKERS"
  [[ "$MODE" == "noauth" ]] && def=20
  while true; do
    prompt_default "并发 workers" "$def"
    if [[ "${REPLY}" =~ ^[1-9][0-9]*$ ]] && (( REPLY <= 64 )); then
      WORKERS="$REPLY"
      break
    fi
    echo "  请输入 1~64 的整数"
  done
}

input_retry() {
  banner
  echo "【4/5】失败重试配置"
  echo
  if [[ "$MODE" == "auth" ]]; then
    echo "  鉴权失败时自动重试，可提高成功率"
    echo "  网络抖动 / 限流时建议开一点重试"
  else
    echo "  不鉴权模式主要是本地解析，一般不需要重试"
    echo "  保留配置是为了和命令行参数一致"
  fi
  echo
  while true; do
    prompt_default "失败重试次数（含首次）" "$DEFAULT_RETRIES"
    if [[ "${REPLY}" =~ ^[1-9][0-9]*$ ]] && (( REPLY <= 20 )); then
      RETRIES="$REPLY"
      break
    fi
    echo "  请输入 1~20 的整数"
  done
  while true; do
    prompt_default "重试间隔秒数" "$DEFAULT_RETRY_INTERVAL"
    if [[ "${REPLY}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
      # 允许 0
      RETRY_INTERVAL="$REPLY"
      break
    fi
    echo "  请输入 >=0 的数字"
  done
}

input_outdir() {
  banner
  echo "【5/5】输出目录（最终凭证写到这里）"
  echo
  echo "  转换后每个账号一个文件:"
  echo "    xai-{email}.json"
  echo "    或 xai-{sub}.json"
  echo "  例如: xai-24428bbb-2286-4a7f-9b5f-fd37af727260.json"
  echo
  prompt_default "输出文件夹" "$DEFAULT_OUT_DIR"
  OUT_DIR="$(abs_path "$(expand_path "${REPLY}")")"
  mkdir -p "$OUT_DIR"
}

confirm_run() {
  local n mode_cn
  n="$(count_lines "$SSO_FILE")"
  if [[ "$MODE" == "auth" ]]; then mode_cn="鉴权"; else mode_cn="不鉴权(仅转换)"; fi

  banner
  echo "即将开始"
  echo
  echo "  模式     : $mode_cn  (--mode $MODE)"
  echo "  输入     : $SSO_FILE  (${n} 条)"
  echo "  并发     : $WORKERS"
  echo "  重试次数 : $RETRIES"
  echo "  重试间隔 : ${RETRY_INTERVAL}s"
  echo "  输出目录 : $OUT_DIR"
  echo
  prompt_default "开始? (y/n)" "y"
  case "${REPLY,,}" in
    y|yes|是|"") ;;
    *) echo "已取消"; exit 0 ;;
  esac

  echo
  echo "python3 $PY_SCRIPT --mode $MODE --sso $SSO_FILE --out-dir $OUT_DIR --workers $WORKERS --retries $RETRIES --retry-interval $RETRY_INTERVAL"
  echo "========================================"
  echo

  set +e
  python3 "$PY_SCRIPT" --mode "$MODE" --sso "$SSO_FILE" --out-dir "$OUT_DIR" --workers "$WORKERS" --retries "$RETRIES" --retry-interval "$RETRY_INTERVAL"
  local rc=$?
  set -e

  echo
  echo "========================================"
  local cnt
  cnt="$(find "$OUT_DIR" -maxdepth 1 -type f -name 'xai-*.json' 2>/dev/null | wc -l | tr -d ' ')"
  echo "目录内 xai-*.json: ${cnt}  →  $OUT_DIR"
  echo "exit=$rc"
}

main() {
  check_deps
  input_mode
  input_text
  input_workers
  input_retry
  input_outdir
  confirm_run
}

main "$@"
