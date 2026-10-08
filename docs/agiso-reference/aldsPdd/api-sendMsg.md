# 消息发送

来源：https://open.agiso.com/document/#/aldsPdd/api/sendMsg（2026-10-08 抓取的渲染文本）

消息发送

简要描述：  接口调用示例

￥高级
发送聊天窗口消息（需要开拼多多助手，每笔订单30天内只能发送5条消息）

请求URL：

https://gw-api.agiso.com/aldsPdd/ImMsg/SendMsg

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


msg
	
是
	
String
	
消息内容

返回示例


    {
      "IsSuccess": true,
      "Data": null
      "Error_Code": 0,
      "Error_Msg": ""
      "AllowRetry": null,
      "RequestId": "20201027142251106"
    }
