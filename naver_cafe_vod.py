#!/usr/bin/env python3
# naver_cafe_vod.py

import asyncio, argparse, subprocess, sys, shlex, time, re, os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode, urljoin

from playwright.async_api import async_playwright

LOGIN_URL = "https://nid.naver.com/nidlogin.login?mode=form&url=https%3A%2F%2Fcafe.naver.com%2F"

def ts_now():
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def is_m3u8(u: str) -> bool:
    return ".m3u8" in u.lower()

def normalize_query(u: str) -> str:
    pu = urlparse(u)
    qs = parse_qsl(pu.query, keep_blank_values=True)
    return urlunparse((pu.scheme, pu.netloc, pu.path, pu.params, urlencode(qs), pu.fragment))

async def wait_login(ctx, timeout_ms=120000):
    """NID_SES 쿠키가 보일 때까지 대기 (이미 로그인 상태면 즉시 True)"""
    end = time.time() + timeout_ms/1000
    while time.time() < end:
        for c in await ctx.cookies():
            if c.get("name") == "NID_SES" and c.get("value"):
                return True
        await asyncio.sleep(0.3)
    return False

async def fetch_text(page, url, headers):
    try:
        r = await page.request.get(url, headers=headers)
        if r.ok:
            return await r.text()
    except:
        pass
    return ""

def pick_first_last_ts(lines):
    """
    m3u8 본문에서 .ts 라인들을 찾아 첫/마지막 번호와 패딩폭(pad) 탐지.
    (000000.ts ~ 000XYZ.ts 같은 순번형에만 적용 가능)
    """
    ts_files = [ln.strip() for ln in lines if ln.strip().endswith(".ts") and not ln.strip().startswith("#")]
    if not ts_files:
        return None
    num_pat = re.compile(r"(\d+)\.ts(?:$|\?)")
    nums = []
    for u in ts_files:
        m = num_pat.search(u)
        if not m:
            continue
        s = m.group(1)
        nums.append((u, s, len(s)))
    if not nums:
        return None
    nums_sorted = sorted(nums, key=lambda x: int(x[1]))
    first_s, last_s = nums_sorted[0][1], nums_sorted[-1][1]
    pad = nums_sorted[0][2]
    return int(first_s), int(last_s), pad

def build_curl_url_from_m3u8(m3u8_url: str, first: int, last: int, pad: int) -> str:
    """
    .m3u8 → -[first-last].ts 로 치환 (패딩 유지)
    예) .../ABC.m3u8?token= → .../ABC-[000000-000123].ts?token=
    """
    pu = urlparse(m3u8_url)
    path = pu.path
    if not path.lower().endswith(".m3u8"):
        raise ValueError("m3u8 URL 형식이 아님")
    base = path[: -len(".m3u8")]
    rng = f"[{first:0{pad}d}-{last:0{pad}d}]"
    new_path = f"{base}-{rng}.ts"
    return urlunparse((pu.scheme, pu.netloc, new_path, pu.params, pu.query, pu.fragment))

def stamp_output_name(out_path: Path, stamp: str) -> Path:
    """
    최종 출력 파일명 뒤에 _<timestamp> 붙여 고유하게 저장.
    예) video.mp4 → video_20250813_221530.mp4
    """
    stem = out_path.stem
    suffix = out_path.suffix or ".mp4"
    return out_path.with_name(f"{stem}_{stamp}{suffix}")

