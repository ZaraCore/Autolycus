# 配置手册

命令默认在 Ubuntu 的项目目录执行。Windows 不自动读取 `.env`，差异见 [Windows 说明](WINDOWS.md)。本手册对应 v0.2.2：Ubuntu 使用容器内 cron，Windows 保留任务计划。

## 文件用途与优先级

| 文件 | 用途 |
| --- | --- |
| `.env.example` | 环境变量模板，可以提交 Git。 |
| `.env` | 每台机器的真实地址、名称与凭据，不提交 Git。 |
| `config/deployment.example.toml` | 已适配后台统计接口的部署模板，可以提交 Git。 |
| `config.toml` | 本地时间表、规则、字段和模型名单，不提交 Git。 |
| `config.example.toml` | 通用接口适配示例，路径和字段是占位值，不是现成站点配置。 |

Compose 通过 `env_file` 将 `.env` 注入容器；Python CLI 本身不会读取 `.env`。凭据仅从环境变量读取，不写进 TOML。

`AUTOLYCUS_BASE_URL`、`AUTOLYCUS_SITE_ID`、`AUTOLYCUS_SITE_NAME` 分别覆盖 TOML 中的 `site.base_url`、`site.id`、`site.name`，即使环境变量填空也会覆盖。Docker Compose 还固定 `AUTOLYCUS_DATABASE=/var/lib/autolycus/autolycus.db`，覆盖 TOML 数据库路径，数据存放在命名卷 `autolycus_runtime`。

## `.env` 填写示例

将占位文字换成实际值：

```dotenv
AUTOLYCUS_BASE_URL='https://your-backend.example.com'
AUTOLYCUS_SITE_ID='primary'
AUTOLYCUS_SITE_NAME='我的巡检站点'
AUTOLYCUS_ACCESS_TOKEN='后台管理接口访问令牌原文'
AUTOLYCUS_USER_ID='令牌所属账号的用户ID'
AUTOLYCUS_FEISHU_WEBHOOK='https://open.feishu.cn/open-apis/bot/v2/hook/替换成实际值'
AUTOLYCUS_FEISHU_SECRET=
```

| 参数 | 填写要求与意义 |
| --- | --- |
| `AUTOLYCUS_BASE_URL` | 后台 HTTPS 基础地址，不是控制台页面 URL；不能带账号、查询参数或片段。 |
| `AUTOLYCUS_SITE_ID` | 本地站点唯一标识，例如 `primary`，用于统计与发送记录，运行后保持稳定。 |
| `AUTOLYCUS_SITE_NAME` | 报告显示的站点名，可以中文。 |
| `AUTOLYCUS_ACCESS_TOKEN` | 能访问后台统计接口的管理令牌，不是模型调用 API Key。不要加 `Bearer `，程序会自动添加。 |
| `AUTOLYCUS_USER_ID` | 作为 `New-Api-User` 请求头发送，填写令牌所属账号的用户 ID；适配后台通常需要。 |
| `AUTOLYCUS_FEISHU_WEBHOOK` | 目标群自定义机器人的完整地址。当前发送器要求 `https://open.feishu.cn/open-apis/bot/v2/hook/...` 格式。 |
| `AUTOLYCUS_FEISHU_SECRET` | 该机器人启用签名校验时填写；未启用则留空。换机器人时同步核对，不沿用旧密钥。 |
| `AUTOLYCUS_DATABASE` | Python 支持的数据库路径覆盖项；Compose 已固定此项，一般不要在 `.env` 自定义。 |

值建议使用英文单引号，尤其含 `$`、`#` 或空格时，避免变量插值或注释。不要粘贴智能引号或多行令牌。令牌生成方式、权限和有效期取决于后台，格式检查不能验证。

不要上传 `.env`，也不要公开完整的 `docker compose config` 输出（可能含凭据）。Windows DPAPI 密文不能直接迁移到 Linux。

## `config.toml` 参数说明

以 `config/deployment.example.toml` 为基础；下列接口与字段是已适配后台的格式，不是所有 New API 的通用协议。

### `[site]` 站点和接口

