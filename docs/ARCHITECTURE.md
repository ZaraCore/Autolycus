# 项目结构与验证边界

src/autolycus共用HTTP采集、规则、报告、SQLite、飞书发送。Windows DPAPI仅在Windows加载；Linux的fcntl仅在daemon运行时导入。包导入和普通CLI不要求另一平台存在。

daemon为容器调度父进程，现有--scheduled为两平台共用的一次巡检入口；maintenance提供心跳检查和SQLite备份。进程心跳与业务成功状态分开。

config/deployment.example.toml为通用部署模板，.env.example为环境变量模板。实际.env、config.toml、站点配置、数据库、日志、DPAPI密文、原始响应和历史讨论存本地，不进入源码包。

新scripts/linux维护Docker部署；scripts/windows维护新Windows任务。现有本地旧管理脚本不迁移，防止破坏已安装任务。deploy/docker放镜像构建文件，根目录compose.yaml定义固定服务名、只读配置和命名数据卷。

GitHub Actions在Ubuntu22.04跑Python测试、bash语法检查、Compose配置检查及镜像构建/CLI冒烟。CI不是服务器真实鉴权/飞书投递验收，不使用部署密钥。Windows本地已用Git Bash通过五个Linux脚本的语法检查，但没有Docker，实际容器执行仍需CI或Ubuntu验证。

prepare-source.py按明确允许清单生成源码zip，不扫描复制整个工作目录。首次上传Git前仍需检查文件清单及git diff，gitignore不能清除已经提交过的密钥；本工作目录开始本轮时尚不是Git仓库，没有初始化仓库或向远端推送。
