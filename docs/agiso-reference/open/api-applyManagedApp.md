# 申请电商业务【托管中】应用

来源：https://open.agiso.com/document/#/open/api/applyManagedApp（2026-10-08 抓取的渲染文本）

申请电商业务【托管中】应用

简要描述：  接口调用示例

￥基础
申请电商业务【托管中】应用

请求URL：

https://gw-api.agiso.com/open/AppManage/ApplyManagedApp

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
appName
	
是
	
String
	
应用名称


description
	
否
	
String
	
应用描述


callBackUrl
	
否
	
String
	
授权回调地址


website
	
否
	
String
	
应用网址（官网）


ips
	
否
	
String
	
IP白名单，多个IP之间用逗号“,”分隔


notifyUrl
	
否
	
String
	
通知推送地址（订单付款等消息推送）


allowHandAuth
	
否
	
Boolean
	
是否允许自动发货后台进行手动授权。

返回示例


    {
      "IsSuccess": true,
      "Data":// 应用信息
      {
        "AppName": "应用名称",
        "AppId": 123456789,// 应用ID
        "AppSecret": "xxxxxxxxx",// secret
        "Description": "应用描述",
        "CallBackUrl": "http://xxx.com/yy",//授权回调地址
        "Website": "http://xxx.com", // 应用网址（官网）
        "Ips": "192.168.0.1,192.168.0.2", // IP白名单，多个IP之间用逗号“,”分隔
        "NotifyUrl": "http://xxx.com/noti",//通知推送地址（订单付款等消息推送）
        "AllowHandAuth": true // 是否允许自动发货后台进行手动授权
      },
      "Error_Code": 0,
      "Error_Msg": "",
      "AllowRetry": null,
      "RequestId": "2023022717413855"
    }
