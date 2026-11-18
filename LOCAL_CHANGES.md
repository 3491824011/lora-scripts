# 本地修改说明

本仓库基于 [Akegarasu/lora-scripts](https://github.com/Akegarasu/lora-scripts) 的 main 分支提交 `b3a66c640533702bcd5bc5cc592fc03101fa42e0`（2026-11-03，提交信息：`Add comprehensive tests for MCP functionality and backend integration`）。本地改动最初在 `234fb6fd8fb765b648740961a367f788f4674aef` 上开发，已 rebase 到当前 main。

## 相对上游的改动

1. `scripts/dev/moss_image_train_network.py`
   - 缓存文本编码器输出前检测显存总量。
   - 显存小于 20 GiB 时，Qwen3.5-9B 文本编码器保留在 CPU，避免小显存显卡 OOM；结果一致，只是速度更慢。

2. 训练配置导入 / 保存
   - 新增 `mikazuki/compiler/importer.py`：解析 sd-scripts 的 `train.toml`，映射到工作台草稿参数并返回逐键状态。
   - 新增 `mikazuki/compiler/models.py` 中的 `ImportMappingEntry`、`ImportResult`、`ImportDraftRequest`。
   - 新增 `POST /api/v2/drafts/import` 接口（`mikazuki/app/api_v2.py`）。
   - 新增 `frontend/import.html` 独立导入页面；若 `train.toml` 通过 `[dataset] dataset_config` 引用独立数据集 TOML，可在该页补选数据集文件。
   - 新增 `frontend/workbench_tools.js`，由 `mikazuki/app/application.py` 在 `/train` 页面运行时注入「导入配置」「保存配置」按钮。

## 使用提示

- 模型文件放在仓库根目录的 `models/` 下即可在模型选择框中浏览；也可以在路径输入框中直接填写本机任意绝对路径。`models/` 中的占位文件用于保证目录存在，不包含模型权重。
- 数据集图片放在 `train/` 下即可在数据集选择框中浏览；导入只支持单个数据集目录，多子集配置会提示只取第一个。

## 未纳入仓库的内容

以下内容属于本地运行数据或个人训练资料，已在 `.gitignore` 中排除：

- `models/`、`train/`、`output/`、`logs/`
- `python/`、`tokenizer/`
- `config/runs/`、`config/caption-jobs.db`
- `参数/`（个人训练配置，包含本机路径、数据集说明和训练参数）
- `scripts/dev/moss_image_train_network.py.bak`

仓库中不包含任何模型权重、训练素材图片、数据集或训练产物。
