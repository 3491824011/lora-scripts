import asyncio
import csv
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

import toml
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from mikazuki.app.events import (
    SSE_HEADERS,
    format_sse as _format_sse,
    resolve_event_cursor as _resolve_metric_cursor,
)
from mikazuki.catalog import get_catalog_service
from mikazuki.compiler import ImportDraftRequest, TrainDraft, compile_draft, import_train_toml
from mikazuki.compiler.models import SimpleDatasetDraft
from mikazuki.frontend_release import release_version_payload
from mikazuki.jobs import get_job_runner, get_job_store
from mikazuki.jobs.artifacts import JobArtifactError, read_job_artifacts
from mikazuki.jobs.logs import read_log_from, tail_log
from mikazuki.jobs.metrics import get_job_metrics_service, parse_tag_filter
from mikazuki.jobs.models import TERMINAL_STATES
from mikazuki.storage.files import (
    IMAGE_EXTENSIONS,
    IMAGE_MEDIA_TYPES,
    BrowsePathError,
    FileManagerLaunchError,
    FileManagerUnavailableError,
    SafetensorsMetadataError,
    UnsupportedFileTypeError,
    file_manager_capability,
    list_files,
    read_safetensors_metadata,
    resolve_output_file,
    show_output_in_file_manager,
)

router = APIRouter()


@router.get("/health")
async def health():
    release = release_version_payload()
    return {
        "status": "ok",
        **release,
        "python": platform.python_version(),
        "devMode": os.environ.get("MIKAZUKI_DEV", "0") == "1",
    }


@router.get("/trainers")
async def list_trainers():
    catalog = get_catalog_service()
    return {
        "trainers": [item.model_dump() for item in catalog.list_trainers()],
        "manifestHash": catalog.manifest_hash,
    }


@router.get("/trainers/{trainer_id}")
async def get_trainer(trainer_id: str):
    trainer = get_catalog_service().get_trainer(trainer_id)
    if trainer is None:
        raise HTTPException(status_code=404, detail="trainer not found")
    return trainer.model_dump(exclude_none=True)


@router.get("/trainers/{trainer_id}/params")
async def get_trainer_params(
    trainer_id: str,
    view: str = Query(default="recommended", pattern="^(required|recommended|advanced|all)$"),
):
    catalog = get_catalog_service()
    trainer = catalog.get_trainer(trainer_id)
    if trainer is None:
        raise HTTPException(status_code=404, detail="trainer not found")
    return {
        "trainerId": trainer_id,
        "view": view,
        "groups": catalog.get_param_groups(trainer_id, view=view),
        "manifestHash": catalog.manifest_hash,
    }


@router.get("/training/schema")
async def get_training_schema():
    """Describe the supported structured draft without tightening its runtime model."""
    schema = TrainDraft.model_json_schema()
    dataset_schema = SimpleDatasetDraft.model_json_schema()
    dataset_schema["properties"]["mode"]["enum"] = ["simple"]
    dataset_schema["properties"]["root"]["description"] = (
        "Directory on the backend machine directly containing the training images and caption sidecars. "
        "Simple mode does not recursively train images in subdirectories."
    )
    definitions = schema.setdefault("$defs", {})
    definitions.update(dataset_schema.pop("$defs", {}))
    definitions["SimpleDatasetDraft"] = dataset_schema
    schema["properties"]["dataset"] = {
        "anyOf": [{"$ref": "#/$defs/SimpleDatasetDraft"}, {"type": "null"}],
        "default": None,
        "title": "Dataset",
    }
    return schema


@router.post("/drafts/import")
async def import_draft(payload: ImportDraftRequest):
    """把 sd-scripts 的 train.toml 转成工作台草稿。

    只按当前训练器参数目录逐键对应，不新增参数；返回每个键的去向供核对。
    """
    catalog = get_catalog_service()
    trainer = catalog.get_trainer(payload.trainerId)
    if trainer is None:
        raise HTTPException(status_code=404, detail="trainer not found")

    text = payload.toml
    source: Optional[Path] = None
    if not text and payload.path:
        source = Path(payload.path).expanduser()
        if source.suffix.lower() not in {".toml", ".txt"}:
            raise HTTPException(status_code=400, detail="only .toml/.txt is accepted")
        if not source.is_file():
            raise HTTPException(status_code=400, detail="file not found")
        if source.stat().st_size > 4 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="file is too large")
        text = await asyncio.to_thread(source.read_text, encoding="utf-8", errors="replace")

    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="toml is empty")

    dataset_text = payload.datasetToml
    if not dataset_text and source is not None:
        try:
            config = toml.loads(text)
            dataset_config = config.get("dataset", {}).get("dataset_config")
            if isinstance(dataset_config, str) and dataset_config.strip():
                reference = Path(dataset_config).expanduser()
                if not reference.is_absolute():
                    reference = source.parent / reference
                if reference.is_file() and reference.stat().st_size <= 4 * 1024 * 1024:
                    dataset_text = await asyncio.to_thread(
                        reference.read_text, encoding="utf-8", errors="replace"
                    )
        except Exception:
            # 数据集配置只是可选增强；主 train.toml 的解析结果仍然可用。
            dataset_text = payload.datasetToml

    result = import_train_toml(
        trainer,
        text,
        manifest_hash=catalog.manifest_hash,
        base_name=payload.name or "",
        dataset_text=dataset_text,
    )
    return result.model_dump(exclude_none=True)


