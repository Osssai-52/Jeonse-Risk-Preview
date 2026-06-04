"""
02b_typemix.py  (설계 v3)
주택유형 구성비 + 다가구 분포 변수 — 행정동(adm_cd) 단위.

구성비(전월세 전체 실거래 건수 기준, 표제부 코드 문제 회피):
  villa_share / apt_share / officetel_share = 유형별 전월세거래수 / 동 전체 전월세거래수
  (전세+월세 모두 포함. 오피스텔은 75%가 월세라 전세만 세면 과소대표 → 전월세 전체로 집계)
다가구(전세 실거래 없음 → 구성비 제외):
  dagagu_count = 표제부 '단독주택 & 가구수>=2' 건물 수 (동 분포 변수로만 유지)

매핑: 전세거래는 법정동명→KIKmix→adm(이름매칭), 표제부는 10자리코드 직매칭. 1:N복제/N:1합산.
출력: data/processed/dong_typemix_adm.csv
"""

import sys
import glob
import os
import numpy as np
import pandas as pd
from pathlib import Path

EXT = Path(__file__).resolve().parents[1] / "data" / "external"
PROC = Path(__file__).resolve().parents[1] / "data" / "processed"
KIK_PATH = EXT / "KIKmix.20210401.xlsx"
OUT = PROC / "dong_typemix_adm.csv"

RENT_FILES = {"villa": "villa_rent.csv", "apt": "apt_rent.csv", "officetel": "officetel_rent.csv"}


def load_csv(path, **kw):
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc, dtype=str, low_memory=False, **kw)
        except (UnicodeDecodeError, Exception):
            continue
    raise ValueError(f"읽기 실패: {path}")


def kik_maps():
    kik = pd.read_excel(KIK_PATH, dtype=str)
    kik = kik[kik["시도명"] == "서울특별시"]
    mal = kik["말소일자"].astype(str).str.strip()
    kik = kik[(kik["말소일자"].isna() | (mal == "") | (mal.str.lower() == "nan"))
              & kik["읍면동명"].notna() & kik["동리명"].notna()].copy()
    kik["bjd_name"] = kik["법정동코드"].str[:5] + "_" + kik["동리명"].str.strip()
    name_map = kik[["bjd_name", "행정동코드", "읍면동명", "시군구명"]].drop_duplicates()
    code_map = kik[["법정동코드", "행정동코드"]].drop_duplicates()  # 표제부 10자리 직매칭
    return name_map, code_map


def rent_counts_by_type():
    """유형별 전월세 전체 거래수를 법정동명키로 집계 + 오피스텔 전세/월세 비중 진단."""
    rows = []
    diag = {}
    for typ, f in RENT_FILES.items():
        d = load_csv(EXT / f, usecols=["법정동시군구코드", "법정동", "월세금액"])
        wol = pd.to_numeric(d["월세금액"], errors="coerce").fillna(0)
        diag[typ] = (int((wol == 0).sum()), len(d))  # (전세수, 전월세 전체)
        d["유형"] = typ
        d["bjd_name"] = d["법정동시군구코드"].str.zfill(5) + "_" + d["법정동"].str.strip()
        rows.append(d[["bjd_name", "유형"]])
    allr = pd.concat(rows, ignore_index=True)
    cnt = allr.groupby(["bjd_name", "유형"]).size().unstack(fill_value=0)
    return cnt, diag


def dagagu_counts():
    """표제부 단독주택&가구수>=2 = 다가구 건물수, 10자리 법정동코드 기준."""
    frames = []
    for f in sorted(glob.glob(str(EXT / "03. 표제부_*.csv"))):
        d = load_csv(f, usecols=["시군구코드", "법정동코드", "주용도코드명", "가구수(가구)"])
        d = d[d["주용도코드명"] == "단독주택"].copy()
        d["가구"] = pd.to_numeric(d["가구수(가구)"], errors="coerce")
        d = d[d["가구"] >= 2]
        d["bjd10"] = d["시군구코드"].str.zfill(5) + d["법정동코드"].str.zfill(5)
        frames.append(d[["bjd10"]])
    allb = pd.concat(frames, ignore_index=True)
    return allb.groupby("bjd10").size().rename("dagagu_count")


def main():
    name_map, code_map = kik_maps()
    cnt, diag = rent_counts_by_type()         # index=bjd_name, cols=villa/apt/officetel
    daga = dagagu_counts()                    # index=bjd10

    # 구성비: 전월세 전체 거래수. 법정동명 → adm (1:N 복제), N:1 합산 (비율이라 복제 무해)
    c = cnt.reset_index().merge(name_map, on="bjd_name", how="inner")
    g = c.groupby("행정동코드")
    out = pd.DataFrame({"adm_nm": g["읍면동명"].first(), "자치구": g["시군구명"].first()})
    for t in ["villa", "apt", "officetel"]:
        out[t] = g[t].sum() if t in c.columns else 0
    out["rent_n"] = out[["villa", "apt", "officetel"]].sum(axis=1)
    for t in ["villa", "apt", "officetel"]:
        out[t + "_share"] = np.where(out["rent_n"] > 0, out[t] / out["rent_n"], np.nan).round(4)

    # 다가구: 표제부 10자리 → adm. 절대카운트라 1:N은 복제 대신 '균등배분'(건물수/행정동수)으로
    # 분배해 총량 보존(복제 시 분할 법정동에서 3~4배 과대계상되어 위험지역에 허위신호).
    n_adm = code_map.groupby("법정동코드")["행정동코드"].nunique()
    dd = daga.reset_index().merge(code_map, left_on="bjd10", right_on="법정동코드", how="inner")
    dd["share"] = dd["dagagu_count"] / dd["법정동코드"].map(n_adm)
    daga_adm = dd.groupby("행정동코드")["share"].sum()
    out["dagagu_count"] = out.index.map(daga_adm).fillna(0).round().astype(int)

    out = out.reset_index().rename(columns={"행정동코드": "adm_cd"})
    out = out[["adm_cd", "adm_nm", "자치구", "rent_n",
               "villa_share", "apt_share", "officetel_share", "dagagu_count"]]
    out = out.sort_values("adm_cd").reset_index(drop=True)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")

    # ---- 확인 ----
    print(f"저장: {OUT}  ({len(out)}개 행정동)  ※ 구성비 = 전월세 전체 거래 기준")
    print("\n[유형별 전세/월세 비중 진단]")
    for t, (jn, tot) in diag.items():
        print(f"  {t}: 전월세 전체 {tot:,}건 중 전세 {jn:,}건 ({jn/tot*100:.1f}%)")
    print("\n[구성비 평균(동 단위, 전월세 전체 기준)]")
    for t in ["villa", "apt", "officetel"]:
        print(f"  {t}_share 평균 {out[t+'_share'].mean():.3f}  (결측 {out[t+'_share'].isna().sum()})")
    print(f"\ndagagu_count: 합 {out['dagagu_count'].sum():,}  "
          f"min/median/max {out['dagagu_count'].min()}/{out['dagagu_count'].median():.0f}/{out['dagagu_count'].max()}")
    print("\n오피스텔 구성비(전월세) 상위5 동:")
    for _, r in out.sort_values("officetel_share", ascending=False).head(5).iterrows():
        print(f"  {r['자치구']} {r['adm_nm']}: {r['officetel_share']:.3f} (전월세 {int(r['rent_n'])}건)")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
