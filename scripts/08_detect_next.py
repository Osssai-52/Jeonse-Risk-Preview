"""
08_detect_next.py  (설계 v3)
다음 위험지역(예방자원 우선지역) 탐지.

정의: S_JVWI 상위 25% AND 소속 자치구 누적피해 하위 50%
  = "아직 피해는 적지만 위험신호 높은 → 예방자원 우선 투입 후보"

입력: sjvwi_adm.csv, 서울특별시_자치구별_전세사기_발생건수.csv
출력: next_risk_dong.csv (adm_cd, adm_nm, 자치구, S_JVWI, 구피해, 주요위험변수)
각 동의 위험 원인 = S_JVWI 기여도(가중치×정규화값) 상위 변수.
"""

import sys
import pandas as pd
from pathlib import Path

PROC = Path(__file__).resolve().parents[1] / "data" / "processed"
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
OUT = PROC / "next_risk_dong.csv"

WEIGHTS = {"dagagu_count": 20, "new_density": 18, "전세가율": 18, "고전세가율비율": 14,
           "공시지가대비전세가괴리": 12, "officetel_share": 10, "pop_density": 8}
LABEL = {"dagagu_count": "다가구밀집", "new_density": "신축밀집", "전세가율": "전세가율",
         "고전세가율비율": "고전세가율", "공시지가대비전세가괴리": "공시지가괴리",
         "officetel_share": "오피스텔비중", "pop_density": "인구밀도"}


def load_damage():
    for enc in ("cp949", "utf-8-sig", "utf-8"):
        try:
            d = pd.read_csv(RAW / "서울특별시_자치구별_전세사기_발생건수.csv", encoding=enc); break
        except Exception:
            d = None
    d = d[d["구분"] != "총합계"].copy()
    for c in ["2023년", "2024년", "2025년"]:
        d[c] = pd.to_numeric(d[c].astype(str).str.replace(",", "").str.strip(), errors="coerce")
    d["구피해"] = d[["2023년", "2024년", "2025년"]].sum(axis=1)
    return d[["구분", "구피해"]].rename(columns={"구분": "자치구"})


def top_vars(row, k=3):
    """동의 S_JVWI 기여도(가중치×정규화) 상위 k개 변수 라벨."""
    contrib = {v: WEIGHTS[v] * row["n_" + v] for v in WEIGHTS}
    top = sorted(contrib, key=contrib.get, reverse=True)[:k]
    return ", ".join(f"{LABEL[v]}({contrib[v]:.0f})" for v in top)


def main():
    df = pd.read_csv(PROC / "sjvwi_adm.csv", encoding="utf-8-sig", dtype={"adm_cd": str})
    dmg = load_damage()

    # 1) S_JVWI 상위 25% 기준선
    thr = df["S_JVWI"].quantile(0.75)
    # 2) 자치구 누적피해 하위 50% (중앙값 이하)
    dmg_med = dmg["구피해"].median()
    low_gu = set(dmg[dmg["구피해"] <= dmg_med]["자치구"])

    df = df.merge(dmg, on="자치구", how="left")
    # 3) 두 조건
    sel = df[(df["S_JVWI"] >= thr) & (df["자치구"].isin(low_gu))].copy()
    sel["주요위험변수"] = sel.apply(top_vars, axis=1)
    sel = sel.sort_values("S_JVWI", ascending=False).reset_index(drop=True)

    out = sel[["adm_cd", "adm_nm", "자치구", "S_JVWI", "구피해", "주요위험변수"]]
    out.to_csv(OUT, index=False, encoding="utf-8-sig")

    # ---- 확인 ----
    print(f"저장: {OUT}")
    print(f"S_JVWI 상위25% 기준선: {thr:.1f} | 피해 하위50% 구(중앙값 {dmg_med:.0f}이하): {len(low_gu)}개")
    print(f"하위50% 구: {', '.join(sorted(low_gu))}")
    print(f"\n=== 다음 위험지역(예방자원 우선) {len(out)}개 동 ===")
    for i, r in out.iterrows():
        print(f"  {i+1:2d}. {r['자치구']} {r['adm_nm']}: S_JVWI {r['S_JVWI']:.1f} "
              f"(구피해 {int(r['구피해'])}) | {r['주요위험변수']}")
    print("\n[자치구 분포]")
    print("  " + ", ".join(f"{k} {v}" for k, v in out["자치구"].value_counts().items()))
    gj = out[out["자치구"] == "광진구"]
    print(f"\n광진구 포함 동: {len(gj)}개 " + (", ".join(gj["adm_nm"]) if len(gj) else "(없음)"))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
