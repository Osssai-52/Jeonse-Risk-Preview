# 전세거래 취약도 조기경보 모델 — Claude Code 셋업 가이드

## 이 폴더를 Claude Code에서 여는 법

1. 이 `jeonse-project` 폴더 전체를 작업 PC에 둔다.
2. 터미널에서 폴더로 이동 후 `claude` 실행 (또는 Claude Code 앱에서 폴더 열기).
3. Claude Code가 자동으로 `CLAUDE.md`를 읽어 프로젝트 맥락을 파악한다.
   → 매 세션마다 배경 설명 안 해도 됨.

## 첫 작업 순서

### 0단계: 환경 준비
```
pip install geopandas pandas scikit-learn scipy folium matplotlib PublicDataReader
```

### 1단계: 외부 데이터 받기
- 공공데이터포털(data.go.kr) 가입 → 아래 2개 활용신청
  - 국토교통부_연립다세대 매매 실거래가
  - 국토교통부_연립다세대 전월세 실거래가
- 인증키를 환경변수에 저장:
  ```
  export MOLIT_API_KEY="발급받은키"
  python scripts/00_download_external.py
  ```
- 건축물대장 최신본은 공공데이터포털/open.eais.go.kr 에서 받아 data/external/ 에 둔다.
- (또는 rt.molit.go.kr 자료제공에서 수동 CSV 다운로드)

### 2단계: Claude Code에게 시킬 것
Claude Code 채팅창에 이렇게 요청하면 됨 (예시):

> "scripts/03_jeonse_ratio.py 의 TODO를 채워줘. data/external/villa_sale.csv 와
>  villa_rent.csv 의 실제 컬럼명을 먼저 확인하고, 전세만 필터한 뒤 동 단위
>  전세가율을 계산해줘. CLAUDE.md 의 원칙을 지켜줘."

Claude Code는 파일을 직접 읽고 컬럼 확인 → 코드 수정 → 실행 → 디버깅까지 한다.

## 채팅 vs Claude Code 역할 분담

| 작업 | 어디서 |
|------|--------|
| 코드 작성·실행·디버깅, 데이터 처리, 지도 생성 | **Claude Code** |
| "이 변수 가중치 적절한가", "발표 논리 어떻게", "결과 해석" | **이 채팅(claude.ai)** |
| 캠퍼스 반출 데이터 처리 | 캠퍼스 폐쇄망 PC |

즉, **무겁고 반복적인 파일 작업 = Claude Code**, **판단·해석·전략 = 채팅**.

## 파이프라인 전체

```
00_download_external.py      외부 실거래가 다운로드
01_build_spatial_db.py       250m 격자 공간DB
02_make_variables.py         건물→격자·동 변수 집계
03_jeonse_ratio.py           전세가율 (핵심)
04_normalize_kde.py          MinMax 정규화 + KDE
05_vulnerability_index.py    S-JVWI 취약도 지수
06_kmeans_cluster.py         위험 유형 군집
07_08_validate_detect.py     검증 + 다음위험지역 탐지
09_visualize.py              Folium 히트맵
```

## 핵심 문서
- `docs/ANALYSIS_DESIGN.md` — 전체 분석 설계 (왜 이렇게 하는지)
- `docs/DATA_SPEC.md` — 데이터 출처·연도·역할
- `CLAUDE.md` — Claude Code용 프로젝트 컨텍스트

## 잊지 말 것
1. 입력 변수는 최신(2025~26)으로 통일. 건축물대장 2016년본 쓰지 말 것.
2. 피해 CSV(2023~25)는 검증용 닻. 직접 예측 타깃 아님.
3. 자치구 25개로 머신러닝 회귀 금지. 검증은 상관·순위만.
4. 메인 단위 250m 격자, 학습 단위 행정동, 검증 단위 자치구.
