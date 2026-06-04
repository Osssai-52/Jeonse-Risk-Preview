"""
07_validate.py  (설계 v3)
검증: 동 S_JVWI를 구로 집계 → 피해 CSV(2023~25 누적)와 교차검증.
 - 자치구 평균 S_JVWI ↔ 피해 Spearman (+ 인구당 피해)
 - 상위 동의 피해다발구 적중률 (top20 / 상위25%)
 - 알려진 진앙(화곡·독산 등) S_JVWI 상위 백분위 적중 사례
출력: validation_summary.csv (발표용 요약표)
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import spearmanr

PROC = Path(__file__).resolve().parents[1] / "data" / "processed"
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
OUT = PROC / "validation_summary.csv"

HOTSPOT4 = ["관악구", "강서구", "동작구", "금천구"]
EPICENTER = ["화곡", "독산", "가산", "시흥", "대림", "신대방", "사당", "신림"]


def load_damage():
    for enc in ("cp949", "utf-8-sig", "utf-8"):
        try:
            d = pd.read_csv(RAW / "서울특별시_자치구별_전세사기_발생건수.csv", encoding=enc); break
        except Exception:
            d = None
    d = d[d["구분"] != "총합계"].copy()
    for c in ["2023년", "2024년", "2025년"]:
        d[c] = pd.to_numeric(d[c].astype(str).str.replace(",", "").str.strip(), errors="coerce")
    d["피해누적"] = d[["2023년", "2024년", "2025년"]].sum(axis=1)
    return d[["구분", "피해누적"]].rename(columns={"구분": "자치구"})


def main():
    df = pd.read_csv(PROC / "sjvwi_adm.csv", encoding="utf-8-sig", dtype={"adm_cd": str})
    pop = pd.read_csv(PROC / "dong_popdensity_adm.csv", encoding="utf-8-sig",
                      dtype={"adm_cd": str})[["adm_cd", "pop"]]
    df = df.merge(pop, on="adm_cd", how="left")
    dmg = load_damage()
    N = len(df)
    df["pct"] = df["S_JVWI"].rank(ascending=False) / N * 100   # 상위 백분위

    # 구 집계
    gu = df.groupby("자치구").agg(meanS=("S_JVWI", "mean"), pop=("pop", "sum")).reset_index()
    gu["hi_share"] = df.assign(hi=df["S_JVWI"] >= df["S_JVWI"].quantile(0.75)) \
        .groupby("자치구")["hi"].mean().values
    gu = gu.merge(dmg, on="자치구", how="inner")
    gu["피해_인구1만"] = gu["피해누적"] / gu["pop"] * 10000

    r_abs, p_abs = spearmanr(gu["meanS"], gu["피해누적"])
    r_pc, p_pc = spearmanr(gu["meanS"], gu["피해_인구1만"])
    r_hi, _ = spearmanr(gu["hi_share"], gu["피해누적"])

    # 피해 구 티어
    med = dmg["피해누적"].median()
    hi_gu = set(dmg[dmg["피해누적"] > med]["자치구"])         # 상위50% 피해구
    def hit(n_top):
        t = df.nsmallest(n_top, "pct")  # 상위 n
        return (t["자치구"].isin(hi_gu).mean() * 100,
                t["자치구"].isin(HOTSPOT4).mean() * 100)
    h20 = hit(20); hq = hit(int(N * 0.25))

    # 진앙 사례
    epi = df[df["adm_nm"].str.contains("|".join(EPICENTER), na=False)].copy()
    epi = epi.sort_values("S_JVWI", ascending=False)

    rows = [
        ("자치구 평균 S_JVWI ↔ 피해누적 Spearman", f"{r_abs:.3f}", f"p={p_abs:.4f}, n=25"),
        ("자치구 평균 S_JVWI ↔ 인구당피해 Spearman", f"{r_pc:.3f}", f"p={p_pc:.4f}"),
        ("자치구 고위험동비율 ↔ 피해누적 Spearman", f"{r_hi:.3f}", "고위험=S_JVWI 상위25%"),
        ("상위 20개 동의 고피해구(상위50%) 적중률", f"{h20[0]:.0f}%", f"{int(h20[0]/100*20)}/20"),
        ("상위 20개 동의 피해다발 4구 적중률", f"{h20[1]:.0f}%", "관악·강서·동작·금천"),
        ("상위 25% 동의 고피해구 적중률", f"{hq[0]:.0f}%", f"n={int(N*0.25)}"),
        ("상위 25% 동의 피해다발 4구 적중률", f"{hq[1]:.0f}%", ""),
    ]
    summary = pd.DataFrame(rows, columns=["검증지표", "값", "비고"])
    summary.to_csv(OUT, index=False, encoding="utf-8-sig")

    # ---- 출력 ----
    print(f"저장: {OUT}\n")
    print("=== 검증 요약 ===")
    print(summary.to_string(index=False))
    print(f"\n피해 상위50% 구({len(hi_gu)}개): {', '.join(sorted(hi_gu))}")
    print("\n=== 알려진 진앙 적중 사례 (S_JVWI 상위 백분위) ===")
    for _, r in epi.head(12).iterrows():
        print(f"  {r['자치구']} {r['adm_nm']}: S_JVWI {r['S_JVWI']:.1f} (상위 {r['pct']:.0f}%)")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
