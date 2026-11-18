# SD-Trainer

LoRA-scripts（SD-Trainer）是基于 [kohya-ss/sd-scripts](https://github.com/kohya-ss/sd-scripts) 的本地训练与数据集工作台。v2 界面集成训练配置、Caption 生成、人工标签编辑、任务日志和训练指标。

> **下载注意**
>
> 这里提供的是源码，不是免安装便携包。Windows 上第一次运行前，请先执行 `scripts\install-cn.ps1`（或 `scripts\install.ps1`）安装依赖，装好后再双击根目录的 `run_gui.bat`。如果希望下载后无需安装即可使用，请用 `.github/scripts/build-windows-portable.ps1` 打便携包。

[English](README.md) · [人类操作指南](docs/human/README.md) · [MCP 接入](docs/human/mcp.md) · [Agent 使用文档](docs/agent/usage/README.md) · [Agent 开发文档](docs/agent/dev/README.md)


## 这个版本多了什么

跟上游原版相比，当前仓库主要加了两个日常训练会用到的功能。

### 导入已有的训练配置

如果你之前用 sd-scripts 训练过，手里已经有 `train.toml`，不用再对着工作台从头填一遍。训练页左下角有「导入配置」，选 `.toml` 或 `.txt` 就可以。能对上号的参数会填进当前草稿，认不出来的会单独列出来，不会悄悄丢掉。导入只是读取文件，不会改动原来的配置，确认没问题再保存。

如果 `train.toml` 里的 `[dataset] dataset_config` 指向另一个数据集配置文件，可以打开 `/import` 页面（例如 `http://127.0.0.1:28000/import`，端口按实际设置）把两份文件一起选上；按文件路径导入时，程序也会自动读取相对路径指向的数据集文件。

### 小显存跑 MOSS-Image

MOSS-Image 的 Qwen3.5-9B 文本编码器比较占显存。现在程序会先看一下显卡的总显存，小于 20 GiB 时把文本编码器留在 CPU 上缓存，显存够才搬到 GPU。速度会慢一点，结果是一样的，显存不到 20 GiB 的卡也能先跑起来。

如果设置页提示没有检测到显卡，或者提示当前 Python 没有 CUDA 版 PyTorch，先看启动窗口的提示。常见情况是当前 Python 装的是 CPU 版 PyTorch，重新运行 `scripts\install-cn.ps1`（或 `scripts\install.ps1`）安装 CUDA 版依赖即可。16 GB 显卡只要 PyTorch 能正常识别到 CUDA，就会按上面的低显存方式工作。

模型文件不用复制进仓库：模型选择框可以直接浏览本机任意文件夹，也可以在路径输入框里填绝对路径。数据集默认放在 `train/`；这两个目录里的占位文件只是为了让空目录能保留在仓库里，里面没有模型或图片。


## 训练工作台

选择训练器，配置模型资产和数据集，在启动任务前查看参数帮助与配置检查结果。表单随训练器展示对应参数，支持常用/全部参数切换、搜索和配置完成度检查。

当前目录提供 SD、SDXL、SD3、FLUX.1、Chroma、Lumina、HunyuanImage 2.1、Anima 和 MOSS-Image Base / SFT LoRA；实验性训练器会在界面中标注。训练代码直接收录于 `scripts/dev`，已同步 sd-scripts v0.12.3。MOSS-Image 的模型与依赖要求见[安装配置指南](docs/human/moss-image.md)。

![v2 训练工作台](assets/screenshots/training-workspace.jpg)

任务保留配置、状态和日志，详情页直接展示损失与学习率曲线。指标读取兼容 TensorBoard 的事件文件，无需另外启动 TensorBoard 服务。

## Caption 与人工编辑

Caption 工作台可扫描数据集，使用 WD/CL 标签器、BLIP/GIT 系列模型及支持的 chat VLM 批量生成标签或自然语言描述。默认跳过已有 Caption，可选手动选图及写入前复核，并与训练任务共享 GPU 队列。界面会在执行前显示模型可用性与依赖要求。

![v2 Caption 工作台](assets/screenshots/caption-workspace.jpg)

独立的 Tag 编辑器支持逐图编辑、筛选、标签建议、批量增删、文本或正则替换以及格式整理。批量修改先预览再应用；备份与冲突检测支持在文件未被外部修改时安全回滚。

## 通过 MCP 让 agent 操作

GUI 启动时默认同时开启内置 MCP。在本机 MCP 客户端选择 Streamable HTTP，连接 `http://127.0.0.1:28000/mcp/`；端口不同时，从 GUI 设置复制实际地址。设置中的开关即时生效，并在下次启动时保留。Agent 可以查看数据、提交实验、监控日志与指标、读取输出样图，使用与网页相同的训练队列。连接详情与可选的独立 stdio 入口见 [MCP 接入说明](docs/human/mcp.md)。

## Windows NVIDIA 便携版

如果你下载的是这个仓库的源码，它不包含 Python 运行时。先按下面「从源码安装」安装依赖，再双击根目录的 `run_gui.bat` 启动；仓库里已经带了构建好的前端，不需要另外安装 Node.js。

官方上游的 [Releases](https://github.com/Akegarasu/lora-scripts/releases) 提供 `lora-scripts_windows_portable_nvidia.7z` 免安装便携包，但那是上游原版，不包含本仓库新增的功能。需要给本仓库打便携包时，可以运行 `.github/scripts/build-windows-portable.ps1`。

## 从源码安装

默认 CUDA 13.0 安装推荐使用已验证的 Python 3.11 x64；Python 3.10 源码安装须选择 cu128。获取源码需要 Git。构建前端还需要带 Corepack 的 Node.js 22 LTS（至少 22.12）或 24+，运行已构建的前端不需要 Node.js。

安装器默认提供 PyTorch 2.14.1、torchvision 0.29.1、xFormers 0.0.35 与 CUDA 13.0。Windows 传入 `-Cuda cu128`、Linux 传入 `--cuda cu128`，可选择 PyTorch 2.11.0 / torchvision 0.26.0。如需保留其他兼容组合，先在项目环境中安装对应的 PyTorch，再传入 `-SkipTorch` 或 `--skip-torch`；PyTorch 至少需要 2.6。启动时会按已安装 PyTorch 的 CUDA 版本选择 ONNX Runtime。

```sh
git clone https://github.com/3491824011/lora-scripts
cd lora-scripts
```

### 构建前端

当前开发版本在 `version.json` 中关闭了 `frontend.autoDownload`。仓库里已经带了一份构建好的 `frontend/dist`，普通下载可以直接启动；修改前端代码后，按下面的步骤重新构建：

```sh
cd frontend
corepack pnpm install --frozen-lockfile
corepack pnpm run build
cd ..
```

Corepack 使用 `frontend/package.json` 中固定的 pnpm 版本。构建结果与版本信息会写入 `frontend/dist`。

### Windows

在仓库根目录打开 PowerShell，执行：

```powershell
.\scripts\install-cn.ps1
.\scripts\run_gui.ps1
```

使用官方安装源时，将安装命令换成 `.\scripts\install.ps1`。
安装 CUDA 12.8 版本时使用 `.\scripts\install-cn.ps1 -Cuda cu128` 或 `.\scripts\install.ps1 -Cuda cu128`。

装完依赖后，也可以直接双击仓库根目录的 `run_gui.bat`。它会优先使用 `venv` 或便携版 `python` 目录里的解释器；如果还没安装过依赖，会提示先运行安装脚本。

### Linux

在仓库根目录执行：

```sh
bash scripts/install.bash
source venv/bin/activate
bash scripts/run_gui.sh
```

GUI 启动脚本使用当前激活的 Python，因此每次新开终端都需要先激活 `venv`。启动后打开 [http://127.0.0.1:28000](http://127.0.0.1:28000)。
安装 CUDA 12.8 版本时使用 `bash scripts/install.bash --cuda cu128`。

更新 Python 依赖后，应重新运行安装器并重启 GUI。已启用前端自动下载的发布版本可以从 GitHub Release、Jihulab 或静态镜像获取匹配前端；开发版本仍需按上面的步骤构建。详见[前端版本与分发说明](docs/agent/dev/releases.md)。

### Docker

Dockerfile 会构建前端，并将当前源码与 PyTorch 2.14.1 / CUDA 13.0 一起打包：

```sh
docker build -t lora-scripts:local .
docker run --gpus all -p 28000:28000 lora-scripts:local
```

构建 CUDA 12.8 版本时需同时设置两个参数：

```sh
docker build --build-arg PYTORCH_IMAGE=pytorch/pytorch:2.11.0-cuda12.8-cudnn9-runtime --build-arg CUDA_FLAVOR=cu128 -t lora-scripts:cu128 .
```

宿主机需要兼容的 NVIDIA 驱动与 NVIDIA Container Toolkit。请把数据集、模型和输出目录挂载到容器内 `/app/lora-scripts` 下的对应位置，以便在容器外保留文件。

### 通过脚本训练

安装依赖后，也可在仓库根目录编辑并运行 Windows 的 `scripts/train.ps1` 或 Linux 的 `scripts/train.sh`。Linux 需要先激活 `venv`。这些入口与 GUI 使用同一份随仓库分发的训练代码。

## GUI 参数

在已激活的环境中传给 `python gui.py`，或传给便携版的 `run_gui.bat`。

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--host` | `127.0.0.1` | 服务器绑定地址 |
| `--port` | `28000` | 服务器端口 |
| `--listen` | 关闭 | 监听所有网络接口 |
| `--skip-prepare-environment` | 关闭 | 跳过依赖检查与准备 |
| `--skip-prepare-onnxruntime` | 关闭 | 跳过 ONNX Runtime 准备 |
| `--disable-auto-mirror` | 关闭 | 禁用自动软件源镜像选择 |
| `--dev` | 关闭 | 启用后端自动重载，跳过前端自动下载 |
| `--frontend-source` | 读取配置，默认 `github` | `github`、`jihulab`/`cn`、`static`、`auto` 或 `off` |
| `--frontend-static-base-url` | 未设置 | 静态前端镜像根地址 |
| `--skip-frontend-download` | 关闭 | 跳过前端自动下载 |
| `--force-frontend-download` | 关闭 | 重新安装匹配版本的前端制品 |

## 许可

[GNU AGPL v3](LICENSE)。随仓库收录的组件与下载的模型分别遵循各自许可。
