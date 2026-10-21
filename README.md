# B站弹幕同传助手（BiliDanmakuBridge）

把 **LiveTranslate** 翻译出来的字幕，自动填进 B 站直播间的弹幕框并发出去。

> 本项目**不负责翻译**，也不调用 B 站 API、不保存账号密码或 Cookie。
> 它只做两件事：读取 LiveTranslate 写在硬盘上的译文文件；在浏览器页面里模拟人工发弹幕。

---

## 一、它是怎么工作的

```
LiveTranslate（装在哪个目录都可以）
  └─ <LiveTranslate目录>\transcripts\livetrans_日期_时间_translation.txt
        │  只读“服务启动之后新写入”的行
        ▼
sender_server.py（本机小服务，127.0.0.1:8770）
        │  浏览器脚本每 0.8 秒来取一次
        ▼
bilidanmaku.user.js（Tampermonkey 油猴脚本）
        │  把译文填进直播间弹幕框，点发送
        ▼
B站直播间
```

### 译文从哪里来？

译文**全部来自 LiveTranslate**：

1. LiveTranslate 用 ASR 识别直播声音（例如 SenseVoice / Whisper）；
2. 再用翻译模型（例如 DeepSeek）翻译成中文；
3. 把每一句译文写进安装目录下的 `transcripts` 文件夹，文件名类似：

   ```text
   livetrans_20261021_003749_translation.txt
   ```

4. 文件里的每一行长这样：

   ```text
   [00:38:02] 没事，要转生成大妈技能吗？
   ```

本项目只读取这种“带时间戳的译文行”，自己不做识别、不做翻译。

### 为什么不用 B 站 API？

发送动作发生在**你已登录的浏览器页面**里：脚本把文字填进弹幕输入框，再点发送。
所以不需要 Cookie、不需要账号密码，也不需要申请开发者权限。
代价是 B 站页面改版时，输入框定位可能失效，需要更新脚本（见排错）。

---

## 二、准备东西

| 需要 | 说明 |
|---|---|
| Windows 10/11 | 本项目在 Windows 上测试 |
| LiveTranslate | 已经能正常翻译，装在哪个目录都行 |
| Python 3.10+ | **只依赖标准库**，不需要 pip 安装任何包 |
| 浏览器 + Tampermonkey | Chrome / Edge / Firefox 都可以，装“篡改猴”扩展 |
| B站小号 | 强烈建议用小号，不要用大号 |

> 没有 Python 也可以先用 LiveTranslate 自带的 `.venv` 里的 Python，但最省事的办法是单独装一个 Python。

---

## 三、安装步骤（小白版）

### 1. 下载本项目

在 GitHub 仓库页面点 **Code → Download ZIP**，解压到任意目录，例如：

```text
D:\Tools\BiliDanmakuBridge
```

路径尽量用英文、不要有空格；有中文也能用，只是排错时麻烦一点。

### 2. 安装 Python

1. 打开 <https://www.python.org/downloads/>；
2. 下载 Python 3.10 或更高版本（3.12 也可以）；
3. 安装第一页一定要勾选 **Add python.exe to PATH**；
4. 验证：按 `Win + R`，输入 `cmd` 回车，然后输入：

   ```bat
   python --version
   ```

   能看到 `Python 3.10.x` 或更高版本就说明装好了。

> `run.bat` 也会自动尝试 `py -3`、`python`、`python3` 和常见安装目录，找不到才会提示你安装。

### 3. 安装油猴（Tampermonkey）

在浏览器的扩展商店搜索 **Tampermonkey**（中文叫“篡改猴”），安装并启用。

### 4. 先让 LiveTranslate 跑起来

1. 启动 LiveTranslate，开始翻译一场直播；
2. 找到 LiveTranslate 的安装目录；
3. 打开里面的 `transcripts` 文件夹；
4. 确认里面有 `livetrans_*_translation.txt`，并且文件里能看到 `[时间] 译文`。

> 找不到安装目录？右键 LiveTranslate 的快捷方式 → **打开文件所在位置**，然后在旁边找 `transcripts`。
> 记不住也没关系，下一步的 `run.bat` 会自动搜索。

### 5. 启动本地服务

双击 **`run.bat`**。

正常会看到类似这样的窗口：

```text
[detect] 使用译文目录: D:\Apps\LiveTranslate\transcripts
========================================================
  B站弹幕同传助手 · 本地服务已启动
  监听:   http://127.0.0.1:8770
  转录:   D:\Apps\LiveTranslate\transcripts
  格式:   【译文】  上限 40 字  末尾句号删除
  超长:   超过 40 字自动在标点处断句，分段发送，间隔 2 秒
...
[watcher] 开始监听: livetrans_20261021_003749_translation.txt（从末尾开始，不补发历史）
```

