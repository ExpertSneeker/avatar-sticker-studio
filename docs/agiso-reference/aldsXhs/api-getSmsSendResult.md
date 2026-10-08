# 查询短信发送结果

来源：https://open.agiso.com/document/#/aldsXhs/api/getSmsSendResult（2026-10-08 抓取的渲染文本）

获取短信发送结果

简要描述：  接口调用示例

￥基础
根据订单号，获取短信发送结果

请求URL：

https://gw-api.agiso.com/aldsXhs/Sms/GetSmsSendResult

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
	
String
	
订单号

返回示例


    {
        "isSuccess": true,
        "data": [
            {
                "send_time": "2025-09-09 16:28:54",                                         // 发送时间
                "sms_content": "【阿奇索】订单尾号123已发货，提取网址：http://91kami.cn/xxss", // 短信内容
                "status": "3",                                                              //未回执：1 发送失败：2 发送成功：3
                "count": "1",                                                               // 计费条数，如果短信过长，会分多次计费
                "code": "DELIVERED",                                                        //错误码
                "message": "DELIVERED",                                                     // 错误说明
                "message_id": "897223057406534192^0",                                       // message_id
                "phone": "187****5711",                                                     // 手机号
                "tag": "xhs_3587c6da8674"                                                   // 透传字段
            }
        ],
        "error_Code": 0,
        "error_Msg": ""
    }
