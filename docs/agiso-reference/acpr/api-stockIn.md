# 加卡

来源：https://open.agiso.com/document/#/acpr/api/stockIn（2026-10-08 抓取的渲染文本）

加卡

简要描述：  接口调用示例

￥基础
用于添加卡密。该功能需配合「创建入库批次号」接口使用

请求URL：

https://gw-api.agiso.com/acpr/CardPwd/StockIn

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
stockInBatchId
	
是
	
String
	
入库批次号


data
	
是
	
String
	
卡券内容，内容格式需要根据卡种类型，具体查看备注


isUseFirst
	
否
	
Bool
	
优先出售


allowReplace
	
否
	
Bool
	
覆盖已存在的


expireTime
	
否
	
String
	
注：卡种开启到期日时必填，其他忽略

返回示例


        {
          "IsSuccess": true,
          "Data": {
            "AddFailCount": 0,
            "AddSuccessCount": 2,
            "ReplaceSoldSuccessCount": 0,
            "ReplaceUnSoldSuccessCount": 0,
            "ResultMsg": ""
          },
          "Error_Code": 0,
          "Error_Msg": "",
          "AllowRetry": null,
          "RequestId": "20211108142251106"
        }
        

返回参数说明

参数名	类型	说明
AddFailCount
	
Int
	
添加失败数量


AddSuccessCount
	
String
	
添加成功数量


ReplaceSoldSuccessCount
	
String
	
覆盖成功数量


ReplaceUnSoldSuccessCount
	
String
	
覆盖失败


ResultMsg
	
String
	
消息内容

备注

卡种类型对应加卡"data"参数JSON格式例子：
700:循环卡:[{"CardNo":"卡号","Pwd":"卡密"}]
800:套卡：[{"CardNo":"卡号"}]
820:唯一卡：[{"CardNo":"卡号","Pwd":"卡密"}]
840:重复卡：[{"CardNo":"卡号","Pwd":"卡密"}]
850:图片卡：[{"Url":"图片URL地址","Md5":"图片M5d值","OriName":"图片名称"}]

如果只有卡号没有卡密的场景，Pwd就不用传了。eg：820:唯一卡：[{"CardNo":"卡号"}]
