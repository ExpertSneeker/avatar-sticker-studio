# 查询售后单

来源：https://open.agiso.com/document/#/aldsDoudian/api/afterSaleDetail（2026-10-08 抓取的渲染文本）

查询售后单

简要描述：  接口调用示例

￥高级
根据售后单Id查询售后单明细

请求URL：

https://gw-api.agiso.com/aldsDoudian/Order/AfterSaleDetail

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
afterSaleId
	
是
	
Long
	
售后单Id

返回示例


    {
        "isSuccess": true,
        "data": {
            "order_info": {                                 
                "shop_order_id": 6931781998977357824,           // 店铺单ID
                "sku_order_infos": [                            // 售后单关联订单信息
                    {
                        "sku_order_id": 6931781998977357824,    // sku单ID
                        "order_status": 3,                      // 订单状态1 待确认/待支付（订单创建完毕）105 已支付(风控订单不发货) 2 备货中 101 部分发货 3 已发货（全部发货）4 已取消 5 已完成（已收货）
                        "pay_amount": 1,                        // 买家实付金额（分） 
                        "post_amount": 0,                       // 买家购买运费（分）
                        "item_quantity": 1,                     // 订单件数
                        "create_time": 1720076744,              // 创建时间
                        "tax_amount": 0,                        // 购买税费（分）
                        "is_oversea_order": 0,                  // 是否为跨境业务
                        "product_name": "办公椅，测试商品，勿拍", // 商品名称
                        "product_id": 3660207428038974464,      // 商品ID
                        "product_image": "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/SXJcUUhG_m_0b9d7c9892e9b1c905015b4ef1f32a07_sx_309394_www1500-1500",  // 商品图片
                        "sku_spec": [                           // 商品规格信息
                            {
                                "name": "默认", 
                                "value": "默认" 
                            }
                        ],
                        "shop_sku_code": "D007",                // 商家sku自定义编码
                        "sku_id": 3393133152982786,             // skuID
                        "item_sum_amount": 1,                   // sku商品总原价（不含优惠）
                        "sku_pay_amount": 1,                    // 商品实际支付金额
                        "promotion_amount": 0,                  // 优惠总金额
                        "pay_type": 4,                          // 支付方式：0 : "货到付款" 1："在线支付"
                        "after_sale_item_count": 1,             // 商品单对应的售后数量
                        "given_sku_details": [
                            {
                            "name": "默认", 
                            "value": "默认" 
                        }]                                      // 赠品信息
                    }
                ]
            },                                              
            "process_info": {
                "after_sale_info": {
                    "after_sale_id": 146501574716378560,         // 售后单ID
                    "after_sale_status": 7,                      // 售后状态：6-售后申请；7-售后退货中；8-【补寄维修返回：售后待商家发货】；11-售后已发货；12-售后成功；13-【换货补寄维修返回：售后商家已发货，待用户收货】； 14-【换货补寄维修返回：售后用户已收货】 ；27-拒绝售后申请；28-售后失败；29-售后退货拒绝；51-订单取消成功；53-逆向交易已完成；
                    "after_sale_status_desc": "待买家退货",       // 售后状态文案
                    "refund_type": 4,                            // 退款方式
                    "refund_type_text": "订单货款",               // 退款方式文案
                    "refund_status": 1,                          // 退款状态;1-待退款;2-退款中;3-退款成功;4退款失败;5追缴成功;
                    "reason": "其他",                             // 申请原因
                    "reason_code": 15,                           // 原因码；通过【afterSale/rejectReasonCodeList】接口获取
                    "apply_time": 1723686010,                    // 售后单申请时间
                    "after_sale_type": 0,                        // 售后类型： 0-售后退货退款；1-售后仅退款；2-发货前退款；3-换货；4-系统取消；5-用户取消；6-价保；7-补寄；8-维修
                    "apply_role": 1,                             // 售后申请角色：1-买家；2-商家；3-客服；4-系统
                    "post_receiver":"xxxxxxxx",                  // 换货、补寄时的收货人名字（只有换货、补寄时，这个字段才会有值），此字段已加密，使用前需要解密
                    "post_tel_sec":"xxxxxxxx",                   // 换货、补寄时的收货人的联系电话（只有换货、补寄时，这个字段才会有值），此字段已加密，使用前需要解密
                    "post_address":{                             // 换货、补寄时的收货四级地址（只有换货、补寄时，这个字段才会有值）
                        "detail":"xxxxxxx"                       // 地址详情，此字段已加密，使用前需要解密
                        "landmark":"xxx"                         // 收件地址标志物
                        "province":{
                            "id":"",
                            "name":"省",
                        },
                        "city":{
                            "id":"",
                            "name":"市",
                        },
                        "town":{
                            "id":"",
                            "name":"县",
                        },
                        "street":{
                            "id":"",
                            "name":"街道",
                        },
                    }
                },
                "logistics_info": {                              // 物流信息
                    "return": {                                  // 买家退货物流信息
                        "tracking_no": "",                       // 物流单号
                        "company_name": "",                      // 物流公司名称
                        "company_code": "",                      // 物流公司编码
                        "logistics_time": "0"                    // 买家填写退货物流时间
                    }
                }
            }
        },
        "error_Code": 0,
        "error_Msg": ""
    }