@router.post("/compile")
async def compile_train_draft(
    draft: TrainDraft,
    persist: bool = Query(default=True),
    validate_paths: bool = Query(default=True),
):
    result = compile_draft(draft, persist=persist, validate_paths=validate_paths)
    if result.errors and any(item.code == "trainer.not_found" for item in result.errors):
        raise HTTPException(status_code=404, detail=result.errors[0].message)
    return result.model_dump(exclude_none=True)


@router.post("/jobs")
async def create_job(
    draft: TrainDraft,
    validate_paths: bool = Query(default=True),
):
    result = await get_job_runner().start_job(draft, validate_paths=validate_paths)
    payload = result.model_dump(exclude_none=True)
    if result.compile.errors:
        return JSONResponse(status_code=400, content=payload)
    return payload


@router.get("/jobs")
async def list_jobs(limit: int = Query(default=50, ge=1, le=200)):
    jobs = get_job_store().list_jobs(limit=limit)
    return {"jobs": [job.model_dump(exclude_none=True) for job in jobs]}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = get_job_store().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job.model_dump(exclude_none=True)


@router.get("/jobs/{job_id}/artifacts")
async def get_job_artifacts(job_id: str):
    job = get_job_store().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    try:
        return await asyncio.to_thread(read_job_artifacts, job)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except JobArtifactError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=503, detail="job artifacts could not be read") from error


@router.get("/jobs/{job_id}/logs")
async def get_job_logs(job_id: str, tail: int = Query(default=500, ge=0, le=5000)):
    job = get_job_store().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    cursor, lines = await asyncio.to_thread(tail_log, job.logPath or "", tail=tail)
    return {"jobId": job_id, "cursor": cursor, "lines": lines}


@router.get("/jobs/{job_id}/metrics")
async def get_job_metrics(
    job_id: str,
    cursor: int = Query(default=0, ge=0),
    max_points: int = Query(default=2000, ge=2, le=20000),
    tags: Optional[str] = Query(default=None),
):
    job = get_job_store().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return await asyncio.to_thread(
        get_job_metrics_service().snapshot,
        job,
        cursor=cursor,
        max_points=max_points,
        tags=parse_tag_filter(tags),
    )


@router.get("/jobs/{job_id}/metric-events")
async def get_job_metric_events(
    job_id: str,
    cursor: Optional[int] = Query(default=None, ge=0),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
):
    if get_job_store().get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")

    initial_cursor = _resolve_metric_cursor(cursor, last_event_id)

    async def metric_event_stream():
        current_cursor = initial_cursor
        last_state = None
        first_snapshot = True
        last_heartbeat = time.monotonic()

        while True:
            job = get_job_store().get_job(job_id)
            if job is None:
                yield _format_sse("state", {"jobId": job_id, "state": "missing"})
                break

            snapshot = await asyncio.to_thread(
                get_job_metrics_service().snapshot,
                job,
                cursor=current_cursor,
                max_points=2000,
            )
            if first_snapshot or snapshot.get("pointCount", 0) > 0:
                current_cursor = int(snapshot.get("cursor", current_cursor))
                yield _format_sse("metric", snapshot, event_id=current_cursor)
                first_snapshot = False

            if job.state != last_state:
                yield _format_sse(
                    "state",
                    {
                        "jobId": job.id,
                        "state": job.state,
                        "cursor": current_cursor,
                        "endedAt": job.endedAt,
                        "exitCode": job.exitCode,
                        "errorMessage": job.errorMessage,
                    },
                )
                last_state = job.state

            if job.state in TERMINAL_STATES:
                break

            now = time.monotonic()
            if now - last_heartbeat >= 15:
                yield _format_sse(
                    "heartbeat",
                    {"jobId": job.id, "cursor": current_cursor, "timestamp": time.time()},
                )
                last_heartbeat = now
            await asyncio.sleep(1)

    return StreamingResponse(
        metric_event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/jobs/{job_id}/events")
async def get_job_events(job_id: str):
    if get_job_store().get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")

    async def event_stream():
        cursor = 0
        last_state = None
        while True:
            job = get_job_store().get_job(job_id)
            if job is None:
                yield _format_sse("state", {"state": "missing"})
                break

            if job.state != last_state:
                yield _format_sse("state", job.model_dump(exclude_none=True))
                last_state = job.state

            cursor, lines = await asyncio.to_thread(read_log_from, job.logPath or "", cursor=cursor)
            for line in lines:
                yield _format_sse("log", {"line": line, "cursor": cursor})

            if job.state in TERMINAL_STATES:
                break
            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/jobs/{job_id}/terminate")
async def terminate_job(job_id: str):
    job = get_job_runner().terminate_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job.model_dump(exclude_none=True)


@router.get("/files")
async def browse_files(
    kind: str = Query(default="file"),
    root: str = Query(default="workspace"),
    path: str = Query(default=""),
):
    try:
        items = list_files(kind=kind, root=root, path=path or None)
    except BrowsePathError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"items": [item.model_dump() for item in items]}