**这个黑色窗口不要关。** 关了浏览器脚本就会显示“未连接”。

### 6. 安装油猴脚本

任选一种：

**方法 A（推荐）**

浏览器打开：

```text
http://127.0.0.1:8770/bilidanmaku.user.js
```

Tampermonkey 会自动弹出安装页，点“安装”。

**方法 B**

1. 点 Tampermonkey 图标 → **添加新脚本**；
2. 把 `bilidanmaku.user.js` 的全部内容粘进去；
3. 按 `Ctrl + S` 保存。

### 7. 打开直播间

打开 `https://live.bilibili.com/你的直播间号`，刷新页面。
右上角会出现一个黑色小面板：

```text
● 弹幕同传 运行中
待发 0 ｜ 已发 12 ｜ 失败 0
最近：【车坏了，糟透了。】
[暂停] [试发：关] [收起]
```

**第一次务必先点“试发：开”**：
它只会把文字填进弹幕框，不会发送。确认填的位置正确、内容正常后，再点回“试发：关”开始真实发送。

快捷键：**F9 = 暂停 / 继续**。面板可以拖动、收起。

---

## 四、LiveTranslate 装在别处怎么办

这是本版本最重要的改动：**不再写死 `E:\LiveTranslate`**。

### 默认：自动搜索

`config.json` 里的 `transcript_dir` 留空即可：

```json
{
  "transcript_dir": ""
}
```

`run.bat` 启动时会自动搜索：

- 桌面、文档、下载、OneDrive；
- 各个盘符的根目录（C:、D:、E:……）；
- `Program Files`、`Program Files (x86)`、`%LOCALAPPDATA%`、`%APPDATA%`；
- 常见的 `LiveTranslate` / `livetranslate` / `live_translate` 文件夹名。

找到后会打印：

```text
[detect] 使用译文目录: D:\Apps\LiveTranslate\transcripts
```

如果同时装了两个 LiveTranslate，会选**最新写过译文**的那个。
如果启动时没找到，程序会继续运行，并**每 15 秒再自动找一次**；你先启动 LiveTranslate 也可以。

### 手动指定（最稳）

如果自动找错，或者你想固定用某一个目录，把 `config.json` 改成：

```json
{
  "transcript_dir": "D:\\Apps\\LiveTranslate\\transcripts"
}
```

注意 Windows 路径里的反斜杠要写成两个 `\\`。

也可以启动时临时指定，不改配置文件：

```bat
run.bat --transcript-dir "D:\Apps\LiveTranslate\transcripts"
```

### 怎么找到这个目录

1. 右键 LiveTranslate 的快捷方式 → **打开文件所在位置**；
2. 在同一个文件夹里找 `transcripts`；
3. 里面最新的 `livetrans_*_translation.txt` 就是译文来源。

目录里光有 `transcripts` 还不够，必须已经有 `*_translation.txt` 文件（说明 LiveTranslate 至少翻译过一句）。

---

## 五、怎么确认译文在流动

按顺序检查：

1. `run.bat` 窗口里出现：

   ```text
   [watcher] 开始监听: livetrans_..._translation.txt
   ```

2. 浏览器面板的 **待发 / 已发** 数字有变化；
3. 浏览器打开 <http://127.0.0.1:8770/status>，能看到：

   ```json
   {
     "ok": true,
     "transcript_dir": "D:\\Apps\\LiveTranslate\\transcripts",
     "waiting": 0,
     "stats": { ... }
   }
   ```

如果 `transcript_dir` 是空的，说明还没找到目录；按上一节手动填。
如果 `transcript_dir` 正确但 `waiting` 一直是 0，通常是 LiveTranslate 没有在翻译，或者还没写出新译文。

---

## 六、配置 `config.json`

```json
{
  "port": 8770,
  "transcript_dir": "",
  "prefix": "【",
  "suffix": "】",
  "max_length": 40,
  "min_length": 2,
  "strip_period": true,
  "split_interval": 2.0,
  "stale_seconds": 60,
  "dedupe_seconds": 15,
  "poll_interval": 0.5
}
```

| 项 | 说明 |
|---|---|
| `transcript_dir` | 空 = 自动搜索；也可以填 LiveTranslate 的 `transcripts` 绝对路径 |
| `port` | 本地服务端口，默认 `8770`。油猴脚本里也写死 8770，改端口要同时改脚本 |
| `prefix` / `suffix` | 弹幕前后加的字，默认 `【译文】`；都不想要就都留空 |
| `max_length` | **每条弹幕的总长上限（含前后缀）**，默认 40。B站上限是 80 个“字符”，一个汉字/全角标点占 2 字符，所以实际只有 40 字。超过时不会截断丢内容，而是自动在标点处断句、分成多条发出。设为 `0` = 不限长（会被 B站截断） |
| `min_length` | 短于这个字数的译文不发（挡掉“嗯”“啊”这类） |
| `strip_period` | 删掉译文末尾的句号；句中的句号、问号、感叹号、逗号都保留 |
| `split_interval` | 超长译文分段后，每段之间隔几秒，默认 2 秒 |
| `stale_seconds` | 超过这么久还没发出去的译文自动丢弃（防止一开机补发一堆旧的） |
| `dedupe_seconds` | 这么短时间内重复的同一句只发一次 |
| `poll_interval` | 读取译文文件的间隔，默认 0.5 秒 |

