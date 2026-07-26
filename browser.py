import argparse
import os
import time
import json
import requests
from bs4 import BeautifulSoup

OIDC_ISSUER = "https://auth.x.ai"
CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
SCOPE = "openid profile email offline_access grok-cli:access api:access conversations:read conversations:write"

def run_session_auth_flow(sso_cookie: str, out_dir: str):
    print("🚀 [1/4] 初始化会话并注入 SSO Cookie...")
    session = requests.Session()
    
    # 模拟浏览器 User-Agent，防止被 Cloudflare 拦截
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/png,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    
    # 注入 sso cookie 到 x.ai 域
    session.cookies.set("sso", sso_cookie.strip(), domain=".x.ai", path="/")
    
    print("🔑 [2/4] 向 OIDC 服务器请求 Device Code...")
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
    verification_uri_complete = dc_data.get("verification_uri_complete")
    
    print(f"🌐 [3/4] 访问验证链接以触发授权确认...")
    # 通过带 Cookie 的 session 访问授权验证完整链接
    auth_page_resp = session.get(verification_uri_complete)
    
    print(f"🔄 访问状态码: {auth_page_resp.status_code}")
    
    # 如果页面包含表单或需要自动同意授权，可以解析并提交
    # 某些情况下，只要带着有效 SSO 的 session 访问了 verification_uri_complete，后端就会自动放行
    
    print("⏳ [4/4] 开始轮询换取 OAuth 凭证 (Token)...")
    token_url = f"{OIDC_ISSUER}/oauth2/token"
    
    for i in range(20):
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
        if error != "authorization_pending":
            print(f"⚠️ 轮询返回状态: {error} - {token_data.get('error_description')}")
        else:
            print(f"⏳ 等待授权确认中... ({i+1}/20)")
            
        time.sleep(4)
        
    print("❌ 凭证换取超时。请检查该 SSO Cookie 是否已经失效、过期或者没有通过 xAI 登录。")
    return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="使用纯 Session 完美解决 xAI Device Auth 流程")
    parser.add_argument("--sso", required=True, help="包含 SSO Cookie 的文件路径 或 直接传入 Cookie 字符串")
    parser.add_argument("--out-dir", default="./xai_credentials", help="凭证输出目录")
    
    args = parser.parse_args()
    
    sso_input = args.sso
    if os.path.isfile(sso_input):
        with open(sso_input, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
            sso_cookie_value = lines[0] if lines else ""
    else:
        sso_cookie_value = sso_input
        
    if not sso_cookie_value:
        print("❌ 错误：未在文件中找到有效的 SSO Cookie 内容。")
        exit(1)
        
    run_session_auth_flow(sso_cookie_value, args.out_dir)