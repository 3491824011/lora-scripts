"""把 sd-scripts 的 train.toml 导入成工作台草稿。

设计约束：
- 只认当前训练器参数目录（``trainer.params``）里真实存在的参数名，绝不新增参数。
- 类型转换、枚举匹配、数值范围全部复用 ``compiler._normalize_param_value``，
  与前端表单走同一条校验路径。
- 数据集字段落到 ``SimpleDatasetDraft`` 的同名字段上，与前端 ``Te()`` 的默认结构一致。
- 每个 toml 键都产出一条 mapping 记录，便于「每个参数对应每个」地核对。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import toml

from mikazuki.catalog.models import ParamDefinition, TrainerDefinition

from .compiler import (
    MANAGED_PARAMS,
    _is_path_param,
    _normalize_param_value,
    _should_omit_value,
)
from .models import (
    ImportMappingEntry,
    ImportResult,
    SimpleDatasetDraft,
    ValidationMessage,
)


# 顶层 toml 键 → 草稿字段。这些键在训练器目录里也存在，但工作台把它们交给
# 数据集/输出名结构管理，所以必须转到结构字段上，而不是当普通参数写进 params。
DATASET_KEY_MAP: Dict[str, str] = {
    "train_batch_size": "batchSize",
    "batch_size": "batchSize",  # dataset.toml 里的写法
    "resolution": "resolution",
    "caption_extension": "captionExtension",
    "caption_extention": "captionExtension",
    "keep_tokens": "keepTokens",
    "enable_bucket": "enableBucket",
    "min_bucket_reso": "minBucketReso",
    "max_bucket_reso": "maxBucketReso",
    "bucket_reso_steps": "bucketResoSteps",
    "bucket_no_upscale": "bucketNoUpscale",
    "shuffle_caption": "shuffleCaption",
}

SAMPLE_KEY_MAP: Dict[str, str] = {
    "sample_every_n_epochs": "everyNEpochs",
    "sample_every_n_steps": "everyNSteps",
    "sample_sampler": "sampler",
}

# 工作台完全自行生成、导入时必须忽略且要告知用户的键。
DERIVED_KEYS = {
    "dataset_config": "数据集配置由工作台按上方字段生成，导入时忽略该路径。",
    "sample_prompts": "采样提示词文件由工作台生成，导入时忽略该路径。",
    "config_file": "训练配置由工作台生成，导入时忽略。",
    "output_config": "训练配置由工作台生成，导入时忽略。",
    "reg_data_dir": "工作台当前不支持正则化数据集，导入时忽略。",
    "in_json": "工作台当前不支持 json 数据集清单，导入时忽略。",
    "dataset_repeats": "重复次数请写在子集 num_repeats 里，导入时忽略该键。",
}


def parse_train_toml(text: str) -> Dict[str, Any]:
    return toml.loads(text)


def _flatten_sections(payload: Dict[str, Any]) -> List[Tuple[str, str, Any, bool]]:
    """把一级 section 摊平，与 sd-scripts 读取配置的方式保持一致。

    返回 (展示用键, 参数名, 值, 是否嵌套过深) 四元组。
    形如 ``[save] output_name = "x"`` 会变成 ``("save.output_name", "output_name", "x", False)``。
    """
    items: List[Tuple[str, str, Any, bool]] = []
    for key, value in payload.items():
        if key in {"general", "datasets"}:
            continue
        if not isinstance(value, dict):
            items.append((key, key, value, False))
            continue
        for sub_key, sub_value in value.items():
            items.append((f"{key}.{sub_key}", sub_key, sub_value, isinstance(sub_value, dict)))
    return items


def _default_sample_prompt(trainer_id: str, resolution: List[int]) -> Dict[str, Any]:
    """与前端草稿默认值保持一致的空白采样提示词。"""
    if trainer_id == "moss_image.lora":
        steps, cfg_scale = 50, 3
    else:
        steps, cfg_scale = 20, 1
    width, height = (resolution + [1024, 1024])[:2]
    return {
        "prompt": "",
        "width": int(width),
        "height": int(height),
        "seed": 1337,
        "steps": steps,
        "cfgScale": cfg_scale,
    }


def import_train_toml(
    trainer: TrainerDefinition,
    text: str,
    *,
    manifest_hash: str = "",
    base_name: str = "",
) -> ImportResult:
    try:
        payload = parse_train_toml(text)
    except Exception as exc:  # toml 语法错误
        return ImportResult(
            trainerId=trainer.id,
            manifestHash=manifest_hash,
            errors=[
                ValidationMessage(
                    severity="error",
                    code="import.toml.invalid",
                    field="toml",
                    message=f"TOML 解析失败：{exc}",
                )
            ],
        )

    if not isinstance(payload, dict):
        return ImportResult(
            trainerId=trainer.id,
            manifestHash=manifest_hash,
            errors=[
                ValidationMessage(
                    severity="error",
                    code="import.toml.invalid",
                    field="toml",
                    message="TOML 根节点必须是表。",
                )
            ],
        )

    mappings: List[ImportMappingEntry] = []
    warnings: List[ValidationMessage] = []
    errors: List[ValidationMessage] = []
    params: Dict[str, Any] = {}
    model_assets: Dict[str, Any] = {}
    sample: Dict[str, Any] = {}
    dataset: Dict[str, Any] = {}
    name = ""

    # ---- 数据集表：[[datasets]] / [datasets] 两种写法都认 ----
    dataset_table, subset_table, dataset_notes = _extract_dataset_tables(payload, mappings)
    for note in dataset_notes:
        warnings.append(note)

    general_table = payload.get("general")
    if isinstance(general_table, dict):
        for key, value in general_table.items():
            target = DATASET_KEY_MAP.get(key)
            if target is None:
                mappings.append(
                    ImportMappingEntry(
                        key=f"general.{key}",
                        target="skipped",
                        field="",
                        value=_plain(value),
                        status="skipped",
                        message="[general] 中该键工作台不消费。",
                    )
                )
                continue
            dataset[target] = _coerce_dataset_value(target, value)
            mappings.append(
                ImportMappingEntry(
                    key=f"general.{key}",
                    target="dataset",
                    field=target,
                    value=_plain(dataset[target]),
                    status="mapped",
                )
            )

    if dataset_table is not None:
        for key, value in dataset_table.items():
            target = DATASET_KEY_MAP.get(key)
            if target is None:
                mappings.append(
                    ImportMappingEntry(
                        key=f"datasets.{key}",
                        target="skipped",
                        field="",
                        value=_plain(value),
                        status="skipped",
                        message="[[datasets]] 中该键工作台不消费。",
                    )
                )
                continue
            dataset[target] = _coerce_dataset_value(target, value)
            mappings.append(
                ImportMappingEntry(
                    key=f"datasets.{key}",
                    target="dataset",
                    field=target,
                    value=_plain(dataset[target]),
                    status="mapped",
                )
            )

    if subset_table is not None:
        for key, value in subset_table.items():
            if key == "image_dir":
                dataset["root"] = _as_text(value)
                mappings.append(
                    ImportMappingEntry(
                        key="datasets.subsets.image_dir",
                        target="dataset",
                        field="root",
                        value=_plain(dataset["root"]),
                        status="mapped",
                    )
                )
            elif key == "num_repeats":
                try:
                    dataset["numRepeats"] = int(value)
                except (TypeError, ValueError):
                    errors.append(
                        ValidationMessage(
                            severity="error",
                            code="import.num_repeats.invalid",
                            field="datasets.subsets.num_repeats",
                            message="num_repeats 必须是整数。",
                        )
                    )
                    continue
                mappings.append(
                    ImportMappingEntry(
                        key="datasets.subsets.num_repeats",
                        target="dataset",
                        field="numRepeats",
                        value=dataset["numRepeats"],
                        status="mapped",
                    )
                )
            else:
                mappings.append(
                    ImportMappingEntry(
                        key=f"datasets.subsets.{key}",
                        target="skipped",
                        field="",
                        value=_plain(value),
                        status="skipped",
                        message="子集里该键工作台不消费（多子集/正则化暂不支持）。",
                    )
                )

    # ---- 顶层标量键 ----
    # sd-scripts 的 read_config_from_file 会把一级 section 摊平成一个命名空间
    # （library/args.py:1244「combine all sections into one」），工作台编译出的
    # train.toml 正是按 [memory]/[save]/[training] 分组写的。这里做同样的摊平，
    # 保存出来的文件才能原样导入回去。
    for display_key, key, value, nested in _flatten_sections(payload):
        if nested:
            mappings.append(
                ImportMappingEntry(
                    key=display_key,
                    target="skipped",
                    field="",
                    value=_plain(value),
                    status="skipped",
                    message="嵌套超过一层的表不是训练参数，已跳过。",
                )
            )
            continue

        if key in DERIVED_KEYS:
            mappings.append(
                ImportMappingEntry(
                    key=display_key,
                    target="skipped",
                    field="",
                    value=_plain(value),
                    status="skipped",
                    message=DERIVED_KEYS[key],
                )
            )
            continue

        if key == "output_name":
            name = _as_text(value) or ""
            mappings.append(
                ImportMappingEntry(
                    key=display_key,
                    target="name",
                    field="name",
                    value=name,
                    status="mapped",
                )
            )
            continue

        if key == "train_data_dir":
            dataset["root"] = _as_text(value)
            mappings.append(
                ImportMappingEntry(
                    key=display_key,
                    target="dataset",
                    field="root",
                    value=_plain(dataset["root"]),
                    status="mapped",
                    message="没有 [[datasets]] 时，用该目录作为数据集根目录。",
                )
            )
            continue

        if key in DATASET_KEY_MAP:
            target = DATASET_KEY_MAP[key]
            dataset[target] = _coerce_dataset_value(target, value)
            mappings.append(
                ImportMappingEntry(
                    key=display_key,
                    target="dataset",
                    field=target,
                    value=_plain(dataset[target]),
                    status="mapped",
                )
            )
            continue

        if key in SAMPLE_KEY_MAP:
            target = SAMPLE_KEY_MAP[key]
            sample[target] = _plain(value)
            mappings.append(
                ImportMappingEntry(
                    key=display_key,
                    target="sample",
                    field=target,
                    value=_plain(sample[target]),
                    status="mapped",
                )
            )
            continue

        param = trainer.params.get(key)
        if param is None:
            mappings.append(
                ImportMappingEntry(
                    key=display_key,
                    target="unknown",
                    field="",
                    value=_plain(value),
                    status="unknown",
                    message="当前训练器参数目录里没有这个参数，未导入。",
                )
            )
            warnings.append(
                ValidationMessage(
                    severity="warning",
                    code="import.param.unknown",
                    field=key,
                    message=f"参数不在当前训练器的 argparse 定义中，已跳过：{key}",
                )
            )
            continue

        if key in MANAGED_PARAMS:
            mappings.append(
                ImportMappingEntry(
                    key=display_key,
                    target="skipped",
                    field="",
                    value=_plain(value),
                    status="skipped",
                    message="由编译器管理的参数，导入时忽略。",
                )
            )
            continue

        normalized, issue = _normalize_param_value(param, value, key)
        if issue is not None:
            errors.append(issue)
            mappings.append(
                ImportMappingEntry(
                    key=display_key,
                    target="params",
                    field=key,
                    value=_plain(value),
                    status="invalid",
                    message=issue.message,
                )
            )
            continue
        if _should_omit_value(param, normalized):
            mappings.append(
                ImportMappingEntry(
                    key=display_key,
                    target="params",
                    field=key,
                    value=_plain(normalized),
                    status="skipped",
                    message="空值，等同未设置。",
                )
            )
            continue

        bucket = model_assets if param.group == "model" else params
        bucket[key] = normalized
        mappings.append(
            ImportMappingEntry(
                key=display_key,
                target="modelAssets" if param.group == "model" else "params",
                field=key,
                value=_plain(normalized),
                status="mapped",
            )
        )

    # ---- 拼草稿 ----
    dataset_values = SimpleDatasetDraft().model_dump()
    dataset_values.update({k: v for k, v in dataset.items() if v is not None})
    if not dataset_values.get("root"):
        dataset_values["root"] = ""

    sample_values: Dict[str, Any] = {
        "enabled": sample.get("everyNEpochs") is not None or sample.get("everyNSteps") is not None,
        "everyNEpochs": sample.get("everyNEpochs"),
        "everyNSteps": sample.get("everyNSteps"),
        "sampler": sample.get("sampler"),
        "prompts": [_default_sample_prompt(trainer.id, dataset_values["resolution"])],
    }

    if not name:
        name = base_name or ""

    draft: Dict[str, Any] = {
        "version": 3,
        "name": name,
        "modelAssets": model_assets,
        "params": params,
        "dataset": dataset_values,
        "runtime": {"gpuIds": [], "numCpuThreadsPerProcess": 8},
        "sample": sample_values,
        "manifestHash": manifest_hash,
        "savedAt": "",
    }

    mapped_count = sum(1 for item in mappings if item.status == "mapped")
    skipped_count = sum(1 for item in mappings if item.status == "skipped")
    unknown_count = sum(1 for item in mappings if item.status == "unknown")

    return ImportResult(
        trainerId=trainer.id,
        manifestHash=manifest_hash,
        draft=draft,
        mappings=mappings,
        warnings=warnings,
        errors=errors,
        mappedCount=mapped_count,
        skippedCount=skipped_count,
        unknownCount=unknown_count,
    )


def _extract_dataset_tables(
    payload: Dict[str, Any],
    mappings: List[ImportMappingEntry],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], List[ValidationMessage]]:
    """取出第一个数据集表与第一个子集表；多数据集/多子集只取第一个并提醒。"""
    notes: List[ValidationMessage] = []
    raw = payload.get("datasets")
    if raw is None:
        return None, None, notes

    tables: List[Dict[str, Any]] = []
    if isinstance(raw, list):
        tables = [item for item in raw if isinstance(item, dict)]
    elif isinstance(raw, dict):
        tables = [raw]

    if not tables:
        return None, None, notes

    if len(tables) > 1:
        notes.append(
            ValidationMessage(
                severity="warning",
                code="import.datasets.multiple",
                field="datasets",
                message=f"train.toml 里有 {len(tables)} 个数据集表，工作台只支持一个，已取第一个。",
            )
        )

    table = dict(tables[0])
    subsets = table.pop("subsets", None)

    subset: Optional[Dict[str, Any]] = None
    subset_tables: List[Dict[str, Any]] = []
    if isinstance(subsets, list):
        subset_tables = [item for item in subsets if isinstance(item, dict)]
    elif isinstance(subsets, dict):
        subset_tables = [subsets]

    if len(subset_tables) > 1:
        notes.append(
            ValidationMessage(
                severity="warning",
                code="import.subsets.multiple",
                field="datasets.subsets",
                message=f"该数据集有 {len(subset_tables)} 个子集，工作台只支持一个目录，已取第一个。",
            )
        )
    if subset_tables:
        subset = dict(subset_tables[0])

    return table, subset, notes


def _coerce_dataset_value(field: str, value: Any) -> Any:
    if field == "resolution":
        return _parse_resolution(value)
    if field == "captionExtension":
        text = _as_text(value) or ".txt"
        return text if text.startswith(".") else f".{text}"
    if field in {"batchSize", "numRepeats", "minBucketReso", "maxBucketReso", "bucketResoSteps", "keepTokens"}:
        try:
            return int(value)
        except (TypeError, ValueError):
            return SimpleDatasetDraft().model_dump()[field]
    if field in {"enableBucket", "bucketNoUpscale", "shuffleCaption"}:
        return _as_bool(value)
    return value


def _parse_resolution(value: Any) -> List[int]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return [int(value[0]), int(value[1])]
    if isinstance(value, (int, float)):
        return [int(value), int(value)]
    if isinstance(value, str):
        parts = [item.strip() for item in value.replace("x", ",").split(",") if item.strip()]
        if len(parts) == 1 and parts[0].isdigit():
            return [int(parts[0]), int(parts[0])]
        if len(parts) == 2:
            return [int(parts[0]), int(parts[1])]
    return SimpleDatasetDraft().model_dump()["resolution"]


def _as_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _plain(value: Any) -> Any:
    """把 toml 值收敛成可 JSON 序列化的形态。"""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return str(value)


__all__ = ["import_train_toml", "parse_train_toml"]
