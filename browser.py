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
    options.set_argument("--window-size=1920,1080")
    # 模拟真实 User-Agent 避开 CF 判定
    options.set_user_agent("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
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
        # 先访问主站建域
        page.get("https://x.ai")
        time.sleep(2)
        
        # 尝试注入不同域名的 Cookie 保证覆盖
        cookie_dict = {
            "name": "sso",
            "value": sso_cookie.strip(),
            "domain": ".x.ai",
            "path": "/",
            "secure": True
        }
        try:
            page.set.cookies(cookie_dict)
        except Exception:
            page.add_cookie(cookie_dict)
            
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
        interval = dc_data.get("interval", 5)  # 获取推荐轮询间隔
        
        print(f"🌐 [4/5] 获取验证链接成功，正在无头浏览器中打开授权页...")
        page.get(verification_uri_complete)
        time.sleep(5)  # 等待 Cloudflare / JS 逻辑加载完毕
        
        # 检查是否成功授权或点击确认按钮
        print("🖱️ 自动检测并尝试点击页面授权按钮...")
        deadline = time.time() + 15
        clicked = False
        while time.time() < deadline:
            clicked = page.run_js(r"""
                const buttons = Array.from(document.querySelectorAll('button, [role="button"], a, input[type="submit"]'));
                const target = buttons.find(node => {
                    const text = (node.innerText || node.textContent || node.value || '').replace(/\s+/g, '').toLowerCase();
                    return text.includes('allow') || text.includes('authorize') || text.includes('确认') || text.includes('授权') || text.includes('continue') || text.includes('accept');
                });
                if (target && !target.disabled) {
                    target.click();
                    return true;
                }
                return false;
            """)
            if clicked:
                print("✅ 成功在无头浏览器中捕获并点击授权按钮！")
                break
            time.sleep(1.5)
            
        time.sleep(3)
        
        print(f"⏳ [5/5] 开始轮询换取 OAuth 凭证 (Token) (间隔设定: {max(interval, 6)}秒)...")
        token_url = f"{OIDC_ISSUER}/oauth2/token"
        poll_interval = max(interval, 6) # 设置安全间隔防止 slow_down
        
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
            elif error == "slow_down":
                print("⚠️ 触发 slow_down，自动延长等待间隔...")
                poll_interval += 2
            else:
                print(f"⚠️ 轮询返回状态: {error} - {token_data.get('error_description')}")
                
            time.sleep(poll_interval)
            
        print("❌ 凭证换取超时，请确认该 SSO Cookie 是否最新、是否有效。")
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
            lines = [line.strip() for line in f if line.strip()]
            sso_cookie_value = lines[0] if lines else ""
    else:
        sso_cookie_value = sso_input
        
    if not sso_cookie_value:
        print("❌ 错误：未在文件中找到有效的 SSO Cookie 内容。")
        exit(1)
        
    run_browser_device_flow(sso_cookie_value, args.out_dir)