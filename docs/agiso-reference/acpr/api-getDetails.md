# 获取卡种详情

来源：https://open.agiso.com/document/#/acpr/api/getDetails（2026-10-08 抓取的渲染文本）

获取卡种详情

简要描述：  接口调用示例

￥基础
获取卡种详情

请求URL：

https://gw-api.agiso.com/acpr/CardPwdKind/GetDetails

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

返回示例


          {
            "IsSuccess": true,
            "Data": {
              "IdNo": 32,
              "Title": "京东激活码",
              "AliasName": null,
              "ClassId": 0,
              "Sort": 0,
              "WarningNum": 5,
              "TotalCount": 3,
              "UsedCount": 1,
              "CardType": 800,
              "CardNoShowType": 0,
              "PwdShowType": 0,
              "ShowTpl": "{卡号}",
              "PrefixCardNo": "",
              "PrefixPwd": "",
              "SplitCardPwd": null,
              "PurPrice": 0.00000000,
              "ModifyTime": "2017-12-07T16:59:54",
              "CreateTime": "2017-12-07T16:40:59"
            },
            "Error_Code": 0,
            "Error_Msg": "",
            "AllowRetry": null,
            "RequestId": "20211122942251106"
          }
          

返回参数说明

参数名	类型	说明
IdNo
	
Long
	
Id


title
	
String
	
卡种名称


AliasName
	
String
	
卡种别名


ClassId
	
Long
	
卡种分类


Sort
	
Int
	
排序


WarningNum
	
Int
	
预警数量


TotalCount
	
Int
	
总数量


UsedCount
	
Int
	
已用数量


CardType
	
Long
	
卡种类型


CardNoShowType
	
Int
	
卡号显示类型


PwdShowType
	
Int
	
密码显示类型


ShowTpl
	
String
	
显示模板


PrefixCardNo
	
String
	
卡号前缀


PrefixPwd
	
String
	
密码前缀


SplitCardPwd
	
String
	
分隔符


PurPrice
	
Decimal
	
成本单价


ModifyTime
	
String
	
修改时间


CreateTime
	
String
	
创建时间

备注

卡种类型：700:循环卡、800:套卡、820:唯一卡、840:重复卡、850:图片卡


卡号及密码显示类型：0:文本、1:条形码、2:二维码、4:条形码+二维码
