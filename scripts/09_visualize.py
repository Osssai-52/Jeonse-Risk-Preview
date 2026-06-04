"""
09_visualize.py  (설계 v3)
Folium 인터랙티브 지도(HTML) + 발표용 정적 PNG(GeoPandas/matplotlib).

입력: BND_ADM_DONG_PG.shp(경계) + sjvwi_adm / clusters_adm / next_risk_dong + 피해 CSV
출력: outputs/
  sjvwi_map.html/.png          취약도 choropleth
  next_risk_map.html/.png      다음위험지역 강조
  cluster_map.html/.png        군집 유형
  validation_scatter.png       자치구 S_JVWI vs 피해 산점도
경계(8자리코드)↔우리(10자리 adm_cd)는 (자치구, 정규화이름)으로 조인.
"""

import sys
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import folium
import branca.colormap as cm
from scipy.stats import spearmanr
from pathlib import Path

plt.rcParams["font.family"] = "Malgun Gothic"      # 윈도우 한글 폰트
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]
EXT, PROC, OUT = ROOT / "data/external", ROOT / "data/processed", ROOT / "outputs"
RAW = ROOT / "data/raw"
OUT.mkdir(exist_ok=True)
BND = EXT / "BND_ADM_DONG_PG.shp"

WEIGHTS = {"dagagu_count": 20, "new_density": 18, "전세가율": 18, "고전세가율비율": 14,
           "공시지가대비전세가괴리": 12, "officetel_share": 10, "pop_density": 8}
LABEL = {"dagagu_count": "다가구밀집", "new_density": "신축밀집", "전세가율": "전세가율",
         "고전세가율비율": "고전세가율", "공시지가대비전세가괴리": "공시지가괴리",
         "officetel_share": "오피스텔비중", "pop_density": "인구밀도"}
CLUSTER_COLORS = ["#e41a1c", "#377eb8", "#4daf4a", "#984ea3",
                  "#ff7f00", "#a65628", "#f781bf", "#999999"]


def norm_name(s):
    return str(s).strip().replace("·", ".").replace("ㆍ", ".").replace("제", "")


def top_vars(row, k=3):
    c = {v: WEIGHTS[v] * row["n_" + v] for v in WEIGHTS}
    return ", ".join(LABEL[v] for v in sorted(c, key=c.get, reverse=True)[:k])


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


def build_gdf():
    """경계 + 분석결과 조인 → 4326 GeoDataFrame."""
    sj = pd.read_csv(PROC / "sjvwi_adm.csv", encoding="utf-8-sig", dtype={"adm_cd": str})
    cl = pd.read_csv(PROC / "clusters_adm.csv", encoding="utf-8-sig",
                     dtype={"adm_cd": str})[["adm_cd", "cluster", "cluster_label"]]
    nx = pd.read_csv(PROC / "next_risk_dong.csv", encoding="utf-8-sig", dtype={"adm_cd": str})
    sj["주요위험변수"] = sj.apply(top_vars, axis=1)
    d = sj.merge(cl, on="adm_cd", how="left")
    d["구피해"] = d["자치구"].map(dict(zip(load_damage()["자치구"], load_damage()["피해누적"]))).fillna(0)
    d["is_next"] = d["adm_cd"].isin(set(nx["adm_cd"]))
    d["key"] = d["adm_nm"].map(norm_name)

    g = gpd.read_file(BND)
    g = g[g["ADM_CD"].astype(str).str.startswith("11")].to_crs("EPSG:5179").copy()
    g["geometry"] = g.geometry.simplify(20)                # 파일 경량화
    g["sgg5"] = g["ADM_CD"].astype(str).str[:5]
    g["key"] = g["ADM_NM"].map(norm_name)
    votes = g.merge(d[["key", "자치구"]].drop_duplicates(), on="key", how="left")
    sgg2gu = votes.dropna(subset=["자치구"]).groupby("sgg5")["자치구"].agg(lambda s: s.mode().iloc[0])
    g["자치구"] = g["sgg5"].map(sgg2gu)

    gdf = g.merge(d, on=["자치구", "key"], how="inner").to_crs("EPSG:4326")
    return gdf


def sjvwi_color(v):
    if pd.isna(v): return "#cccccc"
    return ("#1a9850" if v < 20 else "#a6d96a" if v < 30 else
            "#fee08b" if v < 40 else "#fc8d59" if v < 50 else "#d73027")


# ---------- 1) 취약도 choropleth ----------
def map_sjvwi(gdf):
    m = folium.Map(location=[37.55, 126.99], zoom_start=11, tiles="cartodbpositron")
    folium.GeoJson(
        gdf, name="S-JVWI",
        style_function=lambda f: {"fillColor": sjvwi_color(f["properties"]["S_JVWI"]),
                                  "color": "white", "weight": 0.5, "fillOpacity": 0.75},
        highlight_function=lambda f: {"weight": 2, "color": "black"},
        tooltip=folium.GeoJsonTooltip(
            fields=["자치구", "adm_nm", "S_JVWI", "주요위험변수"],
            aliases=["자치구", "행정동", "S-JVWI", "주요위험"], localize=True),
    ).add_to(m)
    cmap = cm.StepColormap(["#1a9850", "#a6d96a", "#fee08b", "#fc8d59", "#d73027"],
                           vmin=0, vmax=62, index=[0, 20, 30, 40, 50, 62],
                           caption="S-JVWI 전세거래 취약도 (높을수록 위험)")
    cmap.add_to(m)
    m.save(OUT / "sjvwi_map.html")


