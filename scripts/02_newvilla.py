"""
02_newvilla.py
표제부(자치구별 CSV)로 신축빌라 변수 생성 → 행정동(adm_cd) 단위.

입력: data/external/03. 표제부_OO구.csv  (25개 구, utf-8-sig)
  주요 컬럼: 시군구코드(5), 법정동코드(5), 주용도코드명, 사용승인일(YYYYMMDD), 지상층수
매핑: data/external/KIKmix.20210401.xlsx (법정동코드 10자리 ↔ 행정동코드)

빌라 판별(표제부 한계상 근사):
  주용도코드명 == '공동주택' 중 지상층수 5층 이하 → 연립·다세대(빌라)로 간주.
  (공동주택에는 아파트도 포함되나 표제부에 빌라/아파트 구분 코드가 없어
   층수로 아파트를 근사 분리. 발표 시 한계로 명시.)
신축 판별: 사용승인일 앞 4자리 = 준공연도, 2021년 이후 → 신축. 결측/이상은 비신축 처리.

법정동 10자리코드 = 시군구코드(5) + 법정동코드(5) → KIKmix와 직접 조인.
카디널리티: 1:N(법정동→행정동) 복제, N:1(행정동에 여러 법정동) 건수 합산.
  ※ 카운트 변수라 1:N 복제 시 절대건수가 중복되지만, newvilla_ratio는
    분자·분모가 함께 복제되어 보존됨(설계서상 비율이 핵심 변수).

[중요] villa_total / newvilla_count 는 1:N 복제로 중복이 포함된 값이다.
  → 행정동 간 상대 비교용일 뿐, 전 서울 합산(sum)으로 쓰면 건물이
    중복 집계되어 틀린다. 실제 사용 변수는 newvilla_ratio(비율) 하나다.
"""

import sys
import glob
import os
import re
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path

EXT = Path(__file__).resolve().parents[1] / "data" / "external"
PROC = Path(__file__).resolve().parents[1] / "data" / "processed"
PROC.mkdir(parents=True, exist_ok=True)

KIK_PATH = EXT / "KIKmix.20210401.xlsx"
BND_PATH = EXT / "BND_ADM_DONG_PG.shp"   # 통계청(SGIS) 행정동 경계, EPSG:5186
OUT = PROC / "newvilla_adm.csv"

AREA_CRS = "EPSG:5179"   # 면적 계산용 미터 좌표계

NEW_YEAR = 2021        # 이 연도 이후 준공 = 신축
MAX_FLOOR_VILLA = 5    # 빌라 근사: 지상층수 이하

SEOUL_GU = [
    "종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구", "성북구",
    "강북구", "도봉구", "노원구", "은평구", "서대문구", "마포구", "양천구", "강서구",
    "구로구", "금천구", "영등포구", "동작구", "관악구", "서초구", "강남구", "송파구",
    "강동구",
]


def load_csv(path):
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc, dtype=str, low_memory=False)
        except (UnicodeDecodeError, Exception):
            continue
    raise ValueError(f"읽기 실패: {path}")


def check_files():
    """25개 구 파일 점검 + 빠진 구 보고."""
    files = sorted(glob.glob(str(EXT / "03. 표제부_*.csv")))
    present = {os.path.basename(f).replace("03. 표제부_", "").replace(".csv", ""): f
               for f in files}
    missing = [gu for gu in SEOUL_GU if gu not in present]
    print(f"표제부 파일: {len(present)}개 / 서울 25개구")
    print(f"빠진 구: {missing if missing else '없음'}")
    return present


def norm_name(s):
    """행정동명 정규화: '제N동'→'N동', 가운뎃점 통일. KIKmix(2021)↔경계(2025) 매칭용."""
    s = str(s).strip()
    s = s.replace("·", ".").replace("ㆍ", ".")
    s = re.sub(r"제(\d)", r"\1", s)
    return s


