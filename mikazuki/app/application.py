import mimetypes
import os
import sys
import webbrowser
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from mikazuki.app.api_v2 import router as api_v2_router
from mikazuki.app.caption_api import router as caption_api_router
from mikazuki.app.settings_api import router as settings_api_router
from mikazuki.app.tag_editor_api import router as tag_editor_api_router
from mikazuki.mcp.integration import MCPService
from mikazuki.storage.paths import app_root

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
FRONTEND_DIST = app_root() / "frontend" / "dist"
FAVICON = app_root() / "assets" / "favicon.ico"
INDEX_HTML = FRONTEND_DIST / "index.html"
# 配置导入/保存脚本放在 frontend/ 下而不是 dist/ 里，前端整目录升级不会把它删掉。
TOOLS_SCRIPT = app_root() / "frontend" / "workbench_tools.js"
TOOLS_SCRIPT_URL = "/__workbench_tools.js"
TOOLS_SCRIPT_TAG = f'<script src="{TOOLS_SCRIPT_URL}" defer></script>'


def render_index() -> HTMLResponse | None:
    """返回注入了工作台工具脚本的 index.html；文件缺失时返回 None。"""
    if not INDEX_HTML.exists():
        return None
    html = INDEX_HTML.read_text(encoding="utf-8", errors="replace")
    if TOOLS_SCRIPT.exists() and TOOLS_SCRIPT_TAG not in html:
        if "</body>" in html:
            html = html.replace("</body>", f"{TOOLS_SCRIPT_TAG}\n</body>", 1)
        else:
            html = f"{html}\n{TOOLS_SCRIPT_TAG}\n"
    return HTMLResponse(html)


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        if path in ("", ".", "./", "index.html", "./index.html"):
            page = render_index()
            if page is not None:
                return page
        try:
            return await super().get_response(path, scope)
        except HTTPException as ex:
            if ex.status_code == 404:
                page = render_index()
                if page is not None:
                    return page
                return await super().get_response("index.html", scope)
            else:
                raise ex


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with _app.state.mcp_service.lifespan():
        if sys.platform == "win32" and os.environ.get("MIKAZUKI_DEV", "0") != "1":
            webbrowser.open(f'http://{os.environ.get("MIKAZUKI_HOST", "127.0.0.1")}:{os.environ.get("MIKAZUKI_PORT", "28000")}')
        yield


app = FastAPI(lifespan=lifespan)
app.state.mcp_service = MCPService(app)


cors_config = os.environ.get("MIKAZUKI_APP_CORS", "")
if cors_config != "":
    if cors_config == "1":
        cors_config = ["http://localhost:8004", "*"]
    else:
        cors_config = cors_config.split(";")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_config,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def add_cache_control_header(request, call_next):
    response = await call_next(request)
    if "Cache-Control" not in response.headers:
        response.headers["Cache-Control"] = "max-age=0"
    return response

app.include_router(api_v2_router, prefix="/api/v2")
app.include_router(caption_api_router, prefix="/api/v2/caption")
app.include_router(tag_editor_api_router, prefix="/api/v2/tag-editor")
app.include_router(settings_api_router, prefix="/api/v2/settings")
app.mount("/mcp", app.state.mcp_service, name="mcp")


@app.get("/")
async def index():
    page = render_index()
    if page is not None:
        return page
    return JSONResponse(
        status_code=503,
        content={"status": "frontend_not_built", "message": "frontend/dist/index.html does not exist"},
    )


@app.get("/favicon.ico", response_class=FileResponse)
async def favicon():
    return FileResponse(FAVICON)


@app.get("/import", response_class=FileResponse)
async def import_page():
    """参数导入页：独立于前端构建产物，前端升级不会覆盖。"""
    page = app_root() / "frontend" / "import.html"
    if not page.exists():
        return JSONResponse(status_code=404, content={"detail": "import.html not found"})
    return FileResponse(page)


@app.get(TOOLS_SCRIPT_URL)
async def workbench_tools_script():
    """工作台左下角的配置导入/保存脚本。"""
    if not TOOLS_SCRIPT.exists():
        return JSONResponse(status_code=404, content={"detail": "workbench_tools.js not found"})
    return FileResponse(TOOLS_SCRIPT, media_type="application/javascript", headers={"Cache-Control": "no-cache"})

if FRONTEND_DIST.exists():
    app.mount("/", SPAStaticFiles(directory=str(FRONTEND_DIST), html=True), name="static")