# ---------- 2) 다음 위험지역 강조 ----------
def map_next(gdf):
    m = folium.Map(location=[37.55, 126.99], zoom_start=11, tiles="cartodbpositron")
    folium.GeoJson(gdf, style_function=lambda f: {
        "fillColor": "#d73027" if f["properties"]["is_next"] else "#eeeeee",
        "color": "#b30000" if f["properties"]["is_next"] else "#cccccc",
        "weight": 1.5 if f["properties"]["is_next"] else 0.3,
        "fillOpacity": 0.7 if f["properties"]["is_next"] else 0.2}).add_to(m)
    nxt = gdf[gdf["is_next"]]
    for _, r in nxt.iterrows():
        c = r.geometry.centroid
        folium.CircleMarker(
            [c.y, c.x], radius=6, color="#7a0177", fill=True, fill_color="#c51b8a",
            fill_opacity=0.9,
            popup=folium.Popup(f"<b>{r['자치구']} {r['adm_nm']}</b><br>"
                               f"S-JVWI {r['S_JVWI']:.1f} (구피해 {int(r['구피해'])})<br>"
                               f"⚠ 위험신호 높으나 피해 낮음<br>주요위험: {r['주요위험변수']}",
                               max_width=260)).add_to(m)
    m.save(OUT / "next_risk_map.html")


# ---------- 2b) 취약 상위 동 (피해 무관) ----------
def map_high_risk_all(gdf):
    thr = gdf["S_JVWI"].quantile(0.75)
    g = gdf.copy(); g["is_hi"] = g["S_JVWI"] >= thr
    m = folium.Map(location=[37.55, 126.99], zoom_start=11, tiles="cartodbpositron")
    folium.GeoJson(g, style_function=lambda f: {
        "fillColor": "#d73027" if f["properties"]["is_hi"] else "#eeeeee",
        "color": "#b30000" if f["properties"]["is_hi"] else "#cccccc",
        "weight": 1.5 if f["properties"]["is_hi"] else 0.3,
        "fillOpacity": 0.7 if f["properties"]["is_hi"] else 0.2}).add_to(m)
    for _, r in g[g["is_hi"]].iterrows():
        c = r.geometry.centroid
        folium.CircleMarker(
            [c.y, c.x], radius=5, color="#7a0177", fill=True, fill_color="#c51b8a",
            fill_opacity=0.9,
            popup=folium.Popup(f"<b>{r['자치구']} {r['adm_nm']}</b><br>"
                               f"S-JVWI {r['S_JVWI']:.1f} (구피해 {int(r['구피해'])})<br>"
                               f"주요위험: {r['주요위험변수']}", max_width=260)).add_to(m)
    title = ("<div style='position:fixed;top:10px;left:50%;transform:translateX(-50%);"
             "z-index:9999;background:white;padding:6px 14px;border:1px solid grey;"
             "font-size:15px;font-weight:bold'>전세거래 취약 상위 동 (피해 무관)</div>")
    m.get_root().html.add_child(folium.Element(title))
    m.save(OUT / "high_risk_all_map.html")

    fig, ax = plt.subplots(figsize=(9, 9))
    g.plot(color="#eeeeee", edgecolor="white", linewidth=0.3, ax=ax)
    g[g["is_hi"]].plot(color="#d73027", edgecolor="#7a0177", linewidth=0.8, ax=ax)
    ax.set_title(f"전세거래 취약 상위 동 (피해 무관)  ·  S-JVWI 상위25%({thr:.0f}↑) {int(g['is_hi'].sum())}동",
                 fontsize=14)
    ax.axis("off"); fig.savefig(OUT / "high_risk_all_map.png", dpi=130, bbox_inches="tight"); plt.close(fig)

    hi = g[g["is_hi"]]
    print(f"  ✓ high_risk_all_map (상위25% {len(hi)}동) "
          f"| 금천 {(hi['자치구']=='금천구').sum()} 관악 {(hi['자치구']=='관악구').sum()} "
          f"강서 {(hi['자치구']=='강서구').sum()}")


