# 发送短信

来源：https://open.agiso.com/document/#/aldsDoudian/api/smsSend（2026-10-08 抓取的渲染文本）

发送短信

简要描述：  接口调用示例

￥基础
根据订单号发送短信(支持多个)

请求URL：

https://gw-api.agiso.com/aldsDoudian/Sms/Send

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
orderIds
	
是
	
String
	
订单号，多个订单号用半角逗号分隔。（示例：440518076xxxxxx,440518076xxxxxx）


templateId
	
是
	
String
	
短信模板Id


templateParam
	
否
	
JSON
	
模板参数,替换短信模板里的占位符，示例:短信模板内容为：订单号：${orderId}，传递：{“orderId”:"123"}会将对应的占位符替换，输出内容：订单号：123


signName
	
否
	
String
	
指定发送短信时使用的签名，默认取最早有效签名


smsAccountType
	
否
	
Int
	
所属关联通道: 0普通短信(默认) 1教育类短信

返回示例


    {
        "isSuccess": true,
        "data": [
            {
                "message_id": "",
                "code": 628003202,
                "message": "该商家向该手机号发送短信条数已达到限制: 187xxx"
            },
            {
                "message_id": "112cb8e3-debc-4a12-b669-d1dde1e120c7",
                "code": 0,
                "message": ""
            }
        ],
        "error_Code": 0,
        "error_Msg": ""
    }
