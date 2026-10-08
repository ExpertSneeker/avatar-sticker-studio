# 确认收货通知

来源：https://open.agiso.com/document/#/aldsXhs/push/tradeConfirmPush（2026-10-08 抓取的渲染文本）

确认收货后通知

简要描述：  推送示例

￥高级
确认收货后，推送对应消息。
推送的签名请务必验证，以验证数据来源的合法性。验证方法参考以下说明。
推送时，有可能消息重复推送。实际开发中，请一定要在使用消息前进行去重判断。主要依据是订单编号Tid和订单状态。
推送方式，用jquery做示例：$.post('http://test.com/agiso?timestamp=11222212121&sign=f8aa165fc951f266667e0605d78b93af&aopic=32768', { json: '{"Tid":"592823138",......}' })

推送参数：

参数名	类型	获取方式	说明
fromPlatform
	
string
	
Query/Get
	
参数值：AldsXhs。常见问题


timestamp
	
Number
	
Query/Get
	
时间戳


aopic
	
Number
	
Query/Get
	
推送类型，8:确认收货后;


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
        "sellerId":"64f196de9bac760001e6de2x", // 店铺Id
        "orderId": "P755073560412360911",   // 交易订单号
        "orderStatus": 7,                   // 订单状态，1已下单待付款 2已支付处理中 3清关中 4待发货 5部分发货 6待收货 7已完成 8已关闭 9已取消 10换货申请中
        "updateTime": 1740041385334         // 更新时间（毫秒）
}
