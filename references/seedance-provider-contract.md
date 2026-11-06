# Seedance 2.5 接入约定

官方资料：

- [Doubao Seedance 2.5 教程](https://docs.volcengine.com/docs/82379/2607688?lang=zh)
- [创建视频生成任务](https://docs.volcengine.com/docs/82379/1520757?lang=zh)
- [查询视频生成任务](https://www.volcengine.com/docs/82379/1521309)

## 环境变量

- `ARK_API_KEY`：必需，只从环境变量读取。
- `ARK_BASE_URL`：可选，默认 `https://ark.cn-beijing.volces.com/api/v3`。
- `ARK_SEEDANCE_MODEL_ID`：可选，覆盖脚本默认模型 ID。
- `PORTAL_X_REFERENCE_VIDEO_URL`：可选，内置参考视频 `assets/reference-video-1.mp4` 的公网 URL；也可通过命令行参数传入。

不要把密钥写入 Skill 文件、提示词、日志或结果 JSON。

## 素材映射

Seedance API 通过 `content` 数组接收提示词和多模态素材：

- 用户图片：`image_url`，角色为 `first_frame`，提示词中引用 `@图1`。
- 用户视频：`video_url`，角色为 `reference_video`，提示词中引用 `@视频1`。
- 固定 PORTAL-X 参考视频：`video_url`，角色为 `reference_video`。用户输入图片时引用 `@视频1`，用户输入视频时引用 `@视频2`。

本玩法是“用户主体/画面 + 固定特效参考”的全模态参考生成，不把用户视频当作延长任务，因此不要设置 `inner_generation_options.pe_classification=extend`。

## 输入素材

- 用户图片可使用公网 HTTP(S) URL，也可由脚本把小于 30 MB 的本地图片编码为官方支持的 `data:image/...;base64,...` 格式。
- 用户视频与固定参考视频使用公网 HTTP(S) URL。若视频是本地文件，先使用当前环境可用的素材上传能力获得临时 URL，不把本地视频路径直接写入 `video_url.url`。

固定参考视频可在运行期通过 `--reference-video-url` 传入，或把稳定 URL 配置到 `PORTAL_X_REFERENCE_VIDEO_URL`。

## 时长映射

- 图片输入默认生成 5 秒，用户可用 `--duration` 覆盖。
- 视频输入默认读取上传视频的真实时长：本地文件使用 `--source-video-file` 交给 `ffprobe` 检测；只有远程 URL 时使用 `--source-duration` 传入已知秒数。
- Seedance 的 `duration` 为整数秒，因此将源视频时长四舍五入到最近整数秒。例如 15.047 秒映射为 15 秒。
- 当前模型接受 4–30 秒；源视频四舍五入后超出范围时停止并说明限制，不静默截断。
- 三段 PORTAL-X 特效时间码按最终总时长等比例分配，避免长视频只在前 5 秒出现特效。

## 异步状态

- `queued` / `running`：继续轮询。
- `succeeded`：提取并下载视频。
- `failed` / `expired` / `cancelled`：返回任务 ID 和脱敏错误。
- 超时：保留任务 ID，禁止无限轮询或伪称任务失败。

默认每 5 秒轮询，最多等待 15 分钟。结果 JSON 写入 `temp_data/result.json`，视频默认下载到 `temp_data/portal-x-video.mp4`。
