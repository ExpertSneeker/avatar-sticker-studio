# 更新发卡方案

来源：https://open.agiso.com/document/#/acpr/api/planUpdate（2026-10-08 抓取的渲染文本）

更新发卡方案

简要描述：  接口调用示例

￥基础
更新发卡方案

请求URL：

https://gw-api.agiso.com/acpr/SendCardPlan/Update

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
IdNo
	
是
	
Long
	
发卡方案IdNo


PlanJson
	
是
	
String
	
JSON数据结构（根据PlanType类型）字符串，可参考发卡方案列表接口示例


Title
	
是
	
String
	
发卡方案名称


AliasName
	
否
	
String
	
别名

返回示例


          {
            "IsSuccess": true,
            "Error_Code": 0,
            "Error_Msg": "",
            "AllowRetry": null,
            "RequestId": "20230108142251106"
          }
