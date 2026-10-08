# 获取卡种列表

来源：https://open.agiso.com/document/#/acpr/api/getList（2026-10-08 抓取的渲染文本）

获取卡种列表

简要描述：  接口调用示例

￥基础
获取卡种列表

请求URL：

https://gw-api.agiso.com/acpr/CardPwd/GetList

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
pageIndex
	
是
	
Long
	
页码默认 1


pageSize
	
是
	
Long
	
默认100，最大100


filterName
	
否
	
String
	
卡种名称，支持模糊匹配


classId
	
否
	
Int
	
卡种分类Id

返回示例


        {
          "IsSuccess": true,
          "Data": {
            {
              "List":[
                {
                  "IdNo":123110,
                  "CardType":820,
                  "Title":"测试Jd",
                  "RemainingCount":13,
                  "UsedCount":1,
                  "TotalCount":14,
                  "CreateTime":"2021-06-15 18:43:16",
                  "PurPrice":"1"
                }
              ],
              "TotalCount":65,
              "PageNo":1,
              "PageSize":20
            }
          },
          "Error_Code": 0,
          "Error_Msg": "",
          "AllowRetry": null,
          "RequestId": "20211108142251106"
        }
        

返回参数说明

参数名	类型	说明
IdNo
	
Long
	
Id


CardType
	
Long
	
卡种类型


title
	
String
	
卡种名称


RemainingCount
	
Int
	
库存


UsedCount
	
Int
	
已用数量


TotalCount
	
Int
	
总数量


CreateTime
	
String
	
创建时间


PurPrice
	
Decimal
	
成本单价

备注

卡种类型：700:循环卡、800:套卡、820:唯一卡、840:重复卡、850:图片卡