def load_dong_area(gu_name_map):
    """
    행정동 경계(SGIS)에서 행정동 면적(km²)을 (자치구, 정규화이름) 키로 산출.
    이 파일의 ADM_CD는 8자리 통계청 코드라 행안부 10자리 adm_cd와 직접 매칭 불가
    → 이름(정규화) 매칭으로 면적만 가져온다. (adm_cd2가 있는 vworld 파일이면 코드 직매칭 가능)

    주의: 서울엔 동명이동이 있다(신사동=강남구·관악구). 이름만으로 합치면 면적이 섞이므로
    통계청 시군구 prefix(ADM_CD[:5])를 KIKmix 동명-자치구와 다수결 매칭해 자치구를 부여한 뒤
    (자치구, 이름)으로 키를 만든다.
    gu_name_map: KIKmix 기반 {정규화 동이름 -> [자치구...]} 다수결 투표용 (자치구, key) set.
    """
    g = gpd.read_file(BND_PATH)
    g = g[g["ADM_CD"].astype(str).str.startswith("11")].copy()   # 서울(통계청 시도 11*)
    base_date = str(g["BASE_DATE"].iloc[0]) if "BASE_DATE" in g.columns else "?"
    n_seoul = len(g)
    g = g.to_crs(AREA_CRS)
    g["area_km2"] = g.geometry.area / 1e6
    g["sgg5"] = g["ADM_CD"].astype(str).str[:5]
    g["key"] = g["ADM_NM"].map(norm_name)

    # 통계청 sgg5 → 자치구 다수결 (각 prefix의 동명들을 KIKmix 자치구에 투표)
    votes = g.merge(gu_name_map, on="key", how="left")
    sgg2gu = (votes.dropna(subset=["자치구"])
              .groupby("sgg5")["자치구"]
              .agg(lambda s: s.mode().iloc[0]))
    g["자치구"] = g["sgg5"].map(sgg2gu)

    dups = sorted(g.loc[g.duplicated(["자치구", "key"], keep=False), "ADM_NM"].unique().tolist())
    area = g.groupby(["자치구", "key"])["area_km2"].sum()
    return area, base_date, n_seoul, g["area_km2"].sum(), dups


def load_mapping():
    """서울 활성 법정동(10자리)↔행정동 매핑."""
    kik = pd.read_excel(KIK_PATH, dtype=str)
    kik = kik[kik["시도명"] == "서울특별시"].copy()
    말소 = kik["말소일자"].astype(str).str.strip()
    kik = kik[kik["말소일자"].isna() | (말소 == "") | (말소.str.lower() == "nan")]
    kik = kik[kik["읍면동명"].notna() & kik["동리명"].notna()].copy()
    m = kik[["법정동코드", "행정동코드", "읍면동명", "시군구명"]].drop_duplicates()
    return m, kik["행정동코드"].nunique()


