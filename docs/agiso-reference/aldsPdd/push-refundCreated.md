# 买家取消订单时通知

来源：https://open.agiso.com/document/#/aldsPdd/push/refundCreated（2026-10-08 抓取的渲染文本）

买家取消订单时通知

简要描述：  推送示例

￥高级
消费者/系统/平台客服 创建售后单时，会触发此消息。
推送的签名请务必验证，以验证数据来源的合法性。验证方法参考以下说明。
推送时，有可能消息重复推送。在业务进行之前，对消息进行去重判断，以Tid组合为唯一标识。
推送方式，用jquery做示例：$.post('http://test.com/agiso?timestamp=11222212121&sign=f8aa165fc951f266667e0605d78b93af&aopic=32768', { json: '{"Tid":"592823138",......}' })

推送参数：

参数名	类型	获取方式	说明
fromPlatform
	
string
	
Query/Get
	
参数值：PddAlds。常见问题


timestamp
	
Number
	
Query/Get
	
时间戳


aopic
	
Number
	
Query/Get
	
推送类型，8:退款创建;


sign
	
String
	
Query/Get
	
签名算法：
   将json和timestamp参数名和参数值组合起来（注意：json在前，timestamp在后），然后前后添加上AppSecret ，再进行Md5加密（加密算法参考接入指南-完整调用API示例代码中MD5算法）。
例：
url：http://test.com/agiso?timestamp=11222212121&sign=f8aa165fc951f266667e0605d78b93af&aopic=256，
postData: { json: {"Tid":2067719225654838,"Status":"WAIT_BUYER_CONFIRM_GOODS",......,"TotalFee":"3.00"} }，
_appsecret: 9f8g9d78sg9d8f8ew9f89ds9f8ds9af8(开发者AppSecret)，
连接后的串: 9f8g9d78sg9d8f8ew9f89ds9f8ds9af8json{"Tid":2067719225654838,"Status":"WAIT_BUYER_CONFIRM_GOODS",......,"TotalFee":"3.00"}timestamp112222121219f8g9d78sg9d8f8ew9f89ds9f8ds9af8
再对连接后的字符串，进行MD5加密，
MD5结果: f8aa165fc951f266667e0605d78b93af（不区分大小写）


json
	
String
	
Form/Post
	
推送消息,如：
{
 "mall_id": 9112588,    // 店铺Id
 "refund_fee": 1,    // 退款金额(单位:分)
 "bill_type": 2,    // 售后类型: 1-仅退款；2-退货退款；3-换货；4-补寄；5-维修
 "modified": 1556356040640,    // 更新时间
 "refund_id": 408780010,    // 售后单id
 "operation": 1000,    // 售后操作:1000-消费者申请；1001-平台客服新建；1002-平台客服开启；1003-系统创建
 "tid": "190427-391328563312668"    // 订单编号
}
