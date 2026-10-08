# 商家同意退款消息

来源：https://open.agiso.com/document/#/aldsDoudian/push/refundRefundAgreed（2026-10-08 抓取的渲染文本）

商家同意退款消息

简要描述：  推送示例

￥高级
买家在发货前申请整单退款，卖家同意退款或超时自动同意退款时。
买家在发货后申请仅退款，卖家同意退款或超时自动同意退款时。
买家在发货后申请申请退货，卖家确认收货或系统超时自动确认收货时。
卖家收到买家换货包裹，核验后无法换货，同意换货但转直接退款时。
推送的签名请务必验证，以验证数据来源的合法性。验证方法参考以下说明。
推送时，有可能消息重复推送。实际开发中，请一定要在使用消息前进行去重判断。主要依据是订单编号Tid和订单状态。
推送方式，用jquery做示例：$.post('http://test.com/agiso?timestamp=11222212121&sign=f8aa165fc951f266667e0605d78b93af&aopic=32768', { json: '{"Tid":"592823138",......}' })

推送参数：

参数名	类型	获取方式	说明
fromPlatform
	
string
	
Query/Get
	
参数值：AldsDoudian。常见问题


timestamp
	
Number
	
Query/Get
	
时间戳


aopic
	
Number
	
Query/Get
	
推送类型，128:商家同意退款消息;


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
          "agree_time":1630306403                       // 同意退款时间         
          "update_time": "2022-09-02T10:27:50+08:00",   // 售后单更新时间
          "p_id": 457824112312123,                      // 父订单ID
          "s_id": 457824112312123,                      // 子订单ID
          "shop_id": 7784061,                           // 店铺ID
          "aftersale_id": 657824112312121,              // 父订单ID
          "aftersale_status": 6,                        // 售后状态码
          "aftersale_type": 0,                          // 售后类型： 0: 退货 1: 售后仅退款 2: 发货前整单退款 3：换货
          "refund_amount": 1000,                        // 申请退款的金额（含运费）
          "reason_code": 1,                             // 申请售后原因码
          "refund_voucher_num": 1,                      // 申请退款的卡券的数量
          "refund_post_amount": 100                     // 申请退的运费金额
        }
