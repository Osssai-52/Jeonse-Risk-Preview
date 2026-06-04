"""
02d_pop_density.py  (설계 v3)
인구밀도 변수 — 동 인구 / 동 면적(km²). 행정동(adm_cd) 단위.

인구: B031 서울 행정동 거주인구(data/raw, 성별×연령 분리 → 행정동 합산). 최신 기준연월 사용.
면적: building_vars_adm.csv 의 area_km2 (경계파일 EPSG:5179 기반).
키: B031 ADMI_CD(8자리) == adm_cd[:8] (adm_cd 끝 2자리는 항상 '00').
출력: data/processed/dong_popdensity_adm.csv
"""

import sys
import pandas as pd
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
PROC = Path(__file__).resolve().parents[1] / "data" / "processed"
B031 = RAW / "B031. 서울시 행정동 단위 거주인구 데이터" / "2. 파일데이터" / "TB_T_RSPOP_ADMI.txt"
BVARS = PROC / "building_vars_adm.csv"
OUT = PROC / "dong_popdensity_adm.csv"


def load_b031():
    d = pd.read_csv(B031, encoding="utf-8-sig", sep="|", engine="python", dtype=str)
    d.columns = [c.strip().strip("`").strip() for c in d.columns]
    d = d[[c for c in d.columns if not c.startswith("Unnamed")]]
    for c in d.columns:
        d[c] = d[c].astype(str).str.strip().str.strip("`").str.strip()
    return d


def main():
    d = load_b031()
    latest = sorted(d["STD_YM"].unique())[-1]
    cur = d[d["STD_YM"] == latest].copy()
    cur["RSPOP_CNT"] = pd.to_numeric(cur["RSPOP_CNT"], errors="coerce")
    pop = cur.groupby("ADMI_CD")["RSPOP_CNT"].sum()      # 성별×연령 합산 = 총인구

    bv = pd.read_csv(BVARS, encoding="utf-8-sig", dtype={"adm_cd": str})
    out = bv[["adm_cd", "adm_nm", "자치구", "area_km2"]].copy()
    out["pop"] = out["adm_cd"].str[:8].map(pop)
    out["pop_density"] = (out["pop"] / out["area_km2"]).round(1)
    out = out[["adm_cd", "adm_nm", "자치구", "pop", "area_km2", "pop_density"]]
    out.to_csv(OUT, index=False, encoding="utf-8-sig")

    # ---- 확인 ----
    print(f"저장: {OUT}  ({len(out)}개 행정동)")
    print(f"B031 기준연월(최신): {latest}  | 서울 총인구 합계: {out['pop'].sum():,.0f}명")
    print(f"인구 결측 동: {out['pop'].isna().sum()}개 | 면적 결측 동: {out['area_km2'].isna().sum()}개")
    s = out["pop_density"].dropna()
    print(f"인구밀도(명/km²) min/median/max: {s.min():,.0f} / {s.median():,.0f} / {s.max():,.0f}")
    print("\n인구밀도 상위 5개 동:")
    for _, r in out.sort_values("pop_density", ascending=False).head(5).iterrows():
        print(f"  {r['자치구']} {r['adm_nm']}: {r['pop_density']:,.0f} 명/km² (인구 {r['pop']:,.0f})")
    print("\n자치구 평균 인구밀도 상위 5개 구:")
    gu = out.dropna(subset=["pop", "area_km2"]).groupby("자치구").apply(
        lambda x: x["pop"].sum() / x["area_km2"].sum())
    for gu_, v in gu.sort_values(ascending=False).head(5).items():
        print(f"  {gu_}: {v:,.0f} 명/km²")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
