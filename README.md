# 弈台 · AI 中国象棋

基于大语言模型的中国象棋对战平台：在浏览器里配置模型，让它们在棋盘上实时对弈，并展示思考过程。

本项目是对 [zstar1003/AiChineseChess](https://github.com/zstar1003/AiChineseChess) 的二次改进版，并保留原作者与原仓库出处。**原仓库目前没有 LICENSE 文件**，版权仍归原作者所有。把仓库 Fork 过来并注明来源，并不等于取得完整的开源许可或再许可授权，也不能据此声称“只靠 Fork 就已经合规开源”。本仓库不添加 MIT 或其他许可证。若希望另行增加开源协议，需要先取得原作者授权。

<div align="center">
  <h4>
    <a href="README.md">🇨🇳 中文</a>
    <span> | </span>
    <a href="README_EN.md">🇬🇧 English</a>
  </h4>
</div>

## 本改进版做了什么

- **多种 API**：DeepSeek、Kimi / Moonshot、Gemini 的 OpenAI 兼容入口、**Anthropic Claude 官方 Messages API**、OpenAI 及各类兼容中转站（OpenRouter、硅基流动、火山方舟、阿里百炼等），以及 **Ollama / LM Studio 等本机模型**。
- **自动兼容**：若服务只接受 `max_completion_tokens`（常见于部分 OpenAI 推理模型），或返回普通 JSON / 不支持 `stream`，程序会自动切换并重试一次。
- **规则范围（不是完整竞赛规则）**：目前实现将军、应将、将死、困毙，以及默认 300 步上限判和；模型只从当前合法棋步中选择。长将、长捉等重复局面规则尚未验证。
- **断网重试与继续**：请求失败可自动重连，也可手动「立即重试 / 继续对战」。
- **对局记录**：每步自动保存到 `games/` 目录。
- **小屏适配**：页面可滚动，棋盘等比缩放，顶部控制条保持可见。
- **密钥安全**：API Key **只放在当前页面内存**，不会写入 localStorage、磁盘、棋谱或配置文件。刷新页面后，云端 API 需重新输入 key；本机地址可留空。

## 支持与暂不支持的接口

下列接口只是按公开请求格式在代码里做了适配。自动化测试使用本机模拟服务，**没有对列出的每一家兼容 API 做真实付费接口实测**。服务商接口可能变化，能否连通以对方当前文档为准。

**代码已适配（未经逐家真实接口实测）**

| 类型 | 怎么填 |
| --- | --- |
| DeepSeek / Kimi / Gemini（OpenAI 兼容入口） | 直接选对应预设，或按服务商提供的根地址和模型 ID 填写 |
| OpenAI 及兼容中转站 | Provider 选「OpenAI 兼容 · 自定义」，`base_url` 填如 `https://你的服务/v1` |
| Anthropic Claude 官方接口 | Provider 选「Claude · Anthropic 原生」，默认 `https://api.anthropic.com/v1`（程序自动请求 `/messages`） |
| Ollama / LM Studio 等本机模型 | `base_url` 例如 `http://127.0.0.1:11434/v1`，**API key 可留空** |

填写根地址即可；若多写了 `/chat/completions` 或 `/messages`，程序会自动去掉。本机地址（`localhost`、`127.0.0.1`、`::1`）不会发送 `Authorization` / `x-api-key`。

**暂不支持**

- Azure OpenAI 原生接口（需要 `api-version` 等查询参数）
- AWS Bedrock / Google Vertex AI 等需要云厂商签名的接口
- 仅提供 Responses API（`/responses`）、没有 Chat Completions 或 Messages 兼容层的模型

Claude 官方原生接口已在代码中适配（同样只做过模拟测试）；若只有 OpenRouter 等中转站，也可以把 Claude 当作 OpenAI 兼容模型来用。

## 环境要求

- Python 3.8+（推荐 3.12；若用 `uv sync`，需要 3.12+）
- 一台能打开浏览器的电脑；程序默认只在本机 `http://localhost:5003` 提供服务

## 安装和启动

先获取代码。Fork 只用于保留上游提交历史，不能代替许可证：

```bash
git clone <你的仓库地址> AiChineseChess
cd AiChineseChess
```

### macOS

**方式一：用 uv（更快，可选）**

```bash
# 如未安装 uv，见 https://docs.astral.sh/uv/
uv sync
uv run python app.py
```

**方式二：用系统 Python**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

终端出现 `访问地址: http://localhost:5003` 后，用浏览器打开该地址。若页面是旧的，按 Command + Shift + R 强制刷新。

### Windows

1. 安装 [Python 3](https://www.python.org/downloads/)，安装时勾选 **Add python.exe to PATH**。
2. 打开「命令提示符」或 PowerShell，进入项目目录后运行：

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

3. 用浏览器打开 http://localhost:5003

结束程序：在运行它的终端里按 `Ctrl + C`。

## 使用说明

1. 在左侧为红方、黑方各选一个 API / 模型配置。页面下方「API 配置管理」可新增或修改配置（显示名称、服务商、根地址、模型 ID、输出上限、超时等）。
2. 云端模型请在对局配置里输入 API key。**保存配置不会保存 key**；刷新页面后需重新输入。本机 Ollama / LM Studio 可留空。
3. 可选：点「测试连接」（会先确认）。只会发送 **1 次小请求**，可能产生费用，不显示 key 或原始返回。
4. 点「开始对战」，观看双方思考和下棋。对局进行或暂停时配置会锁定；要换模型或 key，请先停止再开新局。
5. 每步棋谱会写入项目下的 `games/` 目录。这个目录里的对局文件不会被提交到 Git。

### 密钥与安全提示

- 不要把 key 发到聊天、截图或公开仓库。
- 请优先使用 HTTPS。HTTP 会明文传输 key，只建议可信的本机服务（如 Ollama）使用。
- 本程序不会关闭 TLS 证书校验，也不会自动跟随重定向把 key 发到新地址。
- 「测试连接」和实际对局都可能计费，请自行留意余额。

## 效果演示

[![DeepSeek vs Gemini](assets/image.jpg)](https://www.bilibili.com/video/BV1M9thzRE56)

## 项目结构（简要）

- `app.py`：Web 服务、对战循环与连接测试
- `models/chess_game.py`：中国象棋规则
- `models/llm_player.py`：调用模型并解析棋步
- `models/api_config.py`：各家 API 的校验、请求头与兼容逻辑
- `templates/`、`static/`：页面与前端逻辑
- `games/`：自动保存的对局记录（已从版本库忽略）
- `static/js/socket.io.min.js`：第三方 Socket.IO 客户端 4.0.1。该文件按其文件头以 MIT 许可证分发，版权归其作者。这份许可证只覆盖该第三方文件，不使本仓库整体变为 MIT，也不改变上游未附 LICENSE 的事实。

## 开发与自检

修改代码后，可用下面的命令做本地检查（全部走模拟服务，**不会调用真实付费 API**）：

```bash
python -m unittest tests.test_rules tests.test_custom_api -v
python tests/test_e2e_battle.py
python test_network_resume.py
```

若已安装 Node.js，还可以跑前端逻辑测试（非运行应用所必需）：

```bash
npm install --prefix /tmp/aichess-dom-tests jsdom@26
python -c "from app import app; print(app.test_client().get('/').data.decode())" > /tmp/aichess-page.html
NODE_PATH=/tmp/aichess-dom-tests/node_modules node tests/test_profiles_dom.cjs /tmp/aichess-page.html
```
