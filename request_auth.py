import argparse
import os
import json
import requests

OIDC_ISSUER = "https://auth.x.ai"
CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
SCOPE = "openid profile email offline_access grok-cli:access api:access conversations:read conversations:write"

def run_pure_requests_flow(sso_cookie: str, out_dir: str):
    print("🚀 [1/3] 初始化会话并注入 SSO Cookie...")
    session = requests.Session()
    
    # 模拟标准浏览器的请求头，尽可能贴近真实客户端
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/png,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    
    # 注入 Cookie 到 x.ai 域
    session.cookies.set("sso", sso_cookie.strip(), domain=".x.ai", path="/")
    
    print("🔑 [2/3] 向 OIDC 服务器请求 Device Code...")
    resp = session.post(
        f"{OIDC_ISSUER}/oauth2/device/code",
        data={
            "client_id": CLIENT_ID,
            "scope": SCOPE
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    
    if resp.status_code != 200:
        print(f"❌ 获取 Device Code 失败: {resp.text}")
        return False
        
    dc_data = resp.json()
    device_code = dc_data.get("device_code")
    user_code = dc_data.get("user_code")
    verification_uri = dc_data.get("verification_uri")
    
    print(f"✅ 获取成功！User Code: {user_code}")
    print(f"🌐 尝试直接通过 API 提交设备授权确认...")
    
    # 尝试直接向 accounts 提交确认请求（部分 OIDC 实现支持直接 POST user_code 进行授权）
    confirm_resp = session.post(
        f"https://accounts.x.ai/oauth2/device",
        data={
            "user_code": user_code,
            "submit": "Continue"
        },
        allow_redirects=True
    )
    print(f"🔄 确认请求返回状态码: {confirm_resp.status_code}")
    
    print("⏳ [3/3] 开始轮询换取 OAuth 凭证 (Token)...")
    token_url = f"{OIDC_ISSUER}/oauth2/token"
    
    for i in range(15):
        token_resp = requests.post(
            token_url,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": CLIENT_ID,
                "device_code": device_code,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        token_data = token_resp.json()
        
        if "access_token" in token_data:
            print("🎉 成功获取 OAuth 凭证！")
            os.makedirs(out_dir, exist_ok=True)
            out_file = os.path.join(out_dir, "auth.json")
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(token_data, f, indent=2, ensure_ascii=False)
            print(f"📁 凭证已成功保存至: {out_file}")
            return True
            
        error = token_data.get("error")
        if error == "authorization_pending":
            print(f"⏳ 等待授权确认中... ({i+1}/15)")
        else:
            print(f"⚠️ 轮询返回状态: {error} - {token_data.get('error_description')}")
            
        time.sleep(6)
        
    print("❌ 纯请求方式授权超时。")
    return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="纯 Requests 鉴权脚本")
    parser.add_argument("--sso", required=True, help="包含 SSO Cookie 的文件路径")
    parser.add_argument("--out-dir", default="./xai_credentials", help="凭证输出目录")
    
    args = parser.parse_args()
    
    with open(args.sso, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
        sso_cookie_value = lines[0] if lines else ""
        
    run_pure_requests_flow(sso_cookie_value, args.out_dir)