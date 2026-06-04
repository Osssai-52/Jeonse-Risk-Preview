"""
05_master_v3.py  (설계 v3)
공시지가대비전세가괴리 파생 + 전 변수후보 마스터 통합 → dong_master.csv (adm_cd outer join).

괴리 = jeonse_per_m2(통합 전세가, 만원/㎡)*10000 / gongsi_per_m2(원/㎡).
  값↑ = 땅값 대비 전세가 과도 = 시세부풀리기 의심.
통합 소스: jeonse_ratio_all_adm / dong_typemix_adm / building_vars_adm /
           dong_popdensity_adm / dong_campus.
출력: data/processed/dong_master.csv
"""

import sys
import pandas as pd
from pathlib import Path

PROC = Path(__file__).resolve().parents[1] / "data" / "processed"
OUT = PROC / "dong_master.csv"


def rd(name):
    return pd.read_csv(PROC / name, encoding="utf-8-sig", dtype={"adm_cd": str})


def main():
    jr = rd("jeonse_ratio_all_adm.csv")      # 전세가율, 고전세가율비율, jeonse_per_m2, 거래건수
    tm = rd("dong_typemix_adm.csv")          # rent_n, villa/apt/officetel_share, dagagu_count
    bv = rd("building_vars_adm.csv")         # res_building_n, area_km2, new_density, avg_age, old30_ratio, avg_units, small_ratio
    pd_ = rd("dong_popdensity_adm.csv")      # pop, area_km2, pop_density
    cam = rd("dong_campus.csv")              # youth_ratio, gongsi_per_m2

    # 식별자 통합(adm_nm, 자치구): 모든 소스에서 모아 첫 non-null
    ids = pd.concat([
        jr[["adm_cd", "adm_nm", "자치구"]], tm[["adm_cd", "adm_nm", "자치구"]],
        bv[["adm_cd", "adm_nm", "자치구"]], pd_[["adm_cd", "adm_nm", "자치구"]],
        cam[["adm_cd", "adm_nm"]].assign(자치구=pd.NA),
    ], ignore_index=True)
    ids = ids.groupby("adm_cd").agg({"adm_nm": "first", "자치구": "first"}).reset_index()

    # 변수만 남기고 outer join
    m = ids
    m = m.merge(jr[["adm_cd", "전세가율", "고전세가율비율", "jeonse_per_m2", "거래건수"]], on="adm_cd", how="outer")
    m = m.merge(tm[["adm_cd", "rent_n", "villa_share", "apt_share", "officetel_share", "dagagu_count"]], on="adm_cd", how="outer")
    m = m.merge(bv[["adm_cd", "res_building_n", "area_km2", "new_density", "avg_age", "old30_ratio", "avg_units", "small_ratio"]], on="adm_cd", how="outer")
    m = m.merge(pd_[["adm_cd", "pop", "pop_density"]], on="adm_cd", how="outer")
    m = m.merge(cam[["adm_cd", "youth_ratio", "gongsi_per_m2"]], on="adm_cd", how="outer")

    # 식별자 재보강(outer로 새 adm_cd 생겼을 수 있음)
    m = m.merge(ids.rename(columns={"adm_nm": "adm_nm2", "자치구": "자치구2"}), on="adm_cd", how="left")
    m["adm_nm"] = m["adm_nm"].combine_first(m["adm_nm2"])
    m["자치구"] = m["자치구"].combine_first(m["자치구2"])
    m = m.drop(columns=["adm_nm2", "자치구2"])

    # 파생: 공시지가대비전세가괴리
    m["공시지가대비전세가괴리"] = (m["jeonse_per_m2"] * 10000.0 / m["gongsi_per_m2"]).round(4)

    var_cols = ["전세가율", "고전세가율비율", "jeonse_per_m2", "공시지가대비전세가괴리",
                "villa_share", "apt_share", "officetel_share", "dagagu_count",
                "new_density", "avg_age", "old30_ratio", "avg_units", "small_ratio",
                "pop_density", "youth_ratio", "gongsi_per_m2"]
    support = ["area_km2", "pop", "rent_n", "거래건수", "res_building_n"]
    m = m[["adm_cd", "adm_nm", "자치구"] + var_cols + support].sort_values("adm_cd").reset_index(drop=True)
    m.to_csv(OUT, index=False, encoding="utf-8-sig")

    # ---- 확인 ----
    print(f"저장: {OUT}  (전체 {len(m)}개 동, 변수 {len(var_cols)}개)")
    print("\n[변수별 결측 동 개수]")
    for c in var_cols:
        n = m[c].isna().sum()
        if n: print(f"  {c}: {n}")
    print(f"완전 케이스(전 변수 값): {m[var_cols].notna().all(axis=1).sum()}개")

    gap = m["공시지가대비전세가괴리"].dropna()
    print(f"\n[공시지가대비전세가괴리] min/median/mean/max: "
          f"{gap.min():.3f}/{gap.median():.3f}/{gap.mean():.3f}/{gap.max():.3f}")
    print("상위 5개 동 (전세/㎡, 공시/㎡ 함께 — 저공시지가 그린벨트 artifact 점검):")
    for _, r in m.sort_values("공시지가대비전세가괴리", ascending=False).head(5).iterrows():
        print(f"  {r['자치구']} {r['adm_nm']}: {r['공시지가대비전세가괴리']:.3f} "
              f"(전세 {r['jeonse_per_m2']*10000:,.0f} / 공시 {r['gongsi_per_m2']:,.0f})")
    print("하위(괴리 작은) 3개 동:")
    for _, r in m.dropna(subset=["공시지가대비전세가괴리"]).sort_values("공시지가대비전세가괴리").head(3).iterrows():
        print(f"  {r['자치구']} {r['adm_nm']}: {r['공시지가대비전세가괴리']:.3f}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
