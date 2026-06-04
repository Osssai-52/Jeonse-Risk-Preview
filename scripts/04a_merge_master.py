"""
04a_merge_master.py
외부 데이터(dong_external)와 캠퍼스 폐쇄망 데이터(dong_campus)를
행정동 코드(adm_cd, 10자리 행안부)로 통합 → 동 단위 마스터 테이블.

입력:
  data/processed/dong_external.csv  전세가율·신축빌라 등 (외부)
  data/processed/dong_campus.csv    청년비율·공시지가 등 (캠퍼스 반출)
출력:
  data/processed/dong_master.csv    adm_cd 기준 outer join
"""

import sys
import pandas as pd
from pathlib import Path

PROC = Path(__file__).resolve().parents[1] / "data" / "processed"
EXT_PATH = PROC / "dong_external.csv"
CAM_PATH = PROC / "dong_campus.csv"
OUT = PROC / "dong_master.csv"


def load(path):
    return pd.read_csv(path, encoding="utf-8-sig", dtype={"adm_cd": str})


def coalesce(df, target, candidates):
    """여러 컬럼을 우선순위대로 합쳐 단일 컬럼으로 정리."""
    s = None
    for c in candidates:
        if c in df.columns:
            s = df[c] if s is None else s.combine_first(df[c])
    df[target] = s
    drop = [c for c in candidates if c in df.columns and c != target]
    return df.drop(columns=drop)


def main():
    ext = load(EXT_PATH)
    cam = load(CAM_PATH)

    # adm_cd 외 공통 식별 컬럼(adm_nm, 자치구)은 충돌 방지 위해 접미사 처리
    m = ext.merge(cam, on="adm_cd", how="outer", suffixes=("", "_cam"))

    # adm_nm·자치구 단일 컬럼 정리
    m = coalesce(m, "adm_nm", ["adm_nm", "adm_nm_cam"])
    m = coalesce(m, "자치구", ["자치구", "자치구_cam"])

    # 컬럼 순서: 식별자 → 외부 변수 → 캠퍼스 변수
    id_cols = ["adm_cd", "adm_nm", "자치구"]
    var_cols = [c for c in m.columns if c not in id_cols]
    out = m[id_cols + var_cols].sort_values("adm_cd").reset_index(drop=True)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")

    # --- 확인 ---
    print(f"저장: {OUT}  (전체 {len(out)}개 동, outer join)")
    print(f"입력: external {len(ext)}개 / campus {len(cam)}개\n")

    print("변수별 결측 동 개수:")
    for c in var_cols:
        print(f"  {c}: 결측 {out[c].isna().sum()}개 (값 {out[c].notna().sum()}개)")

    complete = out[var_cols].notna().all(axis=1).sum()
    print(f"\n모든 변수 값 있는 완전 케이스: {complete}개 / {len(out)}개")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
