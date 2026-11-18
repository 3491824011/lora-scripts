# 本地修改说明

本仓库基于 [Akegarasu/lora-scripts](https://github.com/Akegarasu/lora-scripts) 的 main 分支提交 `b3a66c640533702bcd5bc5cc592fc03101fa42e0`（2026-11-03，提交信息：`Add comprehensive tests for MCP functionality and backend integration`）。本地改动最初在 `234fb6fd8fb765b648740961a367f788f4674aef` 上开发，已 rebase 到当前 main。

## 相对上游的改动

1. `scripts/dev/moss_image_train_network.py`
   - 保持上游行为：缓存文本编码器输出时优先把 Qwen3.5-9B 文本编码器放到 GPU。
   - GPU 放不下（`torch.cuda.OutOfMemoryError`）时不再静默改用 CPU，而是抛出明确错误，提示开启「低显存保护」或改用 ConvRot INT8 文本编码器。
   - 新增 `--vram_guard` / `--vram_guard_threshold_gb`：默认关闭，行为与上游一致；开启后仅在显卡总显存低于阈值时把文本编码器留在 CPU 缓存输出，结果一致，只是速度更慢。

2. 训练配置导入 / 保存
   - 新增 `mikazuki/compiler/importer.py`：解析 sd-scripts 的 `train.toml`，映射到工作台草稿参数并返回逐键状态。
   - 新增 `mikazuki/compiler/models.py` 中的 `ImportMappingEntry`、`ImportResult`、`ImportDraftRequest`。
   - 新增 `POST /api/v2/drafts/import` 接口（`mikazuki/app/api_v2.py`）。
   - 新增 `frontend/import.html` 独立导入页面；若 `train.toml` 通过 `[dataset] dataset_config` 引用独立数据集 TOML，可在该页补选数据集文件。
   - 新增 `frontend/workbench_tools.js`，由 `mikazuki/app/application.py` 在 `/train` 页面运行时注入「导入配置」「保存配置」按钮。

3. 下载后可直接启动
   - 根目录新增 `run_gui.bat`：优先使用 `venv` 或项目内 `python`，都找不到时提示先运行 `scripts\setup-windows.bat`。
   - 新增 `scripts/setup-windows.ps1` 与 `scripts/setup-windows.bat`：首次运行时按需下载 Python 3.11 到项目的 `python/` 目录，再调用安装脚本安装 CUDA 版 PyTorch 和其余依赖。
   - 提交构建好的 `frontend/dist`；从 GitHub 下载源码后不需要再装 Node.js 构建前端。

4. 模型选择器支持本机任意目录
   - `mikazuki/storage/files.py` 新增 `local` 浏览根，允许文件选择器读取仓库目录之外的本地模型文件夹。
   - `frontend/src/components/ParamControl.vue` 与 `FilePicker.vue` 的模型路径改用本地根，并允许从当前目录一直向上浏览到盘符根。

5. 显卡检测。
   - `GET /api/v2/devices/gpus` 在 PyTorch 没有 CUDA 时尝试读取 `nvidia-smi`，设置页仍能显示显卡型号和显存，并提示当前 Python 没有安装 CUDA 版 PyTorch。
   - `run_gui.bat` 启动前检查当前 Python 的 PyTorch 和 CUDA 状态；没有 PyTorch 时提示运行 `scripts\setup-windows.bat` 并退出，没有 CUDA 时打印明确提示。

6. 多子目录数据集。
   - 选择没有直接图片、但包含 `10_角色`、`6_身体` 这类子目录的父目录时，编译器会按目录名前缀生成多个 `[[datasets.subsets]]`，每个子目录使用自己的重复次数。

## 使用提示

- 模型文件不需要复制到仓库里：模型选择框可以浏览本机任意文件夹，也可以直接在路径输入框中填写绝对路径。`models/` 只是默认占位目录，不包含模型权重。
- 数据集图片放在 `train/` 下即可在数据集选择框中浏览；训练数据目录支持上面说的 `N_名称` 子目录自动展开。导入 `train.toml` 时仍只取第一个数据集，多子集配置会提示只取第一个。

## 未纳入仓库的内容

以下内容属于本地运行数据或个人训练资料，已在 `.gitignore` 中排除：

- `models/`、`train/`、`output/`、`logs/` 下的实际模型、数据集和训练产物（仅保留 `models/put stable diffusion model here.txt` 与 `train/.keep` 两个目录占位文件）
- `python/`、`tokenizer/`
- `config/runs/`、`config/caption-jobs.db`
- `参数/`（个人训练配置，包含本机路径、数据集说明和训练参数）
- `scripts/dev/moss_image_train_network.py.bak`

仓库中不包含任何模型权重、训练素材图片、数据集或训练产物。
