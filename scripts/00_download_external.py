"""
00_download_external.py
외부 데이터 다운로드: 국토교통부 실거래가 (전체 주택 유형, 매매 + 전월세)

[방법 1 - 권장] 공공데이터포털 OpenAPI + PublicDataReader
  사전 준비:
    1) https://www.data.go.kr 회원가입
    2) 아래 유형별 "매매/전월세 실거래가 자료" 활용신청
       (연립다세대, 아파트, 오피스텔 — 각 매매/전월세)
    3) 발급받은 인증키를 환경변수 MOLIT_API_KEY 에 저장 (또는 SERVICE_KEY 직접 입력)
    4) pip install PublicDataReader

[방법 2 - 수동] rt.molit.go.kr → 자료제공 메뉴에서 CSV 다운로드 → data/external/

수집 대상 (서울 25개 자치구, 2024.06 ~ 2026.05):
  - 연립다세대 매매/전월세 (villa_sale/villa_rent)
  - 아파트       매매/전월세 (apt_sale/apt_rent)
  - 오피스텔     매매/전월세 (officetel_sale/officetel_rent)
  ※ 단독·다가구는 제외: 지번·전용면적이 개인정보로 마스킹돼 전세가율 계산 불가.

기존 파일은 건너뛴다(SKIP_EXISTING). 다시 받으려면 해당 csv 삭제 후 재실행.
"""

import os
import time
import pandas as pd
from pathlib import Path

# ---- 설정 ----
SERVICE_KEY = os.environ.get("MOLIT_API_KEY", "your-api-key")
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "external"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 서울 25개 자치구 법정동 코드 앞5자리 (시군구코드)
SEOUL_SIGUNGU = {
    "종로구": "11110", "중구": "11140", "용산구": "11170", "성동구": "11200",
    "광진구": "11215", "동대문구": "11230", "중랑구": "11260", "성북구": "11290",
    "강북구": "11305", "도봉구": "11320", "노원구": "11350", "은평구": "11380",
    "서대문구": "11410", "마포구": "11440", "양천구": "11470", "강서구": "11500",
    "구로구": "11530", "금천구": "11545", "영등포구": "11560", "동작구": "11590",
    "관악구": "11620", "서초구": "11650", "강남구": "11680", "송파구": "11710",
    "강동구": "11740",
}

# 수집 기간 (현재 시점 진단이므로 최신 24개월)
START_YM = "202406"
END_YM = "202605"

SKIP_EXISTING = True

# (부동산유형, 거래유형, 출력파일) — 단독다가구 제외
TARGETS = [
    ("연립다세대", "매매", "villa_sale.csv"),
    ("연립다세대", "전월세", "villa_rent.csv"),
    ("아파트", "매매", "apt_sale.csv"),
    ("아파트", "전월세", "apt_rent.csv"),
    ("오피스텔", "매매", "officetel_sale.csv"),
    ("오피스텔", "전월세", "officetel_rent.csv"),
]


MAX_RETRY = 4   # 구 단위 빈 결과(throttling/403) 재시도 횟수


def fetch_gu(api, property_type, trade_type, code):
    """한 구를 수집. 빈 결과(throttling 추정)면 backoff 후 재시도.
    서울 모든 구는 24개월간 거래가 반드시 있으므로 0건=실패로 간주하고 재시도."""
    for attempt in range(1, MAX_RETRY + 1):
        try:
            df = api.get_data(
                property_type=property_type, trade_type=trade_type,
                sigungu_code=code, start_year_month=START_YM, end_year_month=END_YM,
            )
        except Exception as e:
            df = None
            if attempt == MAX_RETRY:
                print(f"    예외(최종): {e}")
        if df is not None and len(df):
            return df, attempt
        time.sleep(min(2 ** attempt, 10))   # 2,4,8,10s backoff
    return None, MAX_RETRY


def download_one(api, property_type, trade_type, fname):
    """한 (유형, 거래유형)을 서울 25개 구에 대해 수집 → csv 저장."""
    out_path = OUT_DIR / fname
    if SKIP_EXISTING and out_path.exists():
        print(f"건너뜀(이미 있음): {fname}")
        return
    frames, failed = [], []
    for gu, code in SEOUL_SIGUNGU.items():
        df, attempt = fetch_gu(api, property_type, trade_type, code)
        if df is not None and len(df):
            df["자치구"] = gu
            frames.append(df)
            tag = "" if attempt == 1 else f" (재시도 {attempt}회)"
            print(f"  [{property_type}/{trade_type}] {gu}: {len(df)}건{tag}")
        else:
            failed.append(gu)
            print(f"  [{property_type}/{trade_type}] {gu}: 실패(0건)")
        time.sleep(0.3)
    if frames:
        out = pd.concat(frames, ignore_index=True)
        out.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"저장: {out_path}  총 {len(out)}건  성공 {len(frames)}/25구"
              f"{'  실패:'+','.join(failed) if failed else ''}\n")
    else:
        print(f"저장 안함: {fname}  전 구 실패\n")


def download_via_api():
    """PublicDataReader로 TARGETS 전체 수집."""
    from PublicDataReader import TransactionPrice

    api = TransactionPrice(SERVICE_KEY)
    for property_type, trade_type, fname in TARGETS:
        download_one(api, property_type, trade_type, fname)


if __name__ == "__main__":
    if SERVICE_KEY == "여기에_인증키_입력":
        print("인증키가 없습니다. 둘 중 하나를 하세요:")
        print(" 1) 환경변수 MOLIT_API_KEY 설정 후 재실행")
        print(" 2) rt.molit.go.kr 자료제공 메뉴에서 수동 다운로드 → data/external/")
    else:
        download_via_api()
