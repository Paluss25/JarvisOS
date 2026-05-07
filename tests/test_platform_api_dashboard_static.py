import pytest
from starlette.exceptions import HTTPException as StarletteHTTPException

from platform_api.app import SPAStaticFiles


@pytest.mark.asyncio
async def test_spa_static_files_falls_back_to_index_for_client_routes(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<div id=\"root\"></div>", encoding="utf-8")
    assets = dist / "assets"
    assets.mkdir()
    (assets / "index.js").write_text("console.log('ok')", encoding="utf-8")

    files = SPAStaticFiles(directory=str(dist), html=True)
    scope = {"type": "http", "method": "GET", "headers": []}

    route_response = await files.get_response("login", scope)
    asset_response = await files.get_response("assets/index.js", scope)

    assert route_response.status_code == 200
    assert asset_response.status_code == 200


@pytest.mark.asyncio
async def test_spa_static_files_preserves_api_and_missing_asset_404s(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<div id=\"root\"></div>", encoding="utf-8")

    files = SPAStaticFiles(directory=str(dist), html=True)
    scope = {"type": "http", "method": "GET", "headers": []}

    with pytest.raises(StarletteHTTPException):
        await files.get_response("api/missing", scope)
    with pytest.raises(StarletteHTTPException):
        await files.get_response("assets/missing.js", scope)
