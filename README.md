# Autolycus

Autolycus 定时查询已适配的 New API 后台统计接口，将巡检结果通过自定义机器人 Webhook 发送到飞书群。Windows 与 Ubuntu 共用业务代码，Ubuntu 使用 Docker 部署。

本项目面向已确认接口和权限的后台，不保证所有 New API 分支均可直接使用。

## 报告内容

- 渠道成功率：调用量前 20，展示成功率、成功/总量及次数前三的错误码。
- 分组成功率：使用后台重试聚合结果，仅展示成功率低于 95% 且有调用记录的分组。
- 重点模型延迟：按配置的分组和模型查询成功消费日志，展示成功次数、P50 和 P95；无成功记录时省略。预置名单包括 OpenAI、OpenAI 官key、Banana 和 Gemini官key，共 24 个分组模型目标。
- 飞书展示：静态 Markdown 卡片，三类结果均采用表格；渠道、分组及模型名称加粗。异常成功率、模型延迟及不可用提示按[颜色阈值](docs/CONFIGURATION.md#异常数值颜色-highlight)标橙或标红；成功率超过 95% 标绿，恰好 95% 保留默认颜色。

表格列：

| 报告部分 | 列 |
| --- | --- |
| 渠道成功率 | 渠道、成功率、成功/总量、主要错误（次数） |
| 分组成功率 | 分组、成功率、成功/总量 |
| 重点模型延迟 | 模型、成功次数、P50、P95 |

模型延迟按上述四个分组显示小标题（例如 `Banana分组：`），每组一张表，模型单元格不重复分组名称。Banana 与 Gemini官key 各配置 7 个 Gemini 图像模型；整个分组无成功记录时不显示标题，查询失败仍提示数据不可用。部署模板默认关闭模型监测，核对名单后启用。

百分比最多保留两位小数，延迟用 `s` 表示秒，保留一位小数并省略末尾的 `.0`；次数不添加千位分隔符。无有效耗时样本或查询失败时仍明确提示，不伪造数值。

性能统计使用固定起止时间；渠道监控使用后台返回的滚动窗口，两者分别标注区间。成功消费记录的延迟不代表异步任务最终完成。

本次展示优化见 [v0.2.1 发布说明](docs/RELEASE-v0.2.1.md)；从早期版本迁移 cron 和配置时，同时参阅 [v0.2.0 发布说明](docs/RELEASE-v0.2.0.md)。

## 文档入口

| 文档 | 内容 |
| --- | --- |
| [配置手册](docs/CONFIGURATION.md) | `.env`、`config.toml` 的填写方法、每项含义、修改汇报时间和模型名单 |
| [Ubuntu 部署与维护](docs/DEPLOYMENT.md) | 构建、启停、升级、备份、回退和验收 |
| [Windows 使用说明](docs/WINDOWS.md) | Windows 凭据保存和任务安装 |
| [结构及验证边界](docs/ARCHITECTURE.md) | 模块职责与验证范围 |

## Ubuntu 快速开始

需要 Ubuntu 22.04、Git、Docker Engine、`docker compose`，以及到后台、飞书和下载服务的网络。以下命令在 Ubuntu 终端执行。

### 1. 获取源码并填写配置

```bash
git clone https://github.com/ZaraCore/Autolycus.git
cd Autolycus
cp -n .env.example .env
cp -n config/deployment.example.toml config.toml
chmod 600 .env
chmod 644 config.toml
nano .env
nano config.toml
```

`.env` 保存站点地址、名称、后台凭据和飞书凭据；`config.toml` 保存接口字段、时间表、规则和模型名单。两者均留在部署机器，不提交 Git。请按[配置手册](docs/CONFIGURATION.md)替换模板值，重点模型默认关闭，需自行配置后开启。

### 2. 检查格式、构建、预览

```bash
sudo docker compose config --quiet
sudo docker compose build monitor
sudo docker compose run --rm --no-deps --pull never monitor \
  python -m autolycus --config /etc/autolycus/config.toml --schedule-preview
sudo docker compose run --rm --no-deps --pull never monitor \
  python -m autolycus --config /etc/autolycus/config.toml
```

`config --quiet` 无输出表示 Compose 格式通过，不证明凭据有效，也不验证 TOML 的业务参数。`--schedule-preview` 校验配置并列出未来七天计划，不访问后台；最后一条查询真实后台并输出报告，不发送消息。

普通网络无需代理。下载失败时参考[网络与代理说明](docs/DEPLOYMENT.md#网络与代理)，不要将个人代理地址写死在公共代码中。

### 3. 验证发送并开启自动调度

先暂停其他机器上的发送任务，避免重复推送。第一条命令会实际发送一次消息，第二条开启自动调度：

```bash
sudo docker compose run --rm --no-deps --pull never monitor \
  python -m autolycus --config /etc/autolycus/config.toml --notify
sudo bash scripts/linux/manage.sh resume
sudo docker compose ps
```

部署模板使用北京时间：周一至周五 09:00—18:00 每小时一次，周末 09:00、12:00、18:00。自然周划分，不识别节假日或调休。调整方法见[修改汇报时间](docs/CONFIGURATION.md#修改汇报时间)。

## 常用维护命令

在项目目录执行：

```bash
sudo bash scripts/linux/manage.sh status   # 容器状态与计划执行核对
sudo bash scripts/linux/manage.sh logs     # 最近容器日志
sudo bash scripts/linux/manage.sh pause    # 暂停调度
sudo bash scripts/linux/manage.sh resume   # 恢复，并应用本地配置变化
sudo bash scripts/linux/manage.sh preview  # 真实数据预览，不发送
sudo bash scripts/linux/manage.sh backup   # 备份运行数据库
sudo bash scripts/linux/upgrade.sh v0.2.1  # 升级到本次发布版本
sudo bash scripts/linux/rollback.sh        # 切回记录的前一镜像
```

升级构建新镜像、检查配置，再停止旧服务、备份数据库并启动新版；本地配置和数据保留。现有脚本只升级程序镜像，不自动同步宿主机脚本或 Compose；部署文件变动需按版本说明处理。回退不自动恢复旧数据库。详见[部署手册](docs/DEPLOYMENT.md)。

## 当前调度与验收边界

Ubuntu 新版使用容器内 Supercronic 执行 cron job，根据 `config.toml` 在启动时生成北京时间任务。到计划点启动一次巡检，取消每 10 秒检查循环；失败重试在本次任务内处理。部署迁移、健康检查和验收步骤见 [cron 调度说明](docs/CRON.md)。

- `healthy` 表示 cron 调度进程存活，不代表后台查询或飞书投递成功；还要核对执行状态并抽查群消息。
- 关机、休眠或虚拟机挂起时无法运行；cron 启动或恢复时不补执行已经错过的触发点。主动暂停期间也可能显示为 `missing`。
- 两台机器的独立数据库不能相互防重，只保留一个主动发送端。
- 已完成 Ubuntu 虚拟机真实数据预览、手动飞书投递、`v0.1.1` 镜像升级与健康检查。v0.2.x 的 cron 定时触发、新版表格报告与颜色显示、回退和重启恢复仍需在 Ubuntu 现场分别验收。

## 开发验证

使用 Python 3.11 或更高版本，Windows 示例：

```powershell
python -m pip install -e '.[dev]'
python -X utf8 -m pytest -q
python -X utf8 run.py --demo normal
```

演示不访问真实后台、不发送消息。`python -X utf8 scripts/prepare-source.py` 生成源码包，排除真实配置、凭据与运行数据。
