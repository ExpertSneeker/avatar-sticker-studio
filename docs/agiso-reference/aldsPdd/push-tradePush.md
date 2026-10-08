# 订单确认时自动采购卡券

来源：https://open.agiso.com/document/#/aldsPdd/push/tradePush（2026-10-08 抓取的渲染文本）

订单确认时自动采购卡券

简要描述：  推送示例

￥高级
普通订单拼团成功会产生此消息；定金订单付完尾款，会产生此消息。
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
	
推送类型，1:交易确认;


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
        "MallId":"110770592823138",    // 店铺Id
        "Tid":"200624-0199468655650824",    // 订单编号
        "BuyerMemo":"",   // 买家留言信息
        "OrderSn":"200624-0199468655650824",   // 订单编号
        "ConfirmTime":"2020-06-24T10:42:51",   // 成交时间
        "CreatedTime":"2020-06-24T10:42:46",   // 创建时间
        "PayAmount":0.1,   // 支付金额（元）支付金额=商品金额-折扣金额+邮费
        "GoodsAmount":0.1,   // 商品金额（元）商品金额=商品销售价格*商品数量-订单改价折扣金额
        "Remark":"",   // 商家订单备注
        "ItemList":[   // 订单中商品sku列表
            {
                "goods_id":"2557644875",   // 商品编号
                "sku_id":"55533589398",   // 商品规格编码
                "outer_id":"003",   //商家外部编码（sku），注意：编辑商品后必须等待商品审核通过后方可生效，订单中商品信息为交易快照的商品信息。
                "outer_goods_id":"87952",   // 商家外部编码（商品），注意：编辑商品后必须等待商品审核通过后方可生效，订单中商品信息为交易快照的商品信息。
                "goods_name":"卡通形象平面设计",   // 商品名称
                "goods_price":0.1,   // 商品销售价格
                "goods_spec":"定制(拍前联系)",   // 商品规格，使用（规格值1,规格值2）组合作为sku的表示，中间以英文逗号隔开
                "goods_count":1,   // 商品数量
                "goods_img":""   // 商品图片
            }
        ]
}
