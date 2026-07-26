import argparse
import os
import time
import json
import requests
from DrissionPage import Chromium, ChromiumOptions

OIDC_ISSUER = "https://auth.x.ai"
CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
SCOPE = "openid profile email offline_access grok-cli:access api:access conversations:read conversations:write"

def create_browser():
    options = ChromiumOptions()
    options.set_argument("--no-sandbox")
    options.set_argument("--disable-gpu")
    options.set_argument("--disable-dev-shm-usage")
    
    # 关键修复：在 Linux 无头服务器上必须开启 headless 模式
    options.headless(True)
    
    for candidate in [
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/usr/bin/google-chrome",
    ]:
        if os.path.isfile(candidate):
            options.set_browser_path(candidate)
            break
            
    browser = Chromium(options)
    page = browser.latest_tab
    return browser, page

def run_browser_device_flow(sso_cookie: str, out_dir: str):
    print("🚀 [1/5] 启动无头浏览器准备接管 OIDC 鉴权流程...")
    browser, page = create_browser()
    
    try:
        print("🍪 [2/5] 正在注入 SSO Cookie...")
        page.get("https://x.ai")
        page.set.cookies({
            "name": "sso",
            "value": sso_cookie.strip(),
            "domain": ".x.ai",
            "path": "/",
            "secure": True,
            "httpOnly": True
        })
        
        print("🔑 [3/5] 向 OIDC 服务器请求 Device Code...")
        resp = requests.post(
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
        
        print(f"🌐 [4/5] 获取验证链接成功，正在无头浏览器中打开...")
        page.get(verification_uri_complete)
        time.sleep(3)
        
        print("🖱️ 等待并尝试自动点击授权确认按钮...")
        deadline = time.time() + 20
        clicked = False
        while time.time() < deadline:
            clicked = page.run_js(r"""
                const buttons = Array.from(document.querySelectorAll('button, [role="button"], input[type="submit"]'));
                const target = buttons.find(node => {
                    const text = (node.innerText || node.textContent || node.value || '').replace(/\s+/g, '').toLowerCase();
                    return text.includes('allow') || text.includes('authorize') || text.includes('确认') || text.includes('授权') || text.includes('continue');
                });
                if (target && !target.disabled) {
                    target.click();
                    return true;
                }
                return false;
            """)
            if clicked:
                print("✅ 成功在浏览器中点击授权按钮！")
                break
            time.sleep(1.0)
            
        if not clicked:
            print("⚠️ 未自动检测到按钮，由于处于无头模式，请确保 SSO Token 有效或页面无需二次点击。")
            
        time.sleep(3)
        
        print("⏳ [5/5] 开始轮询换取 OAuth 凭证 (Token)...")
        token_url = f"{OIDC_ISSUER}/oauth2/token"
        
        for _ in range(15):
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
                
            time.sleep(5)
            
        print("❌ 凭证换取超时，请确认浏览器中的账号状态是否正常。")
        return False

    except Exception as exc:
        print(f"❌ 执行浏览器鉴权流程异常: {exc}")
        return False
    finally:
        try:
            browser.quit()
        except:
            pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="使用 DrissionPage 浏览器自动化解决 SSO 鉴权 invalid_grant 问题")
    parser.add_argument("--sso", required=True, help="包含 SSO Cookie 的文件路径 或 直接传入 Cookie 字符串")
    parser.add_argument("--out-dir", default="./xai_credentials", help="凭证输出目录")
    
    args = parser.parse_args()
    
    sso_input = args.sso
    if os.path.isfile(sso_input):
        with open(sso_input, "r", encoding="utf-8") as f:
            sso_cookie_value = f.read().strip()
    else:
        sso_cookie_value = sso_input
        
    run_browser_device_flow(sso_cookie_value, args.out_dir)