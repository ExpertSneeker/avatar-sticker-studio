# 申请短信模板

来源：https://open.agiso.com/document/#/aldsDoudian/api/smsApplyTemplate（2026-10-08 抓取的渲染文本）

申请短信模板

简要描述：  接口调用示例

￥基础
申请短信模板

请求URL：

https://gw-api.agiso.com/aldsDoudian/Sms/ApplyTemplate

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
name
	
是
	
String
	
短信模板名称


content
	
是
	
String
	
短信模板内容 示例：订单号：${orderId} 买家：${userId} 识别码:${code} 注意： 英文短信：整条短信（包括签名+模板+变量中的内容）最多支持140个英文字符，超出将按140个字符截取为多条短信进行发送，费用按截取的条数收费； 非英文短信：整条短信（包括签名+模板+变量中的内容）最多支持70字符，超出将按70个字符截取为多条短信进行发送，费用按截取的条数收费


smsAccountType
	
否
	
Int
	
所属关联通道: 0普通短信(默认) 1教育类短信

返回示例


    {
        "isSuccess": true,
        "data": {
            "platform_shop_id": "7784061",           // 平台门店ID 
            "name": "测试短信模板",                   // 模板名称 
            "tpl_type": 4,                           // 模板类型 
            "tpl_id": "ST_7e0c58aax",                // 模板Id:对应发送短信接口的参数 templateId 
            "tpl_content": "订单号：${orderId} 买家：${user} 识别码:${code}",            // 模板内容 
            "platform_tpl_content": "订单号：${orderId} 买家：${user} 识别码:${code}",   // 模板内容 示例：您购买的商品已重新发出，${name}快递运单号：${number}，关注“XXX”公众号刷新订单获取最新物流信息哦~给您造成不便敬请谅解。
            "audit_status": 100,    // 审核状态 =>100 :待审核 200：通过 300：拒绝 
            "ext_info": "{"SmsTemplateApplyId":"672448","AuditDefaultUse":false}", // 扩展信息，SmsTemplateApplyId：模板申请Id 
            "modify_time": "2024-07-10 15:48:37",
            "create_time": "2024-07-10 15:48:37"
        },
        "error_Code": 0,
        "error_Msg": ""
    }
