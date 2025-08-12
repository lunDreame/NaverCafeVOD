# Naver Cafe VOD Downloader

네이버 카페 동영상을 **Playwright**와 **curl**, **ffmpeg**를 이용해 다운로드하는 Python3 스크립트입니다.  
`.m3u8` 스트리밍 주소를 자동 감지하고 TS 세그먼트를 다운로드 후 병합하여 `.mp4` 파일로 저장합니다.

---

## 📦 특징

- **자동 로그인 지원**: NID 쿠키를 감지하여 세션 캐시를 재사용 (state 파일 저장)
- **m3u8 자동 감지**: 브라우저에서 재생 버튼을 누르면 자동 추출
- **TS 세그먼트 병합**: ffmpeg를 이용한 빠른 합치기 (재인코딩 없음)
- **범위 다운로드**: curl의 `[first-last].ts` 패턴을 사용하여 빠르게 다운로드
- **세션 태그 관리**: 다운로드 시각을 기반으로 한 세션 디렉토리 생성

---

## 📋 설치

### 1. Python 환경 준비
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install playwright
pip install --upgrade pip
```

### 2. Playwright 브라우저 설치
```bash
playwright install chromium
```
> 기본적으로 Chromium을 사용하지만 --chrome-channel 옵션으로 로컬 크롬 브라우저도 사용 가능.

### 3. 필수 프로그램
- curl (macOS 기본 포함 / Ubuntu: sudo apt install curl)
- ffmpeg (macOS: brew install ffmpeg, Ubuntu: sudo apt install ffmpeg)

---

## 🚀 사용법

```bash
python naver_cafe_vod.py \
  --url "https://cafe.naver.com/카페명/게시글번호" \
  --out "~/Downloads/video.mp4"
```

### 주요 옵션

|옵션 |설명 |기본값 |
| --- | --- | --- |
| --url | 카페 글 또는 영상 페이지 URL | 필수 |
| --out | 최종 저장할 MP4 파일 경로 (자동으로 _타임스탬프 추가됨) | 필수 |
| --outdir | TS 세그먼트 저장 폴더 베이스 경로 | ./ts_parts |
| --tag | 세션 태그 (미지정 시 현재 시각) | 빈 문자열 |
| --state-path | Playwright 세션 캐시(JSON) 저장 경로 | ./naver_state.json |
| --fresh-login | 세션 무시하고 새 로그인 | False |
| --headless | 브라우저 창 숨김 (로그인엔 비권장) | False |
| --chrome-channel | 설치된 Chrome으로 실행 | False |
| --login-timeout | 로그인 대기 시간(ms) | 120000 |
| --detect-window | 재생 후 m3u8 감지 대기 시간(초) | 25 |

---

## 📂 동작 방식

1. Playwright 브라우저 실행
2. 네이버 로그인
    - 세션 캐시 파일(naver_state.json)이 있으면 재사용
    - 없거나 --fresh-login 시 직접 로그인 필요
3. 영상 재생 버튼 클릭
    - --detect-window 시간 동안 .m3u8 요청 감지
4. m3u8 다운로드 후 TS 범위 계산
5. curl로 TS 세그먼트 다운로드
6. ffmpeg로 MP4 합치기
7. 결과 저장 + TS 세그먼트 보관

### 💡 예제

```bash
# 기본 사용
python naver_cafe_vod.py \
  --url "https://cafe.naver.com/f-e/123456" \
  --out "naver_video.mp4"

# 세션 캐시 무시하고 새 로그인
python naver_cafe_vod.py \
  --url "https://cafe.naver.com/f-e/123456" \
  --out "video.mp4" \
  --fresh-login

# 크롬 채널로 실행 (Playwright Chromium 대신)
python naver_cafe_vod.py \
  --url "https://cafe.naver.com/f-e/123456" \
  --out "video.mp4" \
  --chrome-channel
```

---

## ⚠️ 주의사항

- DRM(예: SAMPLE-AES, Widevine) 적용 영상은 다운로드 불가
- 네이버 카페 정책에 따라 로그인 후에만 재생 가능한 영상은 반드시 로그인 필요
- 법적으로 허용되지 않는 영상 다운로드는 금지
- **본 스크립트 사용으로 인해 발생하는 모든 문제에 대해 본 저자는 책임지지 않습니다.**  
  사용자는 해당 스크립트를 자신의 책임 하에 사용해야 하며, 관련 법률 및 규정을 반드시 준수해야 합니다.

---

## 📜 라이선스

이 스크립트는 개인 학습 및 연구 목적으로만 사용해야 합니다.
저작권이 있는 영상을 무단으로 다운로드하는 것은 법적으로 제재를 받을 수 있습니다.
