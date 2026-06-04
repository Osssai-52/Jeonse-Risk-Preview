"""
04_normalize_kde.py
동 마스터(dong_master.csv) → 비완전케이스 처리 + 파생변수 + MinMax 정규화 + KDE.

처리 순서:
 1. 홍제1·2·3동 area_km2 보강: 경계파일 실제 면적으로 복원
    (※ 기존 '경계 미스매치'는 실제 개편이 아니라 행정동명 정규화 버그였음 —
       '홍제제1동'(KIKmix) vs '홍제1동'(경계). '제' 전부 제거 방식으로 매칭하면
       홍제1/2/3이 정상 매칭되어 실제 면적이 살아난다. 균등배분/중앙값 대체 불필요.)
 2. 나머지 비완전 9개 제외(전세실거래없음 5 + external-only 3 + campus-only 1)
    → 분석대상 416개 동.
 3. 파생변수 공시지가대비전세가괴리 = 전세가/㎡(원) / 공시지가/㎡(원)
    (전세가/㎡는 villa_rent에서 03 로직으로 재산출 → 행정동 매핑)
 4. MinMax 정규화(norm_): 전세가율, 고전세가율비율, newvilla_density,
    공시지가대비전세가괴리, youth_ratio  (newvilla_ratio는 density와 중복이라 제외)
 5. KDE(σ=500m 가우시안): 고전세가율비율, newvilla_density
    ※ 동 중심점 최근접 중앙값 780m라 σ=500m는 사실상 항등(이웃 거의 없음).
      지시대로 적용하되 진단치를 출력한다. 의미있는 평활은 σ≈1000~1500m 권장.

출력: data/processed/dong_master_norm.csv (416개 동)
"""

import sys
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path

EXT = Path(__file__).resolve().parents[1] / "data" / "external"
PROC = Path(__file__).resolve().parents[1] / "data" / "processed"

BND_PATH = EXT / "BND_ADM_DONG_PG.shp"
KIK_PATH = EXT / "KIKmix.20210401.xlsx"
RENT_PATH = EXT / "villa_rent.csv"
MASTER = PROC / "dong_master.csv"
OUT = PROC / "dong_master_norm.csv"

AREA_CRS = "EPSG:5179"
KDE_SIGMA = 500.0          # 가우시안 대역폭(m)
NORM_VARS = ["전세가율", "고전세가율비율", "newvilla_density",
             "공시지가대비전세가괴리", "youth_ratio"]
KDE_VARS = ["고전세가율비율", "newvilla_density"]


def norm_name(s):
    """'제' 전부 제거 + 가운뎃점 통일. 양쪽에 동일 적용 → 어간/서수 제 모두 제거되어 매칭."""
    return str(s).strip().replace("·", ".").replace("ㆍ", ".").replace("제", "")


def load_boundary():
    """경계(SGIS)에서 (자치구, 정규화이름)별 면적·중심점 산출용 GeoDataFrame."""
    g = gpd.read_file(BND_PATH)
    g = g[g["ADM_CD"].astype(str).str.startswith("11")].to_crs(AREA_CRS).copy()
    g["sgg5"] = g["ADM_CD"].astype(str).str[:5]
    g["key"] = g["ADM_NM"].map(norm_name)
    g["area_km2"] = g.geometry.area / 1e6
    cen = g.geometry.centroid
    g["cx"], g["cy"] = cen.x.values, cen.y.values
    return g


def assign_gu(g, name_gu_map):
    votes = g.merge(name_gu_map, on="key", how="left")
    sgg2gu = (votes.dropna(subset=["자치구"]).groupby("sgg5")["자치구"]
              .agg(lambda s: s.mode().iloc[0]))
    g["자치구"] = g["sgg5"].map(sgg2gu)
    return g


def load_csv(path):
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except (UnicodeDecodeError, Exception):
            continue
    raise ValueError(f"읽기 실패: {path}")


def jeonse_per_m2_by_adm():
    """villa_rent → 전세(월세0) 전세가/㎡(만원) 법정동평균 → 행정동(adm_cd) 거래건수 가중평균."""
    rent = load_csv(RENT_PATH)
    rent["보증금액"] = pd.to_numeric(rent["보증금액"], errors="coerce")
    rent["월세금액"] = pd.to_numeric(rent["월세금액"], errors="coerce")
    rent["전용면적"] = pd.to_numeric(rent["전용면적"], errors="coerce")
    rent = rent[(rent["월세금액"].fillna(0) == 0) &
                (rent["전용면적"] > 0) & (rent["보증금액"] > 0)].copy()
    rent["전세_per_m2"] = rent["보증금액"] / rent["전용면적"]
    rent["bjd_key"] = (rent["법정동시군구코드"].astype("Int64").astype(str).str.zfill(5)
                       + "_" + rent["법정동"].astype(str).str.strip())
    bjd = rent.groupby("bjd_key").agg(jp=("전세_per_m2", "mean"),
                                      cnt=("전세_per_m2", "size")).reset_index()

    kik = pd.read_excel(KIK_PATH, dtype=str)
    kik = kik[kik["시도명"] == "서울특별시"]
    말소 = kik["말소일자"].astype(str).str.strip()
    kik = kik[(kik["말소일자"].isna() | (말소 == "") | (말소.str.lower() == "nan"))
              & kik["읍면동명"].notna() & kik["동리명"].notna()].copy()
    kik["bjd_key"] = kik["법정동코드"].str[:5] + "_" + kik["동리명"].str.strip()
    m = kik[["bjd_key", "행정동코드"]].drop_duplicates()

    j = bjd.merge(m, on="bjd_key", how="inner")
    j["jp_w"] = j["jp"] * j["cnt"]
    gg = j.groupby("행정동코드").agg(jp_w=("jp_w", "sum"), cnt=("cnt", "sum"))
    gg["jeonse_per_m2"] = gg["jp_w"] / gg["cnt"]      # 만원/㎡
    return gg["jeonse_per_m2"]