async def run(args):
    async with async_playwright() as p:
        launch_kwargs = dict(headless=args.headless)
        if args.chrome_channel:
            launch_kwargs["channel"] = "chrome"
        browser = await p.chromium.launch(**launch_kwargs)

        state_file = Path(args.state_path).expanduser().resolve()
        use_state = state_file.exists() and not args.fresh_login

        if use_state:
            print(f"[i] 세션 캐시 사용: {state_file}")
            context = await browser.new_context(storage_state=str(state_file))
        else:
            context = await browser.new_context()
        page = await context.new_page()

        seen = []
        req_headers_by = {}
        media = []

        def on_request(req):
            u = req.url
            if is_m3u8(u):
                if u not in seen: seen.append(u)
                req_headers_by[u] = req.headers
        page.on("request", on_request)

        async def on_response(resp):
            u = resp.url
            if not is_m3u8(u): return
            try:
                t = await resp.text()
                if "#EXTINF" in t and u not in media:
                    media.append(u)
            except:
                pass
        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        already_logged_in = await wait_login(context, timeout_ms=1500)
        if already_logged_in and use_state:
            print("[✓] 캐시된 로그인 상태 감지")
        else:
            print(f"[i] 로그인 페이지: {LOGIN_URL}")
            await page.goto(LOGIN_URL, wait_until="domcontentloaded")
            if not await wait_login(context, args.login_timeout):
                print("[!] 로그인 감지 실패 (NID_SES 없음)"); await browser.close(); sys.exit(1)
            print("[✓] 로그인 완료")
            try:
                await context.storage_state(path=str(state_file))
                print(f"[i] 세션 저장: {state_file}")
            except Exception as e:
                print(f"[i] 세션 저장 실패(무시): {e}")

        print(f"[i] 이동: {args.url}")
        await page.goto(args.url, wait_until="domcontentloaded")
        print(f"[i] '재생'을 누르세요. {args.detect_window}s 동안 감지합니다…")

        end = time.time() + args.detect_window
        while time.time() < end:
            try:
                await page.wait_for_event("response", timeout=1000)
            except:
                pass
            if media:
                break
        if not seen:
            print("[!] m3u8 감지 실패"); await browser.close(); sys.exit(2)

        raw = media[-1] if media else seen[-1]
        m3u8 = normalize_query(raw)

        rh = {k.lower(): v for k, v in (req_headers_by.get(raw) or req_headers_by.get(seen[-1]) or {}).items()}
        ua = rh.get("user-agent") or (await page.evaluate("() => navigator.userAgent"))
        referer = rh.get("referer") or page.url
        cookies = rh.get("cookie")
        if not cookies:
            ck = await context.cookies()
            cookies = "; ".join([f"{c['name']}={c['value']}" for c in ck])

        fetch_headers = {
            "User-Agent": ua,
            "Referer": referer,
            "Origin": "https://cafe.naver.com",
            "Accept": "*/*",
            "Cookie": cookies
        }

        text = await fetch_text(page, m3u8, fetch_headers)
        if not text:
            print("[!] m3u8 본문 조회 실패"); await browser.close(); sys.exit(3)
        res = pick_first_last_ts(text.splitlines())
        if not res:
            print("[!] TS 번호 패턴을 찾지 못했습니다. (순번형 ts가 아닌 m3u8)")
            await browser.close(); sys.exit(4)
        first, last, pad = res

        stamp = args.tag if args.tag else ts_now()
        base_outdir = Path(args.outdir).expanduser().resolve()
        session_dir = base_outdir / stamp
        session_dir.mkdir(parents=True, exist_ok=True)

        curl_url = build_curl_url_from_m3u8(m3u8, first, last, pad)
        host = urlparse(curl_url).netloc

        print(f"[i] curl 범위 다운로드 → {session_dir}")
        curl_cmd = [
            "curl",
            "-L", "--compressed",
            "-A", ua,
            "-H", f"Referer: {referer}",
            "-H", "Origin: https://cafe.naver.com",
            "-H", f"Host: {host}",
            curl_url,
            "-o", "#1.ts"
        ]
        print("[i] 실행:", " ".join(shlex.quote(x) for x in curl_cmd))
        try:
            subprocess.check_call(curl_cmd, cwd=str(session_dir))
        except FileNotFoundError:
            print("[!] curl 필요 (macOS 기본 포함, 없으면 설치)"); await browser.close(); sys.exit(5)
        except subprocess.CalledProcessError as e:
            print(f"[!] curl 실패({e.returncode})"); await browser.close(); sys.exit(e.returncode)

        list_path = session_dir / "list.txt"
        with open(list_path, "w", encoding="utf-8") as f:
            for i in range(first, last + 1):
                f.write(f"file '{i:0{pad}d}.ts'\n")

        out_target = stamp_output_name(Path(args.out).expanduser().resolve(), stamp)
        ffmpeg_cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-f", "concat", "-safe", "0",
            "-i", str(list_path),
            "-c", "copy", "-bsf:a", "aac_adtstoasc",
            str(out_target)
        ]
        print("[i] ffmpeg 합치기:", " ".join(shlex.quote(x) for x in ffmpeg_cmd))
        try:
            subprocess.check_call(ffmpeg_cmd)
        except FileNotFoundError:
            print("[!] ffmpeg 필요. 설치 후 재시도하세요.")
            await browser.close(); sys.exit(6)
        except subprocess.CalledProcessError as e:
            print(f"[!] ffmpeg 실패({e.returncode})"); await browser.close(); sys.exit(e.returncode)

        print(f"[✓] 완료: {out_target}")
        print(f"[i] 세그먼트 보관 경로: {session_dir}")

        try:
            await context.storage_state(path=str(state_file))
        except:
            pass

        await browser.close()

def main():
    ap = argparse.ArgumentParser(description="Naver Cafe VOD")
    ap.add_argument("--url", required=True, help="카페 글/영상 URL")
    ap.add_argument("--out", required=True, help="최종 저장 파일(mp4). 실제 저장은 _<timestamp>가 붙습니다.")
    ap.add_argument("--outdir", default="./ts_parts", help="세그먼트 저장 베이스 폴더 (기본 ./ts_parts)")
    ap.add_argument("--tag", default="", help="고정 세션 태그(미지정 시 현재 시각 타임스탬프 사용)")

    ap.add_argument("--state-path", default="./naver_state.json",
                    help="Playwright storage_state 파일 경로(쿠키/세션 캐시)")
    ap.add_argument("--fresh-login", action="store_true",
                    help="세션 캐시 무시하고 새 로그인 진행")

    ap.add_argument("--headless", action="store_true", help="브라우저 창 숨김(로그인엔 비권장)")
    ap.add_argument("--chrome-channel", action="store_true", help="설치된 Chrome 채널로 실행(원하면 사용)")
    ap.add_argument("--login-timeout", type=int, default=120000, help="로그인 대기(ms)")
    ap.add_argument("--detect-window", type=int, default=25, help="재생 후 m3u8 감지 대기(초)")

    args = ap.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\n[!] 사용자 중단")

if __name__ == "__main__":
    main()
