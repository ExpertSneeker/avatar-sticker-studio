# 查询售后订单列表

来源：https://open.agiso.com/document/#/aldsDoudian/api/afterSaleList（2026-10-08 抓取的渲染文本）

售后订单查询

简要描述：  接口调用示例

￥高级
售后订单查询

请求URL：

https://gw-api.agiso.com/aldsDoudian/Order/AfterSaleList

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
page
	
是
	
int
	
页码,第几页,从0开始


size
	
是
	
int
	
每页的数量,最多支持100条


startTime
	
否
	
DateTime
	
订单售后申请的开始时间 (2024-10-10 或 2024-10-10 00:00:00)


endTime
	
否
	
DateTime
	
订单售后申请的结束时间 (2024-10-20 或 2024-10-20 23:59:59)


afterSaleId
	
否
	
String
	
售后单号

返回示例


    {
        "isSuccess": true,
        "data": {
            "items": [
                {
                    "aftersale_info": {                                 // 售后信息 
                        "aftersale_status_to_final_time": 1731986642,   // 售后完结时间，完结时间是平台根据商品的类型，售后状态等综合判断生成，当售后单有完结时间返回时售后单不可再做任何操作；未完结售后单的该字段值为0；Unix时间戳：秒
                        "aftersale_id": "146701382803677771",           // 售后单号 
                        "aftersale_order_type": 1,                      // 售后订单类型，枚举为-1(历史订单),1(商品单),2(店铺单) 
                        "aftersale_type": 1,                            // 售后类型，枚举为0(退货退款),1(已发货仅退款),2(未发货仅退款),3(换货),6(价保),7(补寄) 
                        "aftersale_status": 12,                         // 售后状态和请求参数standard_aftersale_status字段对应；3-换货待买家收货；6-待商家同意；7-待买家退货；8-待商家发货；11-待商家二次同意；12-售后成功；14-换货成功；27-商家一次拒绝；28-售后失败；29-商家二次拒绝； 
                        "related_id": "6936476692437472563",            // 关联的订单ID 
                        "apply_time": 1731986326,                       // 申请时间 
                        "update_time": 1731986645,                      // 最近更新时间 
                        "status_deadline": 0,                           // 当前节点逾期时间 
                        "refund_amount": 1,                             // 售后退款金额，单位为分 
                        "refund_post_amount": 0,                        // 售后退运费金额，单位为分 
                        "aftersale_num": 1,                             // 售后数量 
                        "part_type": 0,                                 // 部分退类型 
                        "aftersale_refund_type": 0,                     // 售后退款类型，枚举为-1(历史数据默认值),0(订单货款/原路退款),1(货到付款线下退款),2(备用金),3(保证金),4(无需退款),5(平台垫付) 
                        "refund_type": 0,                               // 退款方式，枚举为1(极速退款助手)、2(售后小助手)、3(售后急速退)、4(闪电退货) 
                        "arbitrate_status": 0,                          // 仲裁状态，枚举为0(无仲裁记录),1(仲裁中),2(客服同意),3(客服拒绝),4(待商家举证),5(协商期),255(仲裁结束) 
                        "create_time": 1731986327,                      // 售后单创建时间 
                        "refund_tax_amount": 0,                         // 退税费 
                        "left_urge_sms_count": 0,                       // 商家剩余发送短信（催用户寄回）次数 
                        "return_logistics_code": "",                    // 退货物流单号 
                        "risk_decision_code": 0,                        // 风控码 
                        "risk_decision_reason": "",                     // 风控理由 
                        "risk_decision_description": "",                // 风控描述 
                        "return_promotion_amount": 0,                   // 退优惠金额 
                        "refund_status": 3,                             // 退款状态；1-待退款;2-退款中;3-退款成功;4-退款失败;5-追缴成功; 
                        "arbitrate_blame": 0,                           // 仲裁责任方 
                        "return_logistics_company_name": "",            // 退货物流公司名称 
                        "exchange_logistics_company_name": "",          // 换货物流公司名称 
                        "remark": "",                                   // 售后商家备注 
                        "got_pkg": 0,                                   // 买家是否收到货物，0表示未收到，1表示收到 
                        "is_agree_refuse_sign": 0,                      // 是否拒签后退款（1：已同意拒签, 2：未同意拒签） 
                        "store_id": 0,                                  // 门店ID 
                        "store_name": "",                               // 门店名称 
                        "aftersale_sub_type": 0,                        // 售后子类型；8001-以换代修。 
                        "auto_audit_bits": [],                          // 自动审核方式：1-发货前极速退；2-小助手自动同意退款；3-发货后极速退；4-闪电退货；5-跨境零秒退；6-云仓拦截自动退；7-小助手自动同意退货；8-小助手自动同意拒签后退款；9-商家代客填写卡片发起售后；10-治理未发货自动同意退款；11-治理已发货自动同意退款；12-商家快递拦截成功自动退款；13-质检商品免审核；14-协商方案自动同意退款；15-平台卡券自动同意退款；16-三方卡券自动同意退款；17-治理一审自动同意退货退款 
                        "exchange_sku_info": {                          // 换货SKU信息 
                            "sku_id": "",                               // 换货SkuID 
                            "code": "",                                 // 换货SKU code                
                            "num": 0,                                   // 换货数目 
                            "out_sku_id": "",                           // 商家编号 
                            "out_warehouse_id": "",                     // 区域库存仓ID 
                            "supplier_id": "",                          // sku外部供应商编码供应商ID 
                            "url": "",                                  // 商品图片url 
                            "name": "",                                 // 商品名称 
                            "price": "",                                // 换货商品的价格，单位分 
                            "spec_desc": ""                             // sku规格信息 
                        },
                        "order_logistics": [                            // 商家首次发货的正向物流信息 
                            {
                                "tracking_no": "6936476692437472563",   // 物流单号 
                                "company_name": "顺丰同城",              // 物流公司名称 
                                "company_code": "shenzhenshishun",      // 物流公司编码 
                                "logistics_time": 1731916566,           // 物流状态到达时间 
                                "logistics_state": 0                    // 正向物流状态 
                            }
                        ],
                        "reason_second_labels": []                      // 用户申请售后时选择的二级原因标签 
                    },
                    "order_info": {                                     // 订单信息 
                        "shop_order_id": "6936476692437472563",         // 店铺单订单ID 
                        "order_flag": 0,                                // 订单插旗 
                        "related_order_info": [                         // 售后关联的订单信息 
                            {
                                "sku_order_id": "6936476692437472563",  // 商品单信息 
                                "order_status": 4,                      // 订单状态，枚举为2(未发货),3(已发货),5(已收货或已完成),255(已完成) 
                                "pay_amount": 1,                        // 付款金额 
                                "post_amount": 0,                       // 付运费金额 
                                "item_num": 1,                          // 购买数量 
                                "create_time": 1731916551,              // 下单时间 
                                "tax_amount": 0,                        // 税费 
                                "is_oversea_order": 0,                  // 是否为海外订单 
                                "product_name": "办公椅，测试商品，勿拍",  // 商品名称 
                                "product_id": 3660207428038974464,      // 商品ID 
                                "product_image": "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/SXJcUUhG_m_0b9d7c9892e9b1c905015b4ef1f32a07_sx_309394_www1500-1500",  // 商品图片 
                                "shop_sku_code": "112233",               // 商家SKU编码 
                                "logistics_code": "",                    // 商家SKU编码 
                                "aftersale_pay_amount": 1,               // 售后退款金额 
                                "aftersale_post_amount": 0,              // 售后退运费金额 
                                "aftersale_tax_amount": 0,               // 售后退税费金额 
                                "aftersale_item_num": 1,                 // 售后商品数量 
                                "promotion_pay_amount": 0,               // 优惠券金额 
                                "price": 1,                              // 价格 
                                "given_sku_order_ids": [],               // 赠品订单id 
                                "tags": [
                                    {
                                        "tag_detail": "7天",                        // 标签中文名称 
                                        "tag_detail_en": "supply_7day_return",      // 标签编号 
                                        "tag_link_url": "https://school.jinritemai.com/doudian/web/article/101835?from=shop_article"  //      // 标签链接 
                                    },
                                    {
                                        "tag_detail": "15天售后期",
                                        "tag_detail_en": "after_sale_days",
                                        "tag_link_url": "https://school.jinritemai.com/doudian/web/article/109931"
                                    }
                                ],
                                "sku_spec": [
                                    {
                                        "name": "颜色",
                                        "value": "白色"
                                    }
                                ]
                            }
                        ]
                    }
                }
            ],
            "total": 35,    // 总数 
            "page": 1,      // 当前分页 
            "size": 1       // 每页数量 
        },
        "error_Code": 0,
        "error_Msg": ""
    }
