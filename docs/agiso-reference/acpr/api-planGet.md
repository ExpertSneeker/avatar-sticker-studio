# 获取发卡方案详情

来源：https://open.agiso.com/document/#/acpr/api/planGet（2026-10-08 抓取的渲染文本）

获取发卡方案详情

简要描述：  接口调用示例

￥基础
获取发卡方案详情

请求URL：

https://gw-api.agiso.com/acpr/Sendcardplan/Get

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
idNo
	
是
	
Long
	
发卡方案idNo

返回示例


          {
            "IsSuccess": true,
            "Data": {
              "IdNo": 187, 
              "Title": "按数量区间组合",
              "PlanType": 2, // 发卡方案类型 
              "PlanJson": "[{"Interval":{"S":1,"E":1},"GroupCard":[{"Denom":2.0,"Num":1,"CalcType":1,"CpkId":692},{"Denom":1.0,"Num":1,"CalcType":1,"CpkId":693}]}]", // 发卡方案Json字符串数据结构 
              "CardKindIds": ",692,693,", // 卡种Id 
              "CreateTime": "2023-01-29 09:40:43",
              "ModifyTime": "2023-01-29 11:50:49",
              "ShowName": "按数量区间组合"
          },
            "Error_Code": 0,
            "Error_Msg": "",
            "AllowRetry": null,
            "RequestId": "20230108142251106"
          }
          

备注

发卡方案类型：0:组合卡、1:按数量组合、2:按数量区间组合、3:按地址组合、4:按留言组合、4:多组合顺序选一、5:多组合随机选一
