# Windows兼容说明

参数含义和时间表示例见 [配置手册](CONFIGURATION.md)。Ubuntu 的 `.env` 注入方式不适用于直接运行 Windows CLI；Windows 凭据通过交互输入或当前进程环境变量保存。

现有已安装任务仍运行原run.py和本地配置，本轮不修改任务状态、不发送测试消息。原scripts/manage-task.ps1及config.synlink.toml保留在本机并被Git/源码包排除。

新环境的通用管理脚本为scripts/windows/manage-task.ps1，默认配置config.toml、任务名Autolycus-Inspection。不要在已有旧任务的电脑上再安装一份，否则可能重复发送。若只是继续使用当前旧任务，仍用原本的管理方式即可。

新安装时复制config/deployment.example.toml为config.toml，把storage.path改为本机可写的 `data/autolycus.db`，填写本地站点配置和模型名单。环境变量可覆盖站点设置；Windows终端不自动读取.env。凭据仍可用--init-credentials或--save-env-credentials加密保存，Linux不用这些DPAPI命令。

```powershell
python -X utf8 run.py --config config.toml --demo normal
python -X utf8 run.py --config config.toml --init-credentials
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/manage-task.ps1 -Action Install
```

部署测试完成后只保留一个主动发送端。切换到Linux前暂停旧Windows任务；回到Windows前先停止Linux容器。两个机器上的独立数据库不能相互防重。
