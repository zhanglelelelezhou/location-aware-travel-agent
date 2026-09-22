# GitHub 发布检查清单

## 已完成

- [x] 默认模式不依赖 API Key 或网络
- [x] `.env`、缓存、虚拟环境和本地覆盖率文件均被忽略
- [x] README 包含定位、架构、快速开始、真实指标和能力边界
- [x] 一条命令的离线作品集演示
- [x] Python 3.10/3.11/3.12 CI、85% 覆盖率门禁和三套离线评测
- [x] 非 root Docker、只读 Compose、健康检查和容器 HTTP 冒烟 job
- [x] 初始失败报告与修复后报告同时保留
- [x] 面试讲解脚本和高频问题库

## 上传前需要本人决定

- [ ] 选择公开仓库名称与 GitHub 账号
- [ ] 选择仓库可见性（作品集建议 public）
- [ ] 决定许可证：MIT 允许广泛复用；不添加许可证则默认保留全部权利
- [ ] 确认 Git 提交作者姓名和邮箱适合公开展示

## 上传后验证

- [ ] 设置 remote 并推送 `main`
- [ ] 确认 GitHub Actions 的 Python matrix、系统验收和容器 job 全绿
- [ ] 根据最终仓库 URL 添加 CI badge 与 `project.urls`
- [ ] 在 GitHub About 中填写简介、topics 和项目主页
- [ ] 创建 `v0.1.0` release，并在简历中使用固定仓库链接

## 建议 topics

`ai-agent`、`langgraph`、`mcp`、`rag`、`fastapi`、`deepseek`、`tool-calling`、`agent-evaluation`
