# 弈台 · 中国象棋与五子棋

在自己电脑上打开浏览器，就能下中国象棋或五子棋。两种棋都支持三种方式：你和 AI 下、两个 AI 对下、两个人在同一台电脑上轮流下。

本程序默认只在本机运行（`http://localhost:5003`），适合主要用远程模型 API 的朋友。2016 款 Intel MacBook Air、系统为 macOS Monterey，也可以按下面的步骤安装。

本项目是对 [zstar1003/AiChineseChess](https://github.com/zstar1003/AiChineseChess) 的二次改进版，并保留原作者与原仓库出处。**原仓库目前没有 LICENSE 文件**，版权仍归原作者所有。把仓库 Fork 过来并注明来源，并不等于取得完整的开源许可或再许可授权，也不能据此声称“只靠 Fork 就已经合规开源”。本仓库不添加 MIT 或其他许可证。若希望另行增加开源协议，需要先取得原作者授权。

<div align="center">
  <h4>
    <a href="README.md">🇨🇳 中文</a>
    <span> | </span>
    <a href="README_EN.md">🇬🇧 English</a>
  </h4>
</div>

## 这一版能做什么

- **两种游戏**：保留原来的中国象棋，并新增五子棋。
- **三种对局**：人机、AI 对 AI、同机双人。游戏和方式可以改，但只对「下一局」生效。正在下的那一盘不会偷偷换规则；要点「开始新局」并确认，才会停掉当前棋盘并清空，两边的棋子不会串到新局。
- **先后手**：人机时可选「我先手」或「我后手」。象棋先手是红方、后手是黑方；五子棋先手是黑棋、后手是白棋。
- **点棋盘下棋**：人机和同机双人都是点棋盘。象棋先点自己的棋子，再点能走到的位置；五子棋点空的交叉点。合不合法、轮到谁、谁赢了，都由本机程序判断，不靠网页自己说了算。AI 思考时点棋盘不会替它落子。停止或重置之后，迟到的模型回复不会写进新的一局。
- **人机时思考默认折叠**：AI 正在想的时候，页面上看不到它的分析，网络推送也不会提前把思考过程发给你。它落下这一步之后，可以点开「查看这一步的思考」。
- **密钥**：同机双人不用 API key，也不会去访问模型。人机只填 AI 那一方。AI 对 AI 两边分开填。Key 仍然只放在当前页面内存里，不写入磁盘、不写进棋谱。本机地址（localhost / 127.0.0.1）可以不填 key。
- **原来的接口能力还在**：DeepSeek、Kimi、Gemini 的 OpenAI 兼容入口、Claude 官方接口、各类兼容中转，以及 Ollama / LM Studio；断网会自动重试，也可以点「立即重试 / 继续对战」。旧的中国象棋 AI 对 AI 开局方式仍然可用。

## 规则说明（请按这里理解，不要当成完整比赛规则）

**中国象棋**：已实现将军、应将、将死、困毙，以及默认双方合计 300 步仍未分胜负则和棋。模型只能从当前合法棋步里选。长将、长捉等重复局面还没做，不是完整竞赛规则。

**五子棋**：15×15，**自由规则，无禁手**。横、竖、两条斜线，连成五子或更多同色棋子就获胜（六子及以上也算赢）。棋盘下满仍然没有五连，就是和棋。这不是职业连珠，没有三三、四四、长连禁手。请不要把它当成职业比赛规则。

五子棋坐标是列 A–O（从左到右）、行 1–15（从上到下），例如 H8。它和象棋的 `a0a1` 这种四字坐标不是同一套，程序也不会把象棋走法套到五子棋上。

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

- Python 3.8 或更新（推荐 3.12。2016 款 Intel Mac 的 macOS Monterey 可以安装 Python 官网的 3.12）
- 一台能打开浏览器的电脑。程序只给本机用，地址是 http://localhost:5003

## 安装和启动

先获取代码。Fork 只用于保留上游提交历史，不能代替许可证：

```bash
git clone <你的仓库地址> AiChineseChess
cd AiChineseChess
```

### macOS（含 Intel MacBook Air / Monterey）

如果这台 Mac 比较旧，请用 Python 官网的安装包，不必先装 Homebrew。

1. 打开 https://www.python.org/downloads/macos/ ，下载 **Python 3.12** 的 macOS 安装包（页面上的 64-bit universal2 installer 可以在 Intel Mac 上用）。
2. 双击安装。安装时如果看到 “Install certificates” 或 “Update Shell Profile”，建议也运行一下。
3. 打开「终端」（应用程序 → 实用工具 → 终端）。
4. 进入解压好的项目文件夹。例如文件夹在「文稿」里，就输入（中间有一个空格）：

```bash
cd ~/Documents/AiChineseChess
```

5. 安装并启动（每一行输完按回车，等它跑完再输下一行）：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

如果提示找不到 `python3`，改用安装包提供的命令，一般是 `python3.12`，四行都把 `python3` 换成 `python3.12`。

终端出现 `访问地址: http://localhost:5003` 后，用 Safari 或 Chrome 打开这个地址。如果页面还是旧的，按 Command + Shift + R 强制刷新。

已经装过 `uv` 的人也可以用 `uv sync` 然后 `uv run python app.py`。上面的 venv 方式对 Monterey 更直接。

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

## 这次修复怎么覆盖更新

如果项目已经在 `/Users/nan/Downloads/AiChineseChess-multi-game-src`，并且里面有可用的 `.venv`，按 `覆盖升级说明.txt` 把新文件盖上去即可。保留 `.venv` 和 `games`，不要再执行 `python3 -m venv`，也不必重新 `pip install`。

## 三种下法

先在左侧选游戏（中国象棋或五子棋），再选对局方式。

1. **人机对战**：选「我先手」或「我后手」。页面上只保留 AI 那一边的模型配置。云端模型要填 API key；本机 Ollama 可以空着。轮到你时点棋盘。AI 思考时不要点，点了也不会落子。它下完以后，右侧可以展开看它这一步的想法。
2. **AI 对 AI**：两边各自选模型和 key，互不影响。开始后不用点棋盘，看它们下即可。思考过程会直接出现在右侧。
3. **同机双人**：两个人坐在一起轮流点同一块棋盘。不需要 API key，程序也不会去调用模型。

正在下的时候，改左侧的游戏或方式不会改当前棋盘。要换，点「开始新局」，确认后才会停掉这一盘并清空。点「停止」会停掉模型请求；点「重置」会清掉页面上的这一盘（已经写到 `games/` 里的棋谱文件还在）。

网络断了会自动重试，也可以点「立即重试」或暂停后的「继续对战」。这只影响正在请求模型的那一方。

每步棋谱会写入项目下的 `games/` 目录，里面会写明是象棋还是五子棋、是人机还是双人、双方是谁。这个目录里的对局文件不会被提交到 Git。以前保存的象棋棋谱没有「游戏种类」这几项，那就是旧版的中国象棋 AI 对局，可以继续留着，不必删。

### 从旧版本升级

1. 先在旧程序的终端里按 `Ctrl + C`，确认它已经停掉。
2. 把新代码放到一个**新文件夹**，不要直接盖住正在运行的旧目录。
3. 如果想留下以前的棋谱，把旧文件夹里的 `games` 复制到新文件夹。不要复制旧的 `.venv`，新文件夹需要重新执行上面的安装命令。
4. API key 本来就不会被保存。升级后打开页面，云端模型要重新输入 key。
5. 浏览器打开 http://localhost:5003 ，并强制刷新一次。

更短的步骤也写在项目里的 `本地升级与启动.txt`。

### 密钥与安全提示

- 不要把 key 发到聊天、截图或公开仓库。
- 请优先使用 HTTPS。HTTP 会明文传输 key，只建议可信的本机服务（如 Ollama）使用。
- 本程序不会关闭 TLS 证书校验，也不会自动跟随重定向把 key 发到新地址。
- 「测试连接」和实际对局都可能计费，请自行留意余额。

## 效果演示

[![DeepSeek vs Gemini](assets/image.jpg)](https://www.bilibili.com/video/BV1M9thzRE56)

## 项目结构（简要）

- `app.py`：Web 服务、对战循环、人机落子与连接测试
- `models/chess_game.py`：中国象棋规则
- `models/gomoku_game.py`：五子棋 15×15 自由规则
- `models/llm_player.py`：调用模型，并按当前游戏解析棋步或落点
- `models/api_config.py`：各家 API 的校验、请求头与兼容逻辑
- `templates/`、`static/`：页面与前端逻辑
- `games/`：自动保存的对局记录（已从版本库忽略）
- `static/js/socket.io.min.js`：第三方 Socket.IO 客户端 4.0.1。该文件按其文件头以 MIT 许可证分发，版权归其作者。这份许可证只覆盖该第三方文件，不使本仓库整体变为 MIT，也不改变上游未附 LICENSE 的事实。

## 开发与自检

修改代码后，可用下面的命令做本地检查（全部走模拟服务，**不会调用真实付费 API**）：

```bash
python -m unittest tests.test_rules tests.test_gomoku_rules tests.test_custom_api tests.test_platform_modes -v
python tests/test_e2e_battle.py
python test_network_resume.py
```

若已安装 Node.js，还可以跑前端逻辑测试（非运行应用所必需）：

```bash
npm install --prefix /tmp/aichess-dom-tests jsdom@26
python -c "from app import app; print(app.test_client().get('/').data.decode())" > /tmp/aichess-page.html
NODE_PATH=/tmp/aichess-dom-tests/node_modules node tests/test_profiles_dom.cjs /tmp/aichess-page.html
```
