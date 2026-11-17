# Autolycus

一个通过后台HTTP接口采集运行指标、生成报告并发送飞书通知的巡检工具。

## 运行方式

同一套业务代码支持Windows任务计划和Ubuntu 22.04上的Docker容器。两台机器不要同时开启实际发送。

- [Ubuntu部署、升级、备份和回退](docs/DEPLOYMENT.md)
- [Windows兼容与新安装](docs/WINDOWS.md)
- [结构及验证边界](docs/ARCHITECTURE.md)

## Windows开发验证

```powershell
python -m pip install -e '.[dev]'
python -X utf8 -m pytest -q
python -X utf8 run.py --demo normal
```

演示不会访问真实后台或发送消息。原本机配置与加密凭据继续保留，但不属于可发布源码。

## Ubuntu部署

填写本地.env和config.toml后：

```bash
sudo bash scripts/linux/deploy.sh
sudo bash scripts/linux/manage.sh preview
sudo bash scripts/linux/manage.sh status
```

部署会启用计划发送；应先完成本地配置检查并暂停另一个发送端。时间按北京时间：工作日09:00至18:00整点，周末09:00/12:00/18:00。渠道接口的滚动时间范围与性能固定区间分别标注。

## 源码交付

```powershell
python -X utf8 scripts/prepare-source.py
```

生成data/Autolycus-source.zip，不包括真实配置、密钥、运行数据或本地历史材料。先审阅再提交自己的Git仓库。当前尚未进行Ubuntu实机部署验收。