def minmax(s):
    lo, hi = s.min(), s.max()
    return (s - lo) / (hi - lo) if hi > lo else pd.Series(0.0, index=s.index)


def gaussian_kde_smooth(df, value_col, cx, cy, sigma):
    """중심점 가우시안 가중평균(Nadaraya-Watson). 자기자신 포함."""
    x = df[cx].to_numpy(); y = df[cy].to_numpy(); v = df[value_col].to_numpy()
    out = np.full(len(df), np.nan)
    for i in range(len(df)):
        if np.isnan(x[i]):
            out[i] = v[i]; continue
        d2 = (x - x[i]) ** 2 + (y - y[i]) ** 2
        w = np.exp(-d2 / (2 * sigma ** 2))
        w[np.isnan(v) | np.isnan(x)] = 0.0
        out[i] = np.nansum(w * v) / np.nansum(w)
    return out


def main():
    dm = pd.read_csv(MASTER, encoding="utf-8-sig", dtype={"adm_cd": str})

    g = load_boundary()
    name_gu = dm[["adm_nm", "자치구"]].dropna().drop_duplicates()
    name_gu["key"] = name_gu["adm_nm"].map(norm_name)
    g = assign_gu(g, name_gu[["key", "자치구"]].drop_duplicates())
    area_lut = g.groupby(["자치구", "key"])["area_km2"].sum().to_dict()
    gg = g.dropna(subset=["자치구"]).drop_duplicates(["자치구", "key"])
    cx_lut = gg.set_index(["자치구", "key"])["cx"].to_dict()
    cy_lut = gg.set_index(["자치구", "key"])["cy"].to_dict()

    dm["_k"] = dm["adm_nm"].map(norm_name)
    keys = list(zip(dm["자치구"], dm["_k"]))

    # 1) area 결측 보강(경계 실제면적) + density 재계산
    fixed_area = pd.Series([area_lut.get(k) for k in keys], index=dm.index)
    n_fix = int((dm["area_km2"].isna() & fixed_area.notna()).sum())
    dm["area_km2"] = dm["area_km2"].fillna(fixed_area)
    dm["newvilla_density"] = np.where(
        dm["area_km2"] > 0, dm["newvilla_count"] / dm["area_km2"], np.nan).round(2)

    # 3) 파생: 공시지가대비전세가괴리
    jpm2 = jeonse_per_m2_by_adm()                      # 만원/㎡
    dm["jeonse_per_m2_won"] = dm["adm_cd"].map(jpm2) * 10000.0
    dm["공시지가대비전세가괴리"] = (dm["jeonse_per_m2_won"] / dm["gongsi_per_m2"]).round(4)

    # 2) 분석대상 확정: 정규화 변수(괴리 포함) 모두 값 있는 동
    keep = dm[dm[NORM_VARS].notna().all(axis=1)].copy().reset_index(drop=True)

    kk = list(zip(keep["자치구"], keep["_k"]))
    keep["cx"] = [cx_lut.get(k, np.nan) for k in kk]
    keep["cy"] = [cy_lut.get(k, np.nan) for k in kk]

    # 4) MinMax 정규화
    for c in NORM_VARS:
        keep["norm_" + c] = minmax(keep[c]).round(4)

    # 5) KDE (σ=500m)
    for c in KDE_VARS:
        keep["kde_" + c] = np.round(
            gaussian_kde_smooth(keep, c, "cx", "cy", KDE_SIGMA), 4)

    keep = keep.drop(columns=["_k"])
    keep.to_csv(OUT, index=False, encoding="utf-8-sig")

    # ---------- 확인 ----------
    print(f"저장: {OUT}")
    print(f"area 보강된 동(홍제 등): {n_fix}개")
    print(f"최종 분석 동 개수: {len(keep)}개  (마스터 {len(dm)} - 제외 {len(dm)-len(keep)})")
    print(f"중심점 매칭 실패: {int(keep['cx'].isna().sum())}개")

    gap = keep["공시지가대비전세가괴리"]
    print(f"\n[공시지가대비전세가괴리] (전세가/㎡ ÷ 공시지가/㎡, 클수록 땅값 대비 전세가 과함)")
    print(f"  min/median/mean/max: {gap.min():.3f} / {gap.median():.3f} / {gap.mean():.3f} / {gap.max():.3f}")
    print("  상위 5개 동:")
    for _, r in keep.sort_values("공시지가대비전세가괴리", ascending=False).head(5).iterrows():
        print(f"    {r['자치구']} {r['adm_nm']}: {r['공시지가대비전세가괴리']:.3f} "
              f"(전세 {r['jeonse_per_m2_won']:,.0f} / 공시 {r['gongsi_per_m2']:,.0f} 원/㎡)")

    print("\n[norm_ 변수 범위 확인]")
    for c in NORM_VARS:
        s = keep["norm_" + c]
        print(f"  norm_{c}: min={s.min():.3f} max={s.max():.3f} (결측 {int(s.isna().sum())})")

    print("\n[KDE σ=500m 진단] (동 스케일에선 거의 항등 — 참고)")
    for c in KDE_VARS:
        corr = keep[c].corr(keep["kde_" + c])
        print(f"  {c}: raw↔kde 상관 {corr:.4f}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
