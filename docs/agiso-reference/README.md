# 阿奇索参考资料（本地存档）

2026-10-08 从官方站点抓取的渲染文本，便于离线查阅和代码评审；图片未保存，表格以制表符保留。**以官方页面为准**，接口行为变化时重新抓取并在提交说明中注明。不得在本目录存放 AppSecret、店铺 Token 或真实订单数据。

| 目录 | 来源 | 内容 |
| --- | --- | --- |
| [aldsPdd](aldsPdd/README.md) | https://open.agiso.com/document/#/aldsPdd/guide | 拼多多自动发货（现有接入） |
| [aldsDoudian](aldsDoudian/README.md) | https://open.agiso.com/document/#/aldsDoudian/guide | 抖店自动发货 |
| [aldsXhs](aldsXhs/README.md) | https://open.agiso.com/document/#/aldsXhs/guide | 小红书自动发货 |
| [open](open/README.md) | https://open.agiso.com/document/#/open/guide | 开放平台通用（余额、托管应用） |
| [acpr](acpr/README.md) | https://open.agiso.com/document/#/acpr/guide | 91 卡券仓库接口 |
| [yuque-open](yuque-open/README.md) | https://www.yuque.com/agiso/open | 开放平台帮助（授权、推送权限） |
| [yuque-91kami](yuque-91kami/README.md) | https://www.yuque.com/agiso/91kami | 91 卡券仓库产品手册 |

## 三平台关键差异（摘自上表文档，接入前以真实授权/推送复核）

| 项目 | 拼多多 | 抖店 | 小红书 |
| --- | --- | --- | --- |
| 授权页 | `https://aldsPdd.agiso.com/#/authorize?appId=&state=` | `https://aldsDoudian.agiso.com/#/authorize?…` | `https://aldsXhs.agiso.com/#/authorize?…` |
| 推送 `fromPlatform` | `PddAlds` | `AldsDoudian` | `AldsXhs` |
| 接口网关前缀 | `gw-api.agiso.com/aldsPdd/` | `gw-api.agiso.com/aldsDoudian/` | `gw-api.agiso.com/aldsXhs/` |
| 商品列表 | `Goods/List` | `Product/List` | `Product/GetList` |
| 订单详情 | `Trade/Detail`（本站已用，文档目录未列出） | `Order/Detail` | `Order/Detail` |
| 付款推送 aopic | 1 交易确认 | 1 付款成功 | **4** 付款成功 |
| 退款相关 aopic | 8 退款创建、16 退款成功、512 售后关闭 | 2 发起售后、4 售后关闭、8 退款成功、64/128 同意退货/退款 | 16 申请退款、32 退款成功（无售后关闭推送） |
| 备注修改 aopic | 64 买家备注修改 | 无 | 无 |

注意：

- 推送类型编号**各平台不同**，必须先按 `fromPlatform` 区分平台再解释 `aopic`；签名方式相同（`AppSecret + json… + timestamp… + AppSecret` 的 MD5）。
- 抖店付款推送只有父订单 `p_id`、子订单列表 `s_ids`、店铺 `shop_id`、状态和实付金额（分），**不含商品/SKU**；自动开户需再调 `Order/Detail` 取规格。父子订单要按父订单去重为一个客户订单。
- 抖店在服务市场有两个应用：自动发货 `aldsDoudian.agiso.com` 与虚拟自动发货 `aldsdd.agiso.com`，接入的是前者。
- 各平台接口调用配额与收费见各目录 `feeStandrd.md`。
