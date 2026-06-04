"""
07_validate_gu.py  +  08_detect_next.py 통합 골격

[07] 검증: 동별 S-JVWI를 구 단위로 집계 → 2023~25 피해 CSV와 상관분석
  - 표본 25개 → 머신러닝 금지, Spearman 순위상관만
  - 관악·강서·동작·금천이 상위에 오면 검증 성공

[08] 다음 위험지역 탐지: 저피해·고위험 동
  정의: S-JVWI 상위 25% 이면서, 소속 자치구 누적피해 하위 50% 인 동
       = "예방자원 우선지역"
"""

import pandas as pd
from pathlib import Path
from scipy.stats import spearmanr

PROC = Path(__file__).resolve().parents[1] / "data" / "processed"
ROOT = Path(__file__).resolve().parents[1]


def load_csv(path):
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc)
        except Exception:
            continue
    raise ValueError(path)


def main():
    sjvwi = pd.read_csv(PROC / "sjvwi.csv", encoding="utf-8-sig")
    # 피해 CSV (보유) — 업로드 위치에서 복사해두기
    harm = load_csv(ROOT / "data" / "raw" / "서울특별시_자치구별_전세사기_발생건수.csv")

    # 숫자 정리 (CSV에 ' 1,108 ' 같은 공백·콤마 있음)
    for col in ["2023년", "2024년", "2025년"]:
        harm[col] = (harm[col].astype(str)
                     .str.replace(",", "").str.strip().replace("", "0").astype(float))
    harm = harm[harm["구분"] != "총합계"].copy()
    harm["누적피해"] = harm[["2023년", "2024년", "2025년"]].sum(axis=1)

    # --- 07 검증: 동 S-JVWI → 구 평균 ---
    # sjvwi에 자치구 컬럼(gu_nm)이 있어야 함. 없으면 adm_cd 앞자리로 매핑.
    if "gu_nm" not in sjvwi.columns:
        print("sjvwi에 자치구(gu_nm) 컬럼 필요. adm_cd→자치구 매핑 추가하세요.")
        return

    gu_score = sjvwi.groupby("gu_nm")["S_JVWI"].mean().rename("구평균_취약도")
    merged = harm.merge(gu_score, left_on="구분", right_index=True, how="inner")

    rho, p = spearmanr(merged["구평균_취약도"], merged["누적피해"])
    print(f"[검증] 구 취약도 vs 누적피해 Spearman ρ = {rho:.3f}, p = {p:.4f}")
    print("상위 취약도 구 5개:")
    print(merged.sort_values("구평균_취약도", ascending=False)[["구분", "구평균_취약도", "누적피해"]].head())

    # --- 08 다음 위험지역 탐지 ---
    thr_high = sjvwi["S_JVWI"].quantile(0.75)
    harm_rank = harm.set_index("구분")["누적피해"].rank(pct=True)  # 0~1
    sjvwi["구피해백분위"] = sjvwi["gu_nm"].map(harm_rank)

    next_risk = sjvwi[(sjvwi["S_JVWI"] >= thr_high) &
                      (sjvwi["구피해백분위"] <= 0.50)].copy()
    next_risk = next_risk.sort_values("S_JVWI", ascending=False)

    cols = [c for c in ["adm_cd", "adm_nm", "gu_nm", "S_JVWI", "구피해백분위"]
            if c in next_risk.columns]
    next_risk[cols].to_csv(PROC / "next_risk_dong.csv", index=False, encoding="utf-8-sig")
    print(f"\n[탐지] 예방자원 우선지역(저피해·고위험) {len(next_risk)}개 동")
    print(next_risk[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