def main():
    present = check_files()

    frames = []
    for gu, f in present.items():
        df = load_csv(f)
        df["자치구"] = gu
        frames.append(df)
    bld = pd.concat(frames, ignore_index=True)
    print(f"\n전체 표제부 건물 행: {len(bld):,}")

    # 10자리 법정동코드 복원
    bld["bjd10"] = (bld["시군구코드"].str.strip().str.zfill(5)
                    + bld["법정동코드"].str.strip().str.zfill(5))

    # 빌라 판별: 공동주택 & 지상층수 <= 5 (층수 결측은 제외)
    floor = pd.to_numeric(bld["지상층수"], errors="coerce")
    is_villa = (bld["주용도코드명"] == "공동주택") & (floor <= MAX_FLOOR_VILLA)
    villa = bld[is_villa].copy()

    # 신축 판별: 사용승인일 앞 4자리 >= NEW_YEAR (결측/이상 → 비신축)
    yr = pd.to_numeric(villa["사용승인일"].astype(str).str.strip().str[:4], errors="coerce")
    villa["is_new"] = (yr >= NEW_YEAR).fillna(False)

    n_villa = len(villa)
    n_new = int(villa["is_new"].sum())
    print(f"빌라로 분류된 건물: {n_villa:,}  / 그중 신축빌라: {n_new:,}")

    # 법정동(10자리) 집계
    dong = villa.groupby("bjd10").agg(
        villa_total=("is_new", "size"),
        newvilla_count=("is_new", "sum"),
    ).reset_index()
    dong["newvilla_count"] = dong["newvilla_count"].astype(int)

    # KIKmix 매핑 (1:N 복제는 merge 확장으로 자동 처리)
    m, total_adm_seoul = load_mapping()
    merged = dong.merge(m, left_on="bjd10", right_on="법정동코드", how="left")
    unmatched = dong[~dong["bjd10"].isin(m["법정동코드"])]

    matched = merged[merged["행정동코드"].notna()].copy()

    # N:1 합산: 행정동별 카운트 합 → 비율 재계산
    # 주의: villa_total/newvilla_count 는 1:N 복제 중복 포함 → 행정동 비교용,
    #       전 서울 합산용 아님. 핵심 변수는 newvilla_ratio.
    g = matched.groupby("행정동코드")
    agg = pd.DataFrame({
        "adm_nm": g["읍면동명"].first(),
        "자치구": g["시군구명"].first(),
        "villa_total": g["villa_total"].sum().astype(int),
        "newvilla_count": g["newvilla_count"].sum().astype(int),
    })
    agg["newvilla_ratio"] = np.where(
        agg["villa_total"] > 0, agg["newvilla_count"] / agg["villa_total"], 0.0
    ).round(4)
    agg = agg.reset_index().rename(columns={"행정동코드": "adm_cd"})

    out = agg[["adm_cd", "adm_nm", "자치구", "villa_total", "newvilla_count", "newvilla_ratio"]].copy()

    # --- 밀집도: newvilla_count(원시) / 행정동 면적(km²) ---
    out["_k"] = out["adm_nm"].map(norm_name)
    gu_name_map = out[["_k", "자치구"]].drop_duplicates().rename(columns={"_k": "key"})
    area, base_date, n_seoul_bnd, seoul_area_sum, dups = load_dong_area(gu_name_map)
    area_lut = area.to_dict()  # {(자치구, key): km²}
    out["area_km2"] = [area_lut.get((gu, k)) for gu, k in zip(out["자치구"], out["_k"])]
    out["area_km2"] = out["area_km2"].round(4)
    out["newvilla_density"] = (out["newvilla_count"] / out["area_km2"]).round(2)
    no_area = out[out["area_km2"].isna()].copy()
    out = out.drop(columns="_k")

    out = out[["adm_cd", "adm_nm", "자치구", "villa_total", "newvilla_count",
               "newvilla_ratio", "area_km2", "newvilla_density"]]
    out = out.sort_values("newvilla_ratio", ascending=False).reset_index(drop=True)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")

    # --- 확인 ---
    print(f"\n저장: {OUT}")
    print(f"값이 붙은 행정동: {len(out)}개 / 서울 {total_adm_seoul}개 "
          f"(커버리지 {len(out)/total_adm_seoul*100:.1f}%)")
    print(f"경계 파일 기준연도(BASE_DATE): {base_date} | 경계 서울 행정동 수: {n_seoul_bnd} "
          f"| 서울 면적 합 {seoul_area_sum:.1f} km²")
    if dups:
        print(f"  (경계 내 동일 이름 합산 처리: {dups})")
    r = out["newvilla_ratio"]
    print(f"신축빌라 비율 min/median/max: {r.min():.4f} / {r.median():.4f} / {r.max():.4f}")
    print(f"법정동→행정동 매칭 실패: {len(unmatched)}개")

    print(f"\n면적 매칭 실패 행정동(경계 2025 vs KIKmix 2021 개편차): {len(no_area)}개")
    for _, row in no_area.iterrows():
        print(f"  {row['adm_cd']} {row['자치구']} {row['adm_nm']}")

    print("\n[newvilla_ratio 상위 5개 행정동]")
    for _, x in out.sort_values("newvilla_ratio", ascending=False).head(5).iterrows():
        print(f"  {x['자치구']} {x['adm_nm']}: ratio={x['newvilla_ratio']:.4f} "
              f"(신축 {x['newvilla_count']}/{x['villa_total']})")
    print("[newvilla_density 상위 5개 행정동] (신축빌라 수/km²)")
    for _, x in out.sort_values("newvilla_density", ascending=False).head(5).iterrows():
        print(f"  {x['자치구']} {x['adm_nm']}: density={x['newvilla_density']:.2f} "
              f"(신축 {x['newvilla_count']}건 / {x['area_km2']:.3f} km²)")

    # 두 변수 상관 (면적 매칭된 동 한정)
    valid = out.dropna(subset=["newvilla_density"])
    pear = valid["newvilla_ratio"].corr(valid["newvilla_density"], method="pearson")
    spear = valid["newvilla_ratio"].corr(valid["newvilla_density"], method="spearman")
    print(f"\nratio vs density 상관 (n={len(valid)}): "
          f"Pearson={pear:.3f}, Spearman={spear:.3f}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
