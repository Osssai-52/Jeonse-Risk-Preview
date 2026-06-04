"""
02_make_variables.py
건물/필지 데이터 → 250m 격자·행정동 단위 변수 집계

생성 변수:
  - newvilla_density: 준공 5년내 연립·다세대 건물 수 (격자)
  - villa_density: 연립·다세대 전체 건물 수 (격자)
  - newvilla_ratio: 신축빌라 비율 (동)
  - gongsi_gap: 공시지가 대비 전세가 괴리 (동, 03 이후 결합)
  - youth_ratio: 청년(20~39) 인구 비율 (동, B031)
  - inflow: 전입수요 (동, B050)
입력: 외부 건축물대장(최신), B020/B403 공시지가, B031, B050
출력: data/processed/grid_vars.gpkg, dong_vars.csv
"""
# TODO: 건축물대장 컬럼(사용승인일, 주용도, 대지위치) 확인 후 신축·빌라 판별
#       공간조인(sjoin)으로 건물 포인트를 격자에 할당
print("스켈레톤 - Claude Code로 채우기")
