"""
03b_attach_adm.py
03 결과(법정동 기준 전세가율)에 행정동 코드를 부착한다.

매핑표: data/external/KIKmix.20210401.xlsx (법정동↔행정동)
  컬럼: 행정동코드, 시도명, 시군구명, 읍면동명(행정동명),
        법정동코드, 동리명(법정동명), 생성일자, 말소일자
  (행정동코드·법정동코드는 모두 10자리, 시군구 = 앞 5자리)

매칭 키:
  03 결과의 동 키 = "시군구코드5_법정동명"
  KIKmix       = 법정동코드[:5] + "_" + 동리명
  → 원본 실거래가/03 결과에 10자리 법정동 전체코드가 없어 이름 기반 매칭만 가능.
    (실측 결과 313개 동 전부 매칭 성공, 코드 직접 매칭 보강 불필요)

카디널리티 처리:
  - 1:N (법정동 1개 → 행정동 N개): 비율 변수라 N분할 없이 각 행정동에 그대로 복제.
  - N:1 (법정동 N개 → 행정동 1개): 거래건수 가중평균으로 합산(adm_cd 유일성 유지).
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path

EXT = Path(__file__).resolve().parents[1] / "data" / "external"
PROC = Path(__file__).resolve().parents[1] / "data" / "processed"

KIK_PATH = EXT / "KIKmix.20210401.xlsx"
SRC = PROC / "jeonse_ratio_dong.csv"
OUT = PROC / "jeonse_ratio_adm.csv"


def load_mapping():
    """서울 활성 법정동↔행정동 매핑 테이블 추출."""
    kik = pd.read_excel(KIK_PATH, dtype=str)
    kik = kik[kik["시도명"] == "서울특별시"].copy()
    # 말소(폐지) 행 제외 — 결측/공백이면 활성
    말소 = kik["말소일자"].astype(str).str.strip()
    kik = kik[kik["말소일자"].isna() | (말소 == "") | (말소.str.lower() == "nan")]
    # 상위 집계 행(시도·시군구 레벨) 제외: 행정동명/법정동명이 있어야 실제 동
    kik = kik[kik["읍면동명"].notna() & kik["동리명"].notna()].copy()

    kik["시군구5"] = kik["법정동코드"].str[:5]
    kik["match_key"] = kik["시군구5"] + "_" + kik["동리명"].str.strip()
    return kik[["match_key", "행정동코드", "읍면동명", "시군구명"]].drop_duplicates()


def main():
    res = pd.read_csv(SRC, encoding="utf-8-sig", dtype={"법정동코드": str})
    m = load_mapping()

    total_adm_seoul = m["행정동코드"].nunique()

    # --- 매칭 (1:N 복제는 merge 확장으로 자동 처리) ---
    merged = res.merge(m, left_on="법정동코드", right_on="match_key", how="left")
    matched = merged[merged["행정동코드"].notna()].copy()

    # 매칭 실패 법정동 목록
    unmatched = res[~res["법정동코드"].isin(m["match_key"])].copy()

    # --- N:1 합산: 거래건수 가중평균 (가중치 합 0이면 단순평균 대체) ---
    matched["w"] = matched["거래건수"].clip(lower=0)
    matched["전세가율_w"] = matched["전세가율"] * matched["w"]
    matched["고_w"] = matched["고전세가율비율"] * matched["w"]

    g = matched.groupby("행정동코드")
    agg = pd.DataFrame({
        "adm_nm": g["읍면동명"].first(),
        "자치구": g["자치구"].first(),
        "w_sum": g["w"].sum(),
        "전세가율_wsum": g["전세가율_w"].sum(),
        "고_wsum": g["고_w"].sum(),
        "전세가율_simple": g["전세가율"].mean(),
        "고_simple": g["고전세가율비율"].mean(),
        "거래건수": g["거래건수"].sum(),
    })
    agg["전세가율"] = np.where(
        agg["w_sum"] > 0, agg["전세가율_wsum"] / agg["w_sum"], agg["전세가율_simple"]
    ).round(2)
    agg["고전세가율비율"] = np.where(
        agg["w_sum"] > 0, agg["고_wsum"] / agg["w_sum"], agg["고_simple"]
    ).round(1)

    agg = agg.reset_index().rename(columns={"행정동코드": "adm_cd"})
    agg["거래건수"] = agg["거래건수"].astype(int)
    out = agg[["adm_cd", "adm_nm", "자치구", "전세가율", "고전세가율비율", "거래건수"]]
    out = out.sort_values("전세가율", ascending=False).reset_index(drop=True)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")

    # --- 확인 ---
    print(f"저장: {OUT}")
    print(f"값이 붙은 행정동 개수: {len(out)}개")
    print(f"서울 전체 행정동(KIKmix 기준 {total_adm_seoul}개) 중 커버리지: "
          f"{len(out) / total_adm_seoul * 100:.1f}%")
    print(f"\n매칭 실패한 법정동: {len(unmatched)}개")
    if len(unmatched):
        for _, r in unmatched.iterrows():
            print(f"  {r['법정동코드']} ({r['자치구']} {r['동이름']})")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