| 参数 | 模板值 | 作用 |
| --- | --- | --- |
| `id` | `primary` | 站点标识，可被 `.env` 覆盖。 |
| `name` | `Example service` | 报告名称，可被 `.env` 覆盖。 |
| `base_url` | `https://backend.example.com` | 必须替换为真实后台，或在 `.env` 覆盖。 |
| `metrics_path` | `/api/metrics/query` | 性能统计的站内绝对路径，不带查询参数。 |
| `source` | `platform_performance` | 数据来源标签，用于隔离保存的统计，不是接口 URL。 |
| `scope` | `all-default-filters-custom-interval-v2` | 统计口径标签，改变成功定义或查询范围时应更新，避免复用旧口径基准。程序也会根据地址、字段和过滤条件生成摘要。 |
| `timeout_seconds` | `20` | 单次 HTTP 请求超时秒数，必须大于 0，不是整份报告总时限。 |

### `[query]` 与 `[query.filters]`

```toml
[query]
mode = "absolute"
start_parameter = "start"
end_parameter = "end"

[query.filters]
range = "custom"
```

`mode="absolute"` 按固定起止时间查询。`start_parameter`、`end_parameter` 是后台接受的参数名，值由程序转换为 Unix 秒数。`filters` 原样加入查询参数，不能覆盖起止参数。

需要限制主性能统计的分组时，可在 `filters` 中增加 `group = "实际分组名"`。它不是只筛选报告里的分组表：渠道监控独立请求，重点模型查询会覆盖各自的分组、模型和日志类型。

CLI 兼容 `relative` 模式，目前只支持最近一小时 `range="1h"`；容器自动调度预检要求 `absolute`，不要切成滚动模式部署。

### `[fields]` JSON 字段映射

| 参数 | 模板 JSON 路径 | 含义 |
| --- | --- | --- |
| `total` | `data.total` | 总调用量，必填。 |
| `success` | `data.success` | 成功数，必填。 |
| `failure` | `data.failure` | 失败数，必填。 |
| `p50_seconds` | `data.quantiles.p50` | 耗时中位数，秒，可省略。 |
| `p95_seconds` | `data.quantiles.p95` | 95 分位耗时，秒，可省略。 |
| `latency_samples` | `data.duration_count` | 有效耗时样本数，可省略。 |

点号表示逐层取 JSON 对象的键。后台修改字段时在此调整；配置不会将毫秒自动转换为秒。

### `[rules]` 判断参数

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `min_requests` | `100` | 主统计调用量低于此值时待观察，正整数。 |
| `success_rate_min` | `0.70` | 主统计成功率下限，取值 0—1，`0.70` 表示 70%，不能填 `70`。 |
| `max_drop_points` | `10.0` | 相比有效历史基准下降超过多少个百分点时判异常，取值 0—100。 |
| `history_days` | `7` | 搜索有效历史基准的天数，正整数；无基准时只检查固定阈值。 |

当前正式报告隐藏了主统计评估文字，规则仍在内部计算。`success_rate_min` 不控制分组结果的 95% 筛选；渠道前 20、错误码前三、分组低于 95% 都是当前固定展示规则，尚无配置参数。三类结果均使用表格，名称加粗；模型合并为一张带分组列的大表，按分组保留原顺序，名称与分组加粗。整份报告最多三张表；发送器会在本地拒绝超过四张表的正文。

### `[storage]`、`[notification]`

`storage.path` 是 SQLite 文件路径。Docker 模板为 `/var/lib/autolycus/autolycus.db`，Compose 也强制使用此值；Windows 应改为 `data/autolycus.db` 等可写位置。相对路径基于 TOML 所在目录解析。

`notification.enabled=true` 允许发送，但普通 CLI 仍需显式带 `--notify`。容器自动调度要求此值为 `true`；计划入口 `--scheduled` 会发送。暂停自动调度请使用管理脚本 `pause`，不要只改此值。

### `[channel_monitor]`

```toml
[channel_monitor]
enabled = true
path = "/channel_monitor"
```

`enabled` 控制渠道和分组两项补充查询，`path` 为站内路径。程序通过 POST 请求并附加 `Action=Query`；渠道启用错误码统计，分组启用后台重试聚合。

