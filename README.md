# B站弹幕同传助手（BiliDanmakuBridge）

把 [LiveTranslate](https://github.com/TheDeathDragon/LiveTranslate) 翻译出来的字幕，自动填进 B 站直播间的弹幕框并发出去。

> 本项目**不负责翻译**，也不调用 B 站 API、不保存账号密码或 Cookie。

## 工作原理

```
LiveTranslate（装在哪个目录都可以）
  └─ <LiveTranslate目录>\transcripts\livetrans_日期_时间_translation.txt
        │  只读服务启动后新写入的行
        ▼
sender_server.py（本机 127.0.0.1:8770）
        │  浏览器脚本每 0.8 秒取一次
        ▼
bilidanmaku.user.js（Tampermonkey 油猴脚本）
        │  填进直播间弹幕框并发送
        ▼
B站直播间
```

**译文来源**：LiveTranslate 的 ASR + 翻译模型。它把每句译文写成：

```text
[00:38:02] 没事，要转生成大妈技能吗？
```

本工具只读这种带时间戳的行，自己不做识别、不做翻译；启动时从最新文件末尾开始，不补发历史。

## 准备

- Windows 10/11
- [LiveTranslate](https://github.com/TheDeathDragon/LiveTranslate) 已能正常翻译
- Python 3.10+（只依赖标准库，不需要 pip 装包）
- 浏览器 + [Tampermonkey（篡改猴）](https://microsoftedge.microsoft.com/addons/detail/%E7%AF%A1%E6%94%B9%E7%8C%B4/iikmkjmpaadaobahmlepeloendndfphd?hl=zh-CN)
- B站小号（强烈建议）

## 安装

1. 下载本项目：GitHub 页面 → Code → Download ZIP，解压到任意目录，例如 `D:\Tools\BiliDanmakuBridge`。
2. 安装 Python：<https://www.python.org/downloads/>，安装时勾选 **Add python.exe to PATH**。
3. 安装篡改猴：用上面的 Edge 商店链接，装好并启用。
4. 启动 [LiveTranslate](https://github.com/TheDeathDragon/LiveTranslate)，开始翻译，确认它的 `transcripts` 文件夹里有 `livetrans_*_translation.txt`。
5. 双击 **`run.bat`**。看到 `[detect] 使用译文目录: ...` 和 `本地服务已启动` 即可；**这个黑窗口不要关**。
6. **一键安装脚本**：浏览器打开 <http://127.0.0.1:8770/bilidanmaku.user.js>，Tampermonkey 会弹出安装页，点“安装”。
7. 打开直播间并刷新，右上角出现“弹幕同传”面板。第一次先点 **“试发：开”**，确认译文填进弹幕框且位置正确；再点回 **“试发：关”** 开始真实发送。**F9 = 暂停/继续**。

## LiveTranslate 装在别处怎么办

`config.json` 的 `transcript_dir` 默认留空，`run.bat` 会自动搜索常见位置和各盘符根目录；找到后打印 `[detect] 使用译文目录: ...`。

找不到或找错时，只改 `config.json` 里的这一行：

```json
"transcript_dir": "D:\\Apps\\LiveTranslate\\transcripts"
```

也可以启动时临时指定：

```bat
run.bat --transcript-dir "D:\Apps\LiveTranslate\transcripts"
```

找目录：右键 LiveTranslate 快捷方式 → 打开文件所在位置 → 旁边的 `transcripts` 文件夹。

## 配置 `config.json`

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
| `port` | 本地服务端口，默认 `8770`。油猴脚本里也写死 8770，改端口要同时改脚本 |
| `transcript_dir` | 空 = 自动搜索；也可以填 LiveTranslate 的 `transcripts` 绝对路径 |
| `prefix` / `suffix` | 弹幕前后加的字，默认 `【译文】`；都不想要就都留空 |
| `max_length` | **每条弹幕的总长上限**（含前后缀，按汉字数算）。默认 **40** —— B站上限是 80 个「字符」，一个汉字/全角标点占 2 字符，所以实际只有 40 字。超过时**不会截断丢内容**，而是自动在标点处断句、分成多条发出；设为 `0` = 完全不限长（会被B站截断） |
| `min_length` | 短于这个字数的译文不发（挡掉「嗯。」「啊！」这种） |
| `strip_period` | **删掉译文末尾的句号**，默认 `true`。只删末尾——句中的句号，以及 `！` `？` `，` `…` 全部保留。设为 `false` = 末尾句号也原样保留。`。` / `．` 会删，半角 `.` 不删（否则「等等...」的省略号会被误删） |
| `split_interval` | 断句后**每段之间隔几秒**，默认 `2.0`。按上一段**发送完成**的时刻开始计时 |
| `stale_seconds` | 超过这么久还没发出去的译文自动丢弃（防止一开机补发一堆旧的） |
| `dedupe_seconds` | 这么短时间内重复的同一句只发一次 |
| `poll_interval` | 读取译文文件的间隔，默认 0.5 秒 |

**断句规则**：优先在句末标点（`。！？；…`）处断开，没有就用逗号（`，、`），再没有就在上限处硬切。每一段都会各自带上 `【】`，内容不会丢。

改完要**重启 `run.bat`** 才生效。

## 安全

- 用**小号**；自动发弹幕可能违反 B站用户协议，存在禁言/封号风险。
- 先“试发”，确认位置正确再真实发送；F9 可随时暂停。
- 本项目不读取、不保存 B 站密码或 Cookie；发送由浏览器当前登录状态完成。
- 建议每 5~10 秒一条，不要长时间高频刷屏。

## 文件

| 文件 | 作用 |
|---|---|
| `run.bat` | 启动本地服务，自动找 Python 和 LiveTranslate 译文目录 |
| `sender_server.py` | 读取译文、排队、提供本地接口（只依赖标准库） |
| `bilidanmaku.user.js` | 油猴脚本，填弹幕框并发送 |
| `config.json` | 配置 |
