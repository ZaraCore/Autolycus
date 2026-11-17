# P1本地交付验证

已完成：

- 原工作目录68项测试通过。
- 按明确允许清单生成data/Autolycus-source.zip，并解压到独立目录，68项测试再次通过，不依赖本地站点配置。
- 源码包未包含.env、config.toml、真实站点配置、DPAPI密文、数据库、日志及docs/local历史材料。
- Windows新管理脚本PowerShell语法检查通过。
- 五个Linux脚本由Windows Git Bash逐个执行bash -n，全部通过；没有实际执行部署。
- Compose YAML已在本地解析，健康命令、服务和数据卷定义存在；尚未使用真实docker compose校验和构建。
- Windows既有任务及其实际站点配置未改动，未创建新任务、未部署到Ubuntu虚拟机。
- 已创建公开仓库 https://github.com/ZaraCore/Autolycus 并推送main；首次GitHub Actions自动检查已通过，包含Ubuntu22.04测试、Shell语法、Compose配置、Docker镜像构建与容器CLI冒烟。

仍需Ubuntu虚拟机完成：Compose服务实际启动、数据卷权限及运行锁验证、真实接口与飞书验收、重启恢复、升级/回退和备份恢复测试。CI构建成功不能替代这些现场验收。