接口仅确认支持滚动范围，不能认为与主性能统计精确对齐。报告显示接口实际区间；修改为更长计划间隔时，还要验证后台是否接受对应滚动长度。

### `[model_performance]` 重点模型名单

模板已预置 24 个目标，默认关闭。核对名称后，将现有 `[model_performance]` 下的 `enabled` 改为 `true` 即可。以下是只保留两个目标的最小示例；若采用示例，请替换整个模型配置段，不要与现有目标重复追加：

```toml
[model_performance]
enabled = true

[[model_performance.targets]]
group = "OpenAI"
model = "gpt-image-2"

[[model_performance.targets]]
group = "Gemini官key"
model = "gemini-3-pro-image"
```

`group`、`model` 必须与后台实际值完全一致，包括空格和后缀。每个目标独立查询，固定使用成功消费日志 `log_type=2`；无成功记录时省略，查询失败会标不可用。模型越多，查询耗时通常越长。

部署模板现已预置 OpenAI、OpenAI 官key、Banana、Gemini官key 共 24 个目标，默认仍为关闭；已有部署不会自动合并模板名单，需要更新实际使用的 `config.toml`。Banana 与 Gemini官key 均包含：`gemini-2.5-flash-image`、`gemini-3-pro-image`、`gemini-3-pro-image-preview`、`gemini-3.1-flash-image`、`gemini-3.1-flash-image-preview`、`gemini-3.1-flash-lite-image`、`gemini-nano-banana-2.1`。报告在同一张表中通过分组列显示归属，无成功记录的模型省略，查询失败仍明确提示。

## 异常数值颜色 `[highlight]`

默认启用飞书卡片数值着色，省略本段也使用以下默认值：

```toml
[highlight]
enabled = true
success_red_below = 70
success_orange_below = 95
p50_orange_above_seconds = 60
p95_orange_above_seconds = 120
latency_red_multiplier = 2
```

- 默认渠道、分组成功率低于 70% 标红，70% 至不足 95% 标橙，恰好 95% 保留默认颜色，超过 95% 标绿；判断使用未四舍五入的次数。自定义红、橙阈值时优先检查这两个阈值，未触发且超过 95% 才标绿。
- 模型 P50 超过 60 秒、P95 超过 120 秒标橙；分别超过 120 秒、240 秒标红。等于橙色阈值不标色，等于红色阈值仍标橙。
- 查询失败、数据不可用、缺失耗时或没有有效耗时样本标红。无成功调用的模型仍省略。
- 这些是初始展示阈值，不是后台 SLA，不改变规则判定、统计口径或分组低于 95% 的筛选。初始延迟阈值统一适用于所有模型。
- `enabled=false` 关闭颜色。成功率阈值使用 0—100，满足红色不大于橙色；延迟阈值为正秒数，红色倍数大于 1。

仅关键数值及不可用提示着色，名称加粗，模型分组标题保留。着色采用飞书扩展 `<font color='red'>` / `<font color='orange'>` / `<font color='green'>` 标签，其他 Markdown 工具不一定支持。定时报告缓存保留生成时的格式和颜色，修改规则不重新渲染已缓存正文。

## 修改汇报时间

所有计划固定北京时间 UTC+8，与宿主机显示时区无关。请显式保留 `[schedule]`：省略会回落到代码中的旧兼容时间表，不是部署模板的整点表。

部署模板：

```toml
[schedule]
weekday_times = ["09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00"]
weekend_times = ["09:00", "12:00", "18:00"]
interval_mode = "planned_chain"
grace_minutes = 10
```

| 参数 | 意义和约束 |
| --- | --- |
| `weekday_times` | 周一至周五每天的计划列表，不是 cron 表达式。 |
| `weekend_times` | 周六、周日每天的计划列表，不识别法定节假日或调休。 |
| `interval_mode` | `planned_chain` 查询上一个计划点至当前计划点；`fixed_1h` 查询当前计划点前一小时。 |
| `grace_minutes` | 允许计划时间后多少分钟内开始执行，整数 0—15，建议保留 10；不是发送延迟或接口超时。 |

