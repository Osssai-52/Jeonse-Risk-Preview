"""
03_jeonse_ratio_all.py  (설계 v3)
전세가율을 '주택유형 무관'으로 재산출 — 동 전체 전세거래(아파트+빌라+오피스텔)
÷ 동 전체 매매. 행정동(adm_cd) 단위. 단독·다가구는 가격 산출 불가라 제외(설계 v3).

입력(6종, data/external):
  villa_sale/apt_sale/officetel_sale  (매매: 거래금액)
  villa_rent/apt_rent/officetel_rent  (전월세: 보증금액·월세금액)
공통 핵심컬럼: 법정동시군구코드, 법정동, 지번, 전용면적, (매매)거래금액 / (전월세)보증금액·월세금액

산출:
  전세가율        = (동평균 전세/㎡) / (동평균 매매/㎡) × 100
  고전세가율비율  = 건물(시군구+법정동+지번) 매칭 건별 전세가율 80%↑ 비중(매칭 안되면 동평균)
  jeonse_per_m2   = 동평균 전세/㎡(만원) — 04 괴리변수용
매핑: 법정동(시군구5_법정동명) → KIKmix → 행정동코드(adm_cd). 1:N 복제, N:1 거래건수 가중.

출력: data/processed/jeonse_ratio_all_adm.csv
  (기존 villa 전용 jeonse_ratio_adm.csv 는 비교용으로 보존)
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path

EXT = Path(__file__).resolve().parents[1] / "data" / "external"
PROC = Path(__file__).resolve().parents[1] / "data" / "processed"
KIK_PATH = EXT / "KIKmix.20210401.xlsx"
OUT = PROC / "jeonse_ratio_all_adm.csv"

SALE_FILES = ["villa_sale.csv", "apt_sale.csv", "officetel_sale.csv"]
RENT_FILES = ["villa_rent.csv", "apt_rent.csv", "officetel_rent.csv"]
HIGH_THR, RATIO_CAP = 80, 200


def load_csv(path):
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc, dtype=str, low_memory=False)
        except (UnicodeDecodeError, Exception):
            continue
    raise ValueError(f"읽기 실패: {path}")


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(),
                         errors="coerce")


def stack(files, tag):
    frames = []
    for f in files:
        d = load_csv(EXT / f)
        d = d[["법정동시군구코드", "법정동", "지번", "전용면적"] +
              ([ "거래금액"] if tag == "sale" else ["보증금액", "월세금액"])].copy()
        d["유형"] = f.split("_")[0]
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    df["전용면적"] = num(df["전용면적"])
    df["bjd"] = (df["법정동시군구코드"].str.zfill(5) + "_" + df["법정동"].str.strip())
    df["지번"] = df["지번"].astype(str).str.strip()
    return df


def main():
    sale = stack(SALE_FILES, "sale")
    sale["거래금액"] = num(sale["거래금액"])
    sale = sale[(sale["전용면적"] > 0) & (sale["거래금액"] > 0)].copy()
    sale["매매_per_m2"] = sale["거래금액"] / sale["전용면적"]

    rent = stack(RENT_FILES, "rent")
    rent["보증금액"] = num(rent["보증금액"]); rent["월세금액"] = num(rent["월세금액"])
    rent = rent[(rent["월세금액"].fillna(0) == 0) &
                (rent["전용면적"] > 0) & (rent["보증금액"] > 0)].copy()
    rent["전세_per_m2"] = rent["보증금액"] / rent["전용면적"]

    # 동(법정동) 평균 단가
    sale_dong = sale.groupby("bjd")["매매_per_m2"].mean()
    rent_dong = rent.groupby("bjd")["전세_per_m2"].mean()
    dong = pd.concat({"매매_per_m2": sale_dong, "전세_per_m2": rent_dong}, axis=1).dropna()
    dong["전세가율"] = dong["전세_per_m2"] / dong["매매_per_m2"] * 100

    # 고전세가율비율: 건물(법정동+지번) 단위 매칭, 안되면 동평균
    bld = sale.groupby(["bjd", "지번"])["매매_per_m2"].mean().rename("매매_bld")
    rent = rent.join(bld, on=["bjd", "지번"]).join(sale_dong.rename("매매_dong"), on="bjd")
    rent["매매_ref"] = rent["매매_bld"].fillna(rent["매매_dong"])
    rent["건별"] = rent["전세_per_m2"] / rent["매매_ref"] * 100
    valid = rent[(rent["건별"] > 0) & (rent["건별"] <= RATIO_CAP)].copy()
    high = (valid.assign(h=valid["건별"] > HIGH_THR).groupby("bjd")["h"].mean() * 100)
    cnt = valid.groupby("bjd").size()

    # KIKmix 법정동명 → adm_cd (1:N)
    kik = pd.read_excel(KIK_PATH, dtype=str)
    kik = kik[kik["시도명"] == "서울특별시"]
    mal = kik["말소일자"].astype(str).str.strip()
    kik = kik[(kik["말소일자"].isna() | (mal == "") | (mal.str.lower() == "nan"))
              & kik["읍면동명"].notna() & kik["동리명"].notna()].copy()
    kik["bjd"] = kik["법정동코드"].str[:5] + "_" + kik["동리명"].str.strip()
    kmap = kik[["bjd", "행정동코드", "읍면동명", "시군구명"]].drop_duplicates()

    d = dong.reset_index()
    d["jeonse_per_m2"] = d["전세_per_m2"].round(2)
    d["고전세가율비율"] = d["bjd"].map(high)
    d["거래건수"] = d["bjd"].map(cnt)
    m = d.merge(kmap, on="bjd", how="inner")

    # N:1 거래건수 가중 집계
    m["w"] = m["거래건수"].fillna(0).clip(lower=0)
    for c in ["전세가율", "고전세가율비율", "jeonse_per_m2"]:
        m[c + "_w"] = m[c] * m["w"]
    g = m.groupby("행정동코드")
    out = pd.DataFrame({
        "adm_nm": g["읍면동명"].first(), "자치구": g["시군구명"].first(),
        "w": g["w"].sum(), "거래건수": g["w"].sum().astype(int),
    })
    for c in ["전세가율", "고전세가율비율", "jeonse_per_m2"]:
        ws = g[c + "_w"].sum(); sm = g[c].mean()
        out[c] = np.where(out["w"] > 0, ws / out["w"], sm)
    out = out[out["전세가율"] <= RATIO_CAP].reset_index().rename(columns={"행정동코드": "adm_cd"})
    out["전세가율"] = out["전세가율"].round(2)
    out["고전세가율비율"] = out["고전세가율비율"].round(1)
    out["jeonse_per_m2"] = out["jeonse_per_m2"].round(2)
    out = out[["adm_cd", "adm_nm", "자치구", "전세가율", "고전세가율비율", "jeonse_per_m2", "거래건수"]]
    out = out.sort_values("전세가율", ascending=False).reset_index(drop=True)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")

    # ---- 확인 ----
    print(f"저장: {OUT}")
    print(f"매매 거래 {len(sale):,} / 전세 거래 {len(valid):,} (월세제외·정제후)")
    print(f"집계 행정동: {len(out)}개")
    r = out["전세가율"]
    print(f"전세가율 min/median/max: {r.min():.2f}/{r.median():.2f}/{r.max():.2f}")
    print(f"전세가율 80%↑ 동: {(r > HIGH_THR).sum()}개")
    print("자치구 평균 전세가율 상위5:")
    for gu, v in out.groupby("자치구")["전세가율"].mean().sort_values(ascending=False).head(5).items():
        print(f"  {gu}: {v:.2f}%")

    # villa 전용과 비교
    vp = PROC / "jeonse_ratio_adm.csv"
    if vp.exists():
        v = pd.read_csv(vp, encoding="utf-8-sig", dtype={"adm_cd": str})[["adm_cd", "전세가율"]]
        cmp = out.merge(v, on="adm_cd", suffixes=("_all", "_villa")).dropna()
        print(f"\nvilla전용 대비(공통 {len(cmp)}동): 평균 전세가율 "
              f"all {cmp['전세가율_all'].mean():.2f}% vs villa {cmp['전세가율_villa'].mean():.2f}% | "
              f"상관 {cmp['전세가율_all'].corr(cmp['전세가율_villa']):.3f}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
