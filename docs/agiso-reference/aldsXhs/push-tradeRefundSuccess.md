# 退款成功通知

来源：https://open.agiso.com/document/#/aldsXhs/push/tradeRefundSuccess（2026-10-08 抓取的渲染文本）

退款成功后通知

简要描述：  推送示例

￥基础
当商家同意退款后，实际退款到账时，推送对应消息。
卖家收到买家换货包裹，核验后无法换货，同意换货但转直接退款，退款成功时
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
	
推送类型，32:退款成功;


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
        "returnsId":7000893114000949000,    // 售后单ID
        "orderId":4835804142146757000,      // 订单ID
        "returnType":1,                     // 退货类型 1 退货退款 2 换货 3 仅退款(old) 4仅退款(已发货) 5未发货仅退款(未发货取消订单)
        "requestFrom":2,                    // 售后发起主体：1 买家申请 2 卖家申请 3 平台客服发起 4 系统修改
        "refundFee":1632518,                // 退款金额（不包含运费）（单位：元）
        "updateTime":1740041385334,         // 更新时间（毫秒）
        "sellerId":10437917                 // 商家店铺Id
      }

备注

推送参数详细说明可参考小红书退款成功消息文档
