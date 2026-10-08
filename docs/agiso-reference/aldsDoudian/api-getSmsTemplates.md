# 获取短信模板

来源：https://open.agiso.com/document/#/aldsDoudian/api/getSmsTemplates（2026-10-08 抓取的渲染文本）

获取短信模板

简要描述：  接口调用示例

￥基础
获取短信模板

请求URL：

https://gw-api.agiso.com/aldsDoudian/Sms/GetSmsTemplates

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
tplIds
	
否
	
List<string>
	
短信模板Id列表，不传默认查询所有 注意：对于列表类型传多个值的情况，可以添加多个相同键(tplIds),不同值来传递。 多个模板Id请求示例： param1:tplIds = xxxxx1 param2:tplIds = xxxxx2

返回示例


    {
        "isSuccess": true,
        "data": [
            {
            "platform_shop_id": "7784061",           // 平台门店ID 
            "tpl_type": 4,                           // 模板类型：0 发提取网站,1 发卡号, 2 发卡号和密码,3 发货声明,4 开放平台 
            "name": "测试短信模板",                   // 模板名称 
            "tpl_id": "ST_7e0c58aax",                // 模板Id:对应发送短信接口的参数 templateId 
            "tpl_content": "订单号：${orderId} 买家：${user} 识别码:${code}",            // 模板内容 
            "platform_tpl_content": "订单号：${orderId} 买家：${user} 识别码:${code}",   // 模板内容 可忽略该字段
            "audit_status": 100,                                                          // 审核状态 =>100 :待审核 200：通过 300：拒绝 
            "ext_info": "{"SmsTemplateApplyId":"672448","AuditDefaultUse":false}",  // 扩展信息，SmsTemplateApplyId：模板申请Id 
            "modify_time": "2024-07-10 15:48:37",
            "create_time": "2024-07-10 15:48:37"
            }
        ],
        "error_Code": 0,
        "error_Msg": ""
    }
