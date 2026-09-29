---
name: xiaohongshu
description: Use when 用户需要搜索、读取、批量整理、导出、分析或跟踪小红书（RedNote）笔记、评论和作者，或需要发布、点赞、收藏、评论及调用 xiaohongshu-mcp 时。
---

# 小红书数据与操作

只通过 [xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp) 访问小红书。默认只读、先少量试采；批量任务最多4路并发。出现平台警告、验证、登录异常或访问限制时立即停止。

## 开始前

```bash
cd scripts/
./install-check.sh
./start-mcp.sh
./status.sh
```

未登录时调用 `get_login_qrcode`，由用户使用小红书 App 扫码。服务默认地址为 `http://localhost:18060/mcp`。

## 读取原则

1. 用户提供链接时，只处理指定范围，不扩大样本。
2. 从链接或搜索结果取得匹配的 `feed_id` 与 `xsec_token`，不可构造 token。
3. 批量任务先试读1—3条；成功且没有平台警告后，才启动最多4路并发。
4. 默认只取前10条评论；只有分析确实需要且账号状态正常时才增加。
5. 每条记录采集时间、成功/失败、字段缺口和原始链接。
6. 不用标题、标签或经验补写未读取到的正文、评论、图片和视频。
7. 平台出现警告、验证、风控提示、频繁登录或连续空结果时，停止全部请求并通知用户。

## 数据流

```text
搜索结果或用户提供的有效链接
→ feed_id + xsec_token
→ get_feed_detail
→ 正文、互动数据、图片、视频信息、评论
→ 本地分析与导出
```

## 常用脚本

| 脚本 | 用途 |
|---|---|
| `search.sh <关键词>` | 搜索笔记 |
| `post-detail.sh <feed_id> <xsec_token>` | 获取笔记详情和默认评论 |
| `user-profile.sh <user_id> <xsec_token>` | 获取作者主页 |
| `recommend.sh` | 获取首页推荐 |
| `track-topic.sh <话题> [选项]` | 少量热点整理 |
| `mcp-call.sh <工具> [JSON参数]` | 通用调用 |
| `status.sh` | 检查登录状态 |
| `xhs_batch.py` | 采集、标准化、下载、OCR、模型批次、转录清单和清理 |
| `run-xlsx.sh` | 读取来源Excel、生成报告、核验报告 |
| `run-batch.sh` | 两阶段入口：prepare暂停给Codex，finalize生成并核验Excel |

## 常用工具参数

### 搜索

```json
{"keyword":"咖啡","filters":{"sort_by":"最新","note_type":"图文","publish_time":"一周内"}}
```

可选筛选：

- `sort_by`: 综合、最新、最多点赞、最多评论、最多收藏
- `note_type`: 不限、视频、图文
- `publish_time`: 不限、一天内、一周内、半年内
- `search_scope`: 不限、已看过、未看过、已关注
- `location`: 不限、同城、附近

### 笔记详情

```json
{
  "feed_id":"...",
  "xsec_token":"...",
  "load_all_comments":false,
  "limit":10,
  "click_more_replies":false
}
```

批量内容分析默认 `load_all_comments=false`。评论不足以支持总结时，把“评论重点”留空并记录证据缺口。

### 作者主页

```json
{"user_id":"...","xsec_token":"..."}
```

### 写操作

发布、点赞、收藏、评论和回复均属于外部写操作。只有用户明确要求时才调用对应工具；内容分析任务禁止调用。

## 批量整理

批量链接按以下顺序执行：

1. 提取并去重 `feed_id`，保留原始顺序和链接。
2. 用首批1—3条验证登录、字段和账号状态。
3. 使用一个已登录MCP服务并发提交最多4篇；也可显式传入多个已启动的MCP端点。不要自动创建额外账号。
4. 每篇独立计时60秒；超时立即记录并跳过，不重试。
5. 图片和视频只在分析需要时下载到任务临时目录。
6. 交付物验收通过后，按用户约定删除临时媒体；保留最终Excel和必要采集记录。

## 固定批量分析SOP

机械步骤全部由 `scripts/xhs_batch.py` 和 `scripts/run-xlsx.sh` 完成，不调用大模型，不消耗模型Token。只有封面策略、内容类型、商业判断、产品植入、高阅读做法、评论重点和证据缺口交给Codex。

1. 用 `run-xlsx.sh export-source --start 起始序号 --limit 数量` 把来源Excel指定范围转为JSON。
2. 用 `xhs_batch.py collect` 最多4路并发采集；每篇60秒；不重试。
3. 用 `normalize` 标准化正文、互动数据、评论、图片和官方字幕状态。
4. 用 `download-images` 下载图文全部图片，再用 `ocr-images` 本地4路OCR。
5. 用 `model-batches` 生成紧凑JSON。Codex只读取这些批次，按 `references/codex-analysis.md` 和 `references/analysis-contract.json` 输出分析JSON。
6. 用 `validate-analysis` 校验缺行、重复和字段缺失。
7. 用 `run-xlsx.sh build-report` 生成Excel，再用 `verify-report` 检查数据、公式和视觉预览。
8. 用 `transcription-report` 统计“无官方字幕，未转录”的视频。Excel完成并核验后再询问用户是否需要本地或云端转录；未获确认不得转录。
9. 核验通过后，用 `cleanup` 先预览清理范围；用户约定的保留期到达后再加 `--execute` 删除临时媒体。

运行表格脚本前，调用工作区依赖加载器，并设置它返回的 `CODEX_NODE_BIN` 与 `CODEX_NODE_MODULES`。不要自行安装或改用其他Excel库。

## 素材分析边界

- 返回的文字和元数据不能替代图片逐张查看或视频完整观看。
- 图文按图片序号记录OCR、内容结构和产品露出位置。
- 视频优先读取官方字幕；没有字幕时先跳过转录，只按标题、正文、封面和已取得证据分析。
- 素材不完整时明确写“部分完整”或“未确认”。

## 账号安全

- 默认只读、最多4路并发、少量评论。
- 不运行多个小红书客户端同时访问同一账号。
- 不自动点赞、收藏、评论、关注或发布。
- 不使用代理池、批量账号或绕过验证。
- 平台警告出现一次即停止，不以更换工具、浏览器或账号继续尝试。

## 输出记录

每次任务至少记录：指定范围、应读数量、去重数量、成功数量、部分成功数量、失败数量、采集时间、字段缺口、临时素材目录和清理状态。
