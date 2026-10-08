# 售后商家填写物流信息

来源：https://open.agiso.com/document/#/aldsDoudian/api/afterSaleFillLogistics（2026-10-08 抓取的渲染文本）

售后商家填写物流信息

简要描述：  接口调用示例

￥基础
适用场景：
send_type=1：用于补寄商家发货
send_type=3：超市预约上门取货；退货退款和换货场景下商家帮买家填写退货物流信息；
send_type=4：维修场景下商家帮买家填写退货物流信息；

请求URL：

https://gw-api.agiso.com/aldsDoudian/Order/AfterSaleFillLogistics

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
aftersaleId
	
是
	
Long
	
售后单ID


sendType
	
是
	
int
	
发货类型；适用场景： send_type=1：用于补寄商家发货 send_type=3：超市预约上门取货；退货退款和换货场景下商家帮买家填写退货物流信息； send_type=4：维修场景下商家帮买家填写退货物流信息；


companyCode
	
是
	
String
	
物流公司编号 pick_up_type 2:线下取货;3:用户退回，无需物流公司，可传 -


trackingNo
	
是
	
String
	
物流单号 pick_up_type 2:线下取货;3:用户退回，无需快递单号，可传 -


bookTimeBegin
	
否
	
Long
	
预约上门取货时间戳，单位：秒（目前抖超小时达店铺使用）


bookTimeEnd
	
否
	
Long
	
预约上门取货时间戳，单位：秒（目前抖超小时达店铺使用）


storeId
	
否
	
String
	
门店Id


pickUpType
	
否
	
Int
	
1:自行配送;2:线下取货;3:用户退回 ，不传默认自行配送；适用于send_type=3超市预约上门取货场景(不传默认是:1)

返回示例


    {
      "IsSuccess": true,
      "Data": null
      "Error_Code": 0,
      "Error_Msg": ""
      "AllowRetry": null,
      "RequestId": "20221027142251106"
    }
