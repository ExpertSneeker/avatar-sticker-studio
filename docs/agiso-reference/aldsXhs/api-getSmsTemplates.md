# 获取短信发送模板

来源：https://open.agiso.com/document/#/aldsXhs/api/getSmsTemplates（2026-10-08 抓取的渲染文本）

查询短信模板

简要描述：  接口调用示例

￥基础
查询可用的短信模板

请求URL：

https://gw-api.agiso.com/aldsXhs/Sms/GetSmsTemplates

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
No Data

返回示例


        {
          "isSuccess": true,
          "data": [
            {
              "id": 3, // 发送短信时,使用的模板ID
              "name": "卡号场景",
              "tpl_type": 1, // 0:发提取网站,1:发卡号,2:发卡号和密码
              "tpl_content": "订单尾号{#订单尾号}已发货，卡号：{#卡号}。请妥善保管(公共模版)",
              "platform_tpl_content": "订单尾号#{orderSn}已发货，卡号：#{cardNo}。请妥善保管", // 实际发送的内容(调用发送短信接口是使用文本里对应的参数传值:orderSn,cardNo)
              "create_time": "2025-07-04 14:47:32"
            },
            {
              "id": 4, // // 发送短信时,使用的模板ID
              "name": "卡号和卡密场景",
              "tpl_type": 2, // 0:发提取网站,1:发卡号,2:发卡号和密码
              "tpl_content": "订单尾号{#订单尾号}已发货，卡号：{#卡号}。请妥善保管(公共模版)",
              "platform_tpl_content": "订单尾号#{orderSn}的卡号：#{cardNo} 密码：#{pwd} 请妥善保管", // 实际发送的内容(调用发送短信接口是使用文本里对应的参数传值:orderSn,cardNo,pwd)
              "create_time": "2025-07-04 14:47:32"
            }
          ],
          "error_Code": 0,
          "error_Msg": ""
        }
