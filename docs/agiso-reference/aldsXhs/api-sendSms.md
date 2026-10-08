# 发送短信

来源：https://open.agiso.com/document/#/aldsXhs/api/sendSms（2026-10-08 抓取的渲染文本）

发送短信

简要描述：  接口调用示例

￥基础
根据订单号，发送短信

请求URL：

https://gw-api.agiso.com/aldsXhs/Sms/SendSms

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


templateId
	
是
	
Long
	
模板Id(Sms/GetSmsTemplates接口返回的Id)


templateParam
	
是
	
string
	
模板参数,替换短信模板里的占位符，示例:短信模板内容为：订单尾号${orderSn}已发货，卡号：${cardNo}。请妥善保管，传递：{'orderSn':'123','cardNo':'xxx'}会将对应的占位符替换，输出内容：订单尾号123已发货，卡号：xxx。请妥善保管

返回示例


    {
        "isSuccess": true,
        "data": {
            "message_id": "897223057406534192^0", // 调用短信接口成功返回的消息Id
            "success": true // 是否调用成功
        },
        "error_Code": 0,
        "error_Msg": ""
    }
