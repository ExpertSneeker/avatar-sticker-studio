# 提卡

来源：https://open.agiso.com/document/#/acpr/api/handPick（2026-10-08 抓取的渲染文本）

提卡

简要描述：  接口调用示例

￥高级
提卡

请求URL：

https://gw-api.agiso.com/acpr/CardPwd/HandPick

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


num
	
是
	
Int
	
提卡数量


handPickOrderId
	
是
	
String
	
接入方订单编号


buyer
	
否
	
String
	
买家名称


buildCpd
	
否
	
Bool
	
生成完整卡券提取链接，默认False


usePriority
	
否
	
Bool
	
优先出库标识为“优先出售”的卡密，默认True

返回示例


      {
        "IsSuccess": true,
        "Data": {
          // buildCpd传true时返回
          "CpdUrl": "https://mai.91kami.com/cpd/lu3hmk684kfch1n9wfauphnkx7eyrncqf78a39462da14270bd8666333404d81b.aspx" 
          //buildCpd传false时返回
          "CardPwdArr": [
            {
              "c": "xx003",              // 卡号
              "p": "123",                // 密码
              "d": "2024-11-21 23:59:59" // 到期时间
            }
          ]
        },
        "Error_Code": 0,
        "Error_Msg": "",
        "AllowRetry": null,
        "RequestId": "20211108142251106"
      }
      

返回参数说明

参数名	类型	说明
CpdUrl
	
String
	
请求参数 “buildCpd” 为 true 返回链接地址


CardPwdArr
	
String
	
请求参数 “buildCpd” 为 false 时返回卡密信息集合如：[ {"c":"卡号1", "p":"密码1", "d":"2024-11-15 23:59:59"},{"c":"卡号2", "p":"密码3", "d":"2024-11-15 23:59:59"} ]