时间必须是英文引号包住的 24 小时 `HH:MM`，例如 `"09:30"`，不能写 `"9:30"`。两个时间列表都必须非空且无重复。

例如改成工作日 09:30—17:30 每小时一次，周末每天三次：

```toml
[schedule]
weekday_times = ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30", "17:30"]
weekend_times = ["09:00", "12:00", "18:00"]
interval_mode = "planned_chain"
grace_minutes = 10
```

默认整点表下，周六 09:00 的固定性能范围为周五 18:00—周六 09:00；周日 12:00 为周日 09:00—12:00。即使前一次未实际运行，也从上一个计划点计算，不从上次成功发送时间计算。

修改时间表不会回溯补发，也可能改变历史核对的 `missing` 结果。后台固定查询限制在最近七天内，不应设计跨越七天的区间。

## 修改配置后如何生效

更换 Webhook、时间表或模型名单无需重建镜像。在项目目录执行，仅编辑需要修改的文件：

```bash
sudo bash scripts/linux/manage.sh pause
nano .env
nano config.toml
sudo docker compose config --quiet
```

检查 TOML 与未来七天计划（不查询后台、不发送）：

```bash
sudo docker compose run --rm --no-deps --pull never monitor \
  python -m autolycus --config /etc/autolycus/config.toml --schedule-preview
```

升级后，普通 Compose 命令可能默认选到旧的 `autolycus:local` 镜像；管理脚本会读取 `.deploy/active-image`。若需用当前升级镜像做上述计划预览，在记录文件存在时使用：

```bash
sudo env AUTOLYCUS_IMAGE="$(cat .deploy/active-image)" docker compose run \
  --rm --no-deps --pull never monitor \
  python -m autolycus --config /etc/autolycus/config.toml --schedule-preview
```

再预览真实数据并恢复：

```bash
sudo bash scripts/linux/manage.sh preview
sudo bash scripts/linux/manage.sh resume
sudo bash scripts/linux/manage.sh status
```

`preview` 不发送消息；`resume` 创建或重建服务，应用当前配置。单纯 `docker restart` 不刷新已注入的 `.env`。TOML 保存后也需要重新加载调度进程。cron 恢复时等待下一个触发点，不会仅因仍在宽限窗口内而补执行上一计划；宽限窗口用于限制已触发任务和重试。

## 升级脚本可选参数

下列是宿主升级脚本读取的环境变量，不是 TOML 参数，也不会自动从 `.env` 注入宿主脚本：

| 参数 | 默认 | 作用 |
| --- | --- | --- |
| `AUTOLYCUS_UPGRADE_PROXY` | 不指定 | 给 Git 下载和构建依赖下载使用代理，不能替代 Docker 服务拉取基础镜像的代理配置。 |
| `AUTOLYCUS_BUILD_NETWORK` | `default` | 可取 `default` 或 `host`，只改变构建网络，不改变运行容器网络。 |

按需通过 `sudo env 参数=值 bash scripts/linux/upgrade.sh 版本号` 传入。普通网络无需这些选项，不要求 Clash。

## 常见检查结果

| 结果 | 含义或检查方向 |
| --- | --- |
| `config --quiet` 无输出 | Compose 格式通过，不代表凭据有效、TOML 业务校验通过或后台连通。 |
| 飞书 11246 / 子错误码 11310 | 卡片表格数量超限。v0.2.2 合并模型表；历史缓存旧报告仍可能超限，应预览或检查新计划，不随意强制重发。 |
| HTTP 401 | 核对后台令牌、用户 ID、权限与有效期；令牌不加 `Bearer `。 |
| `通知：未发送（预览模式）` | 预期行为，普通查询未明确要求发送。 |
| `healthy` | cron 调度进程存活，不证明投递成功。 |
| `sent` | 飞书接口确认接收，仍需抽查群消息。 |
| `missing` | 计划无执行记录；关机、暂停、休眠或改时间表均可能造成，不等于执行报错。 |
| 模型未展示 | 可能没有成功消费记录，也应核对分组、模型名称完全一致。 |
