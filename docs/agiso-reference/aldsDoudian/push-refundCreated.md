# 买家发起售后申请通知

来源：https://open.agiso.com/document/#/aldsDoudian/push/refundCreated（2026-10-08 抓取的渲染文本）

买家发起售后申请

简要描述：  推送示例

￥基础
买家发起售后申请后，推送对应消息。
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
	
推送类型，2:买家发起售后申请;


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
        "aftersale_id":7000893114000949000, // 售后单ID
        "aftersale_status":6,               // 售后状态：0-售后初始化， 6-售后申请， 7-售后退货中， 27-拒绝售后申请， 12-售后成功， 28-售后失败， 11-售后已发货， 29-退货后拒绝退款， 13-售后换货商家发货， 14-售后换货用户收货， 51-取消成功， 53-逆向交易完成
        "aftersale_type":2,                 // 售后类型： 0: 退货 ，1: 售后仅退款， 2: 发货前退款， 3：换货 ， 4:系统取消，5：用户取消，6：价保，7：补寄
        "apply_time":1630022518,            // 售后申请时间
        "p_id":4835804142146757000,         // 父订单ID
        "reason_code":1,                    // 申请售后原因码，枚举值如下
        "refund_amount":8900,               // 申请退款的金额（含运费）
        "refund_post_amount":0,             // 申请退的运费金额
        "refund_voucher_num":0,             // 申请退款的卡券的数量
        "s_id":4835804142146757000,         // 子订单ID
        "shop_id":10437917                  // 店铺ID
      }

备注

推送参数详细说明可参考抖店买家发起售后申请消息文档
