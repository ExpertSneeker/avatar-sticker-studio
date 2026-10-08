# 订单详情

来源：https://open.agiso.com/document/#/aldsXhs/api/orderDetail（2026-10-08 抓取的渲染文本）

订单查询

简要描述：  接口调用示例

￥高级
根据订单号，查询订单信息

请求URL：

https://gw-api.agiso.com/aldsXhs/Order/Detail

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
tid
	
是
	
String
	
订单号

返回示例


    {
      "isSuccess": true,
        "data": {
            "orderId": "123456",                              // 订单号
            "orderType": 1,                                   // 包裹类型，1普通 2定金预售 3全款预售 4延迟发货 5换货补发
            "orderStatus": 2,                                 // 包裹状态，1已下单待付款 2已支付处理中 3清关中 4待发货 5部分发货 6待收货 7已完成 8已关闭 9已取消 10换货申请中
            "orderAfterSalesStatus": 1,                       // 售后状态，1无售后 2售后处理中 3售后完成(含取消)
            "cancelStatus": 0,                                // 申请取消状态，0未申请取消 1取消处理中
            "createdTime": 1640995200000,                     // 创建时间 单位ms
            "paidTime": 1640995200000,                        // 支付时间 单位ms
            "updateTime": 1640995200000,                      // 更新时间 单位ms
            "deliveryTime": 1640995200000,                    // 包裹发货时间 单位ms
            "cancelTime": 1640995200000,                      // 包裹取消时间 单位ms
            "finishTime": 1640995200000,                      // 包裹完成时间 单位ms
            "promiseLastDeliveryTime": 1640995200000,         // 承诺最晚发货时间 单位ms
            "planInfoId": "abc123",                           // 物流方案id
            "planInfoName": "物流方案名称",                    // 物流方案名称
            "receiverCountryId": "CN",                        // 收件人国家id
            "receiverCountryName": "中国",                    // 中国
            "receiverProvinceId": "123",                      // 收件人省份id
            "skuList": [
                {
                    "skuId": "sku123",                        // 商品id
                    "skuName": "商品名称",                     // 商品名称
                    "erpcode": "erp123",                      // 商家编码(若为组合品，暂不支持组合品的商家编码，但skulist会返回子商品商家编码)
                    "skuSpec": "规格",                        // 规格
                    "skuImage": "image.jpg",                  // 商品图片url
                    "skuQuantity": 10,                        // 商品数量
                    "skuDetailList": [
                        {
                            "skuId": "detailSku123",           // 单品商品Id(渠道商品为生成渠道商品的原商品单品id，组合商品为各个子商品的单品id，多包组为对应单包组商品id,商家编码同理)
                            "erpCode": "detailErp123",        // 商家编码
                            "barcode": "123456",              // 商品条码
                            "scSkuCode": "sc123",             // 商品编码
                            "quantity": 5,                    // 购买数量
                            "registerName": "商品1号",        // 商品备案名称 商品1号
                            "skuName": "商品1号",             // 商品名 商品1号
                            "pricePerSku": 100,               // 单个sku价格
                            "taxPerSku": 10,                  // 单个sku税金
                            "paidAmountPerSku": 90,           // 单个sku实付
                            "depositAmountPerSku": 20,        // 单个sku定金
                            "merchantDiscountPerSku": 5,      // 单个sku商家承担优惠
                            "redDiscountPerSku": 5,           // 单个sku平台承担优惠
                            "rawPricePerSku": 110             // 单个sku原价
                        }
                    ],
                    "totalPaidAmount": 900,                   // 总支付金额（考虑总件数）商品总实付
                    "totalMerchantDiscount": 50,              // 商家承担总优惠
                    "totalRedDiscount": 50,                   // 平台承担总优惠
                    "totalTaxAmount": 100,                    // 商品税金
                    "totalNetWeight": 500,                    // 商品总净重
                    "skuTag": 0,                              // 是否赠品，1 赠品 0 普通商品
                    "isChannel": false,                       // 是否是渠道商品
                    "Channel": false                          // 
                }
            ],
            "boundExtendInfo": {
                "payNo": "pay123",                            // 交易流水号
                "payChannel": "AliPay",                       // 交易渠道，AliPay=支付宝，TP=微信
                "productValue": "1000",                       // 订单价值（货值，订单商品申价之和（税前价））
                "payAmount": "900",                           // 订单支付金额（含运费）
                "taxAmount": "100",                           // 订单税金
                "shippingFee": "50",                          // 运费 含运费税
                "discountAmount": "50",                       // 订单优惠
                "zoneCodes": ["123", "456"]                   // 海关三级地址区域编码
            },
            "transferExtendInfo": {
                "internationalExpressNo": "express123",       // 国际快递单号
                "orderDeclaredAmount": 1000,                  // 订单申报金额
                "paintMarker": "marker",                      // 大头笔
                "collectionPlace": "place",                   // 集包地
                "threeSegmentCode": "code"                    // 三段码
            },
            "simpleDeliveryOrderList": [
                {
                    "deliveryPackageIndex": "index123",       // 发货包裹索引标识 修改快递单号会使用
                    "status": 4,                              // 发货包裹状态,1:已下单待付款 2:已支付处理中 3:清关中 4:待发货 6:待收货 7:已完成 8:已关闭 9:已取消 10:换货申请中
                    "expressTrackingNo": "tracking123",       // 拆包快递单号
                    "expressCompanyCode": "company123",       // 快递公司代码
                    "skuIdList": ["sku1", "sku2"]             // 此发货包裹中有哪些商品，status=4待发货时，列表中的item可以拆包发货。status=6时，列表中的item共享相同的快递公司和单号，修改时一起修改
                }
            ]
        },
      "error_Code": 0,
      "error_Msg": ""
    }
