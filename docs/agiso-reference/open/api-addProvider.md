# 新增标准货源系统供货商

来源：https://open.agiso.com/document/#/open/api/addProvider（2026-10-08 抓取的渲染文本）

新增标准货源系统供应商

简要描述：  接口调用示例

￥免费
无需授权
新增标准货源系统供货商

请求URL：

https://gw-api.agiso.com/open/ProviderManage/AddProvider

请求方式：

POST

公共Header：

参数名	必选	类型	示例
ApiVersion
	
是
	
string
	
httpPost.addHeader("ApiVersion", "1")

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


appId
	
是
	
string
	

参数：

参数名	必选	类型	说明
providerName
	
是
	
String
	
供应商名称


providerHost
	
是
	
String
	
供应商域名


providerPhone
	
否
	
String
	
供应商手机号


remark
	
否
	
String
	
备注

返回示例


    {
        "IsSuccess": true,
        "Data": "6b993af435814747bdebc7b0ccb8ea82", // 供应商ID
        "Error_Code": 0,
        "Error_Msg": "",
        "AllowRetry": null,
        "RequestId": null
    }
