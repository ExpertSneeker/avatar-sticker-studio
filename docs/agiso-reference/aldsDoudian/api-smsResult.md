# 查询短信发送结果

来源：https://open.agiso.com/document/#/aldsDoudian/api/smsResult（2026-10-08 抓取的渲染文本）

短信结果查询

简要描述：  接口调用示例

￥基础
短信结果查询

请求URL：

https://gw-api.agiso.com/aldsDoudian/Sms/SmsResult

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
messageId
	
是
	
string
	
消息Id(对应发送短信接口返回的message_id)


smsAccountType
	
否
	
Int
	
所属关联通道: 0普通短信(默认) 1教育类短信

返回示例


    {
        "isSuccess": true,
        "data": {
            "status_code": "0",                      // 状态码,"0"代表成功
            "description": "发送成功",               // 状态描述
            "signature": "阿奇索",                  // 短信签名
            "template_id": "ST_82aba028",            // 模板ID
            "channel_type": "CN_NTC",                // 短信类型
            "message_id": "226758fc-13e8-4971-a168-98b6beb15447",    // 发送时返回的MessageID
            "msg_count": 2,                          // 计费条数
        },
        "error_Code": 0,
        "error_Msg": ""
    }
