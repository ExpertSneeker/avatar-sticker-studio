# 获取发卡方案列表

来源：https://open.agiso.com/document/#/acpr/api/planGetlist（2026-10-08 抓取的渲染文本）

获取发卡方案列表

简要描述：  接口调用示例

￥基础
获取发卡方案列表

请求URL：

https://gw-api.agiso.com/acpr/SendCardPlan/getlist

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
	
默认20


filterName
	
否
	
String
	
发卡方案名称

返回示例


          {
            "IsSuccess": true,
            "Data": {
              "List": [
                {
                    "IdNo": 193,
                    "Title": "多组合随机选一",
                    "PlanType": 6,
                    "PlanJson": "[[{"Name":"n1","GroupCard":[{"Denom":1.0,"CpkId":721}]}],[{"Name":"n2","GroupCard":[{"Denom":1.0,"CpkId":720}]}]]", // 多组合随机选一 Json字符串数据结构 
                    "CardKindIds": ",721,720,",
                    "CreateTime": "2023-03-21 10:38:37",
                    "ModifyTime": "2023-03-21 10:41:49",
                    "ShowName": "多组合随机选一"
                },
                {
                    "IdNo": 192,
                    "Title": "多组合顺序选一",
                    "PlanType": 5,
                    "PlanJson": "[[{"Name":"n1","GroupCard":[{"Denom":1.0,"CpkId":716}]}],[{"Name":"n2","GroupCard":[{"Denom":1.0,"CpkId":714}]}]]", // 多组合顺序选一 Json字符串数据结构 
                    "CardKindIds": ",716,714,",
                    "CreateTime": "2023-03-21 10:32:07",
                    "ShowName": "多组合顺序选一"
                },
                {
                    "IdNo": 191,
                    "Title": "按留言组合",
                    "PlanType": 4,
                    "PlanJson": "[{"Keyword":"ka1","Pri":1,"GroupCard":[{"Denom":1.0,"CpkId":721}]}]", // 按留言组合 Json字符串数据结构 
                    "CardKindIds": ",721,",
                    "CreateTime": "2023-03-21 10:30:14",
                    "ShowName": "按留言组合"
                },
                {
                    "IdNo": 190,
                    "Title": "按地址",
                    "PlanType": 3,
                    "PlanJson": "[{"Keyword":"厦门","Pri":1,"GroupCard":[{"Denom":1.0,"CpkId":719}]},{"Keyword":"福州","Pri":2,"GroupCard":[{"Denom":1.0,"CpkId":721}]}]", // 按地址 Json字符串数据结构 
                    "CardKindIds": ",719,721,",
                    "CreateTime": "2023-03-21 10:28:25",
                    "ShowName": "按地址"
                },
                {
                    "IdNo": 189,
                    "Title": "按数量组合",
                    "PlanType": 1,
                    "PlanJson": "[{"BuyNum":1,"GroupCard":[{"Num":1,"CpkId":721},{"Num":1,"CpkId":719}]}]", // 按数量组合 Json字符串数据结构 
                    "CardKindIds": ",721,719,",
                    "CreateTime": "2023-03-21 10:19:06",
                    "ShowName": "按数量组合"
                },
                {
                    "IdNo": 188,
                    "Title": "普通组合",
                    "PlanType": 0,
                    "PlanJson": "[{"Denom":1.0,"CpkId":721},{"Denom":2.0,"CpkId":720}]", // 普通组合 Json字符串数据结构 
                    "CardKindIds": ",721,720,",
                    "CreateTime": "2023-03-21 10:18:25",
                    "ShowName": "普通组合"
                },
                {
                    "IdNo": 187,
                    "Title": "按数量区间组合",
                    "PlanType": 2,
                    "PlanJson": "[{"Interval":{"S":1,"E":1},"GroupCard":[{"Denom":2.0,"Num":1,"CalcType":1,"CpkId":692},{"Denom":1.0,"Num":1,"CalcType":1,"CpkId":693}]}]", // 按数量区间组合 Json字符串数据结构 
                    "CardKindIds": ",692,693,",
                    "CreateTime": "2023-01-29 09:40:43",
                    "ModifyTime": "2023-01-29 11:50:49",
                    "ShowName": "按数量区间组合"
                }
            ],
            "TotalCount": 7,
            "PageNo": 1,
            "PageSize": 20
          },
            "Error_Code": 0,
            "Error_Msg": "",
            "AllowRetry": null,
            "RequestId": "20230108142251106"
          }
          

备注

发卡方案类型：0:组合卡、1:按数量组合、2:按数量区间组合、3:按地址组合、4:按留言组合、4:多组合顺序选一、5:多组合随机选一
PlanJson对象属性说明： CpkId：卡种Id； Denom：发货倍数； Num：实发数量； CalcType：数量计算方式，1：按发货倍数计算（Denom）2：按实发数量计算（Num）； Interval：数量区间， Interval.S：区间起始数量、Interval.E：区间结束数量； Pri：优先级；
