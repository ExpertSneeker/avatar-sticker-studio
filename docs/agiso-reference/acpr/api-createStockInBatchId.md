# 创建入库批次号

来源：https://open.agiso.com/document/#/acpr/api/createStockInBatchId（2026-10-08 抓取的渲染文本）

创建入库批次号

简要描述：  接口调用示例

￥基础
加卡需先创建入库批次号，批次号有效时间为30分钟。详见「加卡」接口文档。

请求URL：

https://gw-api.agiso.com/acpr/CardPwd/CreateStockInBatchId

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
cpkId
	
是
	
Long
	
卡种Id


price
	
否
	
Decimal
	
成本单价


summary
	
否
	
String
	
批次描述

返回示例


          {
            "IsSuccess": true,
            "Data": "fe71483c21a846b58e0c369224eee38f",
            "Error_Code": 0,
            "Error_Msg": "",
            "AllowRetry": null,
            "RequestId": "20211108142251106"
          }
          

返回参数说明

参数名	类型	说明
Data
	
String
	
批次号