# ---------- 3) 군집 유형 ----------
def map_cluster(gdf):
    labels = (gdf.dropna(subset=["cluster"])
              .sort_values("cluster").drop_duplicates("cluster"))
    lab_map = dict(zip(labels["cluster"], labels["cluster_label"]))
    m = folium.Map(location=[37.55, 126.99], zoom_start=11, tiles="cartodbpositron")
    def col(f):
        c = f["properties"]["cluster"]
        return CLUSTER_COLORS[int(c) % len(CLUSTER_COLORS)] if c is not None and not pd.isna(c) else "#dddddd"
    folium.GeoJson(gdf, style_function=lambda f: {
        "fillColor": col(f), "color": "white", "weight": 0.5, "fillOpacity": 0.75},
        tooltip=folium.GeoJsonTooltip(fields=["자치구", "adm_nm", "cluster_label"],
                                      aliases=["자치구", "행정동", "위험유형"])).add_to(m)
    items = "".join(
        f"<div><span style='background:{CLUSTER_COLORS[int(c)%8]};width:12px;height:12px;"
        f"display:inline-block;margin-right:5px'></span>{lab_map[c]}</div>"
        for c in sorted(lab_map))
    legend = (f"<div style='position:fixed;bottom:30px;left:30px;z-index:9999;background:white;"
              f"padding:10px;border:1px solid grey;font-size:12px'><b>위험 유형 군집</b>{items}</div>")
    m.get_root().html.add_child(folium.Element(legend))
    m.save(OUT / "cluster_map.html")


# ---------- 정적 PNG ----------
def static_pngs(gdf):
    # 취약도
    fig, ax = plt.subplots(figsize=(9, 9))
    gdf.plot(column="S_JVWI", cmap="RdYlGn_r", legend=True, ax=ax,
             edgecolor="white", linewidth=0.3,
             legend_kwds={"label": "S-JVWI 취약도", "shrink": 0.6})
    ax.set_title("서울 전세거래 취약도 S-JVWI (행정동)", fontsize=15)
    ax.axis("off"); fig.savefig(OUT / "sjvwi_map.png", dpi=130, bbox_inches="tight"); plt.close(fig)

    # 다음위험지역
    fig, ax = plt.subplots(figsize=(9, 9))
    gdf.plot(color="#eeeeee", edgecolor="white", linewidth=0.3, ax=ax)
    gdf[gdf["is_next"]].plot(color="#d73027", edgecolor="#7a0177", linewidth=0.8, ax=ax)
    ax.set_title("다음 위험지역(예방자원 우선) 29개 동", fontsize=15)
    ax.axis("off"); fig.savefig(OUT / "next_risk_map.png", dpi=130, bbox_inches="tight"); plt.close(fig)

    # 군집
    fig, ax = plt.subplots(figsize=(9, 9))
    from matplotlib.colors import ListedColormap
    cl = gdf.dropna(subset=["cluster"]).copy(); cl["cluster"] = cl["cluster"].astype(int)
    cl.plot(column="cluster", categorical=True, legend=True, ax=ax,
            cmap=ListedColormap(CLUSTER_COLORS[:cl["cluster"].nunique()]),
            edgecolor="white", linewidth=0.3,
            legend_kwds={"title": "위험유형 군집", "loc": "lower left", "fontsize": 8})
    # 범례 라벨을 유형명으로
    lab = dict(zip(cl["cluster"], cl["cluster_label"]))
    leg = ax.get_legend()
    for t in leg.get_texts():
        try: t.set_text(lab.get(int(float(t.get_text())), t.get_text()))
        except Exception: pass
    ax.set_title("위험 유형 군집 (K-Means k=7)", fontsize=15)
    ax.axis("off"); fig.savefig(OUT / "cluster_map.png", dpi=130, bbox_inches="tight"); plt.close(fig)


# ---------- 4) 검증 산점도 ----------
def validation_scatter(gdf):
    dmg = load_damage()
    gu = gdf.groupby("자치구")["S_JVWI"].mean().reset_index().merge(dmg, on="자치구")
    r, p = spearmanr(gu["S_JVWI"], gu["피해누적"])
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(gu["S_JVWI"], gu["피해누적"], s=60, color="#d73027", alpha=0.8)
    for _, x in gu.iterrows():
        ax.annotate(x["자치구"], (x["S_JVWI"], x["피해누적"]), fontsize=8,
                    xytext=(3, 3), textcoords="offset points")
    ax.set_xlabel("자치구 평균 S-JVWI"); ax.set_ylabel("누적 전세사기 피해건수(2023~25)")
    ax.set_title(f"검증: 자치구 S-JVWI vs 피해  (Spearman r={r:.3f}, p={p:.4f})", fontsize=13)
    ax.grid(alpha=0.3); fig.savefig(OUT / "validation_scatter.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


def main():
    gdf = build_gdf()
    print(f"경계 조인 동 수: {len(gdf)} (분석결과 매칭)")
    map_sjvwi(gdf); print("  ✓ sjvwi_map.html")
    map_next(gdf); print("  ✓ next_risk_map.html")
    map_high_risk_all(gdf)
    map_cluster(gdf); print("  ✓ cluster_map.html")
    static_pngs(gdf); print("  ✓ 정적 PNG 3종")
    validation_scatter(gdf); print("  ✓ validation_scatter.png")
    print(f"\n출력 폴더: {OUT}")
    for f in sorted(OUT.glob("*")):
        print("  ", f.name)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
