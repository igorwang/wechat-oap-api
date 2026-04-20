#!/usr/bin/env bash
#
# wechat.sh — thin wrapper around the wechat-oap HTTP API for the operations
# that can't go through MCP cleanly (multipart file uploads + health checks).
#
# Env:
#   WECHAT_API_BASE_URL  default https://wxapi.techower.com
#   WECHAT_API_KEY       required for anything except `health`
#
# Subcommands:
#   health
#   upload-cover     <file>                         # material_add type=image  → {media_id, url}
#   upload-thumb     <file>                         # material_add type=thumb  → {media_id}
#   upload-inline    <file>                         # material_uploadimg       → {url}  (for <img> in article body)
#   upload-voice     <file>                         # material_add type=voice  → {media_id}
#   upload-video     <file> <title> <introduction>  # material_add type=video  → {media_id}
#   upload-temp      <type> <file>                  # material/temporary/upload → {media_id, type, created_at}
#
# Exit codes:
#   0  success
#   1  usage / local error
#   2  HTTP transport failure
#   3  WeChat errcode != 0 (errmsg printed on stderr, raw body on stdout)
#   4  local service 4xx/5xx (e.g. 401 auth)

set -euo pipefail

BASE="${WECHAT_API_BASE_URL:-https://wxapi.techower.com}"
BASE="${BASE%/}"
KEY="${WECHAT_API_KEY:-}"

die()   { printf 'error: %s\n' "$*" >&2; exit 1; }
need()  { command -v "$1" >/dev/null 2>&1 || die "missing dependency: $1"; }

need curl
need jq

_auth_header() {
  # Echoes the -H arg; empty string if no key configured.
  if [ -n "$KEY" ]; then printf -- '-H\nX-API-Key: %s\n' "$KEY"; fi
}

_check_file() {
  [ -f "$1" ] || die "file not found: $1"
}

# _post_multipart <path> <curl_form_args...>
# Calls BASE+path, inspects HTTP status and WeChat errcode.
# Prints response body on stdout (always — success or WeChat error).
_post_multipart() {
  local path="$1"; shift
  local url="$BASE$path"
  local tmp_body http_status
  tmp_body="$(mktemp)"
  trap 'rm -f "$tmp_body"' RETURN

  local curl_args=(-sS -o "$tmp_body" -w '%{http_code}' -X POST "$url")
  if [ -n "$KEY" ]; then curl_args+=(-H "X-API-Key: $KEY"); fi
  curl_args+=("$@")

  if ! http_status="$(curl "${curl_args[@]}")"; then
    printf 'transport failure calling %s\n' "$url" >&2
    exit 2
  fi

  cat "$tmp_body"

  if [ "$http_status" -ge 400 ]; then
    printf '\nHTTP %s from local service (auth/validation issue, not a WeChat error)\n' "$http_status" >&2
    exit 4
  fi

  # WeChat wraps business errors in JSON body with errcode != 0, HTTP 200.
  local errcode errmsg
  errcode="$(jq -r '.errcode // 0' "$tmp_body" 2>/dev/null || echo 0)"
  if [ "$errcode" != "0" ] && [ "$errcode" != "null" ]; then
    errmsg="$(jq -r '.errmsg // "(no errmsg)"' "$tmp_body")"
    printf '\nWeChat errcode=%s errmsg=%s\n' "$errcode" "$errmsg" >&2
    case "$errcode" in
      40001|42001) printf 'hint: access_token invalid — service will retry once; if still failing, check WECHAT_APPSECRET in .env\n' >&2 ;;
      40013)       printf 'hint: AppID mismatch — WECHAT_APPID in .env does not match the account\n' >&2 ;;
      40164)       printf 'hint: server egress IP not in 公众号后台 → 基本配置 → IP 白名单\n' >&2 ;;
      40007)       printf 'hint: media_id invalid — temporary material expired (3-day TTL) or typo\n' >&2 ;;
      45009)       printf 'hint: API quota exhausted — confirm with user before POST /wechat/clear-quota\n' >&2 ;;
      53503)       printf 'hint: article content flagged as sensitive by WeChat\n' >&2 ;;
    esac
    exit 3
  fi
}

cmd_health() {
  curl -sS -f "$BASE/healthz"
  echo
}

cmd_upload_cover()  { _check_file "$1"; _post_multipart "/wechat/material/permanent/add?type=image" -F "media=@$1"; }
cmd_upload_thumb()  { _check_file "$1"; _post_multipart "/wechat/material/permanent/add?type=thumb" -F "media=@$1"; }
cmd_upload_voice()  { _check_file "$1"; _post_multipart "/wechat/material/permanent/add?type=voice" -F "media=@$1"; }
cmd_upload_inline() { _check_file "$1"; _post_multipart "/wechat/material/permanent/uploadimg" -F "media=@$1"; }

cmd_upload_video() {
  [ $# -eq 3 ] || die "usage: upload-video <file> <title> <introduction>"
  _check_file "$1"
  _post_multipart "/wechat/material/permanent/add?type=video" \
    -F "media=@$1" \
    -F "title=$2" \
    -F "introduction=$3"
}

cmd_upload_temp() {
  [ $# -eq 2 ] || die "usage: upload-temp <image|voice|video|thumb> <file>"
  local type="$1" file="$2"
  case "$type" in image|voice|video|thumb) ;; *) die "invalid type: $type";; esac
  _check_file "$file"
  _post_multipart "/wechat/material/temporary/upload?type=$type" -F "media=@$file"
}

usage() {
  sed -n '3,25p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
}

main() {
  [ $# -ge 1 ] || usage
  local sub="$1"; shift
  case "$sub" in
    health)         cmd_health ;;
    upload-cover)   [ $# -eq 1 ] || die "usage: upload-cover <file>"  ; cmd_upload_cover "$1" ;;
    upload-thumb)   [ $# -eq 1 ] || die "usage: upload-thumb <file>"  ; cmd_upload_thumb "$1" ;;
    upload-voice)   [ $# -eq 1 ] || die "usage: upload-voice <file>"  ; cmd_upload_voice "$1" ;;
    upload-inline)  [ $# -eq 1 ] || die "usage: upload-inline <file>" ; cmd_upload_inline "$1" ;;
    upload-video)   cmd_upload_video "$@" ;;
    upload-temp)    cmd_upload_temp "$@" ;;
    -h|--help|help) usage ;;
    *) die "unknown subcommand: $sub (run: $0 --help)" ;;
  esac
}

main "$@"
