# 订单详情

来源：https://open.agiso.com/document/#/aldsDoudian/api/orderDetail（2026-10-08 抓取的渲染文本）

订单查询

简要描述：  接口调用示例

￥高级
根据订单号，查询订单信息

请求URL：

https://gw-api.agiso.com/aldsDoudian/Order/Detail

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
shop_order_id
	
是
	
String
	
店铺订单号

返回示例


        {
          "IsSuccess": true,
          "Data": {
            "order_id":"4907538423936588900",     // 店铺订单号（父订单号）
            "order_level":2,                      // 订单层级，主订单是2级 
            "order_type":0,                       // 【订单类型】 0、普通订单 2、虚拟商品订单 4、电子券（poi核销） 5、三方核销 
            "order_type_desc":"普通订单",         // 订单类型描述 
            "order_status":4,                     // 订单状态1 待确认/待支付（订单创建完毕）105 已支付 2 备货中 101 部分发货 3 已发货（全部发货）4 已取消5 已完成（已收货） 
            "order_status_desc":"已关闭",         // 订单状态描述 
            "main_status":21,                     // 主流程状态，1 待确认/待支付（订单创建完毕）103 部分支付105 已支付2 备货中101 部分发货3 已发货（全部发货）4 已取消5 已完成（已收货）21 发货前退款完结22 发货后退款完结39 收货后退款完结 
            "main_status_desc":"发货前退款完成",   // 主流程状态描述 
            "pay_time":1646720740,               //  支付时间，时间戳，秒述 
            "order_expire_time":1800,             // 订单过期时间，时间戳，秒 
            "finish_time":0,                     // 订单完成时间，时间戳，秒 
            "create_time":1646720547,            // 下单时间，时间戳，秒 
            "update_time":1646892779,            // 订单更新时间，时间戳，秒 
            "cancel_reason":"",                  // 取消原因 
            "b_type": 2,                        //  【下单端】 0、站外 1、火山 2、抖音 3、头条 4、西瓜 5、微信 6、值点app 7、头条lite 8、懂车帝 9、皮皮虾 11、抖音极速版 12、TikTok 13、musically 14、穿山甲,15、火山极速版 16、服务市场 26、番茄小说 27、UG教育营销电商平台 28、Jumanji 29、电商SDK 
            "b_type_desc": "抖音",              //  下单端描述 
            "sub_b_type": 3,                    //  【下单场景】 0、未知 1、app内-原生 2、app内-小程序 3、H5 13、电商SDK-头条 35、电商SDK-头条lite 
            "sub_b_type_desc": "H5",            //  下单场景描述 
            "order_amount":1,                    // 订单金额（单位：分） 
            "pay_amount":1,                      // 支付金额（单位：分） 
            "ship_time":0,                       // 发货时间，时间戳，秒 
            "shop_id":7784061,                   // 店铺ID 
            "shop_name":"茶具礼品",              // 商户名称 
            "doudian_open_id":"aaxxxxssss",     // 加密用户ID串 
            "buyer_words":"",                   // 买家留言 
            "seller_words":"",                  // 商家备注 
            "sku_order_list":[                  // 商品单信息 
              {
                  "order_id":"6931411066952816166",         // 子订单 
                  "order_status":"2",                       订单状态1 待确认/待支付（订单创建完毕）105 已支付(风控订单不发货) 2 备货中 101 部分发货 3 已发货（全部发货）4 已取消 5 已完成（已收货） 
                  "pay_amount":1,                           // 支付金额（分） 
                  "parent_order_id":"4907538423936588900",  // 父订单号（店铺订单号） 
                  "code":"333",                             // 商家后台商品编码 
                  "logistics_receipt_time":0,               // 物流收货时间 
                  "confirm_receipt_time":0,                 // 用户确认收货时间 
                  "goods_type":0,                           // 【商品类型】 0、实体 1、虚拟 
                  "product_id":1721288561899563,            // 商品id 
                  "sku_id":1721288561899566,                // 商品skuId 
                  "spec":[                                  // 规格信息 
                      {
                          "name":"包装",
                          "value":"定制（单拍不发）"
                      }
                  ],
                  "out_sku_id":"",                          // 外部Skuid 
                  "supplier_id":"",                         // sku外部供应商编码 
                  "out_product_id":"0",                     // 商品外部编码 
                  "origin_amount":1,                        // 商品现价（单位：分） 
                  "item_num":1,                             // 订单商品数量 
                  "sum_amount":1,                           // 商品现价*件数 
                  "sku_order_tag_ui":[{}],                    // 商品单标签 
                  "product_pic":"https://p9-aio.ecombdimg.com/obj/temai/d42f1583f37761dc27758607abb9f8f6www935-935", // 商品现价*件数 
                  "is_comment":0,                              // 是否评价 :1已评价，0未评价，2 表示追评 
                  "product_name":"一次性保鲜膜套家用防尘保鲜罩一次性保鲜套",   // 商品名称 
                  "after_sale_info":{                          // 售后信息 
                      "after_sale_status":12,                  // 售后状态，0-售后初始化， 6-售后申请， 7-售后退货中， 27-拒绝售后申请， 12-售后成功， 28-售后失败， 11-售后已发货， 29-退货后拒绝退款， 13-售后换货商家发货， 14-售后换货用户收货， 51-取消成功， 53-逆向交易完成 
                      "after_sale_type":2,                     // 售后类型:0 售后退货退款:1-售后退款 2-售前退款 3-换货 4-系统取消 5-用户取消     
                      "refund_status":3                        // 退款状态:0-无需退款 1-待退款 2-退款中 3-退款成功 4-退款失败  
                  },
                  "relation_order":{                           // 关联订单  
                    "write_off_no":"",                         // 核销券码  
                    "relation_order_id":""                     // 关联店铺单订单id  
                  },
                  "given_product_type":""                      // 绑定类型 MASTER-主品单 FREE-免费赠品  
                  "pre_sale_type": 0                           // 预售类型 ，0 现货类型，1 全款预售 2 阶梯发货  
                  "exp_ship_time": 1732118399,                 // 预计发货时间，时间戳，秒 
                  "author_id": 0,                             // 直播主播id（达人） 
                  "author_name": "",                          // 直播主播名称  
                  "room_id": 0,                               // 直播间id  
              }
            ],
            "exp_ship_time": 1732118399,                       // 预计发货时间，时间戳，秒  
            "encrypt_post_tel": "$$xP8HUyAQGaXOEO4tHAv2ZoeEQxAn4wWXun7FRA7T5MYnDnjEUxEUqb3eh2Aek2WjEPjE8GO1ad+LiLkPI+TODD56u6+UpIJ71K4t1iXfVJB1*CgYIASAHKAESPgo8vnQ9ylXbuqO4LV7chHWhFqnePSSbBGDC0bL9YieT6xX5sf13zEgR8rDafzkWWFYlyjqJPDbc7vJmybF3GgA=$1$$",                             // 收件人电话(密文)  
            "encrypt_post_receiver": "##RA8Drz4ZwOh3iv9o3QRM6TRTP4BvjMMLyoptIU/y6X4JVx41GEq2V9rGLdP3J3A+Cg8Y9gZEAnsAG4mIGEPOWqtVvNxBhDmAy44plxiIfQ==*CgYIASAHKAESPgo8qv+sT66jxoWJ4ljJSHa+zfyYxd49Pt1wh+UceqTZiAw2HLbs/ih24wtDPnZVi4Slb7A6LLDXbm5/i9xEGgA=#1##",                        // 收件人姓名(密文)  
            "post_addr": {
              "province": {
                "id": "110000",
                "name": "北京市"  
              },
              "city": {
                "id": "110000",
                "name": "市辖区"
              },
              "town": {
                "id": "110000",
                "name": "海淀区"
              },
              "street": {
                "id": "110000",
                "name": "中关村街道"
              },
              "encrypt_detail": "##Av2EYuW9rDSeF5TUObGZV314xS0a7lvefIIW5weE+dITrp1fSxFUkF7w2bVzW+62eLkqHN16Jz/17o7wFB78A0P6LuLxvR58PZptanTuzyoDQbEOGGkL+gcb2B0p0jAK68XkI4ZD*CgYIASAHKAESPgo8zi1miJ8Znc1mlEAH3RlK8LGz9o4hMOAfmcSRxXKr3kg9YHHggudKhfRmy/cAaZg+/6QoJM/3LDt5qXGIGgA=#1##"  // 详细地址(密文)  
            },

          },
          "Error_Code": 0,
          "Error_Msg": ""
          "AllowRetry": null,
          "RequestId": "20220322142251106"
        }
