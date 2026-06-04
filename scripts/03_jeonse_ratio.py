"""
03_jeonse_ratio.py
전세가율 계산 (이 프로젝트에서 가장 까다로운 단계)

핵심 아이디어:
  국토부 실거래가는 매매/전월세가 별도 파일이고, 같은 건물·면적을
  1:1 매칭하면 데이터가 대부분 버려진다.
  → 동 단위 평균 단가(원/㎡)로 집계해서 비율을 낸다.

  동별 전세가율 = (동별 평균 전세보증금/㎡) / (동별 평균 매매가/㎡) * 100

추가 변수:
  - 고전세가율 비율: 동별로 전세가율 80% 초과 거래 비중
    (단, 건물 단위 매칭이 되는 케이스에 한해 정밀 계산. 안 되면 동 평균으로 근사)
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path

EXT = Path(__file__).resolve().parents[1] / "data" / "external"
PROC = Path(__file__).resolve().parents[1] / "data" / "processed"
PROC.mkdir(parents=True, exist_ok=True)

HIGH_RATIO_THR = 80     # 고전세가율 기준(%)
RATIO_CAP = 200         # 비현실적 전세가율 상한(%) — 초과 시 이상치로 제거


def load_csv(path):
    """한국 공공데이터 인코딩 대응 (생성 파일은 utf-8-sig, 원본 공공데이터는 cp949)."""
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except (UnicodeDecodeError, Exception):
            continue
    raise ValueError(f"읽기 실패: {path}")


def clean_num(s):
    """콤마·공백이 섞인 금액/면적 문자열을 숫자로 정제."""
    return pd.to_numeric(
        s.astype(str).str.replace(",", "", regex=False).str.strip(),
        errors="coerce",
    )


def normalize_dong(df):
    """
    동 식별자 정규화.
    실거래가에는 10자리 법정동 전체코드가 없고 시군구코드(5자리)+법정동명만 있다.
    → 동 식별 키 = '시군구코드_법정동명'. 자치구는 구 단위 검증용으로 유지.
    """
    df = df.copy()
    df["시군구코드"] = df["법정동시군구코드"].astype("Int64").astype(str).str.zfill(5)
    df["동이름"] = df["법정동"].astype(str).str.strip()
    df["법정동코드"] = df["시군구코드"] + "_" + df["동이름"]
    df["지번"] = df["지번"].astype(str).str.strip()
    return df


def main():
    sale = load_csv(EXT / "villa_sale.csv")    # 연립다세대 매매
    rent = load_csv(EXT / "villa_rent.csv")    # 연립다세대 전월세

    # --- 금액/면적 정제 ---
    sale["거래금액"] = clean_num(sale["거래금액"])
    sale["전용면적"] = clean_num(sale["전용면적"])
    rent["보증금액"] = clean_num(rent["보증금액"])
    rent["월세금액"] = clean_num(rent["월세금액"])
    rent["전용면적"] = clean_num(rent["전용면적"])

    # --- 전세만 필터 (월세금액 == 0): 월세/준전세 제외 ---
    rent = rent[rent["월세금액"].fillna(0) == 0].copy()

    # --- 이상치: 전용면적 0/결측, 금액 0/결측 제거 ---
    sale = sale[(sale["전용면적"] > 0) & (sale["거래금액"] > 0)].copy()
    rent = rent[(rent["전용면적"] > 0) & (rent["보증금액"] > 0)].copy()

    # --- 단위면적당 가격(만원/㎡) ---
    sale["매매_per_m2"] = sale["거래금액"] / sale["전용면적"]
    rent["전세_per_m2"] = rent["보증금액"] / rent["전용면적"]

    sale = normalize_dong(sale)
    rent = normalize_dong(rent)

    # --- 동 단위 평균 단가 ---
    sale_dong = sale.groupby("법정동코드")["매매_per_m2"].mean()
    rent_dong = rent.groupby("법정동코드")["전세_per_m2"].mean()

    # --- 동별 전세가율 = (동평균 전세/㎡) / (동평균 매매/㎡) * 100 ---
    dong = pd.concat(
        {"매매_per_m2": sale_dong, "전세_per_m2": rent_dong}, axis=1
    ).dropna()
    dong["전세가율"] = dong["전세_per_m2"] / dong["매매_per_m2"] * 100

    # --- 고전세가율 비율 ---
    # 정밀: 같은 건물(시군구+법정동+지번)로 매매 단가를 매칭해 건별 전세가율 산출.
    # 근사: 매칭되는 매매 거래가 없는 전세 건은 동 평균 매매 단가로 대체(아래 fillna).
    bld_sale = sale.groupby(["법정동코드", "지번"])["매매_per_m2"].mean().rename("매매_per_m2_건물")
    rent = rent.join(bld_sale, on=["법정동코드", "지번"])
    rent = rent.join(sale_dong.rename("매매_per_m2_동평균"), on="법정동코드")
    rent["매매_per_m2_기준"] = rent["매매_per_m2_건물"].fillna(rent["매매_per_m2_동평균"])
    rent["건별전세가율"] = rent["전세_per_m2"] / rent["매매_per_m2_기준"] * 100

    # 건별 이상치(0 이하 또는 RATIO_CAP 초과) 제거 후 동별 80% 초과 비중 + 거래건수
    valid = rent[(rent["건별전세가율"] > 0) & (rent["건별전세가율"] <= RATIO_CAP)].copy()
    valid["고전세가율"] = valid["건별전세가율"] > HIGH_RATIO_THR
    high_share = (valid.groupby("법정동코드")["고전세가율"].mean() * 100).rename("고전세가율비율")
    rent_cnt = valid.groupby("법정동코드").size().rename("거래건수")   # 유효 전세 거래건수

    # 동 이름·자치구 매핑
    name_map = rent.groupby("법정동코드")["동이름"].first()
    gu_map = rent.groupby("법정동코드")["자치구"].first()

    # --- 결과 조립 ---
    result = dong.reset_index()
    result["동이름"] = result["법정동코드"].map(name_map)
    result["자치구"] = result["법정동코드"].map(gu_map)
    result["고전세가율비율"] = result["법정동코드"].map(high_share).fillna(0)
    result["거래건수"] = result["법정동코드"].map(rent_cnt).fillna(0).astype(int)

    # 동 단위 이상치: 전세가율 RATIO_CAP 초과 제거
    result = result[result["전세가율"] <= RATIO_CAP].copy()

    result["전세가율"] = result["전세가율"].round(2)
    result["고전세가율비율"] = result["고전세가율비율"].round(1)
    result = result[["법정동코드", "동이름", "자치구", "전세가율", "고전세가율비율", "거래건수"]]
    result = result.sort_values("전세가율", ascending=False).reset_index(drop=True)

    out = PROC / "jeonse_ratio_dong.csv"
    result.to_csv(out, index=False, encoding="utf-8-sig")

    # --- 확인 통계 ---
    print(f"저장: {out}")
    print(f"집계된 동 개수: {len(result)}개")
    r = result["전세가율"]
    print(f"전세가율 min/median/max: {r.min():.2f} / {r.median():.2f} / {r.max():.2f}")
    print(f"전세가율 80% 초과 동: {(r > HIGH_RATIO_THR).sum()}개")
    print("\n자치구별 평균 전세가율 상위 5개 구:")
    gu_top = result.groupby("자치구")["전세가율"].mean().sort_values(ascending=False).head(5)
    for gu, v in gu_top.items():
        print(f"  {gu}: {v:.2f}%")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
