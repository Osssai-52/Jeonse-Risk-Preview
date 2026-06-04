"""
02c_building_vars.py  (설계 v3)
건물위험 변수 — 표제부 전체 주거건물(단독+공동, 유형 무관), 행정동(adm_cd) 단위.

주거건물 = 주용도 '단독주택'(단독·다가구) + '공동주택'(빌라·아파트). 오피스텔은 표제부
식별 불가라 제외. units = 세대수(세대)+가구수(가구) (단독·다가구는 가구수에 잡힘).

변수:
  new_density   신축밀집도   = 동 면적(km²)당 2021년 이후 준공 주거건물 수
  avg_age       건물노후도   = 평균 준공경과연수 (2026 - 준공연도)
  old30_ratio   노후비율     = 경과연수 30년 이상 건물 비중
  avg_units     건물당평균세대 = 평균 units
  small_ratio   소형주택비율 = units <= SMALL_THR 건물 비중

매핑: 표제부 10자리 법정동코드 → KIKmix → adm. 절대카운트·집계는 1:N '균등배분'
(건물수/행정동수)으로 총량 보존(복제 시 분할 법정동에서 과대계상). 면적은 경계(5179).
출력: data/processed/building_vars_adm.csv
"""

import sys
import glob
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path

EXT = Path(__file__).resolve().parents[1] / "data" / "external"
PROC = Path(__file__).resolve().parents[1] / "data" / "processed"
KIK_PATH = EXT / "KIKmix.20210401.xlsx"
BND_PATH = EXT / "BND_ADM_DONG_PG.shp"
OUT = PROC / "building_vars_adm.csv"

AREA_CRS = "EPSG:5179"
NOW_YEAR = 2026
NEW_YEAR = 2021
OLD_AGE = 30
SMALL_THR = 4          # 소형주택: units 이하


def load_csv(path, **kw):
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc, dtype=str, low_memory=False, **kw)
        except (UnicodeDecodeError, Exception):
            continue
    raise ValueError(f"읽기 실패: {path}")


def norm_name(s):
    return str(s).strip().replace("·", ".").replace("ㆍ", ".").replace("제", "")


def building_aggregates_by_bjd():
    """표제부 주거건물을 10자리 법정동코드별로 집계."""
    frames = []
    for f in sorted(glob.glob(str(EXT / "03. 표제부_*.csv"))):
        d = load_csv(f, usecols=["시군구코드", "법정동코드", "주용도코드명",
                                 "세대수(세대)", "가구수(가구)", "사용승인일"])
        d = d[d["주용도코드명"].isin(["단독주택", "공동주택"])].copy()
        frames.append(d)
    b = pd.concat(frames, ignore_index=True)
    b["bjd10"] = b["시군구코드"].str.zfill(5) + b["법정동코드"].str.zfill(5)
    b["units"] = (pd.to_numeric(b["세대수(세대)"], errors="coerce").fillna(0)
                  + pd.to_numeric(b["가구수(가구)"], errors="coerce").fillna(0))
    yr = pd.to_numeric(b["사용승인일"].astype(str).str.strip().str[:4], errors="coerce")
    b["yr"] = yr.where((yr >= 1900) & (yr <= NOW_YEAR))     # 유효 준공연도만
    b["age"] = NOW_YEAR - b["yr"]
    b["is_new"] = (b["yr"] >= NEW_YEAR).fillna(False)
    b["is_old"] = (b["age"] >= OLD_AGE).fillna(False)
    b["is_small"] = b["units"] <= SMALL_THR
    b["has_yr"] = b["yr"].notna()

    g = b.groupby("bjd10")
    agg = pd.DataFrame({
        "res_n": g.size(),
        "new_n": g["is_new"].sum(),
        "age_sum": g["age"].sum(),              # 유효연도만 합산(결측 제외)
        "yr_n": g["has_yr"].sum(),
        "old_n": g["is_old"].sum(),
        "units_sum": g["units"].sum(),
        "small_n": g["is_small"].sum(),
    })
    return agg


