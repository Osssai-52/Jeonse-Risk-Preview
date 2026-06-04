"""
06_kmeans_cluster.py  (설계 v3)
K-Means 위험 유형 군집 — 동을 위험 특징 조합으로 묶는다.

특징: S-JVWI 7개 정규화 변수(n_*). StandardScaler 후 KMeans.
k: 실루엣 점수로 5~7 중 결정(엘보우 inertia도 출력).
프로파일: 군집별 변수 평균 + 평균 S_JVWI + 평균 구피해 + 대표특징 + 라벨.
출력: clusters_adm.csv + 군집 프로파일.
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

PROC = Path(__file__).resolve().parents[1] / "data" / "processed"
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
OUT = PROC / "clusters_adm.csv"

FEATS = ["dagagu_count", "new_density", "전세가율", "고전세가율비율",
         "공시지가대비전세가괴리", "officetel_share", "pop_density"]
NCOLS = ["n_" + f for f in FEATS]
LABELMAP = {"dagagu_count": "다가구밀집형", "new_density": "신축집중형",
            "officetel_share": "오피스텔밀집형", "전세가율": "고전세가율형",
            "고전세가율비율": "고전세가율형", "공시지가대비전세가괴리": "공시지가괴리형",
            "pop_density": "고밀주거형"}


def load_damage():
    for enc in ("cp949", "utf-8-sig", "utf-8"):
        try:
            d = pd.read_csv(RAW / "서울특별시_자치구별_전세사기_발생건수.csv", encoding=enc); break
        except Exception:
            d = None
    d = d[d["구분"] != "총합계"].copy()
    for c in ["2023년", "2024년", "2025년"]:
        d[c] = pd.to_numeric(d[c].astype(str).str.replace(",", "").str.strip(), errors="coerce")
    return dict(zip(d["구분"], d[["2023년", "2024년", "2025년"]].sum(axis=1)))


def main():
    df = pd.read_csv(PROC / "sjvwi_adm.csv", encoding="utf-8-sig", dtype={"adm_cd": str})
    df["구피해"] = df["자치구"].map(load_damage())
    X = StandardScaler().fit_transform(df[NCOLS])

    print("[k 결정: inertia / silhouette]")
    best_k, best_s = None, -1
    for k in range(4, 9):
        km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X)
        s = silhouette_score(X, km.labels_)
        mark = ""
        if 5 <= k <= 7 and s > best_s:
            best_s, best_k = s, k; mark = " <-"
        print(f"  k={k}: inertia={km.inertia_:.0f}  silhouette={s:.3f}{mark}")

    km = KMeans(n_clusters=best_k, random_state=42, n_init=10).fit(X)
    df["cluster"] = km.labels_
    print(f"\n선택 k={best_k} (실루엣 {best_s:.3f})")

    # 군집 프로파일 (정규화 평균 기준 대표특징 + 라벨)
    prof = df.groupby("cluster").agg(
        n=("adm_cd", "size"), S_JVWI=("S_JVWI", "mean"), 구피해=("구피해", "mean"),
        **{f: (f, "mean") for f in FEATS}, **{nc: (nc, "mean") for nc in NCOLS})
    grand = df[NCOLS].mean()
    labels, feats_desc = {}, {}
    sjv_order = prof["S_JVWI"].sort_values()
    low_cluster = sjv_order.index[0]
    for c in prof.index:
        z = (prof.loc[c, NCOLS] - grand) / df[NCOLS].std()
        top = z.sort_values(ascending=False)
        top_feats = [t[2:] for t in top.index[:2]]   # n_ 제거
        feats_desc[c] = ", ".join(f"{f}↑" for f in top_feats)
        if c == low_cluster and prof.loc[c, "S_JVWI"] < prof["S_JVWI"].median():
            labels[c] = "저위험형"
        elif (z > 0.5).sum() >= 4:
            labels[c] = "복합위험형"
        else:
            labels[c] = LABELMAP.get(top.index[0][2:], "기타위험형")
    # 중복 라벨 구분
    seen = {}
    for c in prof.sort_values("S_JVWI", ascending=False).index:
        lab = labels[c]
        if lab in seen.values():
            labels[c] = lab + f"({feats_desc[c].split(',')[0].strip()})"
        seen[c] = labels[c]
    df["cluster_label"] = df["cluster"].map(labels)

    out = df[["adm_cd", "adm_nm", "자치구", "S_JVWI", "구피해", "cluster", "cluster_label"]]
    out.to_csv(OUT, index=False, encoding="utf-8-sig")

    # ---- 프로파일 출력 ----
    print(f"\n저장: {OUT}\n")
    print("=== 군집 프로파일 ===")
    show = prof.copy()
    show["label"] = [labels[c] for c in show.index]
    show["대표특징"] = [feats_desc[c] for c in show.index]
    for c in show.sort_values("S_JVWI", ascending=False).index:
        r = show.loc[c]
        print(f"\n[군집 {c}] {r['label']}  (n={int(r['n'])}, 평균S_JVWI {r['S_JVWI']:.1f}, 평균구피해 {r['구피해']:.0f})")
        print(f"  대표특징: {r['대표특징']}")
        print("  변수평균: " + " | ".join(f"{f}={r[f]:.2f}" for f in FEATS))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
