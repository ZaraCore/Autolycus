# P1本地交付验证

已完成：

- 原工作目录68项测试通过。
- 按明确允许清单生成data/Autolycus-source.zip，并解压到独立目录，68项测试再次通过，不依赖本地站点配置。
- 源码包未包含.env、config.toml、真实站点配置、DPAPI密文、数据库、日志及docs/local历史材料。
- Windows新管理脚本PowerShell语法检查通过。
- 五个Linux脚本由Windows Git Bash逐个执行bash -n，全部通过；没有实际执行部署。
- Compose YAML已在本地解析，健康命令、服务和数据卷定义存在；尚未使用真实docker compose校验和构建。
- Windows既有任务及其实际站点配置未改动，未创建新任务、未部署到Ubuntu、未初始化Git或推送GitHub。

仍需Ubuntu或CI完成：Docker镜像构建，Compose实际启动，Linux文件权限与fcntl锁验证，真实接口与飞书验收，重启恢复，升级/回退和备份恢复测试。不得将这些待验收项表述为已经通过。
