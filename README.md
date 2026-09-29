# xiaohongshubijifenxi

本仓库打包了本次小红书笔记分析工作中实际调用的 Codex skills：

- `xiaohongshu`：读取、整理和分析小红书笔记。
- `using-superpowers`：技能发现与调用流程。
- `brainstorming`：创意与方案梳理流程。
- `skill-creator`：创建、维护和校验 Codex skills。

## 安装

将需要的技能目录复制到 Codex skills 目录：

```bash
cp -R skills/<skill-name> ~/.codex/skills/
```

`xiaohongshu` 依赖独立的 `xiaohongshu-mcp` 服务，使用前请阅读该技能目录中的说明。

## 安全说明

本仓库不包含小红书 Cookies、登录信息、缓存和临时采集文件。不要把本机生成的 `cookies.json` 提交到 Git。

## 许可证

各技能保留原始许可证：

- `xiaohongshu`：MIT，许可证位于技能目录。
- `using-superpowers`、`brainstorming`：MIT，见仓库根目录 `LICENSE-superpowers`。
- `skill-creator`：Apache-2.0，许可证位于技能目录。

