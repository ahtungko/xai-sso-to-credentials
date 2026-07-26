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
    options.set_user_agent("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    
    # 💡 核心修改：关闭无头模式，显示真实浏览器界面
    options.headless(False)
    
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
    print("🚀 [1/5] 启动有头浏览器准备接管 OIDC 鉴权流程...")
    browser, page = create_browser()
    
    try:
        print("🍪 [2/5] 正在注入 SSO Cookie...")
        page.get("https://x.ai")
        time.sleep(2)
        
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
        interval = dc_data.get("interval", 5)
        
        print(f"🌐 [4/5] 获取验证链接成功，正在浏览器中打开授权页...")
        page.get(verification_uri_complete)
        time.sleep(3)
        
        print("🖱️ 自动检测并逐步点击授权按钮...")
        deadline = time.time() + 20
        success_steps = 0
        
        while time.time() < deadline:
            clicked_continue = page.run_js(r"""
                const buttons = Array.from(document.querySelectorAll('button, [role="button"], input[type="submit"]'));
                const target = buttons.find(node => {
                    const text = (node.innerText || node.textContent || node.value || '').replace(/\s+/g, '').toLowerCase();
                    return text.includes('continue') || text.includes('下一步') || text.includes('1/2');
                });
                if (target && !target.disabled) {
                    target.click();
                    return true;
                }
                return false;
            """)
            
            if clicked_continue:
                print("✅ 成功点击了 Continue 按钮，等待页面加载...")
                success_steps += 1
                try:
                    page.wait.load_complete(timeout=5)
                except Exception:
                    time.sleep(3)
                
            clicked_final = page.run_js(r"""
                const buttons = Array.from(document.querySelectorAll('button, [role="button"], input[type="submit"]'));
                const target = buttons.find(node => {
                    const text = (node.innerText || node.textContent || node.value || '').replace(/\s+/g, '').toLowerCase();
                    return text.includes('allow') || text.includes('authorize') || text.includes('confirm') || text.includes('确认') || text.includes('授权') || text.includes('accept');
                });
                if (target && !target.disabled) {
                    target.click();
                    return true;
                }
                return false;
            """)
            
            if clicked_final:
                print("✅ 成功点击了最终的授权确认按钮！")
                print("⏳ 正在等待服务器确认授权状态...")
                time.sleep(5)
                break
                
            if success_steps > 0 and not clicked_final:
                time.sleep(1)
                continue
                
            time.sleep(1.5)
            
        print(f"⏳ [5/5] 开始轮询换取 OAuth 凭证 (Token)...")
        token_url = f"{OIDC_ISSUER}/oauth2/token"
        poll_interval = max(interval, 6)
        
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
                
            time.sleep(poll_interval)
            
        print("❌ 凭证换取超时。")
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
    parser = argparse.ArgumentParser(description="有头模式 DrissionPage 鉴权脚本")
    parser.add_argument("--sso", required=True, help="包含 SSO Cookie 的文件路径 或 直接传入")
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