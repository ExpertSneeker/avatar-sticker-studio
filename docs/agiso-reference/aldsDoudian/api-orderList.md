# 查询订单列表

来源：https://open.agiso.com/document/#/aldsDoudian/api/orderList（2026-10-08 抓取的渲染文本）

查询订单列表

简要描述：  接口调用示例

￥高级
查询订单列表

请求URL：

https://gw-api.agiso.com/aldsDoudian/Order/List

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
	
页码,第几页(从0开始)


size
	
是
	
int
	
每页的数量,最多支持100条


startTime
	
是
	
DateTime
	
下单的开始时间 (2024-10-10 或 2024-10-10 00:00:00)


endTime
	
否
	
DateTime
	
下单的结束时间 (2024-10-20 或 2024-10-20 23:59:59)

返回示例


    {
        "isSuccess": true,
        "data": {
            "page": 1,
            "shop_order_list": [
                {
                    "shop_id": 7784061,                         // 店铺ID
                    "shop_name": "京艺智造",                     // 商户名称
                    "open_id": "",                              // 抖音小程序ID 
                    "buyer_words": "",                          // 买家留言  
                    "seller_words": "付款后发货失败：调用第三方接口成功，但对方返回失败（）
",   // 商家备注  
                    "logistics_info": [                             // 物流信息
                        {
                            "tracking_no": "6936476692437472563",   // 物流单号
                            "company": "shenzhenshishun",           // 物流公司
                            "ship_time": 1731916566,                // 发货时间
                            "delivery_id": "7438525010135810342",   // 包裹id  
                            "company_name": "顺丰同城",              // 物流公司名称 
                            "product_info": [
                                {
                                    "product_name": "办公椅，测试商品，勿拍",   // 商品名称  
                                    "price": 1,                               // 商品价格  
                                    "outer_sku_id": "",                       // 商家编码  
                                    "sku_id": 3410716076201730,               // 商品skuId  
                                    "sku_specs": [
                                        {
                                            "name": "颜色",
                                            "value": "白色"
                                        }
                                    ],
                                    "product_count": 1,                         // 发货商品数量  
                                    "product_id": 3660207428038974464,          // 商品ID  
                                    "sku_order_id": "6936476692437472563"       // 商品单ID  
                                }
                            ]
                        }
                    ],
                    "sku_order_list": [                                 // 商品单信息 
                        {
                            "parent_order_id": "6936476692437472563",   // 父订单号（店铺订单号）  
                            "send_pay": 0,                              // 流量来源：1-鲁班广告 2-联盟 3-商城 4-自主经营 5-线索通支付表单 6-抖音门店 7-抖+ 8-穿山甲  
                            "send_pay_desc": "-",                       // 流量来源描述  
                            "author_id": 0,                             // 直播主播id（达人） 
                            "author_name": "",                          // 直播主播名称 
                            "theme_type": "0",                          // 【下单来源】 0、其他 1、直播间  
                            "theme_type_desc": "-",                     // 下单来源描述  
                            "room_id": 0,                               // 直播间id  
                            "content_id": "0",                          // 内容id  
                            "video_id": "",                             // 视频id 
                            "origin_id": "0_3660207428038974332",       // 流量来源id  
                            "cid": 0,                                   // 广告id  
                            "c_biz": 8,                                 // 【C端流量来源】 0、unknown 1、鲁班广告 2、联盟 4、商城 8、自主经营 10、线索/表单收集类广告 12、抖音门店 14、抖+ 15、穿山甲 16、服务市场 18、服务市场外包客服 19、学浪  
                            "c_biz_desc": "小店自卖",                    // C端流量来源业务类型描述  
                            "page_id": 0,                               // 鲁班广告落地页ID  
                            "code": "112233",                           // 商家后台商品编码  
                            "logistics_receipt_time": 0,                // 物流收货时间  
                            "confirm_receipt_time": 0,                  // 用户确认收货时间  
                            "goods_type": 0,                            // 【商品类型】 0、实体 1、虚拟  
                            "sku_id": 3410716076201730,                 //  商品skuId 
                            "spec": [                                   //  规格信息 
                                {
                                    "name": "颜色",
                                    "value": "白色"
                                }
                            ],
                            "first_cid": 20036,                         //  一级类目 
                            "second_cid": 20658,                        //  二级类目 
                            "third_cid": 24998,                         //  三级类目 
                            "fourth_cid": 0,                            //  四级类目 
                            "out_sku_id": "",                           //  外部SkuId 
                            "supplier_id": "",                          //  sku外部供应商编码 
                            "out_product_id": "0",                      //  商品外部编码 
                            "reduce_stock_type": 1,                     //  【库存扣减方式】 1、下单减库存 2、支付减库存 
                            "reduce_stock_type_desc": "下单减库存",      //  库存扣减方式名称 
                            "origin_amount": 1,                         //  商品现价 
                            "has_tax": false,                           //  是否包税 
                            "item_num": 1,                              //  订单商品数量 
                            "sum_amount": 1,                            //  商品现价*件数 
                            "source_platform": "",                      //  商品来源平台 
                            "sku_order_tag_ui": [                       //  商品单标签 
                                {},
                                {},
                                {},
                                {},
                                {},
                                {},
                                {}
                            ],
                            "product_pic": "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/SXJcUUhG_m_0b9d7c9892e9b1c905015b4ef1f32a07_sx_309394_www1500-1500", //  商品图片 
                            "is_comment": 0,                            //  是否评价 :1已评价，0未评价，2 表示追评 
                            "product_name": "办公椅，测试商品，勿拍",     //  商品名称 
                            "inventory_list": [                         //  仓库信息 
                                {}
                            ],
                            "pre_sale_type": 0,                         //  预售类型 ，0 现货类型，1 全款预售 2 阶梯发货 
                            "after_sale_info": {                        //  售后信息 
                                "after_sale_status": 12,                //  售后状态，0-售后初始化，27-拒绝售后申请，28-售后失败，11-售后已发货，29-退货后拒绝退款，51-取消成功,这几个状态视为退款中:6-售后申请， 7-售后退货中，12-售后成功，13-售后换货商家发货，14-售后换货用户收货，53-逆向交易完成 
                                "after_sale_type": 1,                   //  售后类型:0 售后退货退款:1-售后退款 2-售前退款 3-换货 4-系统取消 5-用户取消 
                                "refund_status": 3                      //  退款状态:0-无需退款 1-待退款 2-退款中 3-退款成功 4-退款失败 
                            },
                            "receive_type": 0,                          //  1:邮寄，2:自提 
                            "given_product_type": "",                   //  绑定类型 MASTER-主品单 FREE-免费赠品 
                            "order_id": "6936476692437472563",          //  商品订单号 
                            "order_level": 3,                           //  订单层级 
                            "biz": 2,                                   //  业务来源 
                            "biz_desc": "小店",                         //  业务来源 
                            "order_type": 0,                            //  【订单类型】 0、普通订单 1、全款预售订单 2、虚拟商品订单 3、快闪店订单 4、电子券（poi核销） 5、三方核销 6、服务市场 
                            "order_type_desc": "普通订单",              //  订单类型描述 
                            "trade_type": 0,                            //  【交易类型】 0、普通 1、拼团 2、定金预售 3、订金找贷 4、拍卖 5、0元单 6、回收 7、寄卖 
                            "trade_type_desc": "普通",                  //  交易类型描述 
                            "order_status": 4,                          //  订单状态1 待确认/待支付（订单创建完毕）105 已支付(风控订单不发货) 2 备货中 101 部分发货 3 已发货（全部发货）4 已取消 5 已完成（已收货） 
                            "order_status_desc": "已关闭",              //  订单状态描述 
                            "main_status": 22,                          //  主流程状态，1 待确认/待支付（订单创建完毕）103 部分支付105 已支付2 备货中101 部分发货3 已发货（全部发货）4 已取消5 已完成（已收货）21 发货前退款完结22 发货后退款完结39 收货后退款完结 
                            "main_status_desc": "发货后退款完成",        //  主流程状态描述 
                            "pay_time": 1731916560,                     //  支付时间，时间戳，秒 
                            "order_expire_time": 1800,                  //  订单过期时间，时间戳，秒 
                            "finish_time": 0,                           //  订单完成时间，时间戳，秒 
                            "create_time": 1731916551,                  //  下单时间，时间戳，秒 
                            "update_time": 1731986645,                  //  订单更新时间，时间戳，秒 
                            "cancel_reason": "",                        //  取消原因 
                            "b_type": 2,                                //  【下单端】 0、站外 1、火山 2、抖音 3、头条 4、西瓜 5、微信 6、值点app 7、头条lite 8、懂车帝 9、皮皮虾 11、抖音极速版 12、TikTok 13、musically 14、穿山甲,15、火山极速版 16、服务市场 26、番茄小说 27、UG教育营销电商平台 28、Jumanji 29、电商SDK 
                            "b_type_desc": "抖音",                      //  下单端描述 
                            "sub_b_type": 3,                            //  【下单场景】 0、未知 1、app内-原生 2、app内-小程序 3、H5 13、电商SDK-头条 35、电商SDK-头条lite 
                            "sub_b_type_desc": "H5",                    //  下单场景描述 
                            "app_id": 1128,                             //  具体某个小程序的ID 
                            "pay_type": 2,                              //  【支付类型】 0、货到付款 1 、微信 2、支付宝 3、小程序 4、银行卡 5、余额 7、无需支付（0元单） 8、DOU分期（信用支付） 9、新卡支付 
                            "channel_payment_no": "2024111822001496911406999482",   //  支付渠道的流水号 
                            "order_amount": 1,                          //  订单金额（分） 
                            "pay_amount": 1,                            //  支付金额（分） 
                            "post_insurance_amount": 0,                 //  运费险金额（分） 
                            "modify_amount": 0,                         //  改价金额变化量（分） 
                            "modify_post_amount": 0,                    //  改价运费金额变化量（分） 
                            "promotion_amount": 0,                      //  单优惠总金额= 店铺优惠金额+ 平台优惠金额+ 达人优惠金额 
                            "promotion_shop_amount": 0,                 //  店铺优惠金额（分） 
                            "promotion_platform_amount": 0,             //  平台优惠金额（分） 
                            "shop_cost_amount": 0,                      //  订单优惠商家承担部分（分） 
                            "platform_cost_amount": 0,                  //  订单优惠平台承担部分（分） 
                            "promotion_talent_amount": 0,               //  达人优惠金额（分） 
                            "promotion_pay_amount": 0,                  //  支付优惠金额（分） 
                            "encrypt_post_tel": "$$KlqdO3S6/9vQsJesewp8R2oBlX+I2/UABgHSm9Oy1SuYX6R0pLupUedZkqXVIisqK2anlk+ttMeuBbLI7M286cNfqghVjTy7u2079Lv+6two*CgYIASAHKAESPgo85MWGCFPBcT7U9hVhlqarT/gCf5lFGgE2/QD7kk8RnNtk6ejVOgEhHmWsdLcZVL+ZUhMHYZCE9RmWMuAuGgA=$1$$",  //  收件人电话 
                            "encrypt_post_receiver": "##qIOpbLPevlQwA6f+yNJ7HgOqMdCcDttVlAympUYfJk9VrcWMMeMb1JAmpuUKKFpR+5cGN0aBvV4izFUdinLYs+y2h6RBhv3iZShTKqqttg==*CgYIASAHKAESPgo8AezTm/PH44dQuZGevG6eHhvqqq4gTxNsNWaJyhU33eidXUZe8itcPwhIgUU1vWsqpGKbwUJrTtvnXCDyGgA=#1##", //  收件人姓名 
                            "post_addr": {
                                "province": {
                                    "name": "福建省",
                                    "id": "35"
                                },
                                "city": {
                                    "name": "厦门市",
                                    "id": "350200"
                                },
                                "town": {
                                    "name": "思明区",
                                    "id": "350203"
                                },
                                "street": {
                                    "name": "莲前街道",
                                    "id": "350203010"
                                },
                                "encrypt_detail": "##i688Hg7Kf5y7JCzTAYaUWxswmAx8QnTPvGdsCInjgOIZZNGsRNBWUEgKAdgBnlq2QPdz9SEuu1Hx4zdgUDzORVOS3RVAymnPMfuETWjh1rsELUlyvpciCGRh75TrxtdIkm4yr0exFC41EQuw5Sbn*CgYIASAHKAESPgo8VOu2w0Yb+AwqaIo/dDaYUd0Rf7TF/vhnHHKSjNWvj0Wy7ufZtxugca+cTAvyZ9jvnwdRpAZDPK+WwyWxGgA=#1##" //  详细地址 
                            },
                            "exp_ship_time": 1732031999,        //  预计发货时间，时间戳，秒 
                            "ship_time": 1731916566,            //  发货时间，时间戳，秒 
                            "product_id": 3660207428038974464,  //  商品ID 
                            "promotion_detail": {},             //  优惠信息 
                            "post_amount": 0,                   //  快递费（分） 
                            "promotion_redpack_amount": 0,      //  红包优惠金额（分） 
                            "promotion_redpack_platform_amount": 0, //  平台红包优惠金额（分） 
                            "promotion_redpack_talent_amount": 0    //  达人红包优惠金额（分） 
                        }
                    ],
                    "seller_remark_stars": 0,                   //  插旗信息：0：灰 1：紫 2: 青 3：绿 4： 橙 5： 红 
                    "order_phase_list": [],                     //  定金预售阶段单 
                    "doudian_open_id": "1@#VrtJKX59ewuPyvUhIKiAtxNZ0wt2BBDARCd6qdLmaBiz59YmNzPgpz+KC0B+R/RJTQJ3GRv5",   // 加密用户ID串  
                    "serial_number_list": [],                   //  商品序列号，15-17位数字 
                    "isDdpSource": false,                       //  数据来源（true：数据库、false：api接口） 

                    //  以下参数与sku_order_list里的同名属性描述一致 
                    "order_id": "6936476692437472563",      
                    "order_level": 2,                       
                    "biz": 2,                               
                    "biz_desc": "小店",                     
                    "order_type": 0,                        
                    "order_type_desc": "普通订单",          
                    "trade_type": 0,                        
                    "trade_type_desc": "普通",              
                    "order_status": 4,                      
                    "order_status_desc": "已关闭",          
                    "main_status": 22,                      
                    "main_status_desc": "发货后退款完成",   
                    "pay_time": 1731916560,                 
                    "order_expire_time": 1800,                  
                    "finish_time": 0,
                    "create_time": 1731916551,
                    "update_time": 1731986645,
                    "cancel_reason": "",
                    "b_type": 2,
                    "b_type_desc": "抖音",
                    "sub_b_type": 3,
                    "sub_b_type_desc": "H5",
                    "app_id": 1128,
                    "pay_type": 2,
                    "channel_payment_no": "2024111822001496911406999482",
                    "order_amount": 1,
                    "pay_amount": 1,
                    "post_insurance_amount": 0,
                    "modify_amount": 0,
                    "modify_post_amount": 0,
                    "promotion_amount": 0,
                    "promotion_shop_amount": 0,
                    "promotion_platform_amount": 0,
                    "shop_cost_amount": 0,
                    "platform_cost_amount": 0,
                    "promotion_talent_amount": 0,
                    "promotion_pay_amount": 0,
                    "encrypt_post_tel": "$$U/qaYiUFjC/1SRShyJN85xYJnWFzy6DTqG/V0m1+UJElKaiasCPEHg1DapycCfIC4JlZoiDjoLcpLZPYMEmuXavArlKWr/U7WIK96FcW3lwm*CgYIASAHKAESPgo8K/kgWUneg1yJPt5GQUiGszzh1HxSnId/jeJpDIAXlRr1AI2Jzh4ga6Ykk0skQQJDOU7MuFaMrMcSdkcYGgA=$1$$",
                    "open_address_id": "#GKTB7s7wOxP/iHoVtQM9LrM0EXj6pJo6xT/cJJ9rjxCl2AYG6dA4c2YIICDozxGcYz9oftzUWK2dx35VWLdWEmFL/q/BVDo0/GHNVYy0ptWC40lWrefDIeXPQelrdzTMg0MtWbygqA==",
                    "encrypt_post_receiver": "##5e4wPfKQCWbYKOTVtch6HxHddNxyvAI7PQXlv354unHilRmbS0TzvT0Pt9aASrVfeLqmpOdCKB94shj+kDE38A89MPVYuJtdF4U9xkbxjQ==*CgYIASAHKAESPgo8A0knInJ6X2/YJbHNB0mu93T5+2Bif3K2F6jMJG14HKgoWWYrnxLiNG0gFLvZMQUQupspgzll7tlHlOtCGgA=#1##",
                    "post_addr": {
                        "province": {
                            "name": "福建省",
                            "id": "35"
                        },
                        "city": {
                            "name": "厦门市",
                            "id": "350200"
                        },
                        "town": {
                            "name": "思明区",
                            "id": "350203"
                        },
                        "street": {
                            "name": "莲前街道",
                            "id": "350203010"
                        },
                        "encrypt_detail": "##9c125pyLUXJAYmZnUhS+4KdQwNGbBXvrJ6w7Lh1v3rBqtATddX+VzI0Pb4cbFdCgSxzjPQ8YPi5ULeEpotLHrtq4dTHkzNZIyZfA8MrYZtpgzOw823/JW5DNOZpV3RtpKca8TL7mF4lwvWs6vioV*CgYIASAHKAESPgo8Cghl0OymTqTQy6+bT3R1dnWOOp0zqpfpBHctTBUI3YCddjXvS3tPDuIfaHJBuINxH0EsJyKlytxP+5y7GgA=#1##"
                    },
                    "exp_ship_time": 1732031999,
                    "ship_time": 1731916566,
                    "product_id": 0,
                    "promotion_detail": {},
                    "post_amount": 0,
                    "promotion_redpack_amount": 0,
                    "promotion_redpack_platform_amount": 0,
                    "promotion_redpack_talent_amount": 0
                }
            ],
            "size": 1,
            "total": 33
        },
        "error_Code": 0,
        "error_Msg": ""
    }
