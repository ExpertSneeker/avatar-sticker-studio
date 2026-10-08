# 发卡方案提卡

来源：https://open.agiso.com/document/#/acpr/api/planHandPick（2026-10-08 抓取的渲染文本）

发卡方案提卡

简要描述：  接口调用示例

￥高级
发卡方案提卡

请求URL：

https://gw-api.agiso.com/acpr/SendCardPlan/HandPick

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


buyer
	
否
	
String
	
买家名称


spId
	
是
	
Long
	
发卡方案idNo


num
	
是
	
Number
	
数量


payment
	
是
	
Decimal
	
金额


keyword
	
否
	
String
	
关键词，根据发卡方案类型（按地址组合、按留言组合）传值

返回示例


          {
            "IsSuccess": true,
            "Data": [
              {
                  "CardNoShowType": 0,  // 卡号展示类型 
                  "PwdShowType": 0,     // 卡密展示类型 
                  "PrefixCardNo": "卡号：", // 卡号前缀 
                  "PrefixPwd": "密码：",  // 卡密前缀 
                  "Title": "n1",  // 卡种名称 
                  "CpkId": 729,   // 卡种ID 
                  "CardPwdArr": [ // 卡号卡密数组 
                      {
                          "c": "【3】卡号：1000", // 卡号 
                          "p": ""                // 卡密 
                      },
                      {
                          "c": "【4】卡号：1000",
                          "p": ""
                      }
                  ]
              },
              {
                  "CardNoShowType": 0,
                  "PwdShowType": 0,
                  "PrefixCardNo": "卡号：",
                  "PrefixPwd": "密码：",
                  "Title": "n2",
                  "CpkId": 730,
                  "CardPwdArr": [
                      {
                          "c": "【6】卡号：2000",
                          "p": ""
                      },
                      {
                          "c": "【7】卡号：2000",
                          "p": ""
                      },
                      {
                          "c": "【8】卡号：2000",
                          "p": ""
                      },
                      {
                          "c": "【9】卡号：2000",
                          "p": ""
                      }
                  ]
              }
          ],
            "Error_Code": 0,
            "Error_Msg": "",
            "AllowRetry": null,
            "RequestId": "20230108142251106"
          }
          

备注

发卡方案类型：0:组合卡、1:按数量组合、2:按数量区间组合、3:按地址组合、4:按留言组合、4:多组合顺序选一、5:多组合随机选一