@router.get("/files/file-manager-capability")
async def get_file_manager_capability():
    return file_manager_capability()


@router.post("/files/reveal")
async def reveal_output_path(path: str = Query(min_length=1)):
    try:
        resolved = show_output_in_file_manager(path)
    except BrowsePathError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FileManagerUnavailableError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except FileManagerLaunchError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"status": "opened", "path": str(resolved).replace("\\", "/")}


@router.get("/files/content")
async def read_output_file(path: str = Query(min_length=1)):
    try:
        resolved = resolve_output_file(path, extensions=IMAGE_EXTENSIONS)
    except BrowsePathError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except UnsupportedFileTypeError as error:
        raise HTTPException(status_code=415, detail=str(error)) from error

    media_type = IMAGE_MEDIA_TYPES[resolved.suffix.lower()]
    return FileResponse(resolved, media_type=media_type)


@router.get("/files/safetensors-metadata")
async def get_safetensors_metadata(path: str = Query(min_length=1)):
    try:
        return read_safetensors_metadata(path)
    except BrowsePathError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except UnsupportedFileTypeError as error:
        raise HTTPException(status_code=415, detail=str(error)) from error
    except SafetensorsMetadataError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _nvidia_smi_gpus() -> list[dict]:
    """Read GPU names and memory from nvidia-smi.

    This keeps the settings page useful when the Python environment has no
    CUDA-enabled PyTorch. Training still needs a CUDA build; the caller adds
    that explanation to the response.
    """
    executable = shutil.which("nvidia-smi")
    if not executable:
        return []
    try:
        output = subprocess.check_output(
            [
                executable,
                "--query-gpu=index,name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    gpus = []
    for row in csv.reader(output.splitlines()):
        if len(row) < 4:
            continue
        try:
            index = row[0].strip()
            name = ", ".join(part.strip() for part in row[1:-2]).strip()
            total_mb = float(row[-2].strip())
            free_mb = float(row[-1].strip())
        except ValueError:
            continue
        if not name:
            continue
        gpus.append(
            {
                "id": index,
                "name": name,
                "vramTotal": int(total_mb * 1024 * 1024),
                "vramFree": int(free_mb * 1024 * 1024),
            }
        )
    return gpus


def _cuda_unavailable_message() -> str:
    return (
        "检测到 NVIDIA 显卡，但当前 Python 没有可用的 CUDA 版 PyTorch。"
        "请运行 scripts\\install-cn.ps1 或 scripts\\install.ps1 安装 CUDA 版依赖后再启动。"
    )


@router.get("/devices/gpus")
async def list_gpus():
    try:
        import torch

        cuda_available = torch.cuda.is_available()
    except Exception:
        torch = None
        cuda_available = False

    if not cuda_available:
        fallback = _nvidia_smi_gpus()
        if fallback:
            return {"gpus": fallback, "error": _cuda_unavailable_message()}
        return {"gpus": [], "error": "torch cuda is not available"}

    gpus = []
    for index in range(torch.cuda.device_count()):
        try:
            props = torch.cuda.get_device_properties(index)
            name = torch.cuda.get_device_name(index)
        except Exception:
            continue
        try:
            free, total = torch.cuda.mem_get_info(index)
        except Exception:
            free, total = 0, getattr(props, "total_memory", 0)
        gpus.append(
            {
                "id": str(index),
                "name": name,
                "vramTotal": int(total or getattr(props, "total_memory", 0)),
                "vramFree": int(free),
            }
        )

    if not gpus:
        fallback = _nvidia_smi_gpus()
        if fallback:
            return {"gpus": fallback, "error": _cuda_unavailable_message()}
    return {"gpus": gpus}