改完配置要**重启 `run.bat`**。

### 断句规则

优先在句末标点（`。！？；…`）处断开；没有就用逗号（`，、`）；再没有就在上限处硬切。
每一段都会各自带上 `【】`，内容不会丢。

---

## 七、安全设计（这几条是刻意的）

- **不补发历史**：服务启动时从当前最新译文文件的末尾开始，只发之后新写入的行。否则一启动就会把整场几十条瞬间轰出去。
- **失败即停**：发送失败或弹幕框没清空时自动暂停，不盲目重试。
- **F9 急停**：任何时候都能停。暂停期间新译文只保留最新一条，继续后只发这一条，不会把攒下的内容一次性刷出去。
- **不碰账号凭据**：不读取、不保存 B 站密码或 Cookie；发送由浏览器当前登录状态完成。

---

## 八、常见问题（排错）

| 现象 | 处理 |
|---|---|
| `run.bat` 一闪而过 / 提示 `Python 3.10+ was not found` | 安装 Python，安装时勾选 **Add python.exe to PATH**；或者重启一次命令窗口 |
| 黑窗口显示“没有找到 LiveTranslate 的译文目录” | 先启动 LiveTranslate 并翻译出一句；或在 `config.json` 的 `transcript_dir` 填正确路径；程序每 15 秒会自动再找 |
| 油猴面板显示“未连接” | `run.bat` 没启动 / 被关了 / 端口 8770 被别的程序占用 |
| 面板一直“待发 0” | LiveTranslate 没在跑，或 `transcript_dir` 指错；打开 <http://127.0.0.1:8770/status> 看 `transcript_dir` |
| 提示“找不到弹幕输入框” | B 站页面改版了。按 F12 检查弹幕输入框的 XPath，改 `bilidanmaku.user.js` 里的 `XPATH` |
| 弹幕框里字填进去了但不发 | 脚本会自动尝试回车和“发送”按钮；仍不行就先开“试发”确认位置，再手动发一条测试 |
| 端口 8770 被占用 | 关掉上一个 `run.bat` 黑窗口，或重启电脑后重试 |
| 杀毒软件拦截 | 允许 Python 访问本地网络（只监听 `127.0.0.1`，不对外网开放） |
| 页面刷新后脚本没了 | 油猴安装的版本会一直存在；F12 控制台粘贴的版本需要重新粘贴 |
| 自动搜索太慢 | 手动在 `config.json` 填 `transcript_dir`，启动就不再扫描磁盘 |

---

## 九、风险提示

- 自动发弹幕可能违反 B 站用户协议，存在**禁言、封号**风险；请使用**小号**，后果自负。
- 全自动意味着翻译错了、ASR 听错了也会照发；建议先试发、常用 F9 暂停。
- 建议控制频率（大约每 5~10 秒一条），不要长时间高频刷屏。
- B 站页面改版可能导致油猴脚本失效；本项目不保证长期可用。

---

## 十、文件说明

| 文件 | 作用 |
|---|---|
| `run.bat` | 双击启动本地服务；自动查找 Python 和 LiveTranslate 译文目录 |
| `sender_server.py` | 读取译文、排队、提供本地 HTTP 接口（只依赖标准库） |
| `bilidanmaku.user.js` | 油猴脚本：把译文填进直播间弹幕框并发送 |
| `config.json` | 配置（端口、译文目录、前后缀、字数、断句等） |
| `tests/` | 自测（标准库 `unittest`） |
| `README.md` | 本说明 |

---

## 十一、自测

项目不需要安装第三方包。想确认代码没坏，在项目目录运行：

```bat
python -m unittest discover -s tests -t . -v
```

看到 `OK` 即可。

---

## 十二、更新记录

- **2026-10-21（1.2.0）**
  - LiveTranslate 路径可移植：自动搜索 + `config.json` 手动指定 + `--transcript-dir` 启动参数；
  - `run.bat` 自动查找 Python 3.10+，不再写死安装路径；
  - 重写本说明，补充译文来源、读取流程和小白安装步骤；
  - 新增标准库自测。
- **2026-10-18（1.1.0）**
  - 暂停期间不再累积待发弹幕，继续后只发最新一条。