def load_area_by_adm(adm_names):
    """경계(5179) 면적을 (자치구, 정규화이름)로 만들고 adm_cd별 면적 매핑."""
    g = gpd.read_file(BND_PATH)
    g = g[g["ADM_CD"].astype(str).str.startswith("11")].to_crs(AREA_CRS).copy()
    g["sgg5"] = g["ADM_CD"].astype(str).str[:5]
    g["key"] = g["ADM_NM"].map(norm_name)
    g["area_km2"] = g.geometry.area / 1e6
    nm = adm_names.copy()
    nm["key"] = nm["adm_nm"].map(norm_name)
    votes = g.merge(nm[["key", "자치구"]].drop_duplicates(), on="key", how="left")
    sgg2gu = (votes.dropna(subset=["자치구"]).groupby("sgg5")["자치구"]
              .agg(lambda s: s.mode().iloc[0]))
    g["자치구"] = g["sgg5"].map(sgg2gu)
    area = g.groupby(["자치구", "key"])["area_km2"].sum().to_dict()
    out = {}
    for _, r in nm.iterrows():
        out[r["adm_cd"]] = area.get((r["자치구"], r["key"]))
    return out


def main():
    agg = building_aggregates_by_bjd()

    # KIKmix: 법정동코드 → 행정동코드 + 이름, 그리고 법정동당 행정동수(균등배분용)
    kik = pd.read_excel(KIK_PATH, dtype=str)
    kik = kik[kik["시도명"] == "서울특별시"]
    mal = kik["말소일자"].astype(str).str.strip()
    kik = kik[(kik["말소일자"].isna() | (mal == "") | (mal.str.lower() == "nan"))
              & kik["읍면동명"].notna() & kik["동리명"].notna()].copy()
    code_map = kik[["법정동코드", "행정동코드", "읍면동명", "시군구명"]].drop_duplicates()
    n_adm = code_map.groupby("법정동코드")["행정동코드"].nunique()

    sum_cols = ["res_n", "new_n", "age_sum", "yr_n", "old_n", "units_sum", "small_n"]
    m = agg.reset_index().merge(code_map, left_on="bjd10", right_on="법정동코드", how="inner")
    split = m["법정동코드"].map(n_adm)
    for c in sum_cols:                       # 균등배분(1:N)
        m[c] = m[c] / split

    g = m.groupby("행정동코드")
    out = pd.DataFrame({"adm_nm": g["읍면동명"].first(), "자치구": g["시군구명"].first()})
    for c in sum_cols:
        out[c] = g[c].sum()                  # N:1 합산

    out = out.reset_index().rename(columns={"행정동코드": "adm_cd"})
    area_map = load_area_by_adm(out[["adm_cd", "adm_nm", "자치구"]])
    out["area_km2"] = out["adm_cd"].map(area_map)

    out["res_building_n"] = out["res_n"].round().astype(int)
    out["new_density"] = (out["new_n"] / out["area_km2"]).round(2)
    out["avg_age"] = (out["age_sum"] / out["yr_n"]).round(2)
    out["old30_ratio"] = (out["old_n"] / out["yr_n"]).round(4)
    out["avg_units"] = (out["units_sum"] / out["res_n"]).round(2)
    out["small_ratio"] = (out["small_n"] / out["res_n"]).round(4)

    out = out[["adm_cd", "adm_nm", "자치구", "res_building_n", "area_km2",
               "new_density", "avg_age", "old30_ratio", "avg_units", "small_ratio"]]
    out = out.sort_values("adm_cd").reset_index(drop=True)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")

    # ---- 확인 ----
    print(f"저장: {OUT}  ({len(out)}개 행정동, 소형 임계 units<={SMALL_THR})")
    print(f"면적 결측(경계 미매칭) 동: {out['area_km2'].isna().sum()}개")
    print("\n[변수 분포 min/median/max]")
    for c in ["new_density", "avg_age", "old30_ratio", "avg_units", "small_ratio"]:
        s = out[c].dropna()
        print(f"  {c}: {s.min():.2f} / {s.median():.2f} / {s.max():.2f}")

    # 구 단위 재계산(건물수 가중 노후도 / 면적당 신축수)
    guage = (out.assign(aw=out["avg_age"] * out["res_building_n"])
             .groupby("자치구").apply(lambda d: d["aw"].sum() / d["res_building_n"].sum()))
    print("\n[건물노후도(평균 경과연수) 상위 5개 구]")
    for gu_, v in guage.sort_values(ascending=False).head(5).items():
        print(f"  {gu_}: {v:.1f}년")
    gnd = (out.dropna(subset=["area_km2"]).assign(nn=out["new_density"] * out["area_km2"])
           .groupby("자치구").apply(lambda d: d["nn"].sum() / d["area_km2"].sum()))
    print("\n[신축밀집도(구 면적당 신축 주거건물 수) 상위 5개 구]")
    for gu_, v in gnd.sort_values(ascending=False).head(5).items():
        print(f"  {gu_}: {v:.1f} 동/km²")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
