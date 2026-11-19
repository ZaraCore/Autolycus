# 项目结构与验证边界

src/autolycus共用HTTP采集、规则、报告、SQLite、飞书发送。Windows DPAPI仅在Windows加载；Linux的fcntl仅在daemon运行时导入。包导入和普通CLI不要求另一平台存在。

cron 模块生成时间表并启动 Supercronic；daemon 现在是 cron 单次任务的超时与重试包装器，不再空闲轮询。--scheduled 仍是两平台共用的一次巡检入口；maintenance 提供 cron 进程健康检查和 SQLite 备份。调度健康与业务成功状态分开。详见 [cron 调度说明](CRON.md)。

config/deployment.example.toml为通用部署模板，.env.example为环境变量模板。实际.env、config.toml、站点配置、数据库、日志、DPAPI密文、原始响应和历史讨论存本地，不进入源码包。

新scripts/linux维护Docker部署；scripts/windows维护新Windows任务。现有本地旧管理脚本不迁移，防止破坏已安装任务。deploy/docker放镜像构建文件，根目录compose.yaml定义固定服务名、只读配置和命名数据卷。

GitHub Actions在Ubuntu22.04跑Python测试、bash语法检查、Compose配置检查及镜像构建/CLI冒烟。CI不是服务器真实鉴权/飞书投递验收，不使用部署密钥。Windows本地已用Git Bash通过五个Linux脚本的语法检查，但没有Docker，实际容器执行仍需CI或Ubuntu验证。

prepare-source.py按明确允许清单生成源码zip，不扫描复制整个工作目录。上传Git前检查文件清单及git diff，gitignore不能清除已经提交过的密钥。首次公开发布已按允许清单提交，仓库为 https://github.com/ZaraCore/Autolycus ，未提交本机配置和运行数据。
