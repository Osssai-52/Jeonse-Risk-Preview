"""
01_build_spatial_db.py
250m 격자 공간DB 구축 (GeoPath의 100m 격자 → 250m로 변형)

순서:
  1. 서울 행정동/자치구 경계 shp 로드 (B294/B295 또는 SGIS)
  2. 서울 전체 bounding box에 250m 격자 생성 (shapely)
  3. 격자를 행정동 경계로 클립 + 행정동 코드 부여
  4. B031 인구로 총인구 0 격자 제거 (GeoPath와 동일 처리)
출력: data/processed/grid_250m.gpkg
"""
import geopandas as gpd
import numpy as np
from shapely.geometry import box
from pathlib import Path

PROC = Path(__file__).resolve().parents[1] / "data" / "processed"
GRID_SIZE = 250  # m. 빌라 sparse 문제로 100보다 250 권장

def make_grid(bounds, size, crs):
    minx, miny, maxx, maxy = bounds
    xs = np.arange(minx, maxx, size)
    ys = np.arange(miny, maxy, size)
    cells = [box(x, y, x+size, y+size) for x in xs for y in ys]
    return gpd.GeoDataFrame(geometry=cells, crs=crs)

def main():
    # TODO: 경계 shp 경로 지정 (EPSG:5179 등 미터 좌표계로 변환)
    # dong = gpd.read_file("data/raw/dong_boundary.shp").to_crs(5179)
    # grid = make_grid(dong.total_bounds, GRID_SIZE, 5179)
    # grid = gpd.overlay(grid, dong[["adm_cd","geometry"]], how="intersection")
    # grid["grid_id"] = range(len(grid))
    # ... 총인구 0 격자 제거 후 저장
    print("경계 shp 경로 지정 후 TODO 채우기")

if __name__ == "__main__":
    main()
