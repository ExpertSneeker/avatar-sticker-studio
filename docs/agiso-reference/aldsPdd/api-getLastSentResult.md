# 获取最近一笔发送的卡密

来源：https://open.agiso.com/document/#/aldsPdd/api/getLastSentResult（2026-10-08 抓取的渲染文本）

获取最近一笔发送的卡密

简要描述：  接口调用示例

￥基础
根据订单号获取最近一笔发送的卡密

请求URL：

https://gw-api.agiso.com/aldsPdd/Cpd/GetLastSentResult

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


aldsType
	
是
	
Int
	
自动发货类型，具体查看底部备注

返回示例


    {
        "isSuccess": true,
        "data": [
          {
            "title": "唯一卡别名",
            "cardPwdArr": [
              {
                "c": "10000004806",
                "p": ""
              },
              {
                "c": "10000004807",
                "p": ""
              }
            ]
          },
          {
            "title": "图片卡种",
            "cardPwdArr": [
              {
                "c": "http://imgcp.91kami.com/54/201908/c634af0498214e86bb0ec2f6fad5188b.png"
              }
            ]
          }
        ],
        "error_Code": 0,
        "error_Msg": ""
      }
    

返回参数说明

参数名	类型	说明
title
	
String
	
卡种名称


cardPwdArr
	
Array
	
卡密数组


c
	
String
	
卡号


p
	
String
	
卡券

备注

aldsType自动发货类型：付款后发货=1，确认收货后赠送=2
