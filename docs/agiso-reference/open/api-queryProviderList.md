# 查询标准货源系统供货商列表

来源：https://open.agiso.com/document/#/open/api/queryProviderList（2026-10-08 抓取的渲染文本）

查询标准货源系统供货商列表

简要描述：  接口调用示例

￥免费
无需授权
查询目前在用的标准系统供货商列表

请求URL：

https://gw-api.agiso.com/open/ProviderManage/QueryProviderList

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
name
	
否
	
String
	
供应商名称


host
	
否
	
String
	
供应商域名


page
	
否
	
Int
	
页码(默认1),


pageSize
	
否
	
Int
	
条数(默认20)

返回示例


    {
        "IsSuccess": true,
        "Data": {
            "List": [
                {
                    "Id": "0dacb2b393f241e1afceb3ccb55f7fb4",   // 供应商ID
                    "PackageId": "Standard",
                    "Name": "测试的货源1",              // 供应商名称
                    "Host": "http://www.xxx.com1",     // 供应商域名
                    "Phone": "18759385712",            // 联系方式
                    "AppId": 20000,                    // 开发者AppId
                    "Remark": null,
                    "ProviderId": "0dacb2b393f241e1afceb3ccb55f7fb4",  // 供应商ID
                    "ProviderGuid": "ced0a29316d443098b98f09f463f62d3", // 授权Id,提供给商家添加货源
                    "CreateUser": "开发者",
                    "CreateTime": "2026-07-29T17:46:17",
                    "ModifyUser": "开发者",
                    "ModifyTime": "2026-07-29T17:51:59"
                },
            ],
            "TotalCount": 6,
            "Extend": null,
            "PageNo": 1,
            "PageSize": 2
        },
        "Error_Code": 0,
        "Error_Msg": "",
        "AllowRetry": null,
        "RequestId": null
    }
