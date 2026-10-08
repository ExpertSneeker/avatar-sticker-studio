# 付款成功自动发货完成通知

来源：https://open.agiso.com/document/#/aldsDoudian/push/payAutoSendCompleted（2026-10-08 抓取的渲染文本）

付款成功后自动发货完成通知

简要描述：  推送示例

￥高级
付款成功后，自动发货完成，推送对应消息。
推送的签名请务必验证，以验证数据来源的合法性。验证方法参考以下说明。
推送时，有可能消息重复推送。实际开发中，请一定要在使用消息前进行去重判断。主要依据是订单编号Tid和订单状态。
推送方式，用jquery做示例：$.post('http://test.com/agiso?timestamp=11222212121&sign=f8aa165fc951f266667e0605d78b93af&aopic=32768', { json: '{"Tid":"592823138",......}' })

推送参数：

参数名	类型	获取方式	说明
fromPlatform
	
string
	
Query/Get
	
参数值：AldsDoudian。常见问题


timestamp
	
Number
	
Query/Get
	
时间戳


aopic
	
Number
	
Query/Get
	
推送类型，16:付款成功后，自动发货完成;


sign
	
String
	
Query/Get
	
签名算法：
   将json和timestamp参数名和参数值组合起来（注意：json在前，timestamp在后），然后前后添加上AppSecret ，再进行Md5加密（加密算法参考接入指南-完整调用API示例代码中MD5算法）。
例：
url：http://test.com/agiso?timestamp=11222212121&sign=f8aa165fc951f266667e0605d78b93af&aopic=256，
postData: { json: {"Tid":2067719225654838,"Status":"WAIT_BUYER_CONFIRM_GOODS",......,"TotalFee":"3.00"} }，
_appsecret: 9f8g9d78sg9d8f8ew9f89ds9f8ds9af8(开发者AppSecret)，
连接后的串: 9f8g9d78sg9d8f8ew9f89ds9f8ds9af8json{"Tid":2067719225654838,"Status":"WAIT_BUYER_CONFIRM_GOODS",......,"TotalFee":"3.00"}timestamp112222121219f8g9d78sg9d8f8ew9f89ds9f8ds9af8
再对连接后的字符串，进行MD5加密，
MD5结果: f8aa165fc951f266667e0605d78b93af（不区分大小写）


json
	
String
	
Form/Post
	
推送消息,如：
{
                "Tid":"2215900041470428",       // 订单号
                "PlatformShopId":"2131430925",  // 店铺Id
                "AldsType":1,                   // 自动发货的类型：1付款后发货、2买家确认收货后、4好评后赠送
                "CreateTime":"2022-08-29T10:12:51", // 原始平台订单创建时间/下单时间。
                "PayTime":"2022-06-08T12:05:52",    // 原始平台付款时间
                "Status":"70",                      // 原始平台订单原始状态
                "Orders":[                          // 子订单列表
                    {
                        "Num":2,                    // 购买数量
                        "GoodsName":"保鲜可抽真空红酒塞不锈钢葡萄酒瓶塞 红酒塞子酒具用品",// 商品名称
                        "GoodsId":"888390669925",   // 原始商品id
                        "OuterGoodsId":null,        // 原始商品外部编码
                        "SkuId":"888390671925",     // 原始商品SkuId
                        "OuterSkuId":"",            // 原始商品外部SkuId
                        "Oid":"2215900041470428",   // 原始商品订单号
                        "SpType":1,                 // 自动发货内容方式：1单卡种、2组合卡、3无卡、4、接口
                        "SpecName":"",              // 原始sku信息
                        "SendCards":[               // 自动发货卡券列表
                            {
                                "Card":"15449",     // 卡号
                                "Pwd":""            // 密码
                            },
                            {
                                "Card":"15450",
                                "Pwd":""
                            }
                        ]
                    }
                ]
            }
