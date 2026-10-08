# 一单多包发货

来源：https://open.agiso.com/document/#/aldsDoudian/api/logisticsAddMultiPack（2026-10-08 抓取的渲染文本）

一单多包发货

简要描述：  接口调用示例

￥基础
一单多包发货

请求URL：

https://gw-api.agiso.com/aldsDoudian/Order/LogisticsAddMultiPack

请求方式：

POST

公共Header：

参数名	必选	类型	说明
Authorization
	
是
	
string
	
httpPost.addHeader("Authorization","Bearer "+ accessToken)


ApiVersion
	
是
	
string
	
httpPost.addHeader("ApiVersion", "1")


Content-Type
	
是
	
string
	
值必须为：application/x-www-form-urlencoded

公共参数：

参数名	必选	类型	说明
timestamp
	
是
	
Date
	
时间戳，例如：1468476350。API服务端允许客户端请求最大时间误差为10分钟。


sign
	
是
	
string
	
API输入参数签名结果,签名算法参照下面的介绍。

参数：

参数名	必选	类型	说明
tid
	
是
	
string
	
订单号


requestId
	
是
	
string
	
请求唯一标识(一个guid)，相同request_id多次请求，第一次请求成功后，后续的请求会触发幂等，会直接返回第一次请求成功的结果，不会实际触发发货。格式：1267250f-8b9d-4d9e-9fad-0cd9629c83de


packParam
	
是
	
string
	
包裹参数(内容:一个包裹含一个物流单号和单个/多个子订单号，单次请求包裹数过多容易引发超时，建议拆单数量不要超过20)，josn格式, 注意：反序列化后是List<>格式，例：[{"logistics_code":"SF1234567891011","company_code":"shunfeng","shipped_order_info":[{"shipped_order_id":"6932769172126242331","shipped_num":1}]}]

返回示例


    {
        "isSuccess": true,
        "data": {
            "pack_list": [                                  // 包裹信息 
                {
                    "logistics_code": "SF1234567891011",    // 物流单号 
                    "shipped_order_info": [                 // 发货的订单信息 
                        {
                            "shipped_order_id": "6932769172126242331",  // 发货的子订单id 
                            "shipped_num": 1,                           // 发货的子订单数量 
                            "shipped_item_ids": []                      // 发货的四层单id 
                        }
                    ],
                    "pack_id": "7398056775972421900"                    // 包裹id 
                }
            ]
        },
        "error_Code": 0,
        "error_Msg": ""
    }
