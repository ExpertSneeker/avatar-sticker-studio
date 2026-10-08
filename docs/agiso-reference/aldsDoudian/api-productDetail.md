# 查询商品

来源：https://open.agiso.com/document/#/aldsDoudian/api/productDetail（2026-10-08 抓取的渲染文本）

查询商品信息

简要描述：  接口调用示例

￥高级
根据商品Id查询商品明细

请求URL：

https://gw-api.agiso.com/aldsDoudian/Product/Detail

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
productId
	
是
	
String
	
商品Id

返回示例


    {
        "isSuccess": true,
        "data": {
                "product_id": 3660207428038974464,              // 商品ID，整型格式 
                "product_id_str": "3660207428038974332",        // 商品ID，字符串格式 
                "out_product_id": 0,                            // 商品外部ID 
                "outer_product_id": "",                         // 商品外部ID 
                "name": "办公椅，测试商品，勿拍",                 // 商品名称 
                "description": "",
                "market_price": 1,                              // 划线价，单位分 
                "discount_price": 1,                            // 售价，单位分 
                "status": 0,                                    // 商品上下架状态：0上架 1下架 2已删除 
                "spec_id": 1787210656101395,                    // 规格id 
                "check_status": 3,                              // 商品审核状态：1未提审 2审核中 3审核通过 4审核驳回 5封禁 7审核通过，待上架状态 
                "mobile": "18065583339",                        // 手机号 
                "first_cid": 0,                                 // 一级类目 
                "second_cid": 0,                                // 二级类目 
                "third_cid": 0,                                 // 三级类目 
                "pay_type": 1,                                  // 支持的支付方式：0货到付款 1在线支付 2两者都支持 
                "recommend_remark": "",                         // 商家推荐语 
                "presell_type": "0",                            // 预售类型，1-全款预售，0-非预售，2-阶梯库存 
                "extra": "{"category_detail":{"enable":null,"first_cid":20036,"first_cname":"商业/办公家具","fourth_cid":0,"fourth_cname":"","is_leaf":true,"second_cid":20658,"second_cname":"办公家具","third_cid":24998,"third_cname":"办公椅"},"is_publish":1,"quality_opId":"7386565254094487843","spec_seq_info":{"child_spec_seq":["默认"],"spec_values_seq":[["默认"]]}}", // 扩展字段 
                "create_time": "2024-01-05 09:08:23",           // 创建时间 
                "update_time": "2024-07-04T17:23:22+08:00",     // 更新时间 
                "pic": [                                        // 商品主图 
                    "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/SXJcUUhG_m_0b9d7c9892e9b1c905015b4ef1f32a07_sx_309394_www1500-1500",
                    "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/SXJcUUhG_m_9ae21a465dc6a727b4960abd1b82f59c_sx_109842_www747-747",
                    "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/SXJcUUhG_m_730ad1990a9e416263a1e9d5f37c99d4_sx_101200_www800-800"
                ],
                "product_format": "",                           // 属性名称|属性值之间用|分隔, 多组之间用^分开 
                "spec_pics": [],                                // 规格图片 
                "spec_prices": [    
                    {
                        "sku_id": 3393133152982786,             // 规格id；
                        "out_sku_id": 0,                        // 外部商家skui_id编码，商家自定义字段；推荐使用outer_sku_id字段 
                        "outer_sku_id": "",                     // 外部商家skui_id编码    
                        "spec_detail_ids": [    
                            1787210656101427    
                        ],  
                        "stock_num": 1,                         // 可售库存；当前现货可售库存； 
                        "price": 1,                             // 商品价格；单位：分 
                        "code": "D007",                         // 商编码 
                        "settlement_price": 0,      
                        "step_stock_num": 0,                    // 阶梯库存，规则详见名称解释：https://op.jinritemai.com/docs/guide-docs/202/170 
                        "prom_stock_num": 0,                    // 活动库存，，规则详见名称解释：https://op.jinritemai.com/docs/guide-docs/202/170 
                        "prom_step_stock_num": 0,               // 活动阶梯库存，，规则详见名称解释：https://op.jinritemai.com/docs/guide-docs/202/170 
                        "spec_detail_id1": 1787210656101427,        
                        "spec_detail_id2": 0,       
                        "spec_detail_id3": 0,       
                        "sku_type": 0,                          // sku类型；0-普通库存 1-区域库存 10-阶梯库存 
                        "supplier_id": "",                      // 供应商编码 
                        "customs_report_info": {
                            "hs_code": "",      
                            "first_measure_qty": 0,    
                            "second_measure_qty": 0,   
                            "first_measure_unit": "",      
                            "second_measure_unit": "",     
                            "unit": "",     
                            "report_name": "", 
                            "report_brand_name": "",
                            "usage": "",       
                            "g_model": "",     
                            "bar_code": ""     
                        },  
                        "lock_stock_num": 0,                     // 商品ID，整型格式 
                        "lock_step_stock_num": 0,                // 商品ID，整型格式 
                        "sell_properties": [                     // sku对应的销售属性信息 
                            {
                              "perperty_id": "0",                           // 销售属性id，只有在规格由属性库下发时，这个字段才有值。 默认为0 
                              "property_name": "颜色",                      // 规格项名称 
                              "remark": "非常黄",                           // 备注 
                              "value_id": "12345678910",                    // 销售属性值id，只有在规格由属性库下发时，这个才有值。 默认为0 
                              "value_name": "黄色",                         // 规格值名称 
                              "value_spec_detail_id": "123123123123"        // 规格值id 
                            }
                          ],
                    }
                ],
                "img": "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/SXJcUUhG_m_0b9d7c9892e9b1c905015b4ef1f32a07_sx_309394_www1500-1500",    // 头图，主图第一张 
                "category_detail": {                             // 新类目的详情 
                    "first_cid": 20036,                          // 一级类目 
                    "second_cid": 20658,                         // 二级类目 
                    "third_cid": 24998,                          // 三级类目 
                    "fourth_cid": 0,                             // 四级类目 
                    "first_cname": "商业/办公家具",               // 一级类目名称 
                    "second_cname": "办公家具",                   // 二级类目名称 
                    "third_cname": "办公椅",                      // 三级类目名称 
                    "fourth_cname": ""                           // 四级类目名称 
                },
                "maximum_per_order": 0,                           // comment 
                "limit_per_buyer": 0,                             // comment 
                "minimum_per_order": 1,                           // comment 
                "draft_status": 3,                                // 草稿状态：0 无草稿,1 未提审,2 待审核,3 审核通过,4 审核未通过 
                "is_sub_product": false,                          // 是否是组套商品的子商品 
                "pickup_method": "0"                              // 提取方式新字段，推荐使用。"0": 普通商品-使用物流发货, "1": 虚拟商品-无需物流与电子交易凭证, "2": 虚拟商品-使用电子交易凭证, "3": 虚拟商品-充值直连 
        },
        "error_Code": 0,
        "error_Msg": ""
    }
