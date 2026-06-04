"""
07_variable_select.py  (설계 v3)
변수선택 — 데이터가 고르게.
 1) 구 단위 집계 ↔ 피해 CSV(2023~25 누적) Spearman 상관 (절대 피해 + 인구당 피해)
 2) 동 단위 RandomForest: Y=전세가율 상위25%(구조적 고위험; 80%↑는 통합데이터에서 25개뿐이라
    상위25%로 더 균형). X=구성·건물·인구·괴리 (전세가율·고전세가율·jeonse_per_m2 제외=순환방지).
    feature_importances_ + TreeSHAP.
 3) 상관·중요도 둘 다 높은 변수 = 유의미 변수.
출력: data/processed/var_correlation.csv, var_importance.csv
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import spearmanr
from sklearn.ensemble import RandomForestClassifier

PROC = Path(__file__).resolve().parents[1] / "data" / "processed"
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
MASTER = PROC / "dong_master.csv"
DAMAGE = RAW / "서울특별시_자치구별_전세사기_발생건수.csv"

INTENSIVE = ["전세가율", "고전세가율비율", "jeonse_per_m2", "공시지가대비전세가괴리",
             "villa_share", "apt_share", "officetel_share",
             "new_density", "avg_age", "old30_ratio", "avg_units", "small_ratio",
             "pop_density", "youth_ratio", "gongsi_per_m2"]
COUNT_VARS = ["dagagu_count"]
ALL_VARS = INTENSIVE + COUNT_VARS
# RF 특징: Y(전세가율) 직접 파생 제외
RF_FEATURES = ["공시지가대비전세가괴리", "villa_share", "apt_share", "officetel_share",
               "dagagu_count", "new_density", "avg_age", "old30_ratio", "avg_units",
               "small_ratio", "pop_density", "youth_ratio", "gongsi_per_m2"]


def load_damage():
    for enc in ("cp949", "utf-8-sig", "utf-8"):
        try:
            d = pd.read_csv(DAMAGE, encoding=enc); break
        except Exception:
            d = None
    d = d[d["구분"] != "총합계"].copy()
    for c in ["2023년", "2024년", "2025년"]:
        d[c] = pd.to_numeric(d[c].astype(str).str.replace(",", "").str.strip(), errors="coerce")
    d["피해누적"] = d[["2023년", "2024년", "2025년"]].sum(axis=1)
    return d[["구분", "피해누적"]].rename(columns={"구분": "자치구"})


def main():
    m = pd.read_csv(MASTER, encoding="utf-8-sig", dtype={"adm_cd": str})
    dmg = load_damage()

    # ---------- 1) 구 단위 Spearman ----------
    agg = {v: "mean" for v in INTENSIVE}
    agg.update({v: "sum" for v in COUNT_VARS})
    agg["pop"] = "sum"
    gu = m.groupby("자치구").agg(agg).reset_index()
    gu = gu.merge(dmg, on="자치구", how="inner")
    gu["피해_인구1만"] = gu["피해누적"] / gu["pop"] * 10000

    rows = []
    for v in ALL_VARS:
        r1, p1 = spearmanr(gu[v], gu["피해누적"], nan_policy="omit")
        r2, p2 = spearmanr(gu[v], gu["피해_인구1만"], nan_policy="omit")
        rows.append((v, r1, p1, r2, p2))
    corr = pd.DataFrame(rows, columns=["변수", "Spearman_피해누적", "p_누적",
                                       "Spearman_인구당", "p_인구당"])
    corr["abs_누적"] = corr["Spearman_피해누적"].abs()
    corr = corr.sort_values("abs_누적", ascending=False).reset_index(drop=True)
    corr.round(4).to_csv(PROC / "var_correlation.csv", index=False, encoding="utf-8-sig")

    # ---------- 2) 동 RandomForest + SHAP ----------
    thr = m["전세가율"].quantile(0.75)
    d = m.dropna(subset=RF_FEATURES + ["전세가율"]).copy()
    d["Y"] = (d["전세가율"] >= thr).astype(int)
    X, y = d[RF_FEATURES], d["Y"]
    rf = RandomForestClassifier(n_estimators=400, class_weight="balanced",
                                random_state=42, n_jobs=-1)
    rf.fit(X, y)
    imp = pd.DataFrame({"변수": RF_FEATURES, "RF_importance": rf.feature_importances_})

    try:
        import shap
        sv = shap.TreeExplainer(rf).shap_values(X)
        sv = sv[1] if isinstance(sv, list) else (sv[:, :, 1] if getattr(sv, "ndim", 2) == 3 else sv)
        imp["SHAP_meanabs"] = np.abs(sv).mean(axis=0)
    except Exception as e:
        imp["SHAP_meanabs"] = np.nan
        print(f"(SHAP 실패: {e})")
    imp = imp.sort_values("RF_importance", ascending=False).reset_index(drop=True)
    imp.round(5).to_csv(PROC / "var_importance.csv", index=False, encoding="utf-8-sig")

    # ---------- 3) 종합 ----------
    print(f"구 단위 표본 {len(gu)}개 / 동 RF 표본 {len(d)}개 "
          f"(Y=전세가율≥{thr:.1f}% 상위25%, 양성 {int(y.sum())}개)")
    print("\n=== 구 Spearman 상관 (|피해누적| 큰 순) ===")
    print(corr[["변수", "Spearman_피해누적", "p_누적", "Spearman_인구당"]].round(3).to_string(index=False))
    print("\n=== 동 RF 중요도 + SHAP (importance 큰 순) ===")
    print(imp.round(4).to_string(index=False))

    # 종합 순위(상관 절댓값 순위 + 중요도 순위 평균)
    c = corr[["변수", "abs_누적"]].copy()
    c["corr_rank"] = c["abs_누적"].rank(ascending=False)
    i = imp[["변수", "RF_importance"]].copy()
    i["imp_rank"] = i["RF_importance"].rank(ascending=False)
    comb = c.merge(i, on="변수", how="outer")
    comb["종합순위점수"] = comb[["corr_rank", "imp_rank"]].mean(axis=1)
    comb = comb.sort_values("종합순위점수").reset_index(drop=True)
    print("\n=== 종합 (상관·중요도 둘 다 높을수록 상위) ===")
    print(comb[["변수", "abs_누적", "RF_importance", "종합순위점수"]].round(4).to_string(index=False))
    print(f"\n저장: var_correlation.csv, var_importance.csv")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
