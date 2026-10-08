# 删除标准货源系统供货商

来源：https://open.agiso.com/document/#/open/api/deleteProvider（2026-10-08 抓取的渲染文本）

删除标准系货源统供应商

简要描述：  接口调用示例

￥免费
无需授权
删除标准货源系统供货商

请求URL：

https://gw-api.agiso.com/open/ProviderManage/DeleteProvider

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
providerIds
	
是
	
List<String>
	
供应商Ids,传参示例:["6b993af435814747bdebc7b0ccb8ea82","6b993af435814747bdebc7b0ccb8ea83"]

返回示例


    {
        "IsSuccess": true,
        "Data": null,
        "Error_Code": 0,
        "Error_Msg": "",
        "AllowRetry": null,
        "RequestId": null
    }
