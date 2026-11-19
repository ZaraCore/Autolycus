# Ubuntu 22.04 + Docker 部署

首次部署请先阅读 [README 快速开始](../README.md#ubuntu-快速开始) 和 [配置手册](CONFIGURATION.md)。配置手册包括环境变量、TOML 参数以及时间表和模型名单的修改方法。

## 范围与前提

Windows与Linux共用src/autolycus内的采集、规则、报告、存储和通知代码。Windows脚本放在scripts/windows；Linux脚本放在scripts/linux；Docker构建文件放在deploy/docker。原Windows本地配置和原管理脚本保留在本机，但不进入源码包。

需要Ubuntu 22.04、sudo权限、Git、Docker Engine及Compose v2插件，以及到后台/飞书/镜像仓库的网络。Linux脚本还使用系统自带的bash、flock、tar。脚本不安装Docker、不修改系统自动更新。使用 `sudo bash ...` 时会以root调用Docker；不要将.env中的密钥写进命令行参数。

Windows端及GitHub Actions已通过测试。Ubuntu虚拟机已完成真实数据预览、手动飞书发送、v0.1.1镜像升级、数据库备份与调度健康检查；新版定时卡片实际送达、回退和重启恢复仍需分别验收。CI或healthy状态不等同于真实投递成功。

## 1. 获取源码与填写配置

将审核后的源码提交GitHub，再在Ubuntu执行（替换仓库地址）：

```bash
git clone <YOUR_REPOSITORY_URL> autolycus
cd autolycus
cp .env.example .env
cp config/deployment.example.toml config.toml
chmod 600 .env
chmod 644 config.toml
nano .env
nano config.toml
```

`.env`填写真实后台URL、站点ID、站点名、管理员用户ID/系统令牌、飞书Webhook及签名密钥。含 `$`、`#`、空格的值使用单引号，Compose进行注入；脚本不source这个文件。环境变量覆盖TOML的站点与数据库设置。当前Python命令行不自动解析.env，容器通过Compose env_file接收配置。

`config.toml`只放非敏感的时间表、字段映射、阈值、重点模型名单，必须可被容器非root用户读取。不要把令牌写在TOML里。Docker示例默认关闭重点模型，需迁入本地所需的 group/model targets 后启用，避免公开仓库携带某个站点的定制名单。已有Windows配置可以作为人工迁入依据，DPAPI密文不能迁入Linux。

后台适配使用 GET /api/metrics/query 的 custom/start/end；渠道查询仍是POST /channel_monitor?Action=Query的滚动窗口，未解决其精确时间区间限制。部署不改变已验收的报告格式和这项限制。

## 2. 部署前预览与切换

Windows原任务可以先继续运行；但准备启动Linux自动发送前，必须暂停Windows任务，避免两台机器用独立数据库重复推送。

应先完成 README 中的构建、未来计划预览和真实数据预览。若已构建并手动验证过镜像，可用 `sudo bash scripts/linux/manage.sh resume` 启用调度，无需再次执行 deploy.sh。以下 deploy.sh 是包含重新构建的一体化启动方式，不是只做预览的命令。

```bash
sudo bash scripts/linux/deploy.sh
```

脚本构建镜像、校验必填配置、启动容器并等待调度心跳健康。如果配置文件不存在，会创建模板并停止，填写后再运行。返回成功只说明调度进程健康，不代表真实接口及投递已验收。这个命令启动后可能在当前允许窗口内立即执行报告。

```bash
sudo bash scripts/linux/manage.sh preview
sudo bash scripts/linux/manage.sh status
sudo bash scripts/linux/manage.sh logs
```

preview只采集并输出，不发消息；真实计划自动发送。不要贴出 `docker compose config` 的完整输出，里面可能包含密钥。服务未发布入站端口，无需公网端口转发。

## 3. 运行与数据

- 固定东八区计划：周一至周五09:00—18:00每小时；周末09:00、12:00、18:00。相邻计划区间查询；不处理法定节假日和调休。
- Ubuntu 新版由容器内 Supercronic 按生成的 cron 时间表触发，不再每10秒检查计划。每次巡检子进程最多240秒；失败后等待60秒，至多尝试三次，并受当前计划的宽限窗口限制。详见 [cron 调度迁移](CRON.md)。
- 容器内使用fcntl锁避免同一数据目录启动两个调度进程，SQLite原子领取继续保护任务。
- SIGTERM通知 cron 和任务进程组退出；任务先终止查询子进程，最多等待15秒后强制结束。关机或宿主休眠仍会停止服务；cron启动时不补执行此前的计划。
- 新版健康检查校验 cron 进程的启动标识和存活状态，空闲时无需周期写心跳；仅证明调度存活，业务失败由数据库状态及日志反映。Compose不会仅因为unhealthy自动重启，但进程退出后按unless-stopped重启。
- 数据库存于命名卷 `autolycus_runtime`，容器重建不清空。应用以UID10001运行，文件系统只读，仅数据卷和/tmp可写。
- Docker日志限制3×10MB；原文件日志也轮转。数据库尚无自动清理策略，应定期检查磁盘及备份占用。
- 不要执行 `docker compose down -v`，该操作会删除持久数据卷。

```bash
sudo bash scripts/linux/manage.sh pause
sudo bash scripts/linux/manage.sh resume
sudo bash scripts/linux/manage.sh backup
```

主动暂停会保留数据；原核对逻辑仍可能将暂停时段计为漏报，未在本轮引入暂停区间记账。

## 4. 一条命令升级

先确保目标代码已提交到远端，使用明确的tag或分支名：

```bash
sudo bash scripts/linux/upgrade.sh v0.2.0
```

升级默认使用普通构建网络，不强制使用代理。有特殊联网要求的机器可在单次命令中设置 `AUTOLYCUS_UPGRADE_PROXY`（供Git和构建依赖下载使用）及 `AUTOLYCUS_BUILD_NETWORK=host`（仅影响镜像构建）。例如：

```bash
sudo env AUTOLYCUS_UPGRADE_PROXY=http://YOUR_PROXY_HOST:PORT AUTOLYCUS_BUILD_NETWORK=host bash scripts/linux/upgrade.sh v0.2.0
```

这些可选参数不写入项目配置或镜像，不配置时无需Clash。Docker后台拉取基础镜像的代理仍由服务器自己的Docker服务管理。程序运行时的网络设置不受这些参数影响。

脚本fetch指定ref，将该提交导出到本地.releases临时源码目录并构建新镜像；不强行checkout、不覆盖未提交修改、不改.env/config.toml。构建和配置检查通过后，停止旧服务，用SQLite在线备份API生成backups目录的新数据库快照，再启动新版。备份失败则恢复旧服务。

镜像用Git提交标识，当前镜像记录于.deploy/active-image，前一镜像记录于.deploy/previous-image。版本可查看.deploy/source-revision，以及镜像的org.opencontainers.image.version标签。直接手动运行Compose时须设置相同AUTOLYCUS_IMAGE，否则可能选到默认local镜像；日常请使用管理脚本。

此升级脚本升级运行镜像，不自动替换宿主的Compose、部署脚本或本地配置；若新版改变这些部署契约，需按版本说明同步宿主文件并人工审阅。保留旧镜像、backups和.releases会占用磁盘，确认版本稳定后再按需要清理，不自动删除。

## 5. 回退

```bash
sudo bash scripts/linux/rollback.sh
```

先备份当前数据库，再切回前一镜像。默认不回滚数据库，以免丢失升级后已送达记录导致重复发送。若旧镜像无法读取新结构，脚本停止服务，不能宣称回退成功。

需要数据库恢复时：先停容器，保留当前数据备份，再选择明确的升级前快照，用一次性维护容器写入数据卷，并执行integrity_check。此步骤故意不自动执行：恢复旧快照可能丢失新数据及发送记录，需要单独确定恢复点。不把原始文件直接覆盖到正在运行的SQLite数据库上。

本机.env及配置是另一个备份对象，含密钥，应自行保存到受控位置；数据库快照不包含它们。版本升级不会覆盖这些文件。

## 6. Ubuntu验收清单

1. 首次构建、配置预检、非root写入数据卷、健康状态均通过。
2. preview数字与后台同区间核对，Windows停止后真实计划只收到一份报告。
3. 容器停止/恢复、Ubuntu重启后恢复调度；主动停止不会在重启后擅自启动。
4. 升级前后汇总、通知防重记录不丢失；故障升级不报成功。
5. 备份能恢复到独立测试库，旧镜像回退能启动或明确提示结构不兼容。
6. 连续观察工作日、周末和跨夜时段，保留--status核对结果。


## 网络与代理

代理不是安装或升级的强制要求。下载源码由 Git 访问 GitHub，基础镜像由 Docker 服务访问镜像仓库，构建依赖由镜像构建过程中的 pip 访问 PyPI；三者的网络配置分别生效。

仅对需要代理的机器使用以下示例，将 `PROXY_HOST:PORT` 替换为实际可达地址。不要把占位值直接运行，也不要将个人地址提交公共仓库：

```bash
git -c http.proxy=http://PROXY_HOST:PORT clone https://github.com/ZaraCore/Autolycus.git
sudo docker build --network=host \
  --build-arg HTTP_PROXY=http://PROXY_HOST:PORT \
  --build-arg HTTPS_PROXY=http://PROXY_HOST:PORT \
  -f deploy/docker/Dockerfile -t autolycus:local .
```

`host` 仅让构建步骤使用 Ubuntu 宿主网络，不修改运行容器网络。Docker 服务拉取基础镜像的代理需在服务器单独配置；只给 Docker 服务配置代理不会自动让 Git 或构建中的 pip 使用代理。普通直连服务器不需要这些参数。升级脚本的可选变量见 [配置手册](CONFIGURATION.md#升级脚本可选参数)。
