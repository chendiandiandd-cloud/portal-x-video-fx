---
name: portal-x-video-fx-prompt
description: 使用固定 PORTAL-X 机器视觉参考视频和用户上传的图片或视频，自动编排特效提示词、调用 Seedance 2.5、轮询异步任务并交付可观看成片。适用于「参考这个特效直接生成视频」「PORTAL-X 特效」「像素马赛克消散 + 拓扑点线网络 + 瞄准框 HUD」「用我这张图/这条视频套这个特效」等请求；默认直接出片，而不是只返回提示词。
author: chenyanqi.1008
---

# PORTAL-X Seedance 视频生成

目标是交付一条可观看的 PORTAL-X 风格视频，而不是只给提示词。固定参考视频为 `assets/reference-video-1.mp4`，不替换成其他参考视频。

## 默认规格

- 模型：Seedance 2.5
- 时长：图片默认 5 秒；视频默认读取上传视频时长并四舍五入到最近整数秒（Seedance 支持范围内）
- 分辨率：720p
- 画幅：`adaptive`，优先继承用户素材
- 音频：默认生成
- 水印：默认关闭
- 输出：最佳成片 + 简短生成说明；提示词仅在用户要求或生成降级时展示

用户明确指定时长、分辨率、画幅、声音、seed 或水印时，覆盖对应默认值。

## 工作流

### 1. 确认输入

至少需要一张图片或一条视频作为用户主体素材。素材类型不明确时，使用 `read` 或 `analyze_media` skill 确认，不凭文件名猜测。

当前脚本一次处理一个主体素材：

- 图片作为首帧，固定参考视频提供特效、运镜与视觉风格。
- 视频作为第一条参考视频，固定参考视频作为第二条参考视频；生成时长必须继承用户视频时长，不默认生成 5 秒。先用本地上传文件读取时长，四舍五入到 Seedance 接受的整数秒，并按总时长等比例重排三段特效时间码。

若用户上传多个主体素材，默认选择最符合用户指令的一项；无法判断时再询问。

### 2. 准备可访问 URL

Seedance 的图片输入支持公网 URL 或本地文件转 Base64；视频输入和固定参考视频需要模型可访问的 HTTP(S) URL。

- 用户上传图片：可直接通过 `--input-file` 传本地路径，脚本自动编码，不需要先上传。
- 用户上传视频：先使用当前环境可用的素材上传能力生成临时公网 URL，再通过 `--input-url` 传入。
- 固定参考视频：同样需要公网 URL，不要把 `assets/reference-video-1.mp4` 的本地路径直接传给模型。

固定参考视频 URL 的优先级：

1. 命令行 `--reference-video-url`
2. 环境变量 `PORTAL_X_REFERENCE_VIDEO_URL`

接口与素材编号规则见 [Seedance 2.5 接入约定](references/seedance-provider-contract.md)。

### 3. 调用 Seedance 2.5

运行 [`generate_portal_x_video.py`](scripts/generate_portal_x_video.py)。必须通过 `bash` 工具直接执行并设置 `include_secrets=true`，以便读取 `ARK_API_KEY`；模型 ID 优先读取 `ARK_SEEDANCE_MODEL_ID`。若环境缺少 SDK，先执行 `pip install "volcengine-python-sdk[ark]"`，再重试脚本。

图片输入：

```bash
python3 scripts/generate_portal_x_video.py \
  --input-type image \
  --input-file "<用户图片本地路径>" \
  --reference-video-url "<固定参考视频公网 URL>" \
  --duration 5
```

视频输入：

```bash
python3 scripts/generate_portal_x_video.py \
  --input-type video \
  --input-url "<用户视频公网 URL>" \
  --source-video-file "<用户上传视频本地路径>" \
  --reference-video-url "<固定参考视频公网 URL>"
```

脚本会自动：

1. 按输入类型生成固定 PORTAL-X 提示词，并使用 Seedance API 的 `@图1` / `@视频1` / `@视频2` 素材引用。
2. 创建异步视频任务并轮询状态。
3. 成功后提取视频 URL，并下载到 `temp_data/portal-x-video.mp4`。
4. 把任务 ID、状态、成片 URL、本地视频路径、尾帧 URL和警告写入 `temp_data/result.json`。

首次接入或排查参数时可添加 `--dry-run`，只验证并打印请求体，不调用模型、不需要 API Key。

### 4. 处理失败

最多重试 2 次，每次只调整一个主要问题：

- 主体漂移：强化主体与构图保持，减少额外元素。
- 特效不明显：提高白色马赛克、拓扑网络和 HUD 的描述优先级。
- 画面崩坏：缩短动作链，减少镜头切换和主体接触。
- 任务超时：保留 `task_id`，不要无限轮询；超时不等于模型任务失败。
- URL 不可访问：重新上传素材并换用模型可读取的公网 URL。

不要把失败样片当作最终成片。

### 5. 成片质检

交付前检查：

- 主体身份、数量、外观和场景布局是否稳定。
- 白色半透明像素马赛克、三维点线拓扑网络、垂直贯穿线和 PORTAL-X HUD 是否可辨认。
- 参考视频的人物或物体是否被错误复制。
- 是否出现异常肢体、身份漂移、背景融化、乱码、水印或无动机跳切。
- 成片文件能否打开，或视频 URL 是否可访问。

关键项未通过时先重试。

## 最终交付

按顺序交付：

1. Seedance 2.5 返回并下载的成片文件；本地文件存在时优先交付文件，否则交付可访问链接。
2. 一句生成说明：时长、分辨率、画幅和音频状态。

任务 ID、请求体、轮询日志和重试过程默认不展示。

## 降级输出

若缺少 `ARK_API_KEY`、模型权限或公网素材 URL，不伪称已生成视频。明确说明缺失项，并提供脚本已生成的完整 PORTAL-X 提示词与建议参数，便于补齐条件后直接重跑。
